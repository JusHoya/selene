"""Per-robot agent ROS 2 node for SELENE lunar ISRU fleet.

Wires together the FSM, HAL, Navigator, EnergyManager, and Skills
into an autonomous agent that prospects waypoints, monitors battery,
and returns to recharge when energy is critical.

Supports two operating modes:
  - standalone (orchestrated=False, default): self-directed waypoint list
  - orchestrated (orchestrated=True): auction-based task assignment from
    the fleet orchestrator
"""

from __future__ import annotations

import math
import time
import yaml

import rclpy
from rclpy.node import Node

from selene_msgs.msg import RobotState, ResourceMapUpdate
from selene_msgs.msg import TaskAnnouncement, TaskAssignment, BidResponse
from geometry_msgs.msg import Pose2D, Twist, Point
from nav_msgs.msg import Path

from selene_hal import create_hal
from selene_agent.fsm import AgentFSM, AgentState, FSMEvent
from selene_agent.energy_manager import EnergyManager
from selene_agent.navigator import Navigator, OccupancyGrid
from selene_agent.skills import ProspectSkill, ExcavateSkill, HaulSkill, RechargeSkill
from selene_agent.skills.prospect import ProspectPhase
from selene_agent.skills.excavate import ExcavatePhase
from selene_agent.skills.haul import HaulPhase


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
        self.declare_parameter("orchestrated", False)
        self.declare_parameter("auction_timeout_sec", 7.0)  # slightly > orchestrator's 5s
        self.declare_parameter("bid_weight_distance", 0.4)
        self.declare_parameter("bid_weight_energy", 0.35)
        self.declare_parameter("bid_weight_capability", 0.25)

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
        self._orchestrated = self.get_parameter("orchestrated").get_parameter_value().bool_value
        self._auction_timeout = self.get_parameter("auction_timeout_sec").get_parameter_value().double_value

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
        if not self._orchestrated:
            mission = nav_config.get("mission", {})
            raw_waypoints = mission.get("prospect_waypoints", [])
            self._waypoints = [(float(wp[0]), float(wp[1])) for wp in raw_waypoints]
        else:
            self._waypoints = []
        self._waypoint_index = 0

        # -- Skill tracking ------------------------------------------------------
        self._current_skill = None
        self._current_task_id = ""
        self._was_navigating = False  # tracks ProspectSkill NAVIGATING->SETTLING transition

        # -- Auction state tracking ----------------------------------------------
        self._bidding_since: float = 0.0
        self._pending_task_id: str = ""
        self._assigned_target: tuple[float, float] | None = None
        self._assigned_task_type: str = "prospect"

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
        self._bid_pub = self.create_publisher(
            BidResponse, "/orchestrator/bid_response", 10
        )

        # -- Orchestrated-mode subscribers ---------------------------------------
        if self._orchestrated:
            self.create_subscription(
                TaskAnnouncement, "/orchestrator/task_announcement",
                self._on_task_announced, 10)
            self.create_subscription(
                TaskAssignment, "/orchestrator/task_assignment",
                self._on_task_assigned, 10)

        # -- Timers --------------------------------------------------------------
        tick_period = 1.0 / self._tick_rate
        self._tick_timer = self.create_timer(tick_period, self._tick)
        self._state_timer = self.create_timer(0.5, self._publish_state)  # 2 Hz

        # -- Startup log ---------------------------------------------------------
        self.get_logger().info(
            f"[{self._robot_id}] AgentNode started | type={self._robot_type} "
            f"mode={'orchestrated' if self._orchestrated else 'standalone'} "
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
        elif state == AgentState.BIDDING:
            self._handle_bidding(dt)
        elif state == AgentState.ASSIGNED:
            self._handle_assigned()
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
        if self._orchestrated:
            return  # Wait for task announcement from orchestrator

        # Wait for valid odometry before planning any path
        odom = self._hal.get_sensor("odometry").read()
        if not odom.is_valid:
            return

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

    def _handle_bidding(self, dt: float):
        """Monitor auction timeout while waiting for assignment."""
        elapsed = time.time() - self._bidding_since
        if elapsed > self._auction_timeout:
            self.get_logger().info(
                f"[{self._robot_id}] Auction timeout for {self._pending_task_id}"
            )
            self._fsm.handle_event(FSMEvent.AUCTION_LOST)
            self._pending_task_id = ""

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

        # Detect transition from NAVIGATING to work phase (arrival).
        # Each skill type has a different enum for its navigation phase.
        if self._was_navigating:
            phase = self._current_skill._phase
            still_navigating = (
                phase == ProspectPhase.NAVIGATING
                or phase == ExcavatePhase.NAVIGATING
                or phase == HaulPhase.NAVIGATING_TO_PICKUP
            )
            if not still_navigating:
                self._was_navigating = False
                self._fsm.handle_event(FSMEvent.ARRIVED)
                self.get_logger().info(
                    f"[{self._robot_id}] Arrived at waypoint {self._waypoint_index}, "
                    f"phase={phase.value}"
                )

    def _handle_working(self, dt: float):
        """Let current skill work; publish result on completion."""
        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.is_complete():
            skill_name = self._current_skill.get_name()

            if skill_name == "prospect":
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

            elif skill_name == "excavate":
                result = self._current_skill.get_result()
                if result is not None:
                    self.get_logger().info(
                        f"[{self._robot_id}] Excavation complete: "
                        f"extracted={result.extracted_kg:.1f}kg "
                        f"hopper_full={result.hopper_full}"
                    )

            elif skill_name == "haul":
                result = self._current_skill.get_result()
                if result is not None:
                    self.get_logger().info(
                        f"[{self._robot_id}] Haul complete: "
                        f"delivered={result.delivered_kg:.1f}kg "
                        f"to depot {result.depot_position}"
                    )

            self._current_task_id = ""
            self._current_skill = None
            self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
            self._start_recharge()

        elif self._current_skill.has_failed():
            skill_name = self._current_skill.get_name()
            self.get_logger().error(
                f"[{self._robot_id}] {skill_name.capitalize()} failed at waypoint {self._waypoint_index}: "
                f"{self._current_skill.get_error()}"
            )
            if skill_name == "prospect":
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
    # Orchestrated-mode callbacks
    # ===================================================================

    def _on_task_announced(self, msg):
        """Evaluate task and submit bid if eligible."""
        if self._fsm.state != AgentState.IDLE:
            return

        # Capability check
        my_caps = set(self._hal.get_capabilities())
        required = set(msg.required_capabilities)
        if not required.issubset(my_caps):
            return

        # Position (stale odom only affects bid score — navigation is
        # gated by _handle_assigned which waits for valid odometry)
        try:
            odom = self._hal.get_sensor("odometry").read()
            my_pos = (odom.x, odom.y)
        except Exception:
            return

        task_pos = (msg.target_location.x, msg.target_location.y)

        # Energy check
        if not self._energy_manager.can_afford_task(my_pos, task_pos, msg.estimated_energy_cost):
            return

        # Compute bid score
        distance = math.hypot(task_pos[0] - my_pos[0], task_pos[1] - my_pos[1])
        w_dist = self.get_parameter("bid_weight_distance").get_parameter_value().double_value
        w_energy = self.get_parameter("bid_weight_energy").get_parameter_value().double_value
        w_cap = self.get_parameter("bid_weight_capability").get_parameter_value().double_value

        dist_score = 1.0 / (1.0 + distance / 100.0)
        energy_cost = self._energy_manager.compute_energy_cost_wh(distance, msg.estimated_energy_cost)
        remaining = self._energy_manager.get_remaining_wh()
        energy_score = min(remaining / max(energy_cost, 0.01), 1.0)
        cap_score = 1.0 if required.issubset(my_caps) else 0.0

        bid_score = w_dist * dist_score + w_energy * energy_score + w_cap * cap_score

        # ETA
        speed = self._hal.get_kinematics().get_max_speed()
        eta = distance / max(speed, 0.1)
        energy_after = max(remaining - energy_cost, 0.0)

        # Transition to BIDDING
        self._fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
        self._bidding_since = time.time()
        self._pending_task_id = msg.task_id

        # Publish bid
        bid = BidResponse()
        bid.task_id = msg.task_id
        bid.robot_id = self._robot_id
        bid.bid_score = float(bid_score)
        bid.estimated_arrival_time = float(eta)
        bid.energy_after_task = float(energy_after)
        self._bid_pub.publish(bid)

        self.get_logger().info(
            f"[{self._robot_id}] Bid on {msg.task_id}: score={bid_score:.3f} eta={eta:.1f}s")

    def _on_task_assigned(self, msg):
        """Handle task assignment from orchestrator.

        Stores the assignment and transitions to ASSIGNED.  The actual
        skill startup is deferred to ``_handle_assigned()`` in the tick
        loop so it can safely wait for valid odometry.
        """
        if msg.robot_id != self._robot_id:
            # Not for me -- if I was bidding on this task, I lost
            if self._fsm.state == AgentState.BIDDING and self._pending_task_id == msg.task_id:
                self._fsm.handle_event(FSMEvent.AUCTION_LOST)
                self._pending_task_id = ""
            return

        # I won
        self.get_logger().info(f"[{self._robot_id}] Assigned task {msg.task_id}")

        if self._fsm.state == AgentState.BIDDING:
            self._fsm.handle_event(FSMEvent.AUCTION_WON)
        elif self._fsm.state != AgentState.ASSIGNED:
            self.get_logger().warn(
                f"[{self._robot_id}] Assignment in state {self._fsm.state.value}, ignoring")
            return

        # Store assignment — skill startup deferred to _handle_assigned()
        self._assigned_target = (msg.target_location.x, msg.target_location.y)
        self._assigned_task_type = msg.task_type
        self._current_task_id = msg.task_id
        self._pending_task_id = ""

    def _handle_assigned(self):
        """Start navigation for the assigned task.

        Called from the tick loop while in ASSIGNED state.  If path
        planning fails (e.g. odometry not ready yet), retries on the
        next tick instead of faulting.
        """
        target = self._assigned_target
        task_type = self._assigned_task_type
        if target is None:
            return

        # Create skill based on task type
        if task_type == "prospect":
            skill = ProspectSkill()
            skill.start(self._hal, self._navigator, target=target)
        elif task_type == "excavate":
            skill = ExcavateSkill()
            skill.start(self._hal, self._navigator, target=target)
        elif task_type == "haul":
            skill = HaulSkill()
            # Target is pickup location; depot is the recharge/depot position
            depot = (self._recharge_x, self._recharge_y)
            skill.start(self._hal, self._navigator, pickup=target, depot=depot)
        else:
            self.get_logger().error(f"[{self._robot_id}] Unknown task type: {task_type}")
            self._fsm.handle_event(FSMEvent.FAULT)
            return
        if skill.has_failed():
            # Planning failed (likely odom not ready) — retry next tick
            return

        self._current_skill = skill
        self._was_navigating = True
        self._assigned_target = None
        self._fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)

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
