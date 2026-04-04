"""Per-robot agent ROS 2 node for SELENE lunar ISRU fleet.

Wires together the FSM, HAL, Navigator, EnergyManager, and Skills
into an autonomous agent that prospects waypoints, monitors battery,
and returns to recharge when energy is critical.
"""

from __future__ import annotations

import yaml

import rclpy
from rclpy.node import Node

from selene_msgs.msg import RobotState, ResourceMapUpdate
from geometry_msgs.msg import Pose2D, Twist, Point
from nav_msgs.msg import Path

from selene_hal import create_hal
from selene_agent.fsm import AgentFSM, AgentState, FSMEvent
from selene_agent.energy_manager import EnergyManager
from selene_agent.navigator import Navigator, OccupancyGrid
from selene_agent.skills import ProspectSkill, RechargeSkill
from selene_agent.skills.prospect import ProspectPhase


class AgentNode(Node):
    """ROS 2 node driving a single autonomous lunar surface robot."""

    def __init__(self):
        super().__init__("agent_node")

        # -- Declare parameters --------------------------------------------------
        self.declare_parameter("robot_id", "scout_01")
        self.declare_parameter("robot_type", "scout")
        self.declare_parameter("rcdl_path", "")
        self.declare_parameter("hal_backend", "gazebo")
        self.declare_parameter("nav_config_path", "")
        self.declare_parameter("recharge_x", 40.0)
        self.declare_parameter("recharge_y", 40.0)
        self.declare_parameter("energy_critical_threshold", 0.15)
        self.declare_parameter("energy_recharge_target", 0.90)
        self.declare_parameter("tick_rate", 10.0)

        # -- Read parameters -----------------------------------------------------
        self._robot_id = self.get_parameter("robot_id").get_parameter_value().string_value
        self._robot_type = self.get_parameter("robot_type").get_parameter_value().string_value
        rcdl_path = self.get_parameter("rcdl_path").get_parameter_value().string_value
        hal_backend = self.get_parameter("hal_backend").get_parameter_value().string_value
        nav_config_path = self.get_parameter("nav_config_path").get_parameter_value().string_value
        self._recharge_x = self.get_parameter("recharge_x").get_parameter_value().double_value
        self._recharge_y = self.get_parameter("recharge_y").get_parameter_value().double_value
        energy_critical = self.get_parameter("energy_critical_threshold").get_parameter_value().double_value
        self._energy_recharge_target = self.get_parameter("energy_recharge_target").get_parameter_value().double_value
        self._tick_rate = self.get_parameter("tick_rate").get_parameter_value().double_value

        # -- Create HAL ----------------------------------------------------------
        self._hal = create_hal(rcdl_path, self._robot_id, backend=hal_backend, ros_node=self)

        # -- Load navigation config ----------------------------------------------
        with open(nav_config_path, "r") as f:
            nav_config = yaml.safe_load(f)

        # -- Create occupancy grid and navigator ---------------------------------
        grid = OccupancyGrid.from_config(nav_config)
        self._navigator = Navigator(self._hal, grid, ros_node=self)

        # -- Create energy manager -----------------------------------------------
        recharge_station = (self._recharge_x, self._recharge_y)
        self._energy_manager = EnergyManager(
            self._hal.get_battery(),
            critical_threshold=energy_critical,
            recharge_target=self._energy_recharge_target,
            recharge_station=recharge_station,
        )

        # -- Create FSM ----------------------------------------------------------
        self._fsm = AgentFSM(self._robot_id, logger=self.get_logger().info)

        # -- Load prospect waypoints ---------------------------------------------
        mission = nav_config.get("mission", {})
        raw_waypoints = mission.get("prospect_waypoints", [])
        self._waypoints = [(float(wp[0]), float(wp[1])) for wp in raw_waypoints]
        self._waypoint_index = 0

        # -- Skill tracking ------------------------------------------------------
        self._current_skill = None
        self._current_task_id = ""
        self._was_navigating = False  # tracks ProspectSkill NAVIGATING->SETTLING transition

        # -- Publishers ----------------------------------------------------------
        self._state_pub = self.create_publisher(
            RobotState, f"/{self._robot_id}/state", 10
        )
        self._path_pub = self.create_publisher(
            Path, f"/{self._robot_id}/planned_path", 10
        )
        self._map_update_pub = self.create_publisher(
            ResourceMapUpdate, "/orchestrator/map_update", 10
        )

        # -- Timers --------------------------------------------------------------
        tick_period = 1.0 / self._tick_rate
        self._tick_timer = self.create_timer(tick_period, self._tick)
        self._state_timer = self.create_timer(0.5, self._publish_state)  # 2 Hz

        # -- Startup log ---------------------------------------------------------
        self.get_logger().info(
            f"[{self._robot_id}] AgentNode started | type={self._robot_type} "
            f"backend={hal_backend} tick={self._tick_rate}Hz "
            f"waypoints={len(self._waypoints)} "
            f"recharge=({self._recharge_x}, {self._recharge_y})"
        )

    # ===================================================================
    # Main loop (10 Hz)
    # ===================================================================

    def _tick(self):
        dt = 1.0 / self._tick_rate

        # Read current state from HAL
        try:
            battery_state = self._hal.get_battery().get_state()
        except Exception as e:
            self.get_logger().warn(f"[{self._robot_id}] Sensor read failed: {e}")
            return

        # Update energy manager
        self._energy_manager.update(battery_state)

        # Battery critical check (override unless already handling it)
        if (
            self._energy_manager.is_critical()
            and self._fsm.state
            not in (
                AgentState.RETURNING,
                AgentState.RECHARGING,
                AgentState.OFFLINE,
                AgentState.ERROR,
            )
        ):
            charge = self._energy_manager.get_charge_fraction()
            self.get_logger().warn(
                f"[{self._robot_id}] Battery critical ({charge:.1%}), returning to recharge"
            )
            if self._current_skill and self._current_skill.is_running():
                self._current_skill.abort()
            self._fsm.handle_event(FSMEvent.ENERGY_CRITICAL)
            self._start_recharge()
            return

        # State-specific logic
        state = self._fsm.state

        if state == AgentState.IDLE:
            self._handle_idle()
        elif state == AgentState.NAVIGATING:
            self._handle_navigating(dt)
        elif state == AgentState.WORKING:
            self._handle_working(dt)
        elif state == AgentState.RETURNING:
            self._handle_returning(dt)
        elif state == AgentState.RECHARGING:
            self._handle_recharging(dt)

    # ===================================================================
    # State handlers
    # ===================================================================

    def _handle_idle(self):
        """Pick the next waypoint, create a ProspectSkill, and start navigating."""
        if self._waypoint_index >= len(self._waypoints):
            self.get_logger().info(
                f"[{self._robot_id}] Mission complete -- all {len(self._waypoints)} waypoints visited"
            )
            return

        waypoint = self._waypoints[self._waypoint_index]
        self._current_task_id = f"prospect_{self._waypoint_index}"

        self._current_skill = ProspectSkill()
        self._current_skill.start(self._hal, self._navigator, target=waypoint)

        if self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Failed to start prospect at {waypoint}: "
                f"{self._current_skill.get_error()}"
            )
            self._waypoint_index += 1
            self._current_skill = None
            self._current_task_id = ""
            return

        self._was_navigating = True
        self._fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        self.get_logger().info(
            f"[{self._robot_id}] Targeting waypoint {self._waypoint_index}: {waypoint}"
        )

    def _handle_navigating(self, dt: float):
        """Drive the ProspectSkill; detect when navigation phase ends."""
        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Navigation failed: {self._current_skill.get_error()}"
            )
            self._fsm.handle_event(FSMEvent.FAULT)
            return

        # Detect transition from NAVIGATING to SETTLING/SENSING (arrival)
        if self._was_navigating and self._current_skill._phase != ProspectPhase.NAVIGATING:
            self._was_navigating = False
            self._fsm.handle_event(FSMEvent.ARRIVED)
            self.get_logger().info(
                f"[{self._robot_id}] Arrived at waypoint {self._waypoint_index}, "
                f"phase={self._current_skill._phase.value}"
            )

    def _handle_working(self, dt: float):
        """Let ProspectSkill settle, sense, and record; publish result on completion."""
        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.is_complete():
            result = self._current_skill.get_result()
            if result is not None:
                self._publish_map_update(result)
                self.get_logger().info(
                    f"[{self._robot_id}] Prospect complete at waypoint {self._waypoint_index}: "
                    f"ice={result.ice_concentration:.3f} +/-{result.uncertainty:.3f}"
                )
            else:
                self.get_logger().warn(
                    f"[{self._robot_id}] Prospect at waypoint {self._waypoint_index} "
                    f"completed with no result"
                )
            self._waypoint_index += 1
            self._current_task_id = ""
            self._current_skill = None
            self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
            self._start_recharge()

        elif self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Prospect failed at waypoint {self._waypoint_index}: "
                f"{self._current_skill.get_error()}"
            )
            self._waypoint_index += 1
            self._current_task_id = ""
            self._current_skill = None
            self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
            self._start_recharge()

    def _handle_returning(self, dt: float):
        """Drive the RechargeSkill toward the base station."""
        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Return navigation failed: "
                f"{self._current_skill.get_error()}"
            )
            self._fsm.handle_event(FSMEvent.FAULT)
            return

        # RechargeSkill signals _at_station when navigation completes.
        # Transition to RECHARGING and let _handle_recharging take over.
        if self._current_skill._at_station:
            self._fsm.handle_event(FSMEvent.AT_BASE_NEED_CHARGE)
            return

    def _handle_recharging(self, dt: float):
        """Wait for the RechargeSkill to finish charging."""
        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.is_complete():
            charge = self._energy_manager.get_charge_fraction()
            self.get_logger().info(
                f"[{self._robot_id}] Recharge complete, battery at {charge:.1%}"
            )
            self._current_skill = None
            self._current_task_id = ""
            self._fsm.handle_event(FSMEvent.CHARGE_COMPLETE)

    # ===================================================================
    # Recharge helper
    # ===================================================================

    def _start_recharge(self):
        """Create and start a RechargeSkill heading for the base station."""
        self._current_skill = RechargeSkill(
            recharge_position=(self._recharge_x, self._recharge_y),
            recharge_target=self._energy_recharge_target,
        )
        self._current_skill.start(self._hal, self._navigator)
        self._current_task_id = "recharge"

    # ===================================================================
    # State publisher (2 Hz)
    # ===================================================================

    def _publish_state(self):
        msg = RobotState()
        msg.robot_id = self._robot_id
        msg.robot_type = self._robot_type
        msg.fsm_state = self._fsm.state.value

        try:
            odom = self._hal.get_sensor("odometry").read()
            msg.pose = Pose2D(x=odom.x, y=odom.y, theta=odom.theta)
            msg.velocity = Twist()
            msg.velocity.linear.x = odom.linear_velocity
            msg.velocity.angular.z = odom.angular_velocity
        except Exception:
            pass

        msg.battery_level = float(self._energy_manager.get_charge_fraction())
        msg.current_task_id = self._current_task_id
        msg.task_progress = float(
            self._current_skill.get_progress() if self._current_skill else 0.0
        )
        msg.capabilities = self._hal.get_capabilities()
        msg.stamp = self.get_clock().now().to_msg()

        self._state_pub.publish(msg)

        # Also publish path for RViz2 visualization
        self._navigator.publish_path()

    # ===================================================================
    # Map update publisher
    # ===================================================================

    def _publish_map_update(self, result):
        msg = ResourceMapUpdate()
        msg.scout_id = self._robot_id
        msg.location = Point(
            x=result.position[0], y=result.position[1], z=0.0
        )
        msg.ice_concentration = float(result.ice_concentration)
        msg.sensor_uncertainty = float(result.uncertainty)
        msg.stamp = self.get_clock().now().to_msg()
        self._map_update_pub.publish(msg)


# ===================================================================
# Entry point
# ===================================================================


def main(args=None):
    rclpy.init(args=args)
    node = AgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info(f"[{node._robot_id}] Shutting down agent node")
        if hasattr(node, "_hal"):
            node._hal.shutdown()
        node.destroy_node()
        rclpy.shutdown()
