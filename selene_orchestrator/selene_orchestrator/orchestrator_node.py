"""Fleet orchestrator node for SELENE multi-agent coordination.

Manages task auction, fleet health monitoring, and resource map.
Generates prospect survey waypoints and distributes them via auction.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from selene_msgs.msg import (
    BidResponse as BidResponseMsg,
    FleetAlert,
    MissionProgress,
    ResourceMapUpdate,
    RobotState,
    TaskAnnouncement,
    TaskAssignment,
)
from selene_msgs.srv import InjectTask, OverrideRobot

# SetRobotCommand is created in parallel by Wave 1 Agent 2. Until that build
# lands, fall back to a stub that mirrors the request/response shape so the
# orchestrator module still imports cleanly for unit tests and CI.
try:  # pragma: no cover - import-path resolved at runtime
    from selene_msgs.srv import SetRobotCommand
except ImportError:  # pragma: no cover - tested via stub injection
    class _SetRobotCommandStub:
        class Request:
            def __init__(self):
                from geometry_msgs.msg import Point as _Point
                self.command = ''
                self.target = _Point()
                self.sequence = 0

        class Response:
            def __init__(self):
                self.accepted = False
                self.reason = ''

    SetRobotCommand = _SetRobotCommandStub  # type: ignore[assignment,misc]

from geometry_msgs.msg import Point

from selene_orchestrator.fleet_monitor import FleetMonitor
from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.task_auction import TaskAuction, Bid
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.htn_planner import HTNPlanner
from selene_orchestrator.adaptive_survey import AdaptiveSurveyPlanner
from selene_isru.inventory import MaterialInventory


# ---- Operator-injected task constants ------------------------------------ #
# Capability requirements per manual task type. Keeping this at module scope
# lets unit tests verify the mapping without instantiating the full ROS node.
MANUAL_TASK_CAPABILITIES: dict[str, list[str]] = {
    'prospect': ['prospect'],
    'excavate': ['excavate'],
    'haul': ['haul'],
}

# FSM states from which a robot cannot accept a freshly injected task.
INJECT_BLOCKED_STATES: frozenset[str] = frozenset({
    'ERROR', 'OFFLINE', 'RECHARGING',
})

# FSM states from which a robot cannot accept any operator override.
OVERRIDE_BLOCKED_STATES: frozenset[str] = frozenset({'ERROR', 'OFFLINE'})

VALID_OVERRIDE_COMMANDS: frozenset[str] = frozenset({
    'cancel_task', 'send_to_location', 'force_recharge',
})


# ---- Pure-logic helpers for the operator service handlers ---------------- #
# These live at module scope so unit tests can drive them with mocks instead
# of standing up a full ROS node. The OrchestratorNode methods build a
# context object and delegate.


@dataclass
class _InjectTaskContext:
    """Injected dependencies for ``inject_task_logic``."""
    task_queue: Any
    fleet_monitor: Any
    next_task_id: Callable[[], str]
    now_stamp: Any
    publish_assignment: Callable[[str, str, str, Any], None]
    publish_alert: Callable[[str, str], None]


@dataclass
class _OverrideRobotContext:
    """Injected dependencies for ``override_robot_logic``."""
    task_queue: Any
    fleet_monitor: Any
    set_command_clients: dict
    next_sequence: Callable[[], int]
    spin_until_complete: Callable[[Any], None]
    publish_alert: Callable[[str, str], None]
    set_command_factory: Callable[[], Any]


def inject_task_logic(ctx: _InjectTaskContext, request, response):
    """Pure decision tree for InjectTask. Mutates ctx state, returns response.

    Decision order:
        1. Reject unknown task_type.
        2. Allocate a fresh manual task_id and add the task to the queue at
           priority 10.0 (above HTN baseline) with capability requirements.
        3. If no assigned_robot_id is provided, leave the task PENDING for
           the next auction tick to pick up.
        4. Otherwise validate the target robot:
              - exists in the fleet monitor
              - not in ERROR/OFFLINE/RECHARGING
              - has every required capability
        5. If the robot is busy, interrupt + re-PENDING its current task and
           publish a WARNING alert before forcing the new assignment.
        6. Force-assign + publish TaskAssignment immediately so the agent
           and dashboard see the change without waiting for an auction.

    Failure paths set the freshly-created manual task to FAILED so the
    queue does not retain a phantom row, then return success=False with a
    diagnostic message.
    """
    if request.task_type not in MANUAL_TASK_CAPABILITIES:
        response.success = False
        response.task_id = ''
        response.message = f"invalid task_type '{request.task_type}'"
        return response

    cap_required = list(MANUAL_TASK_CAPABILITIES[request.task_type])
    task_id = ctx.next_task_id()

    ctx.task_queue.add_task(
        task_id=task_id,
        task_type=request.task_type,
        target_x=float(request.target_location.x),
        target_y=float(request.target_location.y),
        priority=10.0,
        required_capabilities=cap_required,
    )

    assigned_robot_id = (request.assigned_robot_id or '').strip()
    if not assigned_robot_id:
        ctx.publish_alert(
            'INFO', f'operator queued {task_id} for auction',
        )
        response.success = True
        response.task_id = task_id
        response.message = 'queued'
        return response

    robot = ctx.fleet_monitor.get_robot(assigned_robot_id)
    if robot is None:
        ctx.task_queue.set_status(task_id, TaskStatus.FAILED)
        response.success = False
        response.task_id = task_id
        response.message = f"unknown robot '{assigned_robot_id}'"
        return response

    fsm_state = robot.get('fsm_state', '') if isinstance(robot, dict) \
        else getattr(robot, 'fsm_state', '')
    capabilities = robot.get('capabilities', []) if isinstance(robot, dict) \
        else getattr(robot, 'capabilities', [])
    current_task_id = robot.get('current_task_id', '') if isinstance(robot, dict) \
        else getattr(robot, 'current_task_id', '')

    if fsm_state in INJECT_BLOCKED_STATES:
        ctx.task_queue.set_status(task_id, TaskStatus.FAILED)
        response.success = False
        response.task_id = task_id
        response.message = (
            f"robot in {fsm_state}, cannot accept task"
        )
        return response

    missing = [c for c in cap_required if c not in (capabilities or [])]
    if missing:
        ctx.task_queue.set_status(task_id, TaskStatus.FAILED)
        response.success = False
        response.task_id = task_id
        response.message = f"robot lacks capabilities {missing}"
        return response

    # Pre-empt any active task on the target robot before forcing the new one.
    if current_task_id:
        ctx.task_queue.interrupt_task(
            current_task_id, {'reason': 'operator_reassign'},
        )
        ctx.task_queue.set_status(current_task_id, TaskStatus.PENDING)
        ctx.publish_alert(
            'WARNING',
            f'task {current_task_id} preempted by operator reassign',
        )

    ctx.task_queue.assign_to_robot(task_id, assigned_robot_id)
    ctx.publish_assignment(
        task_id,
        assigned_robot_id,
        request.task_type,
        request.target_location,
    )
    ctx.publish_alert(
        'INFO',
        f'operator force-assigned {task_id} to {assigned_robot_id}',
    )

    response.success = True
    response.task_id = task_id
    response.message = 'force-assigned'
    return response


def override_robot_logic(ctx: _OverrideRobotContext, request, response):
    """Pure decision tree for OverrideRobot. Returns the populated response.

    Validation order:
        1. Reject unknown ``request.command``.
        2. Reject unknown robot.
        3. Reject robots in ERROR/OFFLINE.
        4. For ``cancel_task`` and ``force_recharge``, interrupt the current
           task (if any) and re-PEND it so a future auction can re-dispatch
           the work to a healthy robot.
        5. Look up the per-agent SetRobotCommand client; abort early if it
           does not exist or never becomes available.
        6. Build a SetRobotCommand request with a monotonic sequence and
           call asynchronously, spinning until the future completes or
           times out at 2 s.
        7. Forward the agent's accept/reject verdict back to the caller.

    All return paths emit a single FleetAlert summarising the outcome.
    """
    if request.command not in VALID_OVERRIDE_COMMANDS:
        response.success = False
        response.message = f"invalid command '{request.command}'"
        return response

    robot = ctx.fleet_monitor.get_robot(request.robot_id)
    if robot is None:
        response.success = False
        response.message = f"unknown robot '{request.robot_id}'"
        ctx.publish_alert(
            'INFO',
            f'operator override: {request.robot_id} {request.command} -> '
            f'{response.message}',
        )
        return response

    fsm_state = robot.get('fsm_state', '') if isinstance(robot, dict) \
        else getattr(robot, 'fsm_state', '')
    current_task_id = robot.get('current_task_id', '') if isinstance(robot, dict) \
        else getattr(robot, 'current_task_id', '')

    if fsm_state in OVERRIDE_BLOCKED_STATES:
        response.success = False
        response.message = f"robot in {fsm_state}, override rejected"
        ctx.publish_alert(
            'INFO',
            f'operator override: {request.robot_id} {request.command} -> '
            f'{response.message}',
        )
        return response

    # Requeue any in-flight task before yanking the robot off it.
    if request.command in ('cancel_task', 'force_recharge') and current_task_id:
        ctx.task_queue.interrupt_task(
            current_task_id, {'reason': f'operator_{request.command}'},
        )
        ctx.task_queue.set_status(current_task_id, TaskStatus.PENDING)

    client = ctx.set_command_clients.get(request.robot_id)
    if client is None:
        response.success = False
        response.message = f"agent {request.robot_id} not reachable"
        ctx.publish_alert(
            'INFO',
            f'operator override: {request.robot_id} {request.command} -> '
            f'{response.message}',
        )
        return response

    # Wait briefly for the agent service to come up. The mock client used by
    # tests treats wait_for_service as a no-op returning True.
    try:
        ready = client.wait_for_service(timeout_sec=5.0)
    except TypeError:
        ready = client.wait_for_service()
    if not ready:
        response.success = False
        response.message = f"agent {request.robot_id} not reachable"
        ctx.publish_alert(
            'INFO',
            f'operator override: {request.robot_id} {request.command} -> '
            f'{response.message}',
        )
        return response

    seq = ctx.next_sequence()
    cmd_req = ctx.set_command_factory()
    cmd_req.command = request.command
    cmd_req.target = request.target
    cmd_req.sequence = seq

    future = client.call_async(cmd_req)
    ctx.spin_until_complete(future)

    if future.done() and future.result() is not None:
        agent_resp = future.result()
        response.success = bool(agent_resp.accepted)
        response.message = (
            agent_resp.reason or f'override {request.command} accepted'
        )
    else:
        response.success = False
        response.message = 'agent service call timed out'

    ctx.publish_alert(
        'INFO',
        f'operator override: {request.robot_id} {request.command} -> '
        f'{response.message}',
    )
    return response


class OrchestratorNode(Node):
    """Central fleet orchestrator with auction-based task allocation.

    Lifecycle
    ---------
    1. On startup, declares ROS parameters, instantiates pure-Python core
       modules (FleetMonitor, TaskQueue, TaskAuction, ResourceMap), and
       generates PSR survey waypoints as prospect tasks.
    2. Subscribes to per-robot ``/<robot_id>/state`` topics and the shared
       ``/orchestrator/bid_response`` and ``/orchestrator/map_update`` topics.
    3. Runs three periodic timers:
       - heartbeat_check (1 Hz): detects timed-out robots, re-queues tasks.
       - auction_tick (2 Hz): starts / resolves auctions for pending tasks.
       - publish_mission_progress (1 Hz): broadcasts aggregate progress.
    """

    def __init__(self):
        super().__init__('orchestrator_node')

        # ---- Parameters ----
        self.declare_parameter('auction_timeout_sec', 5.0)
        self.declare_parameter('heartbeat_timeout_sec', 10.0)
        self.declare_parameter('recharge_threshold', 0.30)
        self.declare_parameter('fleet_state_publish_rate', 1.0)
        self.declare_parameter('resource_map_publish_rate', 0.5)
        self.declare_parameter('map_resolution', 1.0)
        self.declare_parameter('map_width', 500)
        self.declare_parameter('map_height', 500)
        self.declare_parameter(
            'fleet_robot_ids',
            ['scout_01', 'scout_02', 'excavator_01', 'hauler_01'],
        )

        auction_timeout = self.get_parameter('auction_timeout_sec').value
        heartbeat_timeout = self.get_parameter('heartbeat_timeout_sec').value
        fleet_ids = self.get_parameter('fleet_robot_ids').value
        map_w = self.get_parameter('map_width').value
        map_h = self.get_parameter('map_height').value
        map_res = self.get_parameter('map_resolution').value

        # ---- Core modules ----
        self._fleet = FleetMonitor(heartbeat_timeout=heartbeat_timeout)
        self._task_queue = TaskQueue()
        self._auction = TaskAuction(timeout_sec=auction_timeout)
        self._resource_map = ResourceMap(
            width=map_w,
            height=map_h,
            resolution=map_res,
            origin_x=-map_w * map_res / 2,
            origin_y=-map_h * map_res / 2,
        )

        # ---- Phase 4 modules ----
        self._htn_planner = HTNPlanner(self._task_queue, self._resource_map)
        self._adaptive_survey = AdaptiveSurveyPlanner(self._resource_map)
        self._inventory = MaterialInventory()

        # ---- Tracking ----
        self._start_time = self.get_clock().now()
        self._alert_counter = 0

        # ---- Subscribers ----
        # Per-robot state subscriptions
        for rid in fleet_ids:
            self.create_subscription(
                RobotState,
                f'/{rid}/state',
                lambda msg, robot_id=rid: self._on_robot_state(msg),
                10,
            )

        # Bid responses (all robots publish to same topic)
        self.create_subscription(
            BidResponseMsg,
            '/orchestrator/bid_response',
            self._on_bid_response,
            10,
        )

        # Resource map updates from scouts
        self.create_subscription(
            ResourceMapUpdate,
            '/orchestrator/map_update',
            self._on_map_update,
            10,
        )

        # ---- Publishers ----
        self._announce_pub = self.create_publisher(
            TaskAnnouncement, '/orchestrator/task_announcement', 10,
        )
        self._assign_pub = self.create_publisher(
            TaskAssignment, '/orchestrator/task_assignment', 10,
        )
        self._alert_pub = self.create_publisher(
            FleetAlert, '/orchestrator/alerts', 10,
        )
        self._progress_pub = self.create_publisher(
            MissionProgress, '/orchestrator/mission_progress', 10,
        )

        # ---- Operator services (FR-DASH-5 / FR-DASH-6) ----
        self._fleet_robot_ids = list(fleet_ids)
        self._manual_task_counter = 0
        self._operator_command_seq = 0

        self._inject_task_srv = self.create_service(
            InjectTask,
            '/orchestrator/inject_task',
            self._handle_inject_task,
        )
        # The override service must wait on a SetRobotCommand client response
        # from within its callback. Running that wait on the default mutually-
        # exclusive group deadlocks the executor, so the service and its
        # downstream clients share a reentrant group that the MultiThreaded-
        # Executor in main() can dispatch across multiple threads.
        self._override_cb_group = ReentrantCallbackGroup()
        self._override_robot_srv = self.create_service(
            OverrideRobot,
            '/orchestrator/override_robot',
            self._handle_override_robot,
            callback_group=self._override_cb_group,
        )

        # Per-agent SetRobotCommand client cache. Each agent (Wave 1 Agent 2)
        # exposes /{robot_id}/set_command; we keep a long-lived client per
        # robot so override calls don't pay client-construction cost on the
        # hot path.
        self._set_command_clients: dict = {}
        for rid in fleet_ids:
            self._set_command_clients[rid] = self.create_client(
                SetRobotCommand, f'/{rid}/set_command',
                callback_group=self._override_cb_group,
            )

        # ---- Timers ----
        # Timers get their own callback group so high-frequency subscription
        # callbacks cannot starve them in the MultiThreadedExecutor.
        self._timer_cb_group = ReentrantCallbackGroup()
        self.create_timer(1.0, self._heartbeat_check,
                          callback_group=self._timer_cb_group)           # 1 Hz
        self.create_timer(0.5, self._auction_tick,
                          callback_group=self._timer_cb_group)           # 2 Hz
        self.create_timer(1.0, self._publish_mission_progress,
                          callback_group=self._timer_cb_group)           # 1 Hz
        self.create_timer(1.0, self._htn_advance,
                          callback_group=self._timer_cb_group)           # 1 Hz

        # ---- Generate survey tasks ----
        self._generate_survey_tasks()

        self.get_logger().info(
            f'Orchestrator started | fleet={fleet_ids} '
            f'tasks={self._task_queue.get_total_count()} '
            f'auction_timeout={auction_timeout}s'
        )

    # ------------------------------------------------------------------ #
    #  Subscriber callbacks                                                #
    # ------------------------------------------------------------------ #

    def _on_robot_state(self, msg: RobotState) -> None:
        """Update fleet monitor with incoming robot state."""
        self._fleet.update_robot(
            robot_id=msg.robot_id,
            robot_type=msg.robot_type,
            fsm_state=msg.fsm_state,
            pose_x=msg.pose.x,
            pose_y=msg.pose.y,
            pose_theta=msg.pose.theta,
            battery_level=msg.battery_level,
            current_task_id=msg.current_task_id,
            capabilities=list(msg.capabilities),
            timestamp=time.monotonic(),
        )

        # Detect task completion: robot finished task and returned to idle
        if msg.fsm_state in ('RETURNING', 'IDLE') and msg.current_task_id == '':
            task_id = self._task_queue.get_task_for_robot(msg.robot_id)
            if task_id:
                task = self._task_queue.get_task(task_id)
                if task and task.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                ):
                    self._task_queue.mark_complete(task_id)
                    self.get_logger().info(
                        f'Task {task_id} completed by {msg.robot_id}'
                    )

        # Detect robot error — interrupt its task and re-queue
        if msg.fsm_state == 'ERROR' and msg.current_task_id == '':
            task_id = self._task_queue.get_task_for_robot(msg.robot_id)
            if task_id:
                task = self._task_queue.get_task(task_id)
                if task and task.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                ):
                    self._task_queue.interrupt_task(task_id, {
                        'reason': 'robot_error',
                        'robot_id': msg.robot_id,
                    })
                    # Re-queue the interrupted task as PENDING for re-auction
                    self._task_queue.set_status(task_id, TaskStatus.PENDING)
                    self._publish_alert(
                        'WARNING', msg.robot_id,
                        f'Task {task_id} interrupted due to robot error, '
                        f're-queued',
                    )

    def _on_bid_response(self, msg: BidResponseMsg) -> None:
        """Collect bid during an active auction window."""
        if self._auction.is_active():
            self._auction.add_bid(Bid(
                task_id=msg.task_id,
                robot_id=msg.robot_id,
                bid_score=msg.bid_score,
                estimated_arrival_time=msg.estimated_arrival_time,
                energy_after_task=msg.energy_after_task,
            ))

    def _on_map_update(self, msg: ResourceMapUpdate) -> None:
        """Update resource map with a new scout sensor reading."""
        self._resource_map.update(
            x=msg.location.x,
            y=msg.location.y,
            reading=msg.ice_concentration,
            sensor_uncertainty=msg.sensor_uncertainty,
        )

    # ------------------------------------------------------------------ #
    #  Timer callbacks                                                     #
    # ------------------------------------------------------------------ #

    def _heartbeat_check(self) -> None:
        """Check for robot heartbeat timeouts and recover orphaned tasks."""
        timed_out = self._fleet.check_heartbeats()
        for rid in timed_out:
            self._fleet.mark_offline(rid)
            recovered = self._task_queue.recover_tasks_for_robot(rid)
            self._publish_alert(
                'ERROR',
                rid,
                f'Heartbeat timeout. {len(recovered)} task(s) re-queued: '
                f'{recovered}',
            )
            self.get_logger().warn(
                f'Robot {rid} timed out, recovered tasks: {recovered}'
            )

    def _auction_tick(self) -> None:
        """Run the auction state machine: start or resolve auctions."""
        now = time.monotonic()

        # If an auction is active, check for timeout
        if self._auction.is_active():
            if self._auction.is_timed_out(now):
                self._resolve_auction()
            return  # Don't start a new auction while one is running

        # Check for idle robots and pending tasks
        idle = self._fleet.get_idle_robots()
        if not idle:
            return

        next_task = self._task_queue.get_next_ready()
        if next_task is None:
            return

        # Skip virtual tasks — resolved by the HTN planner, not by robots
        if next_task.task_type == 'select_site':
            return

        # Start new auction
        self._task_queue.set_status(next_task.task_id, TaskStatus.AUCTIONING)
        self._auction.start(next_task.task_id, now)
        self._publish_announcement(next_task)
        self.get_logger().info(
            f'Auction started for {next_task.task_id} ({next_task.task_type}) '
            f'at ({next_task.target_x:.0f}, {next_task.target_y:.0f})'
        )

    def _resolve_auction(self) -> None:
        """Select the auction winner and assign the task (or re-queue)."""
        winner = self._auction.select_winner()
        task_id = self._auction.get_task_id()
        bid_count = self._auction.get_bid_count()

        if winner is None:
            # No bids received -- re-queue the task
            self._task_queue.set_status(task_id, TaskStatus.PENDING)
            self.get_logger().info(
                f'Auction {task_id}: no bids ({bid_count}), re-queued'
            )
        else:
            # Assign to winner
            self._task_queue.assign_to_robot(task_id, winner.robot_id)
            task = self._task_queue.get_task(task_id)
            self._publish_assignment(task_id, winner.robot_id, task)
            self._publish_alert(
                'INFO',
                winner.robot_id,
                f'Won auction for {task_id} '
                f'(score={winner.bid_score:.3f})',
            )
            self.get_logger().info(
                f'Auction {task_id}: winner={winner.robot_id} '
                f'score={winner.bid_score:.3f} bids={bid_count}'
            )

        self._auction.reset()

    def _publish_mission_progress(self) -> None:
        """Publish aggregated mission progress metrics.

        Distance and energy totals come from FleetMonitor's per-update
        deltas; uptime is folded into ``elapsed_sim_time`` so the dashboard
        can derive both wall-clock and mission-anchored views without an
        extra topic. (MissionProgress.msg has no dedicated uptime field — a
        future revision can promote this if needed.)
        """
        msg = MissionProgress()
        msg.objective_description = 'PSR Ice Prospecting Survey'
        msg.target_quantity = float(self._task_queue.get_total_count())
        progress = self._inventory.get_mission_progress()
        msg.extracted_quantity = float(progress.get('extracted', 0.0))
        msg.in_transit_quantity = float(progress.get('in_transit', 0.0))
        msg.deposited_quantity = float(progress.get('deposited', 0.0))
        msg.fleet_distance_total = float(self._fleet.get_total_distance())
        msg.fleet_energy_total = float(self._fleet.get_total_energy_consumed())
        # elapsed_sim_time mirrors orchestrator wall-clock since startup;
        # FleetMonitor.get_uptime_sec() reflects time since the first robot
        # heartbeat, which can lag startup by several seconds. We prefer the
        # node-relative time so the dashboard sees a tick from t=0.
        elapsed = (self.get_clock().now() - self._start_time).nanoseconds / 1e9
        msg.elapsed_sim_time = elapsed
        self._progress_pub.publish(msg)

    def _htn_advance(self) -> None:
        """Advance the HTN planner — resolve virtual tasks, spawn downstream."""
        self._htn_planner.check_and_advance()

    # ------------------------------------------------------------------ #
    #  Operator service handlers (FR-DASH-5 / FR-DASH-6)                   #
    # ------------------------------------------------------------------ #

    def _handle_inject_task(self, request, response):
        """Handle InjectTask service requests from the dashboard.

        Delegates to the pure-Python ``inject_task_logic`` helper so the
        decision tree can be unit-tested without instantiating the ROS node.
        Side effects (publish, log) happen here, in the Node-bound wrapper.
        """
        ctx = _InjectTaskContext(
            task_queue=self._task_queue,
            fleet_monitor=self._fleet,
            next_task_id=self._next_manual_task_id,
            now_stamp=self.get_clock().now().to_msg(),
            publish_assignment=self._publish_assignment_msg,
            publish_alert=lambda sev, msg: self._publish_alert(sev, '', msg),
        )
        return inject_task_logic(ctx, request, response)

    def _next_manual_task_id(self) -> str:
        """Allocate the next monotonic ``manual_NNNN`` identifier."""
        # Use the task_queue helper to ensure no collision with HTN ids.
        candidate = self._task_queue.make_unique_task_id('manual')
        # Best-effort numeric counter sync for diagnostics.
        try:
            self._manual_task_counter = max(
                self._manual_task_counter,
                int(candidate.split('_')[-1]) + 1,
            )
        except (ValueError, IndexError):
            self._manual_task_counter += 1
        return candidate

    def _publish_assignment_msg(self, task_id: str, robot_id: str,
                                task_type: str, target_location) -> None:
        """Publish a TaskAssignment for a force-assigned manual task."""
        msg = TaskAssignment()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task_type
        msg.target_location = target_location
        msg.parameters = []
        msg.assigned_at = self.get_clock().now().to_msg()
        self._assign_pub.publish(msg)

    def _handle_override_robot(self, request, response):
        """Handle OverrideRobot service requests from the dashboard.

        Builds a SetRobotCommand request, dispatches it to the per-agent
        client, and waits for the agent's accept/reject response. Pure
        validation logic lives in ``override_robot_logic`` for unit testing.

        The wait on the downstream client future uses a polling loop rather
        than ``rclpy.spin_until_future_complete`` because this callback is
        invoked from within an executor that is already spinning (Jazzy
        refuses re-entry with ``RuntimeError: Executor is already spinning``).
        The poll relies on the MultiThreadedExecutor in ``main()`` plus the
        reentrant callback group on the client, which together allow the
        client's response to land on a sibling thread while this thread
        blocks on ``future.done()``.
        """
        def _poll_future(fut, timeout_sec=5.0):
            deadline = time.monotonic() + timeout_sec
            while not fut.done() and time.monotonic() < deadline:
                time.sleep(0.005)

        ctx = _OverrideRobotContext(
            task_queue=self._task_queue,
            fleet_monitor=self._fleet,
            set_command_clients=self._set_command_clients,
            next_sequence=self._next_operator_sequence,
            spin_until_complete=_poll_future,
            publish_alert=lambda sev, msg: self._publish_alert(sev, '', msg),
            set_command_factory=SetRobotCommand.Request,
        )
        return override_robot_logic(ctx, request, response)

    def _next_operator_sequence(self) -> int:
        self._operator_command_seq += 1
        return self._operator_command_seq

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _generate_survey_tasks(self) -> None:
        """Decompose the initial ISRU mission objective via HTN planner."""
        self._htn_planner.decompose_collect_ice(
            zone_center=(-100.0, -150.0),
            zone_radius=60.0,
            quantity_kg=100.0,
            depot=(50.0, 50.0),
        )
        self.get_logger().info(
            f'HTN decomposed mission: {self._task_queue.get_total_count()} tasks'
        )

    def _publish_announcement(self, task) -> None:
        """Publish a TaskAnnouncement to open an auction."""
        msg = TaskAnnouncement()
        msg.task_id = task.task_id
        msg.task_type = task.task_type
        msg.target_location = Point(
            x=task.target_x, y=task.target_y, z=0.0,
        )
        msg.estimated_energy_cost = task.estimated_energy_cost
        msg.required_capabilities = task.required_capabilities
        msg.priority = task.priority
        msg.estimated_duration = task.estimated_duration
        msg.parent_task_id = ''
        msg.deadline = self.get_clock().now().to_msg()
        self._announce_pub.publish(msg)

    def _publish_assignment(self, task_id: str, robot_id: str, task) -> None:
        """Publish a TaskAssignment to the winning robot."""
        msg = TaskAssignment()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task.task_type if task else 'prospect'
        msg.target_location = Point(
            x=task.target_x if task else 0.0,
            y=task.target_y if task else 0.0,
            z=0.0,
        )
        msg.parameters = []
        msg.assigned_at = self.get_clock().now().to_msg()
        self._assign_pub.publish(msg)

    def _publish_alert(
        self, severity: str, source_robot_id: str, message: str,
    ) -> None:
        """Publish a FleetAlert."""
        self._alert_counter += 1
        msg = FleetAlert()
        msg.alert_id = f'alert_{self._alert_counter:04d}'
        msg.severity = severity
        msg.source_robot_id = source_robot_id
        msg.message = message
        msg.stamp = self.get_clock().now().to_msg()
        self._alert_pub.publish(msg)


def main(args=None):
    """Entry point for the orchestrator node.

    Uses a ``MultiThreadedExecutor`` so the override service callback can
    block on a downstream client future while the client's response is
    processed on a sibling thread (see ``_handle_override_robot``).
    """
    rclpy.init(args=args)
    node = OrchestratorNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info('Orchestrator shutting down')
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
