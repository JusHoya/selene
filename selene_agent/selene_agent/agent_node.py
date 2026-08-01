"""Per-robot agent ROS 2 node for SELENE lunar ISRU fleet.

Wires together the FSM, HAL, Navigator, EnergyManager, and Skills
into an autonomous agent that prospects waypoints, monitors battery,
and returns to recharge when energy is critical.

RECHARGE POLICY (deviation D-19, 2026-07-31). This node used to end every
task with an unconditional ``_start_recharge()``, so a robot drove home and
charged after every single waypoint at whatever battery it happened to hold.
The decision now lives in ``_recharge_reason()`` -> ``_settle_after_task()``
and is made from ``EnergyManager.recharge_reason()``: critical, below the
configured ``recharge_threshold`` floor, or out of margin to get home.

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
from rclpy.qos import (
    DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy,
)

from selene_msgs.msg import RobotState, ResourceMapUpdate
from selene_msgs.msg import TaskAnnouncement, TaskAssignment, BidResponse
from selene_msgs.msg import MaterialEvent, TaskResult, FleetAlert
from geometry_msgs.msg import Pose2D, Twist, Point
from nav_msgs.msg import Path

try:
    from selene_msgs.srv import SetRobotCommand
except ImportError:  # pragma: no cover - srv not built yet
    class SetRobotCommand:  # type: ignore
        class Request:
            def __init__(self):
                self.command = ''
                self.target = Point()
                self.sequence = 0

        class Response:
            def __init__(self):
                self.accepted = False
                self.reason = ''

from selene_hal import create_hal
from selene_agent.fsm import AgentFSM, AgentState, FSMEvent
from selene_agent.energy_manager import EnergyManager
from selene_agent.navigator import (
    Navigator, OccupancyGrid, audit_terrain_reachability,
)
from selene_agent.skills import ProspectSkill, ExcavateSkill, HaulSkill, RechargeSkill
from selene_agent.skills.prospect import ProspectPhase
from selene_agent.skills.excavate import ExcavatePhase
from selene_agent.skills.haul import HaulPhase
from selene_agent.operator_command import (
    _OperatorCommandContext,
    operator_command_logic,
)
from selene_agent.recharge_policy import (
    UNAFFORDABLE_PASSES_BEFORE_RECHARGE,
    _RechargeContext,
    begin_recharge_cycle_logic,
    settle_after_task_logic,
    should_recharge_after_refusals,
    validated_recharge_threshold,
)
from selene_agent.material_events import (
    MaterialEventIdGenerator,
    build_material_event_fields,
)


# QoS for the two agent -> orchestrator report topics added closing D-06/D-03.
#
# RELIABLE + TRANSIENT_LOCAL, unlike every other publisher on this node. These
# two topics are the material ledger and the task outcome log: a dropped
# MaterialEvent is mass that vanishes from mission progress with nothing
# logged anywhere, and a dropped TaskResult leaves a finished task showing as
# IN_PROGRESS forever. Transient-local also means an orchestrator that starts
# (or restarts) after an agent still receives that agent's history;
# MaterialEvent.event_id makes that replay idempotent on the subscriber side.
#
# NOT VERIFIED: no ROS install exists on the machine this was written on, so
# Fast DDS's actual transient-local replay behaviour was never exercised. The
# event_id dedupe is designed so that a wrong assumption degrades to LOST
# HISTORY, never to double-counted mass.
#
# Depth 100 is roughly 6x the events a 100 kg mission generates (5 excavate
# tasks -> 5 'extracted', 5 haul tasks -> 5 'loaded' + 5 'unloaded' = 15).
MATERIAL_EVENT_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=100,
)
TASK_RESULT_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=50,
)


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
        # THE RECHARGE STATION, AND IT IS THE ONLY ONE NOW (deviation D-32).
        # Three coordinates used to disagree: this pair, which is what actually
        # reaches the agent; `mission.recharge_position: [-75, -100]` in
        # nav_params.yaml, read by nothing and on 33.91 deg ground; and
        # RechargeSkill's (40, 40) constructor default. The nav_params key is
        # deleted, and this pair is the physical `recharge_pad` <include> in
        # selene_sim/worlds/lunar_psr.sdf and `world.recharge_station.position`
        # in selene_sim/config/world_params.yaml. It is passed explicitly by
        # selene_agent/launch/agent.launch.py so the number is in the dict the
        # agent is handed rather than only in this default.
        self.declare_parameter("recharge_x", -30.0)
        self.declare_parameter("recharge_y", -100.0)
        # READ ONLY BY THE STARTUP REACHABILITY AUDIT, and that is the whole
        # reason it is allowed to exist as a fourth statement of the depot. The
        # audit has to name the two places the mission REQUIRES this robot to
        # reach, and "3 connected components" is a statistic while "depot NOT
        # REACHABLE" is an operator action. The authority remains depot_x /
        # depot_y in selene_orchestrator/config/orchestrator_params.yaml -- what
        # rides on TaskAssignment.depot_location and actually directs a haul --
        # and selene_agent/test/test_startup_reachability_audit.py fails the
        # build if this default stops agreeing with it.
        self.declare_parameter("depot_x", -100.0)
        self.declare_parameter("depot_y", -150.0)
        self.declare_parameter("energy_critical_threshold", 0.15)
        self.declare_parameter("energy_recharge_target", 0.90)
        # D-19. THE RECHARGE FLOOR, AND IT LIVES ON THE AGENT NOW.
        #
        # It used to be declared by the ORCHESTRATOR
        # (selene_orchestrator/orchestrator_node.py, and set in
        # selene_orchestrator/config/orchestrator_params.yaml) where nothing
        # read it -- one of the two names on
        # selene_orchestrator/test/test_no_orphan_parameters.py's allow-list.
        # The recharge decision is made here, by this node, in
        # _recharge_reason(); a knob for it on a node that cannot act on it is
        # the same defect as the bid weights (D-13) and the same fix.
        #
        # NAME PRESERVED ACROSS THE MOVE, deliberately, exactly as the three
        # bid_weight_* names were: `recharge_threshold` is what the register,
        # the params file and four phases of git history call it, and its
        # neighbours' `energy_` prefix is not worth breaking that trail for.
        self.declare_parameter("recharge_threshold", 0.30)
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
        self._depot_xy = (
            self.get_parameter("depot_x").get_parameter_value().double_value,
            self.get_parameter("depot_y").get_parameter_value().double_value,
        )
        energy_critical = (
            self.get_parameter("energy_critical_threshold").get_parameter_value().double_value
        )
        self._energy_recharge_target = (
            self.get_parameter("energy_recharge_target").get_parameter_value().double_value
        )
        self._recharge_threshold, threshold_complaint = (
            validated_recharge_threshold(
                self.get_parameter(
                    "recharge_threshold").get_parameter_value().double_value,
                energy_critical,
                self._energy_recharge_target,
            )
        )
        self._tick_rate = self.get_parameter("tick_rate").get_parameter_value().double_value
        self._orchestrated = self.get_parameter("orchestrated").get_parameter_value().bool_value
        self._auction_timeout = (
            self.get_parameter("auction_timeout_sec").get_parameter_value().double_value
        )

        # -- Create HAL ----------------------------------------------------------
        self._hal = create_hal(rcdl_path, self._robot_id, backend=hal_backend, ros_node=self)

        # -- Load navigation config ----------------------------------------------
        with open(nav_config_path, "r") as f:
            nav_config = yaml.safe_load(f)

        # -- Create occupancy grid and navigator ---------------------------------
        # The planned-path publisher is created here (ahead of the other
        # publishers) because Navigator needs it at construction time. The
        # dashboard subscribes to '/<robot_id>/planned_path' (see
        # selene_dashboard/src/utils/rosTopics.js PLANNED_PATH), so the
        # publisher must be owned here where robot_id is known; Navigator no
        # longer creates its own relative-name 'planned_path' publisher.
        # THE TERRAIN COMES WITH THE GRID (deviation D-28). from_config loads
        # the committed heightmap whenever navigation.max_traversable_slope_deg
        # is present, and RAISES rather than continuing on flat ground if it
        # cannot find it. That abort is deliberate and it is the loud end of the
        # guard: an agent that came up believing every slope was zero would look
        # identical to a working one until a hauler pinned on a wall, which is
        # the 2026-07-31 run this whole workstream came out of.
        grid = OccupancyGrid.from_config(nav_config)
        nav_section = nav_config.get("navigation", {})
        self._path_pub = self.create_publisher(
            Path, f"/{self._robot_id}/planned_path", 10
        )
        self._navigator = Navigator(
            self._hal, grid, ros_node=self, path_publisher=self._path_pub,
            # Both of these reached nothing before 2026-08-01. Navigator built
            # AStarPlanner(grid) and PathFollower(...) with no arguments, so
            # navigation.slope_penalty_weight and the whole path_follower: block
            # were settable and inert -- seven keys, the same defect as the bid
            # weights in D-13.
            slope_penalty_weight=float(
                nav_section.get("slope_penalty_weight", 2.0)),
            path_follower_config=nav_config.get("path_follower"),
        )
        self._nav_grid = grid

        # -- Create energy manager -----------------------------------------------
        recharge_station = (self._recharge_x, self._recharge_y)
        self._energy_manager = EnergyManager(
            self._hal.get_battery(),
            critical_threshold=energy_critical,
            recharge_target=self._energy_recharge_target,
            recharge_station=recharge_station,
            recharge_threshold=self._recharge_threshold,
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
        # TaskAssignment.quantity_kg / depot_location for the current
        # assignment. 0.0 means unconstrained; None means the assignment
        # carried no usable depot and _handle_assigned must fall back.
        self._assigned_quantity_kg: float = 0.0
        self._assigned_depot: tuple[float, float] | None = None

        # -- Operator override state ---------------------------------------------
        self._operator_target: tuple[float, float] | None = None
        self._last_operator_seq: int = -1

        # -- D-19: consecutive announcements passed on for want of energy --------
        # Counts task announcements this robot was CAPABLE of and declined
        # solely because ``can_afford_task`` said no. See
        # ``_note_unaffordable_announcement`` for why this exists at all.
        self._unaffordable_passes: int = 0

        # -- Publishers ----------------------------------------------------------
        self._state_pub = self.create_publisher(
            RobotState, f"/{self._robot_id}/state", 10
        )
        # D-42. The operator's channel for faults in this agent's own inputs.
        # /orchestrator/alerts is the one path that reaches the dashboard
        # (FR-DASH-4) and the exit-gate probe; world_odometry_node publishes
        # here for the same reason and documents the trade at its own
        # create_publisher. Only _check_battery_health uses it today.
        self._alert_pub = self.create_publisher(FleetAlert, "/orchestrator/alerts", 10)
        # D-34. Publish a RobotState on every FSM transition as well as on the
        # 0.5 s timer below, so a state shorter than the sampling period is on
        # the wire at all.
        #
        # ATTACHED HERE AND NOT AT THE AgentFSM(...) CALL, which is ~40 lines
        # above. _on_fsm_transition -> _build_state_msg reads self._state_pub
        # (this line), self._current_skill and self._current_task_id (set in
        # the skill-tracking block). Passing on_transition to the constructor
        # would make AgentNode.__init__ order-sensitive: any transition fired
        # between the FSM's construction and this line would raise
        # AttributeError out of a constructor, and nothing in the class would
        # say why. Attaching last means the observer cannot fire before
        # everything it touches exists. The callback is defensive about
        # _state_pub anyway; this ordering is what makes that check redundant
        # rather than load-bearing.
        self._fsm.set_transition_observer(self._on_fsm_transition)
        # NOTE: self._path_pub is created earlier, next to the Navigator it
        # is handed to (see the occupancy-grid/navigator block above).
        self._map_update_pub = self.create_publisher(
            ResourceMapUpdate, "/orchestrator/map_update", 10
        )
        self._bid_pub = self.create_publisher(
            BidResponse, "/orchestrator/bid_response", 10
        )
        # Measured mass transfers and terminal task outcomes (D-06 / D-03).
        # Created in both operating modes: in standalone mode nothing
        # subscribes, so publishing costs a serialisation and no more, and
        # keeping the code path identical means the orchestrated path is not
        # a separate, less-exercised branch.
        self._material_event_pub = self.create_publisher(
            MaterialEvent, "/orchestrator/material_event", MATERIAL_EVENT_QOS
        )
        self._task_result_pub = self.create_publisher(
            TaskResult, "/orchestrator/task_result", TASK_RESULT_QOS
        )
        # time.time_ns() rather than a ROS clock: this only has to be
        # different across restarts of this process, and it must be available
        # before any clock source is guaranteed to have ticked.
        self._event_ids = MaterialEventIdGenerator(
            self._robot_id, time.time_ns()
        )

        # -- Orchestrated-mode subscribers ---------------------------------------
        if self._orchestrated:
            self.create_subscription(
                TaskAnnouncement, "/orchestrator/task_announcement",
                self._on_task_announced, 10)
            self.create_subscription(
                TaskAssignment, "/orchestrator/task_assignment",
                self._on_task_assigned, 10)

        # -- Operator command service --------------------------------------------
        # Per-robot service that lets the orchestrator (and ultimately the
        # dashboard) cancel tasks, send the robot to a waypoint, or force a
        # recharge cycle. Available in both standalone and orchestrated modes.
        self._operator_srv = self.create_service(
            SetRobotCommand,
            f'/{self._robot_id}/set_command',
            self._on_operator_command,
        )

        # -- Timers --------------------------------------------------------------
        # D-28: the startup reachability audit fires on the first tick that has
        # a valid pose, not here. See _run_terrain_audit_once for why.
        #
        # SET BEFORE THE TIMER THAT READS IT, which is the D-34 lesson about
        # _fsm.set_transition_observer applied to a flag instead of a callback:
        # anything a timer callback touches must exist before the timer does, or
        # the failure is an AttributeError raised inside a callback with nothing
        # in the class to say why. _run_terrain_audit_once still reads it
        # defensively; this ordering is what makes that check redundant rather
        # than load-bearing.
        self._terrain_audit_done = False
        tick_period = 1.0 / self._tick_rate
        self._tick_timer = self.create_timer(tick_period, self._tick)
        self._state_timer = self.create_timer(0.5, self._publish_state)  # 2 Hz
        self._tick_count = 0
        # THE ENERGY-CRITICAL GRACE PERIOD IS GONE (D-42); this counter now has
        # exactly one reader, ``_note_unaffordable_announcement``, where "has the
        # mission started yet" is genuinely a question about elapsed time rather
        # than about data arrival. See ``_tick`` for why a clock was the wrong
        # instrument for the battery question and ``is_valid`` is the right one.
        self._startup_grace_ticks = int(5.0 * self._tick_rate)

        # -- D-42 battery-channel health ------------------------------------
        # Latches, so each fault is reported once rather than at 10 Hz. The
        # publisher-count latch stores the COUNT, so a stack going from two
        # publishers to three says so again.
        self._battery_pubs_reported = 0
        self._battery_silence_reported = False
        self._battery_stale_reported = False
        self._first_tick_wall: float | None = None
        # STARTS TRUE. _check_battery_health runs before the energy branch on
        # every tick and sets it from a live count; defaulting it false would
        # suspend the energy rule on tick 1 of a perfectly healthy robot.
        self._battery_channel_attributable = True

        # -- Startup log ---------------------------------------------------------
        self.get_logger().info(
            f"[{self._robot_id}] AgentNode started | type={self._robot_type} "
            f"mode={'orchestrated' if self._orchestrated else 'standalone'} "
            f"backend={hal_backend} tick={self._tick_rate}Hz "
            f"waypoints={len(self._waypoints)} "
            f"recharge=({self._recharge_x}, {self._recharge_y}) "
            f"recharge_floor={self._recharge_threshold:.0%} "
            f"critical={energy_critical:.0%} "
            f"target={self._energy_recharge_target:.0%}"
        )
        if threshold_complaint:
            self.get_logger().error(
                f"[{self._robot_id}] {threshold_complaint}"
            )

    # ===================================================================
    # Main loop (10 Hz)
    # ===================================================================

    def _tick(self):
        dt = 1.0 / self._tick_rate
        self._tick_count += 1
        if self._first_tick_wall is None:
            self._first_tick_wall = self._clock_now()

        self._run_terrain_audit_once()

        # Read current state from HAL
        try:
            battery_state = self._hal.get_battery().get_state()
        except Exception as e:
            self.get_logger().warn(f"[{self._robot_id}] Sensor read failed: {e}")
            return

        # Update energy manager
        self._energy_manager.update(battery_state)
        self._check_battery_health(battery_state)

        # Battery critical check.
        #
        # THE GATE IS `is_valid`, NOT A CLOCK. This used to read
        # `self._tick_count > self._startup_grace_ticks` -- a flat 5 s of wall
        # clock -- under a comment claiming it was there "so DDS can deliver the
        # first real battery reading (avoids 0% phantom)". Two things were wrong
        # with that, and D-42 cost the exit gate its green on both.
        #
        # First, the mechanism the comment described did not exist. Neither HAL
        # battery has ever reported a phantom 0% before its first message; both
        # construct their cache FULL, so the pre-message reading was 100% and a
        # grace period protected against nothing. What the HAL could not do was
        # SAY it had no reading, which is now `BatteryState.is_valid`.
        #
        # Second, a wall clock cannot express the condition anyway. On
        # 2026-08-01 `agent_scout_02` fired at 6.152 s -- 1.15 s past the grace,
        # and the grace's own comment is the reason it was 5.0 rather than 7.5.
        # A duration tuned against one observation is a guess about the next one.
        # `is_valid` is not a guess: it is false until a message has been handled
        # by `GazeboBattery._cb` and true forever after.
        #
        # AND THE RULE IS SUSPENDED ON AN UNATTRIBUTABLE CHANNEL. When the
        # battery topic has more than one publisher, `GazeboBattery._cb` caches
        # whichever message arrived last with no notion of source, so the value
        # is not this robot's charge -- it is a sample from an interleaved
        # stream. Acting on it is what took the 2026-08-01 exit gate down.
        #
        # THIS IS A REFUSAL, NOT A FILTER, and the distinction is the one this
        # repository keeps having to relearn. Nothing is discarded, smoothed or
        # median-ed: every reading still reaches EnergyManager, still appears in
        # RobotState.battery_level, and still reaches the dashboard. What stops
        # is the AUTOMATIC ACTION, and `_check_battery_health` has already raised
        # a CRITICAL FleetAlert naming the publisher count.
        #
        # THE TRADE-OFF, STATED. A robot whose battery really is flat during
        # contamination will not take itself to the charger, and could strand.
        # That is accepted deliberately: the reading that would have triggered
        # the recharge is, by construction, not known to be about this robot, so
        # the alternative is not "safe behaviour" but "behaviour driven by
        # another robot's battery". An operator who has been told CRITICAL that
        # a robot's battery channel has two publishers can issue force_recharge;
        # an operator whose fleet drove itself to the pad on a stranger's
        # telemetry was given no decision at all.
        if (
            self._battery_channel_attributable
            and self._energy_manager.is_critical()
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
    # Startup reachability audit — deviation D-28 / D-32
    # ===================================================================

    def _run_terrain_audit_once(self):
        """Log, exactly once, what the slope limit does to this robot's world.

        WHY IT IS NOT IN ``__init__``. The audit's most useful output is whether
        THIS ROBOT'S OWN position can reach the depot and the recharge pad, and
        at construction time this node has no position: ``GazeboOdometrySensor``
        hands back a cached reading with ``is_valid=False`` and x, y at 0.0
        until the first ``/odom_world`` message arrives (register D-31). An
        audit run there would have reported reachability from the world origin
        for every robot in the fleet -- a confident answer about a place none of
        them is, which is D-31's defect wearing a different hat. So it waits for
        a real fix, and the flag makes it fire once.

        WHAT IT COSTS. ``per_step_components`` measured 2.0 s on the shipped
        500 x 500 lattice, and this runs inside the 10 Hz tick callback, so that
        tick is ~2 s late. Once, during the 5 s startup grace window, before any
        robot has been given work. Accepted rather than hidden: moving it to a
        thread would buy a deferred log line and a race with the first plan.

        IT REPORTS AND NEVER REFUSES. No branch here can stop the agent, fault
        it, or change a decision. If the depot is unreachable the mission is
        already broken and the operator needs to know before a hauler sets off,
        which is the one thing the 2026-07-31 run could not do.
        """
        if getattr(self, '_terrain_audit_done', False):
            return
        try:
            odom = self._hal.get_sensor("odometry").read()
        except Exception:                       # noqa: BLE001 - report-only path
            return
        if not odom.is_valid:
            return
        self._terrain_audit_done = True
        try:
            audit = audit_terrain_reachability(
                self._nav_grid,
                (odom.x, odom.y),
                landmarks={
                    'depot': self._depot_xy,
                    'recharge_pad': (self._recharge_x, self._recharge_y),
                },
            )
        except Exception as e:                  # noqa: BLE001 - report-only path
            self.get_logger().warn(
                f"[{self._robot_id}] terrain reachability audit failed: {e}")
            return
        audit.report(
            lambda line: self.get_logger().info(f"[{self._robot_id}] {line}"))
        for name in audit.unreachable_landmarks:
            self.get_logger().error(
                f"[{self._robot_id}] {name} at {audit.landmarks[name]} is NOT "
                f"reachable from this robot's start position under the "
                f"{audit.limit_deg} deg per-step slope limit. The mission "
                f"cannot close for this robot and nothing downstream will say "
                f"so -- a hauler sent there will pin on the slope, keep turning "
                f"its wheels, and report success (register D-23/D-24)."
            )

    # ===================================================================
    # State handlers
    # ===================================================================

    def _handle_idle(self):
        """Pick the next waypoint, create a ProspectSkill, and start navigating.

        The recharge check runs FIRST and in both operating modes, because
        IDLE is where a robot that declined to recharge after its last task
        comes to rest. Without it, the only thing that would ever send an idle
        robot home is the 15% ENERGY_CRITICAL branch in ``_tick``, which for a
        scout drawing 10 W idle out of 50 Wh is over an hour away (D-19).
        """
        # Wait for valid odometry before planning ANY path, the recharge path
        # included. Reading it here rather than after the orchestrated
        # early-return below is a change of order, not of meaning: the
        # standalone branch always did this, and a recharge cycle started
        # without a position fails RechargeSkill.start(), which routes the
        # robot to ERROR through _handle_returning. Turning "odom is not ready
        # yet" into a faulted robot would be a worse bug than the one D-19
        # fixes.
        try:
            odom = self._hal.get_sensor("odometry").read()
        except Exception as e:
            self.get_logger().warn(
                f"[{self._robot_id}] Odometry read failed while idle: {e}"
            )
            return
        if not odom.is_valid:
            return

        reason = self._recharge_reason()
        if reason:
            self._begin_recharge_cycle(reason)
            return

        if self._orchestrated:
            return  # Wait for task announcement from orchestrator

        if self._waypoint_index >= len(self._waypoints):
            self.get_logger().info(
                f"[{self._robot_id}] Mission complete -- "
                f"all {len(self._waypoints)} waypoints visited"
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
        # Operator override_goto pseudo-task: navigator drives directly
        # without a wrapping skill. Treat arrival as completion → IDLE.
        if self._current_task_id.startswith("override_goto_"):
            nav_status = self._navigator.update(dt)
            if nav_status == "goal_reached":
                self.get_logger().info(
                    f"[{self._robot_id}] Operator goto complete, returning to IDLE"
                )
                try:
                    self._hal.get_actuator("drive").stop()
                except (KeyError, AttributeError):
                    pass
                self._navigator.stop()
                self._current_task_id = ""
                self._operator_target = None
                self._fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
            elif nav_status == "blocked":
                self.get_logger().error(
                    f"[{self._robot_id}] Operator goto path blocked"
                )
                self._current_task_id = ""
                self._operator_target = None
                self._fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
            return

        if self._current_skill is None:
            return

        self._current_skill.update(dt)

        if self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Navigation failed: {self._current_skill.get_error()}"
            )
            # Release the task id BEFORE entering ERROR. The orchestrator only
            # re-queues an interrupted task when it sees fsm_state == 'ERROR'
            # AND current_task_id == '' (orchestrator_node._on_robot_state);
            # holding the id here strands the task on a faulted robot forever.
            self._current_task_id = ""
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
            # Capture the task id before the clean-up below blanks it: every
            # report published from here is keyed on it, and the orchestrator
            # resolves the extraction site from it (TaskEntry.site_id).
            task_id = self._current_task_id

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
                    # One measured transfer -> one MaterialEvent. This is the
                    # only place an excavated mass leaves the robot; before
                    # this it was formatted into the log line above and
                    # discarded, which is why MaterialInventory had no
                    # production caller and mission progress was structurally
                    # zero (register D-06).
                    self._publish_material_event(
                        task_id, 'extracted',
                        result.extracted_kg, result.residual_mass_kg,
                    )

            elif skill_name == "haul":
                result = self._current_skill.get_result()
                if result is not None:
                    self.get_logger().info(
                        f"[{self._robot_id}] Haul complete: "
                        f"loaded={result.loaded_kg:.1f}kg "
                        f"delivered={result.delivered_kg:.1f}kg "
                        f"to depot {result.depot_position}"
                    )
                    # TWO events, not one. A haul performs two physically
                    # distinct transfers and the ledger's
                    # extracted/in_transit/deposited split is exactly the
                    # difference between them, so a single per-task report
                    # would lose one. residual_mass_kg belongs to the unload:
                    # it is what the bin still held after the dump.
                    self._publish_material_event(
                        task_id, 'loaded',
                        result.loaded_kg, result.bin_mass_after_load_kg,
                    )
                    self._publish_material_event(
                        task_id, 'unloaded',
                        result.delivered_kg, result.residual_mass_kg,
                    )

            self._publish_task_result(task_id, skill_name, True, "")
            self._current_task_id = ""
            self._current_skill = None
            self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
            self._settle_after_task()

        elif self._current_skill.has_failed():
            skill_name = self._current_skill.get_name()
            task_id = self._current_task_id
            failure_reason = self._current_skill.get_error()
            self.get_logger().error(
                f"[{self._robot_id}] {skill_name.capitalize()} failed at "
                f"waypoint {self._waypoint_index}: "
                f"{failure_reason}"
            )
            if skill_name == "prospect":
                self._waypoint_index += 1
            # Report the failure BEFORE the FSM event, while the task id is
            # still held. This is the only way TaskStatus.FAILED becomes
            # reachable at all: the FSM event below is TASK_COMPLETE on both
            # branches, so orchestrator_node._on_robot_state sees the same
            # RETURNING-with-no-task shape either way and marked a failed
            # excavate COMPLETED in its own queue (register D-03).
            #
            # The FSM event is DELIBERATELY left as TASK_COMPLETE. Firing
            # FAULT instead would route the robot to ERROR and change fleet
            # recovery behaviour under any transient skill failure; the agent
            # keeps its recovery semantics and simply says what happened.
            self._publish_task_result(
                task_id, skill_name, False, failure_reason,
            )
            self._current_task_id = ""
            self._current_skill = None
            self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
            # D-19: a FAILED task gets the same energy test as a successful
            # one. It is tempting to send a robot home after a failure "to be
            # safe", but the failure this branch actually sees most is a
            # navigation timeout, and a robot that recharges after every one
            # of those is the fleet-wide stall D-19 was opened for, with an
            # extra step. If the robot is short of energy, _recharge_reason
            # says so on this call exactly as it would after a success.
            self._settle_after_task()

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
            # Release the task id before entering ERROR (see _handle_navigating).
            self._current_task_id = ""
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

        if self._current_skill.has_failed():
            self.get_logger().error(
                f"[{self._robot_id}] Recharge failed: "
                f"{self._current_skill.get_error()}"
            )
            # Release the task id before entering ERROR (see _handle_navigating).
            self._current_task_id = ""
            self._fsm.handle_event(FSMEvent.FAULT)
            return

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

        # Energy check. A refusal here used to be a silent `return`, which was
        # harmless while every completed task ended in a full recharge. It is
        # not harmless now: see _note_unaffordable_announcement (D-19).
        if not self._energy_manager.can_afford_task(my_pos, task_pos, msg.estimated_energy_cost):
            self._note_unaffordable_announcement(msg.task_id)
            return

        # Compute bid score
        distance = math.hypot(task_pos[0] - my_pos[0], task_pos[1] - my_pos[1])
        w_dist = self.get_parameter("bid_weight_distance").get_parameter_value().double_value
        w_energy = self.get_parameter("bid_weight_energy").get_parameter_value().double_value
        w_cap = self.get_parameter("bid_weight_capability").get_parameter_value().double_value

        dist_score = 1.0 / (1.0 + distance / 100.0)
        energy_cost = self._energy_manager.compute_energy_cost_wh(
            distance, msg.estimated_energy_cost
        )
        remaining = self._energy_manager.get_remaining_wh()
        energy_score = min(remaining / max(energy_cost, 0.01), 1.0)
        cap_score = 1.0 if required.issubset(my_caps) else 0.0

        bid_score = w_dist * dist_score + w_energy * energy_score + w_cap * cap_score

        # ETA
        speed = self._hal.get_kinematics().get_max_speed()
        eta = distance / max(speed, 0.1)
        energy_after = max(remaining - energy_cost, 0.0)

        # Transition to BIDDING. The robot could afford this one, so the run
        # of refusals that would eventually send it home is over (D-19).
        self._unaffordable_passes = 0
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

        # D-34 FIELD FRESHNESS. The AUCTION_WON event used to be fired HERE,
        # before the assignment fields below were stored. That was invisible
        # while state was only sampled at 2 Hz; now that every transition
        # publishes a RobotState, firing first would put an ASSIGNED sample on
        # the wire carrying the PREVIOUS task's id (or '') for up to 0.5 s,
        # until the timer corrected it. Downstream that is cosmetic --
        # `apply_robot_progress` acts only on NAVIGATING/WORKING and the
        # orchestrator's completion inference only on RETURNING/IDLE -- but
        # the dashboard renders current_task_id, and a published message that
        # is wrong for half a second is not worth shipping when the fix is to
        # store the fields first.
        #
        # The guard is preserved exactly, and NOT by moving the test: the
        # `elif` cannot simply follow the `if` any more, because the `if`
        # branch mutates the state the `elif` reads. `won` captures the answer
        # before anything changes, so the accepted/rejected decision is
        # identical to the original for every state.
        won = self._fsm.state == AgentState.BIDDING
        if not won and self._fsm.state != AgentState.ASSIGNED:
            self.get_logger().warn(
                f"[{self._robot_id}] Assignment in state {self._fsm.state.value}, ignoring")
            return

        # Store assignment — skill startup deferred to _handle_assigned()
        self._assigned_target = (msg.target_location.x, msg.target_location.y)
        self._assigned_task_type = msg.task_type
        self._current_task_id = msg.task_id
        self._pending_task_id = ""

        # FR-DASH-5 authorised mass, and the haul destination. quantity_kg
        # 0.0 means unconstrained (fill to this robot's own RCDL capacity),
        # which is exactly the behaviour every task had before the field
        # existed, so an orchestrator that never sets it is unaffected.
        quantity = float(msg.quantity_kg)
        self._assigned_quantity_kg = quantity if math.isfinite(quantity) else 0.0
        # A depot of exactly (0,0,0) is the "not set" encoding for every task
        # type that has no depot; _handle_assigned decides what to do about
        # it, because only there do we know whether this is a haul.
        depot = msg.depot_location
        if depot.x == 0.0 and depot.y == 0.0 and depot.z == 0.0:
            self._assigned_depot = None
        else:
            self._assigned_depot = (depot.x, depot.y)

        # LAST, so the ASSIGNED sample this transition publishes carries the
        # task it is about. See the D-34 note above the guard.
        if won:
            self._fsm.handle_event(FSMEvent.AUCTION_WON)

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
            skill.start(self._hal, self._navigator, target=target,
                        quantity_kg=self._assigned_quantity_kg)
        elif task_type == "haul":
            skill = HaulSkill()
            # target_location is the PICKUP; the delivery point is
            # TaskAssignment.depot_location. The pickup is NOT driven onto:
            # HaulSkill stops PICKUP_STANDOFF_M short of it, because that
            # coordinate routinely has a parked excavator on it (D-22). That
            # is the skill's business, not this node's — an operator-injected
            # haul (FR-DASH-5) arrives here by the same path and gets the same
            # standoff.
            #
            # This used to be `(self._recharge_x, self._recharge_y)` — the
            # robot's own charging station — while the HTN planner put the
            # depot in target_location. A haul therefore drove to the depot,
            # "loaded" there, drove to its charger and dumped, never visiting
            # the extraction site at all. Both halves are fixed: the planner
            # now targets the site (OWNER-ORCH) and the depot arrives here.
            depot = self._assigned_depot
            if depot is None:
                depot = (self._recharge_x, self._recharge_y)
                self.get_logger().warn(
                    f"[{self._robot_id}] Haul {self._current_task_id} carried "
                    f"no depot_location; falling back to the recharge station "
                    f"{depot}. The material will be dumped at the charger, "
                    f"not at the ISRU depot."
                )
            skill.start(self._hal, self._navigator, pickup=target, depot=depot,
                        quantity_kg=self._assigned_quantity_kg)
        else:
            self.get_logger().error(f"[{self._robot_id}] Unknown task type: {task_type}")
            # Release the task id before entering ERROR (see _handle_navigating).
            self._current_task_id = ""
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
    # Recharge policy and helpers — deviation D-19
    # ===================================================================

    def _recharge_context(self) -> _RechargeContext:
        """Build the injected-dependency context for ``recharge_policy``."""
        return _RechargeContext(
            robot_id=self._robot_id,
            get_state=lambda: self._fsm.state,
            fire_event=self._fsm.handle_event,
            recharge_reason=self._recharge_reason,
            start_recharge=self._start_recharge,
            get_charge_fraction=self._energy_manager.get_charge_fraction,
            recharge_threshold=self._recharge_threshold,
            log_info=self.get_logger().info,
            abort_current_skill=self._abort_current_skill,
        )

    def _abort_current_skill(self):
        """Abort the running skill, if there is one. Safe in any state."""
        if self._current_skill is not None and self._current_skill.is_running():
            self._current_skill.abort()

    # ------------------------------------------------------------------
    # D-42: the battery topic itself is a thing that can be wrong
    # ------------------------------------------------------------------

    #: Seconds a robot may run with no battery reading at all before it says so.
    #: The battery node publishes at 10 Hz (spawn_robot.launch.py update_rate),
    #: agents start 12 s after the simulator and DDS discovery on this box
    #: completed in well under a second on every run measured, so 10 s of total
    #: silence is not a race, it is an absence.
    BATTERY_SILENCE_S = 10.0

    #: Seconds between readings before the stream counts as stalled. 3 s is
    #: thirty missed messages at 10 Hz.
    BATTERY_STALE_S = 3.0

    def _check_battery_health(self, state) -> None:
        """Report -- never act on -- faults in the battery channel itself.

        WHY THIS EXISTS. D-42: ``agent_scout_02`` acted on ``percentage = 0.0``
        6.152 s after it started, three times, and the register could not name a
        mechanism because nothing anywhere recorded the state of the channel the
        number arrived on. The energy rule read the value and the FSM obeyed it;
        both were correct on their inputs. What was missing was anyone asking
        whether the input was trustworthy.

        Three faults, each with its own remedy and none of them "drive home":

        * MORE THAN ONE PUBLISHER. Something outside this stack is asserting
          this robot's charge. Measured 2026-08-01: signalling ``ros2 launch``
          left a complete SELENE stack alive -- gz sim, four battery nodes, four
          agents, an orchestrator and rosbridge -- and a second launch put two
          battery nodes on this topic. An orphaned battery node latches its last
          cmd_vel forever and keeps integrating locomotion draw with no
          simulator behind it, so it crosses zero, is clamped to EXACTLY 0.0 by
          ``battery_node.py``'s ``max(0.0, ...)``, and publishes that at 10 Hz
          indefinitely. Measured on this box: an orphaned ``battery_scout_02``
          drained at 85 W (1.417 % per 30 s) while the orphaned excavator and
          hauler sat pinned at exactly 1.0 -- they had never moved, so their
          latched speed was zero and they were charging in sunlight. That
          asymmetry is why one robot and not the fleet.
        * NO READING, EVER. The battery node is not running, or the topic name
          moved. Today this is silent: the cached state simply never changes and
          the robot reports a confident 100% for the whole mission.
        * READINGS STOPPED. The node died mid-run, same silence.

        This method LOGS AND ALERTS. It does not change the FSM, does not stop
        the robot and does not fabricate a charge. A robot whose battery channel
        is untrustworthy is not thereby in danger, and inventing an emergency
        response to a reporting fault is how D-42 took check 11 down in the first
        place. The operator gets a CRITICAL FleetAlert on the one channel that
        reaches the dashboard (FR-DASH-4); deciding what to do about it is
        theirs. Same shape and same reasoning as
        ``world_odometry_node._report_degraded``.
        """
        battery = self._hal.get_battery()

        pubs = battery.publisher_count()
        # A channel with more than one publisher is NOT ATTRIBUTABLE, and the
        # energy rule is suspended while it stays that way. See the caller.
        self._battery_channel_attributable = (pubs <= 1)
        if pubs > 1 and pubs != self._battery_pubs_reported:
            self._battery_pubs_reported = pubs
            topic = getattr(battery, 'topic', lambda: '<unknown>')()
            msg = (
                f"[{self._robot_id}] BATTERY TOPIC HAS {pubs} PUBLISHERS "
                f"({topic}). This robot's charge is being asserted by something "
                f"outside its own simulator; the HAL caches whichever message "
                f"arrived last, so the reading is not attributable. Most likely "
                f"a previous stack was never torn down -- check for orphaned "
                f"battery_node processes. Register D-42."
            )
            self.get_logger().error(msg)
            self._publish_alert('CRITICAL', msg)
        elif pubs <= 1:
            self._battery_pubs_reported = 0

        now = self._clock_now()
        if not state.is_valid:
            if (self._first_tick_wall is not None
                    and now - self._first_tick_wall > self.BATTERY_SILENCE_S
                    and not self._battery_silence_reported):
                self._battery_silence_reported = True
                msg = (
                    f"[{self._robot_id}] NO BATTERY READING has arrived in "
                    f"{now - self._first_tick_wall:.1f}s "
                    f"({battery.message_count()} messages received on "
                    f"{getattr(battery, 'topic', lambda: '<unknown>')()}). "
                    f"The HAL is reporting its constructed default and the "
                    f"energy policy is suspended, so this robot will neither "
                    f"recharge nor refuse a task on energy grounds. "
                    f"Register D-42."
                )
                self.get_logger().error(msg)
                self._publish_alert('CRITICAL', msg)
            return

        age = battery.seconds_since_last_message()
        if age is not None and age > self.BATTERY_STALE_S:
            if not self._battery_stale_reported:
                self._battery_stale_reported = True
                elapsed = max(now - (self._first_tick_wall or now), 1e-6)
                msg = (
                    f"[{self._robot_id}] BATTERY READINGS STOPPED "
                    f"{age:.1f}s ago after {battery.message_count()} messages "
                    f"({battery.message_count() / elapsed:.1f} Hz average); the "
                    f"last value ({state.charge_fraction:.1%}) is frozen and "
                    f"the energy policy is still acting on it. Register D-42."
                )
                self.get_logger().error(msg)
                self._publish_alert('CRITICAL', msg)
        else:
            self._battery_stale_reported = False

    def _clock_now(self) -> float:
        """Wall-clock seconds. Named so the D-42 tests can substitute it."""
        return time.monotonic()

    def _publish_alert(self, severity: str, message: str) -> None:
        """Publish a FleetAlert on the operator's channel.

        selene_agent publishing onto /orchestrator/alerts is the same deliberate
        small impurity ``world_odometry_node`` documents: that topic is the ONE
        path to the dashboard (FR-DASH-4) and to the exit-gate probe, multiple
        publishers on one topic is ordinary ROS, and ``source_robot_id`` keeps
        the alert attributable to whoever raised it.
        """
        if self._alert_pub is None:
            return
        alert = FleetAlert()
        alert.severity = severity
        alert.message = message
        alert.source_robot_id = self._robot_id
        alert.stamp = self.get_clock().now().to_msg()
        self._alert_pub.publish(alert)

    def _recharge_reason(self) -> str:
        """Why this robot should go and charge now, or '' if it should not.

        Thin wrapper over ``EnergyManager.recharge_reason``: it supplies the
        position, which is a ROS-side fact.

        THE STARTUP GATE THAT USED TO BE HERE IS GONE, and its docstring was
        wrong in the same way ``_tick``'s comment was. It read: "``_tick``
        already skips ENERGY_CRITICAL for the first 5 s so DDS can deliver a
        real battery reading, because before that the HAL reports a phantom 0%.
        Without the same gate here, every robot in the fleet would read 0%,
        decide it is below the floor and drive to the charging station in the
        first second of the mission."

        No HAL in this repository has ever reported a phantom 0%. Both battery
        implementations construct their cache FULL -- ``GazeboBattery`` from the
        RCDL capacity, ``StubBattery`` from its own model -- so the pre-message
        reading is 100%, and the fleet-wide dash for the charger this paragraph
        predicts could not have happened. The gate was real protection against a
        misremembered mechanism. ``EnergyManager.recharge_reason`` now refuses to
        answer at all on an unvalidated reading, which is the condition the
        author of that paragraph was reaching for. Register D-42.

        A position that cannot be read leaves the return-margin tier out
        rather than forcing a recharge: the flat floor still applies, and
        guessing a distance from an invalid odom reading would produce a
        number with no relationship to where the robot is.
        """
        position = None
        try:
            odom = self._hal.get_sensor("odometry").read()
            if odom.is_valid:
                position = (odom.x, odom.y)
        except Exception:
            position = None
        return self._energy_manager.recharge_reason(position)

    def _settle_after_task(self):
        """In RETURNING after a task: go home, or stay in the field.

        Called immediately after ``FSMEvent.TASK_COMPLETE`` on both the
        success and the failure branch of ``_handle_working``. Before D-19
        the call here was an unconditional ``_start_recharge()``: the robot
        drove back to base and charged after EVERY task regardless of
        battery. Measured live on 2026-07-31, scouts were recharging at
        88-93% charge after every waypoint, spent the majority of two runs in
        RECHARGING, and the survey never finished -- so ``SelectSite`` never
        resolved, no excavate or haul task was ever created, and the D-06
        material ledger could not be exercised at all.
        """
        return settle_after_task_logic(self._recharge_context())

    def _begin_recharge_cycle(self, reason: str) -> bool:
        """Send a robot home to charge from a state that is not RETURNING."""
        return begin_recharge_cycle_logic(self._recharge_context(), reason)

    def _note_unaffordable_announcement(self, task_id: str):
        """Count an announcement declined purely for want of energy.

        The counter lives on the node because it is per-robot mutable state;
        the decision it feeds is ``recharge_policy.should_recharge_after_refusals``,
        whose docstring says why a count rather than a single refusal and why
        this guard has to exist at all once D-19 stops the robot recharging
        after every task.
        """
        self._unaffordable_passes += 1
        in_grace = self._tick_count <= self._startup_grace_ticks
        if not should_recharge_after_refusals(
            self._unaffordable_passes, self._fsm.state, in_grace,
        ):
            return
        charge = self._energy_manager.get_charge_fraction()
        self.get_logger().info(
            f"[{self._robot_id}] Declined "
            f"{UNAFFORDABLE_PASSES_BEFORE_RECHARGE} consecutive "
            f"capability-matched announcements it could not afford (latest "
            f"{task_id}) at {charge:.1%} battery; returning to recharge "
            f"rather than idling above the "
            f"{self._recharge_threshold:.0%} floor"
        )
        # _start_recharge resets the counter, and it is reached on every
        # successful branch of begin_recharge_cycle_logic.
        self._begin_recharge_cycle('cannot_afford_offered_work')

    def _start_recharge(self):
        """Create and start a RechargeSkill heading for the base station."""
        self._unaffordable_passes = 0
        self._current_skill = RechargeSkill(
            recharge_position=(self._recharge_x, self._recharge_y),
            recharge_target=self._energy_recharge_target,
        )
        self._current_skill.start(self._hal, self._navigator)
        self._current_task_id = "recharge"

    # ===================================================================
    # Operator override helpers
    # ===================================================================

    def _start_operator_navigation(self, target_x: float, target_y: float) -> str:
        """Plan a path to *(target_x, target_y)* and begin path-following.

        Returns '' on success, or the planner's failure reason.

        THE RETURN VALUE IS THE WHOLE POINT, and it used to be discarded.
        ``operator_command_logic`` called this and then set
        ``response.accepted = True`` unconditionally, so an operator issuing
        ``send_to_location`` to a goal the terrain guard refuses was told the
        command had been accepted — and the agent abandoned it 0.3 ms later:

            [scout_02] NAVIGATING --(OPERATOR_GOTO)--> NAVIGATING
            [scout_02] Operator goto plan failed: goal (-81.5, -94.5) is on
                       26.1 deg ground, over the 20.0 deg traversable limit
            [scout_02] NAVIGATING --(OPERATOR_CANCEL)--> IDLE

        All three lines inside half a millisecond, and the ONLY record of the
        refusal was a log line on the robot. The service said yes. There was no
        'accepted but not performable' channel back to whoever asked, which is
        the same defect class as a skill that reports success it did not
        achieve.

        WHY IT SURFACED NOW. Until D-28 was closed at 9c1a4d7 nothing read
        ``navigation.max_traversable_slope_deg``, so A* refused a goal only for
        occupancy or bounds and this path was nearly unreachable. The exit
        gate's check 11 picks its target 6 m from the robot on a heading-relative
        bearing; with the slope rule live, that pick lands on refused ground
        often enough to fail the check — and check 11 then measured a stale
        ``planned_path`` and blamed the override. Register D-10.

        Used by the operator ``send_to_location`` command. Skips skill
        creation entirely — the navigator drives the wheels directly,
        and ``_handle_navigating`` recognises the override_goto pseudo-task
        for arrival handling.
        """
        result = self._navigator.plan_to((target_x, target_y))
        if not result.success:
            reason = result.failure_reason or 'planner returned no path'
            self.get_logger().error(
                f"[{self._robot_id}] Operator goto plan failed: {reason}"
            )
            self._operator_target = None
            # Drop back to IDLE so we don't strand the agent.
            try:
                self._fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
            except Exception:
                pass
            return reason
        self._navigator.start_following(result.path)
        return ''

    def _stop_navigation(self):
        """Unconditionally halt motion: stop path following, zero cmd_vel.

        Safe to call in any state, with or without an active skill or path.
        Used by the operator-command handler so a cancel can never leave a
        latched velocity command driving the wheels.
        """
        try:
            self._navigator.stop()
        except Exception as e:  # pragma: no cover - defensive
            self.get_logger().warn(
                f"[{self._robot_id}] navigator.stop() failed: {e}"
            )
        # Belt-and-braces: command zero velocity directly on the HAL even if
        # the navigator had no path (in which case its follower.stop() still
        # publishes 0, but we do not want to depend on that internal detail).
        try:
            self._hal.get_actuator("drive").stop()
        except (KeyError, AttributeError):
            pass

    def _publish_bid_withdrawal(self, task_id: str, robot_id: str):
        """Publish a negative-score bid so the orchestrator drops us."""
        bid = BidResponse()
        bid.task_id = task_id
        bid.robot_id = robot_id
        bid.bid_score = -1.0  # negative = withdrawal sentinel
        bid.estimated_arrival_time = 0.0
        bid.energy_after_task = 0.0
        self._bid_pub.publish(bid)

    def _on_operator_command(self, request, response):
        """ROS 2 service callback — delegates to the pure-Python helper."""
        ctx = _OperatorCommandContext(
            robot_id=self._robot_id,
            get_state=lambda: self._fsm.state,
            fire_event=self._fsm.handle_event,
            get_current_skill=lambda: self._current_skill,
            set_current_skill=lambda s: setattr(self, '_current_skill', s),
            set_current_task_id=lambda t: setattr(self, '_current_task_id', t),
            get_pending_task_id=lambda: self._pending_task_id,
            set_pending_task_id=lambda t: setattr(self, '_pending_task_id', t),
            publish_bid_withdrawal=self._publish_bid_withdrawal,
            start_navigation=self._start_operator_navigation,
            set_operator_target=lambda t: setattr(self, '_operator_target', t),
            start_recharge=self._start_recharge,
            get_last_seq=lambda: self._last_operator_seq,
            set_last_seq=lambda s: setattr(self, '_last_operator_seq', s),
            log_warn=self.get_logger().warn,
            stop_navigation=self._stop_navigation,
        )
        return operator_command_logic(ctx, request, response)

    # ===================================================================
    # State publisher (2 Hz timer + one message per FSM transition)
    # ===================================================================

    def _build_state_msg(self) -> RobotState:
        """Snapshot this robot into a ``RobotState``.

        Split out of ``_publish_state`` for D-34 so the on-transition
        publisher shares one definition of the message with the timer. It
        deliberately does NOT publish and does NOT touch the navigator: see
        ``_on_fsm_transition`` for why the planned path must not ride along.
        """
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
            # D-31. SAY WHETHER THAT POSE IS A MEASUREMENT.
            #
            # GazeboOdometrySensor.read() never raises and never blocks: until
            # the first /odom_world message arrives it hands back the cached
            # OdometryReading its constructor built with an explicit
            # is_valid=False, x and y left at 0.0
            # (selene_hal/selene_hal/gazebo_hal.py:357-359, :385-387;
            # data_types.py:102-109 -- and note SensorReading.is_valid
            # DEFAULTS TO TRUE at data_types.py:39, so that False is a
            # decision the sensor makes, not something the dataclass gives
            # you). So the try/except above catches nothing
            # on the startup path, and every robot published a confident
            # (0, 0) at 2 Hz from the moment this node came up. The
            # orchestrator's FleetMonitor seeded its distance accumulator from
            # that origin and booked |spawn| -- 90.050 m to 127.224 m per
            # robot on the shipped ten-robot fleet -- the first time a real
            # pose arrived.
            #
            # This node already guarded its two other DECISION-MAKING
            # odometry reads on exactly this flag -- _handle_idle (:424) and
            # _recharge_reason (:945) -- so the invalid window was known.
            # The read that fed the whole fleet was the one left unguarded.
            # (_on_task_announced does NOT guard, and that one is deliberate
            # and documented there: a stale pose only perturbs a bid score,
            # and navigation is gated by _handle_assigned.)
            #
            # pose IS STILL POPULATED, deliberately. The flag carries the
            # meaning and the consumer decides; blanking the pose would only
            # move the fabrication from "wrong coordinates" to "coordinates
            # that look like the origin", which is the same defect. And the
            # message must keep flowing regardless, because it is also the
            # heartbeat FleetMonitor.check_heartbeats reads -- withholding it
            # would mark every robot OFFLINE during startup.
            msg.pose_valid = bool(odom.is_valid)
        except Exception:
            # Reached only if the HAL itself is missing the sensor or the
            # backend raises. pose_valid is left at its default False, which
            # is the fail-safe direction; nothing here sets it True.
            pass

        msg.battery_level = float(self._energy_manager.get_charge_fraction())
        msg.current_task_id = self._current_task_id
        msg.task_progress = float(
            self._current_skill.get_progress() if self._current_skill else 0.0
        )
        msg.capabilities = self._hal.get_capabilities()
        msg.stamp = self.get_clock().now().to_msg()

        # Report this robot's own battery capacity so FleetMonitor can turn
        # battery_level deltas into watt-hours per robot instead of assuming
        # a single 50 Wh cell for the whole fleet (fleet_monitor.py:9,16,65) —
        # which is the scout's figure and understates an excavator (80 Wh) by
        # 37.5% and a hauler (65 Wh) by 23%. Reported by the robot, from its
        # own RCDL, so the RCDL stays the single source of truth and
        # selene_orchestrator needs no dependency on selene_hal or pydantic.
        # On failure the field stays 0.0 and FleetMonitor falls back to its
        # documented default.
        try:
            msg.battery_capacity_wh = float(
                self._hal.get_battery().get_capacity_wh()
            )
        except Exception:
            pass

        return msg

    def _publish_state(self):
        """0.5 s timer: the level signal, plus the planned path for RViz2."""
        self._state_pub.publish(self._build_state_msg())

        # Also publish path for RViz2 visualization
        self._navigator.publish_path()

    def _on_fsm_transition(self, prev_state, event, new_state):
        """Publish one extra RobotState at the instant the FSM moves (D-34).

        WHY. ``/{robot_id}/state`` was a level signal sampled at 2 Hz, so any
        state shorter than 0.5 s was structurally unrepresentable on the wire.
        Measured from the two exit-gate runs' launch logs, the IDLE window
        between an operator cancel and the next bid lasted 0.247 s and 0.301 s
        -- half a sampling period -- and neither run's probe ever saw it, so
        checks 6 and 9 SKIPped and PRD rows 3 and 4 went unmeasured on a
        system that had done exactly what they assert. Sampling faster is the
        same defect at higher cost; publishing the edge is the fix.

        WHAT THIS COSTS, as a structural bound and NOT a measurement. Exactly
        one extra message per successful transition. One orchestrated task
        that ends in the field is six transitions (IDLE->BIDDING->ASSIGNED->
        NAVIGATING->WORKING->RETURNING->IDLE), seven if it ends in a recharge
        cycle, and every lost auction is two (IDLE->BIDDING->IDLE). Against a
        2 Hz baseline of 3600 messages per robot per 1800 s run, a robot doing
        a task every two minutes with three lost auctions between them adds
        ~15 transitions/task * 15 tasks ~= 225 messages, about 6%. The hard
        per-robot ceiling is set by what can fire an event: the 10 Hz tick
        (at most a couple of transitions per tick), the orchestrator's 0.5 s
        auction tick, and operator service calls -- call it ~20 Hz against the
        2 Hz baseline, and a robot anywhere near it is in the IDLE/RETURNING/
        RECHARGING busy loop that ``validated_recharge_threshold`` already
        clamps rather than a robot doing work. **I have not measured the real
        transition count; the register publishes none.** The FSM logs every
        transition (``fsm.py``, the ``--(event)-->`` line), so
        ``grep -c -- '-->'`` on the next launch log turns this bound into a
        number, and the next live run must record it.

        NO RATE LIMITER, deliberately. A limiter is a sampler, and a sampler
        is the defect being fixed.

        TWO CONSUMERS SEE A CHANGE, AND NEITHER IS FIXED HERE. Both are
        recorded so they are not discovered as surprises on the next live run.

        1. Any consumer that accumulates PER SAMPLE now gets more samples.
           The gate's check-4 IDLE motion-coherence rule sums per-sample path
           length over runs of IDLE samples (``scripts/phase5_probe.py``
           ``_run_path_length`` / ``MOTION_EPS_M``), and the sample this hook
           inserts lands at the INSTANT of the transition into IDLE -- before
           a robot that was driving has physically stopped, since
           ``stop_navigation`` zeroes the command but the DiffDrive odometry
           the HAL caches still records the coast. An extra sample can both
           lengthen an existing IDLE run and push a 2-sample run past the
           3-sample minimum. The honest fix is to make that rule
           rate-invariant, which is the probe's file and not this one;
           suppressing the IDLE publish here would simply re-alias the exact
           state D-34 exists to expose.

        2. The orchestrator infers task completion from a RETURNING/IDLE
           sample with an empty ``current_task_id``. ``_handle_working``
           clears the id and then fires ``TASK_COMPLETE``, so this hook now
           emits that message microseconds after the authoritative
           ``TaskResult`` instead of 0-500 ms after it. The two are on
           different topics with no cross-topic ordering guarantee. This is
           NOT the "a FAILED task gets recorded COMPLETED" hazard it looks
           like -- ``TaskQueue.mark_failed`` routes to ``set_status`` with no
           guard on the previous status, so the TaskResult overwrites an
           inferred completion whichever lands first, and the final recorded
           status is FAILED either way. What remains is a spurious
           COMPLETED->FAILED pair in the event log and operator event ring,
           and a brief window in which a timer callback could read the
           predecessor as COMPLETED. Both belong to the orchestrator.

        WHAT DOES NOT RIDE ALONG. ``_publish_state`` also republishes the
        planned path; that stays on the timer. A ``nav_msgs/Path`` is large,
        carries no edge information, and multiplying it by the transition rate
        buys nothing.

        DEFENSIVE BY DESIGN. ``AgentFSM`` only calls this once the node has
        installed it (below the publisher block in ``__init__``), but the
        ``_state_pub`` check stays because the cost of being wrong is an
        ``AttributeError`` raised inside a DDS or timer callback. ``AgentFSM``
        catches and logs whatever escapes here rather than letting a state
        publisher take a robot's FSM down with it.

        The three arguments are the transition itself. They are unused today
        -- the message carries the new state and nothing else about the edge
        -- and they are in the signature because an observer that cannot see
        which edge fired cannot ever be more selective than "all of them".
        """
        if getattr(self, '_state_pub', None) is None:
            return
        self._state_pub.publish(self._build_state_msg())

    # ===================================================================
    # Material ledger / task outcome publishers
    # ===================================================================

    def _publish_material_event(self, task_id: str, event_type: str,
                                mass_kg: float, residual_mass_kg: float):
        """Publish one measured mass transfer, or nothing at all.

        The skills return NaN for any mass whose fill sensor could not be
        read (``ExcavateSkill._read_fill`` / ``HaulSkill._read_fill``), and
        that sentinel is honoured here: **a missing measurement produces no
        message**. Publishing 0.0 instead would put a number that was never
        measured into the ledger, and FR-ISRU-2's acceptance — "no material
        is lost or duplicated" — is precisely a claim about numbers that were
        measured. A warning is logged so the gap is visible rather than
        silent.
        """
        mass = float(mass_kg)
        residual = float(residual_mass_kg)
        if not math.isfinite(mass) or not math.isfinite(residual):
            self.get_logger().warn(
                f"[{self._robot_id}] Not publishing a '{event_type}' "
                f"MaterialEvent for task {task_id}: the fill sensor was never "
                f"read (mass={mass!r}, residual={residual!r}). Mission "
                f"progress will under-report by this transfer."
            )
            return

        try:
            fields = build_material_event_fields(
                event_id=self._event_ids.next(),
                robot_id=self._robot_id,
                task_id=task_id,
                event_type=event_type,
                mass_kg=mass,
                residual_mass_kg=residual,
            )
        except ValueError as e:
            self.get_logger().error(
                f"[{self._robot_id}] Refusing to publish MaterialEvent: {e}"
            )
            return

        msg = MaterialEvent()
        msg.event_id = fields['event_id']
        msg.robot_id = fields['robot_id']
        msg.task_id = fields['task_id']
        msg.event_type = fields['event_type']
        msg.mass_kg = fields['mass_kg']
        msg.residual_mass_kg = fields['residual_mass_kg']
        msg.stamp = self.get_clock().now().to_msg()
        self._material_event_pub.publish(msg)

    def _publish_task_result(self, task_id: str, task_type: str,
                             success: bool, failure_reason: str):
        """Publish the terminal outcome of one task.

        Skipped for an empty ``task_id`` — a task the orchestrator never
        issued (the standalone-mode waypoint walk, or a skill that ended
        after an operator cancel cleared the id) has no queue entry to
        terminate, and an outcome keyed on '' would be dropped downstream
        anyway.
        """
        if not task_id:
            return
        msg = TaskResult()
        msg.task_id = task_id
        msg.robot_id = self._robot_id
        msg.task_type = task_type
        msg.success = bool(success)
        msg.failure_reason = failure_reason or ""
        msg.stamp = self.get_clock().now().to_msg()
        self._task_result_pub.publish(msg)

    # ===================================================================
    # Map update publisher
    # ===================================================================

    def _publish_map_update(self, result):
        # Guard the uncertainty before it reaches the wire. ResourceMapUpdate.
        # sensor_uncertainty is a float32 sigma consumed by the orchestrator's
        # Bayesian ResourceMap.update():
        #   - inf/NaN (ProspectSkill's "no usable sigma" sentinel) would put a
        #     non-finite value on a DDS float32 field and, via rosbridge, into
        #     JSON, which cannot represent it;
        #   - 0.0 would assert a noise-free measurement and collapse the
        #     posterior variance to ~1e-6.
        # In both cases the reading carries no usable information, so drop it
        # rather than corrupting the map with a fabricated confidence.
        uncertainty = float(result.uncertainty)
        if not math.isfinite(uncertainty) or uncertainty <= 0.0:
            self.get_logger().warn(
                f"[{self._robot_id}] Dropping map update at "
                f"({result.position[0]:.1f}, {result.position[1]:.1f}): "
                f"unusable sensor uncertainty {uncertainty!r}. Check the RCDL "
                f"noise_stddev for this robot's scalar-field sensor."
            )
            return

        msg = ResourceMapUpdate()
        msg.scout_id = self._robot_id
        msg.location = Point(
            x=result.position[0], y=result.position[1], z=0.0
        )
        msg.ice_concentration = float(result.ice_concentration)
        msg.sensor_uncertainty = uncertainty
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
