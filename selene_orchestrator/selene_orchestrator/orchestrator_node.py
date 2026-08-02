"""Fleet orchestrator node for SELENE multi-agent coordination.

Manages task auction, fleet health monitoring, and resource map.
Generates prospect survey waypoints and distributes them via auction.
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from selene_msgs.msg import (
    BidResponse as BidResponseMsg,
    FleetAlert,
    MaterialEvent,
    MissionProgress,
    ResourceMap as ResourceMapMsg,
    ResourceMapUpdate,
    RobotState,
    TaskAnnouncement,
    TaskAssignment,
    TaskEvent as TaskEventMsg,
    TaskQueueState,
    TaskResult,
    TaskStatus as TaskStatusMsg,
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

from builtin_interfaces.msg import Duration, Time
from geometry_msgs.msg import Point
from std_msgs.msg import ColorRGBA, Header
from visualization_msgs.msg import Marker, MarkerArray

from selene_orchestrator.fleet_monitor import (
    MAX_PLAUSIBLE_POSE_JUMP_M,
    POSE_MOTION_EPSILON_M,
    WHEEL_MOTION_EPSILON_MPS,
    FleetMonitor,
    FleetMotionReport,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus
from selene_orchestrator.task_auction import TaskAuction, Bid
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator import resource_map_viz as rmviz
from selene_orchestrator.task_feed import (
    AUCTION_ABANDONED,
    AUCTION_FLEET_CHANGED,
    AUCTION_NO_BIDS,
    AUCTION_PREEMPTED,
    KIND_OPERATOR,
    KIND_STATUS,
    OUTCOME_ASSIGN,
    OUTCOME_PREFERENCE_DROPPED,
    OUTCOME_REQUEUE,
    REQUEUE_STATUS_BY_REASON,
    TASK_ATTEMPTS_EXHAUSTED,
    TASK_MAX_ATTEMPTS,
    TASK_RETRY_REQUEUED,
    TaskEventLog,
    auction_backoff_sec,
    auction_failure_reason,
    resolve_auction_winner,
    should_preempt,
    task_rows,
)
from selene_orchestrator.htn_planner import HTNPlanner
from selene_orchestrator.adaptive_survey import (
    AdaptiveSurveyPlanner,
    replan_pending_survey_targets,
    should_replan,
    zone_peak_mean,
)
from selene_orchestrator.terrain_guard import (
    DEFAULT_TERRAIN_GUARD,
    DEFAULT_TERRAIN_HALF_EXTENT_M,
    DEFAULT_TERRAIN_MARGIN_M,
    TerrainGuard,
)
from selene_isru.inventory import MaterialInventory


# ---- Survey zone ---------------------------------------------------------- #
# The PSR this mission surveys. Used by BOTH the HTN decomposition
# (_generate_survey_tasks) and the FR-MAP-3 adaptive planner, which have to
# agree: the planner only proposes candidates inside this disc, so a
# disagreement would re-target waypoints outside the zone the mission was
# planned for. These two numbers were previously written out twice, once in
# _generate_survey_tasks and once as AdaptiveSurveyPlanner's constructor
# defaults, and only coincidence kept them equal.
SURVEY_ZONE_CENTER: tuple[float, float] = (-100.0, -150.0)
SURVEY_ZONE_RADIUS: float = 60.0

# Task type carrying survey waypoints, as created by
# HTNPlanner.decompose_collect_ice().
SURVEY_TASK_TYPE: str = 'prospect'


# ---- Operator-injected task constants ------------------------------------ #
# Capability requirements per manual task type. Keeping this at module scope
# lets unit tests verify the mapping without instantiating the full ROS node.
MANUAL_TASK_CAPABILITIES: dict[str, list[str]] = {
    'prospect': ['prospect'],
    'excavate': ['excavate'],
    'haul': ['haul'],
}

# Manual task types that move mass and therefore need a ledger site. A
# MaterialEvent whose task carries no site_id is dropped by
# material_event_logic step 4, so injecting one of these without a site
# produces a robot that really works, a task that really completes, a WARNING
# that reads like a fault, and a mission-progress numerator that never moves.
MATERIAL_TASK_TYPES: frozenset[str] = frozenset({'excavate', 'haul'})

# FSM states from which a robot cannot accept a freshly injected task.
INJECT_BLOCKED_STATES: frozenset[str] = frozenset({
    'ERROR', 'OFFLINE', 'RECHARGING',
})

# FSM states in which a robot is actively EXECUTING its assigned task rather
# than merely holding it. selene_agent/fsm.py's AgentState has nine members:
# IDLE, BIDDING, ASSIGNED, NAVIGATING, WORKING, RETURNING, RECHARGING, ERROR,
# OFFLINE. Two are deliberately absent here:
#   ASSIGNED  -- the assignment has landed but _handle_assigned has not started
#                the skill yet, which is exactly what TaskStatus.ASSIGNED
#                already says.
#   RETURNING -- the agent only enters it after firing FSMEvent.TASK_COMPLETE,
#                and _on_robot_state's completion fallback reads RETURNING as
#                "finished"; promoting there would fight that.
WORKING_FSM_STATES: frozenset[str] = frozenset({'NAVIGATING', 'WORKING'})

# FSM states from which a robot cannot accept any operator override.
OVERRIDE_BLOCKED_STATES: frozenset[str] = frozenset({'ERROR', 'OFFLINE'})

# Overrides that are accepted even from an OVERRIDE_BLOCKED_STATES state.
# ERROR must not be an inescapable state: the agent FSM already allows
# OPERATOR_CANCEL from ERROR -> IDLE (see selene_agent/fsm.py
# _build_full_table) and the agent's own operator_command_logic explicitly
# permits cancel_task in ERROR. Blocking it here made that recovery path
# unreachable from the dashboard, so a faulted robot could never be cleared.
# OFFLINE stays fully blocked — an unreachable agent cannot service the call.
OVERRIDE_BLOCKED_STATE_EXEMPT_COMMANDS: frozenset[str] = frozenset({
    'cancel_task',
})

# States that block even the exempt commands (no agent to talk to).
OVERRIDE_HARD_BLOCKED_STATES: frozenset[str] = frozenset({'OFFLINE'})

VALID_OVERRIDE_COMMANDS: frozenset[str] = frozenset({
    'cancel_task', 'send_to_location', 'force_recharge',
})


# ---- Pure-logic helpers for the operator service handlers ---------------- #
# These live at module scope so unit tests can drive them with mocks instead
# of standing up a full ROS node. The OrchestratorNode methods build a
# context object and delegate.


def _epoch_to_time(seconds: float) -> Time:
    """Wall-clock epoch seconds -> builtin_interfaces/Time.

    The queue and event log keep times as plain floats so they stay ROS-free
    and unit-testable; this is the single conversion point.

    WALL CLOCK, not ``time.monotonic()``: a monotonic value has an arbitrary
    epoch and would serialise into a Time field the dashboard renders as a date
    in 1970. Not simulation time either -- ``use_sim_time`` has zero code
    occurrences repo-wide.
    """
    value = max(0.0, float(seconds))
    sec = int(value)
    # round() at the top of the fractional range can produce exactly 1e9,
    # which is not a legal nanosec; carry it into the seconds field.
    nanosec = int(round((value - sec) * 1e9))
    if nanosec >= 1_000_000_000:
        sec += 1
        nanosec -= 1_000_000_000
    return Time(sec=sec, nanosec=nanosec)


def _ledger_qos(depth: int) -> QoSProfile:
    """RELIABLE + TRANSIENT_LOCAL, KEEP_LAST(depth) — the ledger profile.

    Used by both agent->orchestrator ledger topics. Publisher and subscriber
    must agree or DDS refuses the match entirely, which presents as a topic
    with a publisher, a subscriber, and no messages.

    NOT VERIFIED HERE: Fast DDS's transient-local replay behaviour could not be
    exercised on this box (no ROS install). If the assumption is wrong the
    design degrades to LOST HISTORY, never to double-counted mass, because
    MaterialEvent.event_id dedupe makes replay idempotent either way.
    """
    return QoSProfile(
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=depth,
    )


#: Material event types the ledger understands, mapped to what each one means.
#: Lower-case strings rather than uint8 constants, matching RobotState.fsm_state,
#: FleetAlert.severity and SetRobotCommand.command.
MATERIAL_EVENT_TYPES: frozenset[str] = frozenset({
    'extracted', 'loaded', 'unloaded',
})


# ---- Haul authorisation (D-06) ------------------------------------------- #
# Why a haul must not be dispatched, or '' when it may be. These strings are
# also the TaskStatus.status_reason the task is re-queued with, so the
# dashboard shows the cause instead of a bare PENDING (D-03).
HAUL_BLOCK_NO_SITE: str = 'haul_no_site'
HAUL_BLOCK_NO_MATERIAL: str = 'haul_no_material'


def authorise_task_quantity(task, site_available: Callable[[str], float],
                            ) -> tuple[float, str]:
    """Mass a TaskAssignment may authorise, kg, and why it may not be sent.

    Returns ``(quantity_kg, block_reason)``. ``block_reason`` is '' when the
    assignment may go out; any other value means the caller must NOT publish
    it and is suitable as a ``TaskStatus.status_reason``.

    ZERO IS NOT AVAILABLE AS "AUTHORISE NOTHING", and that is the whole reason
    this function returns two values instead of one. ``TaskAssignment.msg``
    documents ``quantity_kg`` 0.0 as *unconstrained -- fill to the robot's own
    RCDL capacity*, and the agent implements exactly that:
    ``HaulSkill._clamp_quantity`` maps any non-positive request to 0.0, and
    ``_update_loading`` then calls ``trigger_load(max_kg=-1.0)``, which
    ``GazeboTransferActuator`` sends as a bare ``"load"`` and the sim's fill
    model services by filling to ``capacity_kg``. So a haul published with 0.0
    does the OPPOSITE of authorising nothing: it authorises the hauler's whole
    50 kg bin (``selene_hal/config/hauler.yaml:29``) of material no excavator
    ever extracted. ``MaterialInventory.record_load`` then banks the excess as
    unaccounted mass and the next event raises a 'material conservation
    breach' alert -- blaming the instruments for the orchestrator's own
    fabrication. Returning 0.0 here as "nothing is authorised", which is what
    this used to do, was therefore the exact defect it was written to prevent.

    ONLY A HAUL IS GATED. An excavate at 0.0 genuinely means "fill the
    hopper", which is what every HTN-generated excavate wants and what
    ``ExcavateSkill`` does with it.

    AN OPERATOR-NAMED MASS IS HONOURED AS-IS, unclamped, even when the ledger
    says the site is empty (FR-DASH-5 / D-04: the operator asked for that
    number). It is not a fabrication by the orchestrator, and it is not
    silent either: ``record_load`` clamps the accepted mass to what the site
    actually holds and banks the difference in ``get_unaccounted_kg()``, which
    ``material_event_logic`` step 6 reports as a named overdraw and
    ``MissionProgress.unaccounted_quantity`` publishes.

    Args:
        task: a ``TaskEntry``-shaped object, or None.
        site_available: ``MaterialInventory.get_site_available`` -- kg waiting
            at a site, raising ``KeyError`` for a site nobody registered.
    """
    if task is None:
        return 0.0, ''
    explicit = float(getattr(task, 'quantity_kg', 0.0) or 0.0)
    if getattr(task, 'task_type', '') != 'haul':
        return (explicit if explicit > 0.0 else 0.0), ''
    if explicit > 0.0:
        return explicit, ''
    site_id = getattr(task, 'site_id', '') or ''
    if not site_id:
        return 0.0, HAUL_BLOCK_NO_SITE
    try:
        available = float(site_available(site_id))
    except KeyError:
        return 0.0, HAUL_BLOCK_NO_SITE
    if available <= 0.0:
        return 0.0, HAUL_BLOCK_NO_MATERIAL
    return available, ''


def apply_robot_progress(task_queue, msg) -> str:
    """Mirror one RobotState onto its queue entry. Returns the task_id touched.

    Two things, both of which need the queue's view of who holds what:

    1. ``TaskStatus.progress`` -- the ONLY source of it. A task no robot is
       currently running keeps its last reported value.
    2. ASSIGNED -> IN_PROGRESS, the transition D-03 left with no production
       writer at all. Every call site in this repository wrote AUCTIONING,
       ASSIGNED, COMPLETED, FAILED, INTERRUPTED or PENDING; IN_PROGRESS was
       written only by ``test_e2e_integration``'s own fixture. The dashboard
       draws the progress bar solely for ``status === 'IN_PROGRESS'``
       (``TaskQueue.jsx:120,173-182``), so ``TaskStatus.progress`` reached the
       browser and was discarded, and the 'RUN' badge and ``--in-progress``
       style were dead code.

    The promotion is gated on the robot naming THIS task
    (``current_task_id``): an agent free-running its own survey lattice sets
    ``current_task_id`` to ``prospect_<n>`` and an operator goto sets
    ``override_goto_<n>``, neither of which is an orchestrator task id, and
    neither should promote whatever the robot last won an auction for.

    Routed through ``set_status`` rather than assigning ``task.status`` so the
    transition also reaches ``TaskEventLog`` via the queue's status listener.
    ``set_status`` no-ops on an unchanged status, so this fires exactly once
    per task however often the robot reports.
    """
    robot_id = getattr(msg, 'robot_id', '') or ''
    active_task_id = task_queue.get_task_for_robot(robot_id)
    if not active_task_id:
        return ''
    task_queue.set_progress(
        active_task_id, float(getattr(msg, 'task_progress', 0.0)))
    if (getattr(msg, 'current_task_id', '') == active_task_id
            and getattr(msg, 'fsm_state', '') in WORKING_FSM_STATES):
        task_queue.set_status(
            active_task_id, TaskStatus.IN_PROGRESS, 'robot_started')
    return active_task_id


@dataclass
class _InjectTaskContext:
    """Injected dependencies for ``inject_task_logic``.

    ``publish_assignment`` is gone as of 2026-07-30: the force-assign path it
    served was deleted (D-04). A targeted injection is now a constrained
    auction, so nothing in this handler publishes a TaskAssignment.
    """
    task_queue: Any
    fleet_monitor: Any
    next_task_id: Callable[[], str]
    now_stamp: Any
    publish_alert: Callable[[str, str], None]
    #: The mission's ledger site (``HTNPlanner.get_site_id()``), or '' before
    #: SelectSite has resolved. Stamped onto injected excavate/haul tasks so
    #: their MaterialEvents can be credited; see ``inject_task_logic`` step 3.
    site_id: str = ''
    #: The terrain box an injected target must lie inside. Defaulted to the
    #: shipped world rather than to ``None``: a guard that switches itself off
    #: when a caller forgets to supply one reads as protection and is not.
    terrain: TerrainGuard = DEFAULT_TERRAIN_GUARD


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
    #: The terrain box a ``send_to_location`` target must lie inside. Same
    #: default, for the same reason, as ``_InjectTaskContext.terrain``.
    terrain: TerrainGuard = DEFAULT_TERRAIN_GUARD


def inject_task_logic(ctx: _InjectTaskContext, request, response):
    """Pure decision tree for InjectTask. Mutates ctx state, returns response.

    FR-DASH-5, rewritten 2026-07-30 to close D-04. Two things changed.

    (1) ``request.quantity`` IS NOW READ. It was carried in the .srv, collected
    by the dashboard's TaskInjector, and never looked at: the control was dead
    end to end. It is kilograms, validated ``>= 0`` and finite, stored on the
    queue entry, announced, assigned and honoured by the excavate skill. 0.0
    means unconstrained -- fill to the robot's own RCDL capacity, which is what
    every task did before, so 0.0 is exactly backward-compatible. It is NOT
    clamped here: the orchestrator has no HAL and no RCDL, so the capacity
    limit belongs to the agent, against selene_hal/config/<type>.yaml.
    For 'prospect' it is ignored (a survey has no mass) and the response says so.

    (2) A TARGETED INJECTION NO LONGER FORCE-ASSIGNS. ``assigned_robot_id``
    becomes ``TaskEntry.preferred_robot`` and the task enters the auction like
    any other -- which is what docs/PRD.md:533 (FR-DASH-5(b)) asks for, and
    which the old code did only when no robot was named. The removed path was
    already broken for the case it existed to serve: it pre-empted the target
    robot's running task and then published a TaskAssignment that
    ``agent_node._on_task_assigned`` discards for any robot not in BIDDING or
    ASSIGNED -- i.e. exactly the busy robot it was meant to serve. The operator
    lost the running task and gained nothing. To take a robot off its work,
    use OverrideRobot 'cancel_task' first; that path is logged, appears in the
    task history, and works.

    (3) AN EXCAVATE OR HAUL IS STAMPED WITH THE MISSION'S LEDGER SITE, and
    refused when there is not one yet. Manual injections used to be created
    with no ``site_id`` at all, so ``material_event_logic``'s step-4 guard
    dropped every MaterialEvent they produced: the operator got a robot that
    really drilled the mass it asked for, a task that completed, a WARNING
    alert that reads like a fault, and a mission-progress bar that did not
    move. Refusing up front says the same thing at the moment the operator can
    still act on it.

    (4) THE TARGET IS BOUNDED BY THE TERRAIN. It was not bounded by anything:
    the operator's coordinates went straight onto the queue. With the frame
    defect fixed those coordinates are now genuinely world metres, and a world
    metre outside the 500 m heightfield is a place with no ground under it -- a
    robot sent there falls, and the falling body's collision AABB aborts the
    whole simulator (see ``terrain_guard``). Refused, not clamped, because the
    operator is present and can retype it.

    (5) ``request.emergency`` IS READ, and it is the only thing in this system
    that can abort an auction already in flight (2026-08-01). It is A DELIBERATE
    CHANGE TO AUCTION SEMANTICS decided by the operator, not a defect fix, and
    the asymmetry is the whole point: an emergency injection may take the single
    auction slot from a strictly lower-priority task in the same tick, while a
    NON-emergency injection at the same priority 10.0 waits for that auction to
    resolve, exactly as every injection did before. Priority alone still
    preempts nothing. See ``task_feed.should_preempt`` and
    ``TaskQueue.abort_auction``. The response message states which of the two
    behaviours the operator just bought.

    IT BUYS ONE ABORT, NOT A STANDING LICENCE. Nothing ever clears
    ``TaskEntry.emergency``, so the entitlement is bounded by
    ``TaskEntry.preemption_spent`` instead, and it is spent only on a tick that
    goes on to announce the emergency in the same pass -- see
    ``OrchestratorNode._preempt_for_emergency``. An emergency the fleet cannot
    serve therefore aborts nothing, rather than aborting a fresh auction every
    time any robot anywhere finishes anything.

    Decision order:
        1. Reject unknown task_type.
        2. Reject a negative or non-finite quantity.
        3. Reject a target outside the terrain safe area.
        4. Reject an excavate/haul when no extraction site has been selected.
        5. Allocate a fresh manual task_id; add the task at priority 10.0
           (above HTN baseline) with capability requirements, the quantity,
           the preferred robot, the ledger site and the emergency flag.
        6. If a robot was named, run three ADVISORY pre-checks -- it exists,
           it is not in ERROR/OFFLINE/RECHARGING, it has the capability. They
           are advisory because the auction itself now enforces capability and
           availability; they survive because they give the operator an
           immediate, specific reason instead of a task that quietly never
           gets picked up. A failed pre-check still rejects the injection and
           marks the phantom row FAILED.

    Failure paths set the freshly-created manual task to FAILED so the
    queue does not retain a phantom row, then return success=False with a
    diagnostic message.
    """
    if request.task_type not in MANUAL_TASK_CAPABILITIES:
        response.success = False
        response.task_id = ''
        response.message = f"invalid task_type '{request.task_type}'"
        return response

    quantity = float(getattr(request, 'quantity', 0.0) or 0.0)
    if not math.isfinite(quantity) or quantity < 0.0:
        response.success = False
        response.task_id = ''
        response.message = (
            f'invalid quantity {getattr(request, "quantity", None)!r}: '
            f'must be finite and >= 0 kg (0 = fill to capacity)'
        )
        return response

    # THE TERRAIN BOX. Checked BEFORE add_task, like the quantity rejection
    # above and for the same reason: a rejected injection must leave no phantom
    # row behind. Every task type is checked, prospect included -- a survey
    # waypoint off the map drives a scout off the map just as surely as an
    # excavation does.
    terrain = getattr(ctx, 'terrain', DEFAULT_TERRAIN_GUARD)
    target_x = float(request.target_location.x)
    target_y = float(request.target_location.y)
    if not terrain.contains(target_x, target_y):
        response.success = False
        response.task_id = ''
        response.message = terrain.rejection(
            target_x, target_y, request.task_type)
        return response

    # A survey has no mass. Accept the request rather than rejecting it -- the
    # operator has not asked for anything impossible -- but say plainly that
    # the number was discarded, so it does not look honoured in the UI.
    quantity_ignored = request.task_type == 'prospect' and quantity > 0.0
    stored_quantity = 0.0 if request.task_type == 'prospect' else quantity

    # The mission has exactly ONE ledger site: HTNPlanner allocates it when the
    # SelectSite virtual task resolves, and the orchestrator registers it with
    # MaterialInventory in the same tick (_htn_advance). An operator excavation
    # is therefore credited to THAT site whatever coordinates the operator
    # picked -- the ledger is keyed by site_id and never by position. Poses are
    # world-referenced since 2026-07-31 (register D-08's open item is fixed;
    # see selene_sim/selene_sim/world_odometry_node.py) but they are still
    # dead-reckoned, so two robots at one physical place agree only up to their
    # accumulated wheel slip. Naming the credited site in the response is what
    # keeps the operator's coordinates and the ledger's key visibly separate.
    # Rejected BEFORE add_task so no phantom row is left behind, matching the
    # quantity rejection above.
    site_id = (getattr(ctx, 'site_id', '') or '').strip()
    if request.task_type in MATERIAL_TASK_TYPES and not site_id:
        response.success = False
        response.task_id = ''
        response.message = (
            f"no extraction site has been selected yet, so a "
            f"'{request.task_type}' task cannot be credited to the material "
            f'ledger; wait for the survey to resolve SelectSite, or inject a '
            f'prospect task to help it along'
        )
        return response
    stored_site_id = site_id if request.task_type in MATERIAL_TASK_TYPES else ''

    cap_required = list(MANUAL_TASK_CAPABILITIES[request.task_type])
    task_id = ctx.next_task_id()
    assigned_robot_id = (request.assigned_robot_id or '').strip()

    # EMERGENCY (2026-08-01). ``getattr`` with a False default, matching the
    # ``quantity`` read above and for the same two reasons: the ROS-free test
    # lane builds request objects by hand, and a dashboard talking to an
    # orchestrator built before this field existed must degrade to today's
    # behaviour rather than raise. False IS today's behaviour, so the fail-safe
    # direction and the backward-compatible direction are the same one.
    #
    # THIS IS THE ENTIRE CONTROL SURFACE. There is deliberately no ROS
    # parameter: test_no_orphan_parameters.py fails the build on any declared
    # parameter nothing reads and its allow-list is down to one name, and more
    # to the point a tunable would be a way to turn "the operator said
    # emergency" into "the orchestrator decided", which is the thing this design
    # refuses to do.
    emergency = bool(getattr(request, 'emergency', False))

    ctx.task_queue.add_task(
        task_id=task_id,
        task_type=request.task_type,
        target_x=target_x,
        target_y=target_y,
        priority=10.0,
        required_capabilities=cap_required,
        site_id=stored_site_id,
        quantity_kg=stored_quantity,
        preferred_robot=assigned_robot_id,
        emergency=emergency,
    )

    def _reject(message: str):
        ctx.task_queue.set_status(task_id, TaskStatus.FAILED,
                                  'inject_rejected')
        response.success = False
        response.task_id = task_id
        response.message = message
        return response

    if assigned_robot_id:
        robot = ctx.fleet_monitor.get_robot(assigned_robot_id)
        if robot is None:
            return _reject(f"unknown robot '{assigned_robot_id}'")

        fsm_state = robot.get('fsm_state', '') if isinstance(robot, dict) \
            else getattr(robot, 'fsm_state', '')
        capabilities = robot.get('capabilities', []) if isinstance(robot, dict) \
            else getattr(robot, 'capabilities', [])

        if fsm_state in INJECT_BLOCKED_STATES:
            return _reject(f"robot in {fsm_state}, cannot accept task")

        missing = [c for c in cap_required if c not in (capabilities or [])]
        if missing:
            return _reject(f"robot lacks capabilities {missing}")

    suffix = f' (preferred {assigned_robot_id})' if assigned_robot_id else ''
    message = f'queued{suffix}'
    # SAY WHAT THE FLAG WILL DO, IN BOTH DIRECTIONS. This string is the
    # operator's toast (TaskInjector.jsx renders response.message verbatim) and
    # the TaskEvent detail in the dashboard's history (_handle_inject_task
    # copies it), so one sentence written here is the whole account of a
    # semantics change the operator just triggered. The non-emergency branch is
    # stated too, and is not noise: "waits for the auction in flight" is the
    # behaviour a reader is most likely to assume priority 10.0 overrides.
    if emergency:
        message += ('; EMERGENCY: preempts an auction already in flight for a '
                    'lower-priority task -- ONCE, and only when a capable '
                    'robot is idle to take it')
    else:
        message += '; not an emergency: waits for any auction already in flight'
    if quantity_ignored:
        message += f'; quantity {quantity:.1f} kg ignored for prospect'
    elif stored_quantity > 0.0:
        message += f'; target {stored_quantity:.1f} kg'
    if stored_site_id:
        # Said out loud because it may not be where the operator clicked: the
        # ledger has one site per mission and it is keyed by id, not position.
        message += f'; credited to {stored_site_id}'

    urgency = ' as an EMERGENCY (may preempt an auction in flight)' \
        if emergency else ''
    ctx.publish_alert(
        'INFO', f'operator queued {task_id} for auction{suffix}{urgency}')
    response.success = True
    response.task_id = task_id
    response.message = message
    return response


def override_robot_logic(ctx: _OverrideRobotContext, request, response):
    """Pure decision tree for OverrideRobot. Returns the populated response.

    Validation order:
        1. Reject unknown ``request.command``.
        1b. For ``send_to_location``, reject a target off the terrain. FIRST
           among the checks that touch state, and before the robot lookup, so
           the refusal costs nothing and cannot half-apply: a coordinate outside
           the 500 m heightfield is a place with no ground under it, and a robot
           driven there falls until its collision AABB aborts Gazebo (see
           ``terrain_guard``). ``cancel_task`` and ``force_recharge`` ignore
           ``request.target`` entirely, so they are not checked -- rejecting
           them on a field they do not read would be a lie about why.
        2. Reject unknown robot.
        3. Reject robots in OFFLINE (any command) and robots in ERROR for
           every command except ``cancel_task`` — cancel is the operator's
           only way out of ERROR, so it is always allowed through.
        4. For ``cancel_task`` and ``force_recharge``, interrupt the current
           task (if any). It RESTS in INTERRUPTED and a future auction
           re-dispatches it from there: ``get_next_ready`` considers
           REQUEUEABLE_STATUSES, which is PENDING *and* INTERRUPTED. The
           immediate ``set_status(..., PENDING)`` that used to follow was
           deleted on 2026-07-30 -- it made a cancelled task indistinguishable
           from a fresh queue entry, which is D-03's headline defect.
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

    if request.command == 'send_to_location':
        terrain = getattr(ctx, 'terrain', DEFAULT_TERRAIN_GUARD)
        target_x = float(request.target.x)
        target_y = float(request.target.y)
        if not terrain.contains(target_x, target_y):
            response.success = False
            response.message = terrain.rejection(
                target_x, target_y, 'send_to_location')
            ctx.publish_alert(
                'WARNING',
                f'operator override: {request.robot_id} {request.command} -> '
                f'{response.message}',
            )
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

    blocked = (
        fsm_state in OVERRIDE_HARD_BLOCKED_STATES
        or (
            fsm_state in OVERRIDE_BLOCKED_STATES
            and request.command not in OVERRIDE_BLOCKED_STATE_EXEMPT_COMMANDS
        )
    )
    if blocked:
        response.success = False
        response.message = f"robot in {fsm_state}, override rejected"
        ctx.publish_alert(
            'INFO',
            f'operator override: {request.robot_id} {request.command} -> '
            f'{response.message}',
        )
        return response

    # Requeue any in-flight task before yanking the robot off it. It lands in
    # INTERRUPTED and stays there until an auction picks it up again.
    if request.command in ('cancel_task', 'force_recharge') and current_task_id:
        ctx.task_queue.interrupt_task(
            current_task_id, {'reason': f'operator_{request.command}'},
            reason=f'operator_{request.command}',
        )

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


# ---- The material ledger (D-06 / FR-ISRU-2) ------------------------------ #


@dataclass
class _MaterialEventContext:
    """Long-lived state for ``material_event_logic``.

    Built ONCE by the node and reused for every event, because three of its
    fields are accumulators that must survive between calls: the dedupe window,
    the applied counter, and the conservation latch.
    """
    task_queue: Any
    inventory: Any
    #: severity, source_robot_id, message
    publish_alert: Callable[[str, str, str], None]
    residual_tolerance_kg: float = 0.5
    #: Overdraw this small is float32 conversion noise between the
    #: excavator's hopper sensor and the hauler's load cell, not a
    #: disagreement. See MaterialInventory.record_load and
    #: `material_overdraw_tolerance_kg` in orchestrator_params.yaml.
    overdraw_tolerance_kg: float = 0.0
    dedupe_size: int = 4096
    seen_ids: set = field(default_factory=set)
    #: FIFO of the ids in ``seen_ids``, so eviction is O(1) and bounded.
    seen_order: Any = None
    events_applied: int = 0
    #: One alert per conservation BREACH, not per event. A persistent
    #: discrepancy would otherwise emit an alert at every material event and
    #: bury everything else in AlertLog.jsx.
    conservation_ok: bool = True

    def __post_init__(self):
        if self.seen_order is None:
            self.seen_order = deque(maxlen=max(1, int(self.dedupe_size)))


def material_event_logic(ctx: _MaterialEventContext, msg) -> bool:
    """Apply one MaterialEvent to the ledger. Returns True if it was applied.

    This is the writer ``MaterialInventory`` never had. Until 2026-07-30
    ``register_site`` / ``record_extraction`` / ``record_load`` /
    ``record_unload`` had zero production callers, so every mass in
    MissionProgress was structurally 0.0 and ``check_conservation()`` passed
    trivially as 0 == 0 + 0 (register entry D-06).

    Decision order, and every branch of it is a way the ledger could be
    corrupted rather than merely unfilled:

    1. Duplicate ``event_id`` -> return, no side effect, no alert. The
       publisher uses TRANSIENT_LOCAL, so an orchestrator that restarts
       receives each agent's history again; without this, replay would DOUBLE
       the mission's mass. An event with an EMPTY event_id is still applied,
       but it cannot be deduped and a replay would double-count it; nothing in
       this repository publishes one (``MaterialEventIdGenerator`` always
       produces an id), so this is a note about a message from elsewhere, not
       about the agent.
    2. Malformed mass (non-finite, or negative) -> drop with a WARNING. A
       clamp would turn a broken sensor into a plausible number.
    3. Unknown event_type -> drop with a WARNING.
    4. Task unknown to the queue, or its ``site_id`` is empty -> drop with a
       WARNING. NEVER register a site on the fly: an invented site accepts mass
       into a bucket nothing else knows about, and the conservation identity
       then holds trivially again -- exactly the failure this whole change
       exists to remove.
    5. Dispatch to the ledger.
    6. A load the site could not cover -> WARNING naming site, requested and
       accepted mass. That difference is two instruments disagreeing about the
       same material, which is what FR-ISRU-2 says cannot happen.
    7. ``residual_mass_kg`` beyond tolerance after 'unloaded' or 'extracted'
       -> WARNING. Both should leave the container empty; a hauler reporting
       19 kg delivered while its load cell still reads 7 kg is a fault only
       this field can show.
    8. ``check_conservation()`` false -> one WARNING per breach.
    """
    event_id = getattr(msg, 'event_id', '') or ''
    robot_id = getattr(msg, 'robot_id', '') or ''
    task_id = getattr(msg, 'task_id', '') or ''
    event_type = getattr(msg, 'event_type', '') or ''

    # 1. Idempotence.
    if event_id and event_id in ctx.seen_ids:
        return False

    # 2. A mass that is not a mass.
    try:
        mass_kg = float(getattr(msg, 'mass_kg', 0.0))
        residual_kg = float(getattr(msg, 'residual_mass_kg', 0.0))
    except (TypeError, ValueError):
        mass_kg, residual_kg = float('nan'), 0.0
    if not math.isfinite(mass_kg) or mass_kg < 0.0:
        ctx.publish_alert(
            'WARNING', robot_id,
            f'material event {event_id or "<no id>"} dropped: mass_kg '
            f'{getattr(msg, "mass_kg", None)!r} is not a valid mass')
        return False

    # 3. An event type the ledger has no stage for.
    if event_type not in MATERIAL_EVENT_TYPES:
        ctx.publish_alert(
            'WARNING', robot_id,
            f'material event {event_id or "<no id>"} dropped: unknown '
            f"event_type '{event_type}'")
        return False

    # 4. Resolve the site from the TASK, never from a position. Poses are
    #    world-referenced since 2026-07-31 (register D-08's open item;
    #    selene_sim/selene_sim/world_odometry_node.py) but they are still
    #    dead-reckoned, so two robots at one physical place agree only up to
    #    accumulated wheel slip and a position key would split one deposit into
    #    several the moment that slip exceeded its tolerance. An id has no
    #    tolerance to get wrong.
    task = ctx.task_queue.get_task(task_id)
    site_id = getattr(task, 'site_id', '') if task is not None else ''
    if task is None or not site_id:
        ctx.publish_alert(
            'WARNING', robot_id,
            f"material event {event_id or '<no id>'} ({event_type}, "
            f'{mass_kg:.2f} kg) dropped: task '
            f"'{task_id}' is "
            + ('unknown to the queue' if task is None
               else 'not associated with any extraction site'))
        return False

    # 5. Apply.
    try:
        if event_type == 'extracted':
            ctx.inventory.record_extraction(site_id, robot_id, mass_kg)
        elif event_type == 'loaded':
            accepted = ctx.inventory.record_load(
                robot_id, site_id, mass_kg, ctx.overdraw_tolerance_kg)
            # 6. The cross-instrument check. The tolerance is not decoration:
            # every mass here has been through float32 on the wire, and the
            # 1e-6 kg this used to compare against is finer than one ulp at
            # 19 kg (1.9e-6 kg), so the alert fired on healthy hauls. See
            # `material_overdraw_tolerance_kg` in orchestrator_params.yaml.
            if accepted + ctx.overdraw_tolerance_kg < mass_kg:
                ctx.publish_alert(
                    'WARNING', robot_id,
                    f'load overdraw at {site_id}: {robot_id} reported '
                    f'{mass_kg:.2f} kg but only {accepted:.2f} kg had been '
                    f'extracted there; {mass_kg - accepted:.2f} kg is '
                    f'unaccounted')
        else:                                            # 'unloaded'
            ctx.inventory.record_unload(robot_id, mass_kg)
    except KeyError:
        ctx.publish_alert(
            'WARNING', robot_id,
            f"material event {event_id or '<no id>'} dropped: site "
            f"'{site_id}' is not registered in the ledger")
        return False

    # 7. Does the instrument agree with the transfer it just reported?
    if event_type in ('unloaded', 'extracted'):
        if abs(residual_kg) > ctx.residual_tolerance_kg:
            ctx.publish_alert(
                'WARNING', robot_id,
                f'{robot_id} reported {mass_kg:.2f} kg {event_type} but its '
                f'fill sensor still reads {residual_kg:.2f} kg (tolerance '
                f'{ctx.residual_tolerance_kg:.2f} kg)')

    if event_id:
        if len(ctx.seen_order) == ctx.seen_order.maxlen:
            ctx.seen_ids.discard(ctx.seen_order[0])
        ctx.seen_order.append(event_id)
        ctx.seen_ids.add(event_id)
    ctx.events_applied += 1

    # 8. Latched conservation alert.
    ok = ctx.inventory.check_conservation()
    if ok:
        ctx.conservation_ok = True
    elif ctx.conservation_ok:
        ctx.conservation_ok = False
        progress = ctx.inventory.get_mission_progress()
        ctx.publish_alert(
            'WARNING', robot_id,
            'material conservation breach: extracted '
            f'{progress.get("extracted", 0.0):.2f} kg vs at_site '
            f'{progress.get("at_site", 0.0):.2f} + in_transit '
            f'{progress.get("in_transit", 0.0):.2f} + deposited '
            f'{progress.get("deposited", 0.0):.2f}; unaccounted '
            f'{progress.get("unaccounted", 0.0):.2f} kg')
    return True


def build_mission_progress(msg, *, objective_description: str,
                           target_kg: float, ledger: dict,
                           fleet_distance_m: float, fleet_energy_wh: float,
                           elapsed_sec: float, fleet_uptime_sec: float,
                           material_events_applied: int):
    """Fill a MissionProgress message. FR-DASH-7.

    Factored out of the node so the ROS-free lane can assert the field/unit
    mapping; the node passes a real message, a test passes any object with the
    same attributes.

    UNITS, every one of them, because this message has already carried a task
    count into a kg formatter once:
      target/extracted/at_site/in_transit/deposited/unaccounted  kg
      fleet_distance_total                                       METRES
      fleet_energy_total                                         WATT-HOURS
      elapsed_sim_time                                           seconds
      fleet_uptime_sec                                           seconds
    """
    msg.objective_description = objective_description
    msg.target_quantity = float(target_kg)
    msg.extracted_quantity = float(ledger.get('extracted', 0.0))
    msg.in_transit_quantity = float(ledger.get('in_transit', 0.0))
    msg.deposited_quantity = float(ledger.get('deposited', 0.0))
    msg.fleet_distance_total = float(fleet_distance_m)
    msg.fleet_energy_total = float(fleet_energy_wh)
    msg.elapsed_sim_time = float(elapsed_sec)
    msg.fleet_uptime_sec = float(fleet_uptime_sec)
    msg.material_events_applied = int(material_events_applied)
    msg.at_site_quantity = float(ledger.get('at_site', 0.0))
    msg.unaccounted_quantity = float(ledger.get('unaccounted', 0.0))
    return msg


class OrchestratorNode(Node):
    """Central fleet orchestrator with auction-based task allocation.

    Lifecycle
    ---------
    1. On startup, declares ROS parameters, instantiates pure-Python core
       modules (FleetMonitor, TaskQueue, TaskAuction, ResourceMap), and
       generates PSR survey waypoints as prospect tasks.
    2. Subscribes to per-robot ``/<robot_id>/state`` topics, the shared
       ``/orchestrator/bid_response`` and ``/orchestrator/map_update`` topics,
       and the two agent->orchestrator ledger topics
       ``/orchestrator/material_event`` and ``/orchestrator/task_result``.
    3. Runs periodic timers:
       - heartbeat_check (1 Hz): detects timed-out robots, re-queues tasks.
       - auction_tick (2 Hz): starts / resolves auctions for pending tasks.
       - publish_mission_progress (1 Hz): broadcasts aggregate progress.
       - htn_advance (1 Hz): resolves virtual tasks, registers the ISRU site.
       - publish_task_queue (task_queue_publish_rate, default 2 Hz).
       - publish_resource_map (resource_map_publish_rate, default 0.5 Hz).
       - adaptive_survey_tick (adaptive_survey_replan_rate, default 0.2 Hz).
       The last three are disabled by a non-positive rate rather than crashing.
    """

    def __init__(self):
        super().__init__('orchestrator_node')

        # ---- Parameters ----
        self.declare_parameter('auction_timeout_sec', 5.0)
        self.declare_parameter('heartbeat_timeout_sec', 10.0)
        # `recharge_threshold` USED TO BE DECLARED HERE AND READ BY NOBODY —
        # deviation D-19. It was one of the two names on
        # test_no_orphan_parameters.py's allow-list, and the allow-list was
        # right: the orchestrator has no way to act on a battery threshold.
        # The robot decides its own recharges, so the parameter now lives on
        # the agent (selene_agent/agent_node.py, passed by
        # selene_agent/launch/agent.launch.py) where agent_node._recharge_reason
        # reads it. Same move, same reason, as the three bid weights (D-13).
        self.declare_parameter('fleet_state_publish_rate', 1.0)
        self.declare_parameter('resource_map_publish_rate', 0.5)
        # The frame the overlay is stamped with. MEASURED: nothing in this repo
        # publishes TF — /tf and /tf_static have zero publishers at runtime, and
        # no launch file bridges them out of Gazebo. RViz2 can still transform a
        # message whose frame_id is IDENTICAL to the fixed frame, via tf2's
        # same-frame identity shortcut, so the overlay renders with an empty TF
        # tree. Get this wrong and RViz shows "Fixed Frame [x] does not exist"
        # and a blank scene while the publisher works perfectly.
        # selene_sim/rviz/selene_sim.rviz must carry the same string as its
        # Fixed Frame; 'map' also matches the only other frame_id in the repo,
        # the nav_msgs/Path from selene_agent/navigator.py:679.
        self.declare_parameter('resource_map_frame_id', 'map')
        # Cap on cubes in the RViz overlay. MEASURED: 250000 cells at 24 B per
        # Point plus 16 B per ColorRGBA is 10.0 MB per MarkerArray and ~125 ms
        # of executor time per tick, and RM_BOXES renders 36 vertices per cube —
        # 9M vertices with alpha blending. Beyond the cap the observed set is
        # decimated with a deterministic stride, never truncated.
        self.declare_parameter('resource_map_max_marker_cells', 20000)
        # ---- FR-MAP-3: adaptive survey planning ----
        # Rate at which PENDING survey waypoints are re-scored against the fused
        # map. <= 0 disables adaptation and leaves the static hex lattice in
        # place, mirroring resource_map_publish_rate. 0.2 Hz because a scout
        # takes tens of seconds to reach a waypoint; one replan costs ~20 ms of
        # Python for 8 pending tasks at ~430 candidates each.
        self.declare_parameter('adaptive_survey_replan_rate', 0.2)
        # Lattice waypoints that must COMPLETE before adaptation starts.
        # MEASURED over 20 seeded runs of the real ice field: replanning after
        # ONE reading puts 0.29 of second-half waypoints on >=4 wt% ground
        # truth, WORSE than not adapting at all (0.60), because a single blob
        # gives one gradient and the planner chains away from it. After two:
        # 0.66. Must be an int; a float raises ParameterTypeException at start.
        self.declare_parameter('adaptive_survey_seed_waypoints', 2)
        # Peak posterior mean (wt%) that must exist in the zone before the
        # planner is trusted to converge on anything.
        self.declare_parameter('adaptive_survey_min_signal_wt', 1.0)
        # FR-MAP-3: "Weights are configurable."
        # w_variance is INERT at the shipped spacing, and that is not a bug:
        # min_spacing (8.0 m) exceeds ResourceMap's footprint_radius (5.0 m), so
        # every admissible candidate is unobserved and carries exactly
        # prior_variance. FR-MAP-3(a) "highest uncertainty first" is enforced by
        # the candidate FILTER, not by the score. Kept configurable because the
        # PRD asks for it, and because a min_spacing below 5.0 m revives it.
        self.declare_parameter('adaptive_survey_w_variance', 1.0)
        self.declare_parameter('adaptive_survey_w_signal', 0.5)
        self.declare_parameter('adaptive_survey_w_distance', 0.3)
        self.declare_parameter('adaptive_survey_min_spacing', 8.0)
        self.declare_parameter('adaptive_survey_candidate_resolution', 5.0)
        self.declare_parameter('map_resolution', 1.0)
        self.declare_parameter('map_width', 500)
        self.declare_parameter('map_height', 500)
        # ---- FR-DASH-3 / FR-DASH-6: the authoritative task-queue snapshot ----
        # 2.0 Hz against docs/PRD.md:1506 ("task queue reflects orchestrator
        # state within 1 second"), leaving a worst-case 500 ms publish latency
        # before transport. <= 0 disables the topic with a warning rather than
        # dividing by zero, the same convention as resource_map_publish_rate.
        self.declare_parameter('task_queue_publish_rate', 2.0)
        # Depth of the bounded event ring replayed in every snapshot. Every
        # message carries the whole ring, so this is a per-message cost as well
        # as a history depth; the dashboard dedupes on TaskEvent.seq.
        self.declare_parameter('task_queue_event_history', 32)
        # ---- FR-DASH-5: the constrained auction ----
        # Auctions a preferred robot may sit out before its preference is
        # dropped and the auction opens up. 3 rounds at auction_timeout_sec 5.0
        # is ~15 s of waiting for a robot the operator picked.
        self.declare_parameter('inject_preferred_robot_max_rounds', 3)
        # ---- D-20: the auction backoff ----
        # MEASURED live 2026-07-31: one prospect task reached auction round
        # 261, re-announcing every ~5.5 s forever at INFO, because
        # resolve_auction_winner's 'auction_no_bids' re-queued straight to
        # PENDING and get_next_ready returned the same task immediately. One
        # auction runs at a time, so that task held the slot and every other
        # PENDING task in the queue was starved for as long as no robot could
        # bid.
        #
        # Delay after the Nth consecutive no-bid auction is
        # base * 2**(N-1), capped: 5, 10, 20, 40, 80, 120, 120...
        # NOT derived from auction_timeout_sec, though 5.0 is the same number
        # today: how long an auction stays open and how long to wait before
        # opening another are different questions, and coupling them would
        # make a slower auction silently a slower retry.
        self.declare_parameter('auction_backoff_base_sec', 5.0)
        self.declare_parameter('auction_backoff_max_sec', 120.0)
        # Consecutive failed auctions before the task stops being announced at
        # all and rests visibly blocked with status_reason 'auction_abandoned'.
        # 5 rounds at the delays above is ~2.5 minutes of trying before giving
        # up. It is NOT permanent: any robot arriving in IDLE wakes every
        # abandoned task (FleetMonitor.idle_arrivals), because the alternative
        # is a mission that deadlocks, which is worse than the flood. <= 0
        # disables giving up and leaves only the backoff.
        self.declare_parameter('auction_max_failed_rounds', 5)
        # ---- D-22: noticing that the simulator has died ----
        # OBSERVED live 2026-07-31 at 10 robots (4/3/3): Gazebo hit an ODE
        # assertion in collide() and the gz process exited 134 about five
        # minutes in. `ros2 launch` SURVIVED. Every agent kept ticking and kept
        # publishing RobotState at 2 Hz, so heartbeat_timeout_sec saw a
        # perfectly healthy fleet; what stopped was the world. Navigation
        # failed fleet-wide with "Path blocked, no alternate route" as odom
        # froze, three scouts went to ERROR, and the orchestrator carried on
        # auctioning into a dead simulation with NO alert anywhere.
        #
        # Seconds a robot may be stationary WHILE EXPECTED TO MOVE before it
        # counts as stalled -- see FleetMonitor.assess_motion, and note that
        # "while expected to move" is D-30's repair: this used to be time since
        # the pose last changed, a clock that runs while a robot is parked.
        #
        # 10.0 s, TIGHTENED from 20.0 on 2026-07-31, and the tightening is not
        # what removes D-30's false positives -- assess_motion and the mover
        # quorum below do that. It is derived from the agent's own recovery
        # budget, which is the real bound on how long a robot may legitimately
        # sit still inside a motion state:
        #
        #   lower bound  > 5.0 s   one PathFollower stall-and-replan cycle
        #                          (selene_agent/navigator.py:478). One
        #                          legitimate recovery must never alert; 10.0
        #                          is 2x it.
        #   upper bound  < 20.0 s  (MAX_REPLAN_ATTEMPTS 3 + 1) x 5.0 s
        #                          (navigator.py:639, :478) -- the point at
        #                          which the skill fails, the FSM leaves the
        #                          motion state and the detector goes blind.
        #                          The old 20.0 sat exactly on that edge, i.e.
        #                          zero margin. 10.0 leaves half the window.
        #
        # A TURN CONTRIBUTES ZERO STATIONARY SECONDS, which is the claim the
        # old 20 s was really protecting and it did not need protecting.
        # PathFollower never commands zero linear velocity while FOLLOWING
        # (navigator.py:533-549): the worst-case speed_scale is 0.3 above 45
        # deg of heading error, so the floor is 0.5 x 1.0 x 0.3 = 0.15 m/s =
        # 7.5 cm per 0.5 s sample, 7.5x POSE_MOTION_EPSILON_M. Driving the real
        # follower through a 180 deg reversal from rest measures a minimum
        # per-sample displacement of 14.9x the epsilon on the slowest RCDL
        # (test_simulation_stall.py pins this), and D-35's independently
        # MEASURED about-turn -- 164.8 deg swept, carrying the body up to
        # 3.745 m from where it started over ~10.2 s -- is ~0.37 m/s of mean
        # body speed, 18x the epsilon per sample. Two measurements, one
        # analytic and one from a live run, agreeing on the same conclusion.
        #
        # The stated rationale this replaces cited a code path that does not
        # run: "a robot working around an obstacle can be under
        # POSE_MOTION_EPSILON_M for several seconds". ObstacleAvoidance has
        # zero production callers; the module is imported only by
        # selene_agent/test/test_navigator.py.
        #
        # <= 0 disables the check.
        self.declare_parameter('sim_stall_timeout_sec', 10.0)
        # How many robots must be expected to move before a stall may be
        # reported as a FLEET-level condition at all.
        #
        # 2, and it is a measurement rather than a taste. The shipped predicate
        # was run on one wedged robot among a parked fleet and on a dead
        # simulator: the output was IDENTICAL. One witness cannot support a
        # fleet-wide cause because a parked fleet contributes no evidence
        # either way; two can. FleetMotionReport.fleet_wide floors this at 2 so
        # it cannot be configured back down to the n=1 claim D-30 was opened
        # for. Raising it trades sensitivity for confidence: with 3, a genuine
        # simulator death while only two robots are driving is reported as two
        # per-robot ERRORs instead of one CRITICAL. Nothing goes silent either
        # way -- only the cause attribution is gated.
        self.declare_parameter('sim_stall_min_movers', 2)
        # ---- FR-DASH-7 / FR-ISRU-2: the material ledger ----
        # The ISRU processing depot every haul delivers to. NOT the recharge
        # station: see orchestrator_params.yaml for the three-way position
        # inconsistency this deliberately does not fix.
        self.declare_parameter('depot_x', 50.0)
        self.declare_parameter('depot_y', 50.0)
        # MaterialEvent ids retained for duplicate suppression. The topic is
        # TRANSIENT_LOCAL, so a restarting orchestrator is replayed each
        # agent's history and a repeat must be a no-op rather than doubled mass.
        self.declare_parameter('material_event_dedupe_size', 4096)
        # How much mass may remain in a hopper or bin after it reported
        # emptying before that counts as an instrument disagreement. 0.5 kg is
        # 2.5% of the excavator hopper's 20 kg and 1% of the hauler bin's 50 kg.
        self.declare_parameter('material_residual_tolerance_kg', 0.5)
        # How far a hauler's load cell may exceed the excavator's hopper
        # sensor before it is a real disagreement. Below one gram it is
        # float32 conversion noise: one ulp at 19 kg is 1.9e-6 kg and
        # the hard-coded 1e-6 this replaces was finer than that, so the
        # alert fired on every successful haul.
        self.declare_parameter('material_overdraw_tolerance_kg', 0.001)
        # ---- The terrain box every operator-supplied target must lie in ----
        # The heightfield is 500 m square centred on the origin
        # (selene_sim/models/lunar_terrain/model.sdf), so its half-extent is
        # 250 m; the margin is what a target must additionally keep clear of
        # that edge. Both numbers are derived and justified in
        # selene_sim/config/world_params.yaml (world.bounds, safety_margin_m),
        # and selene_sim/test/test_world_extent_agrees.py fails the build if
        # this file, that file, nav_params.yaml and terrain_datum.json stop
        # describing the same square. They are parameters rather than constants
        # so a different world (FR-SIM-7(d) makes the world file configurable)
        # can be given its own bound without a code change.
        self.declare_parameter('terrain_half_extent_m',
                               DEFAULT_TERRAIN_HALF_EXTENT_M)
        self.declare_parameter('terrain_margin_m', DEFAULT_TERRAIN_MARGIN_M)
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
        # FR-MAP-1(e): "published ... at configurable rate (default 0.5 Hz)".
        # This parameter was declared in Phase 3 and never read until now, so
        # the map was never published at all. test_no_orphan_parameters.py
        # exists to stop that happening again.
        map_rate = self.get_parameter('resource_map_publish_rate').value
        self._map_frame_id = self.get_parameter('resource_map_frame_id').value
        self._map_max_marker_cells = self.get_parameter(
            'resource_map_max_marker_cells').value
        replan_rate = self.get_parameter('adaptive_survey_replan_rate').value
        self._adaptive_seed_waypoints = int(
            self.get_parameter('adaptive_survey_seed_waypoints').value)
        self._adaptive_min_signal_wt = float(
            self.get_parameter('adaptive_survey_min_signal_wt').value)
        queue_rate = self.get_parameter('task_queue_publish_rate').value
        event_history = int(
            self.get_parameter('task_queue_event_history').value)
        self._preferred_robot_max_rounds = int(
            self.get_parameter('inject_preferred_robot_max_rounds').value)
        self._auction_backoff_base = float(
            self.get_parameter('auction_backoff_base_sec').value)
        self._auction_backoff_max = float(
            self.get_parameter('auction_backoff_max_sec').value)
        self._auction_max_failed_rounds = int(
            self.get_parameter('auction_max_failed_rounds').value)
        self._sim_stall_timeout = float(
            self.get_parameter('sim_stall_timeout_sec').value)
        self._sim_stall_min_movers = int(
            self.get_parameter('sim_stall_min_movers').value)
        self._depot = (float(self.get_parameter('depot_x').value),
                       float(self.get_parameter('depot_y').value))
        dedupe_size = int(
            self.get_parameter('material_event_dedupe_size').value)
        residual_tolerance = float(
            self.get_parameter('material_residual_tolerance_kg').value)
        overdraw_tolerance = float(
            self.get_parameter('material_overdraw_tolerance_kg').value)
        self._terrain = TerrainGuard(
            half_extent=float(
                self.get_parameter('terrain_half_extent_m').value),
            margin=float(self.get_parameter('terrain_margin_m').value),
        )

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
        # deposited_source wires the HTN planner's deposited_kg to the MEASURED
        # ledger. Without it the planner reports completed_hauls x nominal
        # hopper capacity -- a task count times an assumption -- and that number
        # would reach the dashboard as a mass.
        self._inventory = MaterialInventory()
        self._htn_planner = HTNPlanner(
            self._task_queue, self._resource_map,
            deposited_source=self._inventory.get_total_deposited,
        )
        # FR-MAP-3. The zone comes from the module constants so it cannot
        # drift from the HTN decomposition. signal_probe_radius is deliberately
        # NOT a ROS parameter: it defaults to min_spacing inside the planner,
        # and a value below (min_spacing - footprint_radius) silently zeroes the
        # signal term, which is the exact defect this change fixes.
        self._adaptive_survey = AdaptiveSurveyPlanner(
            self._resource_map,
            psr_center=SURVEY_ZONE_CENTER,
            psr_radius=SURVEY_ZONE_RADIUS,
            w_variance=float(
                self.get_parameter('adaptive_survey_w_variance').value),
            w_signal=float(
                self.get_parameter('adaptive_survey_w_signal').value),
            w_distance=float(
                self.get_parameter('adaptive_survey_w_distance').value),
            min_spacing=float(
                self.get_parameter('adaptive_survey_min_spacing').value),
            candidate_resolution=float(
                self.get_parameter(
                    'adaptive_survey_candidate_resolution').value),
        )
        # Reading count at the last replan; the "new evidence" half of the gate.
        self._adaptive_last_readings = 0

        # ---- D-03 / D-05: the task feed ----
        self._events = TaskEventLog(capacity=event_history)
        # One hook rather than an append at each of the eleven transition
        # sites, so a twelfth cannot be added without being logged.
        self._task_queue.set_status_listener(self._on_task_status_change)
        # ---- D-06: the material ledger ----
        self._material_ctx = _MaterialEventContext(
            task_queue=self._task_queue,
            inventory=self._inventory,
            publish_alert=self._publish_alert,
            residual_tolerance_kg=residual_tolerance,
            overdraw_tolerance_kg=overdraw_tolerance,
            dedupe_size=dedupe_size,
        )
        #: site_ids already handed to MaterialInventory.register_site.
        self._registered_sites: set[str] = set()
        #: task_id -> the haul block reason last alerted on, so a permanently
        #: undispatchable haul produces one alert rather than one per tick.
        self._haul_block_alerted: dict[str, str] = {}
        # ---- D-20: the auction backoff ----
        #: task_id -> the no-bid reason last LOGGED for it. The whole point of
        #: D-20's logging half: 261 rounds produced 261 identical INFO lines
        #: because nothing remembered what the last one said.
        self._auction_failure_logged: dict[str, str] = {}
        # ---- D2: the bounded skill retry ----
        #: task_ids already announced as having spent every attempt, so the
        #: mission-fatal alert is raised ONCE per task rather than at 2 Hz for
        #: the rest of the run. The same latch, for the same reason, as
        #: ``_auction_failure_logged`` above and ``_stalled_robots`` below; an
        #: exhausted task rests in FAILED forever, so without it this is the
        #: D-20 flood arriving from a third direction.
        self._attempts_exhausted_alerted: set[str] = set()
        #: ``FleetMonitor.idle_arrivals`` as of the last auction tick. A change
        #: means a robot arrived in IDLE, which is the only new information
        #: that can make an abandoned task biddable.
        self._last_idle_arrivals = 0
        #: D-22: True while a fleet-level motion stall is being reported, so
        #: the CRITICAL alert is raised once on entry and once on recovery
        #: rather than at 1 Hz for the rest of the mission.
        self._sim_stalled = False
        #: D-30: robots currently reported stalled, so each episode produces
        #: one ERROR and one matching INFO on recovery. Without this latch the
        #: per-robot alert is a 1 Hz flood, which is the failure D-20 exists
        #: to prevent arriving from a different direction.
        self._stalled_robots: set[str] = set()
        #: D-31: FleetMonitor.distance_rejections as of the last report. A
        #: refused pose increment that nobody logs is how the phantom distance
        #: survived a full run; this is compared each heartbeat so a rise gets
        #: exactly one line carrying the MAGNITUDE, not just a count.
        self._distance_rejections_reported = 0

        # ---- Tracking ----
        self._start_time = self.get_clock().now()
        self._alert_counter = 0
        #: D-18: ResourceMapUpdate messages ResourceMap.update() refused. A
        #: reading dropped silently is indistinguishable from a scout that
        #: never sampled, so _on_map_update logs off this counter.
        self._map_updates_rejected = 0
        #: D-18: consecutive _publish_resource_map failures. The map publisher
        #: is the one timer whose payload is derived arithmetic over ~250k
        #: cells, and an exception in an rclpy timer callback propagates out of
        #: the executor: it does not merely skip a frame, it takes the
        #: orchestrator down. Counted so the catch cannot hide a permanent
        #: fault behind an occasional log line.
        self._map_publish_failures = 0

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

        # Measured mass transfers and terminal task outcomes from agents.
        # RELIABLE + TRANSIENT_LOCAL on both ends: this is the ledger, and a
        # dropped sample is mass that vanishes from mission progress with
        # nothing logged anywhere. Transient-local also means an orchestrator
        # that starts after an agent still receives that agent's history, which
        # MaterialEvent.event_id dedupe makes idempotent.
        self.create_subscription(
            MaterialEvent,
            '/orchestrator/material_event',
            self._on_material_event,
            _ledger_qos(100),
        )
        self.create_subscription(
            TaskResult,
            '/orchestrator/task_result',
            self._on_task_result,
            _ledger_qos(50),
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
        # FR-MAP-1(e): the fused posterior itself.
        self._resource_map_pub = self.create_publisher(
            ResourceMapMsg, '/orchestrator/resource_map', 10,
        )
        # FR-MAP-4: the same posterior as a colour-coded RViz2 overlay.
        self._resource_map_marker_pub = self.create_publisher(
            MarkerArray, '/orchestrator/resource_map_markers', 10,
        )
        # FR-DASH-3: the authoritative task table plus the operator event ring.
        # DEFAULT (volatile) QoS, deliberately: a complete 2 Hz snapshot needs
        # no durability negotiation, and transient_local latching is the part of
        # ROS QoS rosbridge handles least predictably -- the bridge subscribes
        # with its own profile and a durability mismatch drops the sample with
        # nothing surfaced client-side.
        self._task_queue_pub = self.create_publisher(
            TaskQueueState, '/orchestrator/task_queue', 10,
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
        # FR-MAP-1(e) / FR-MAP-4. The only timer here whose period comes from a
        # parameter rather than a literal. A rate <= 0 disables publishing
        # outright rather than dividing by zero — the documented way to turn the
        # overlay off on a constrained host.
        if map_rate and map_rate > 0.0:
            self.create_timer(1.0 / map_rate, self._publish_resource_map,
                              callback_group=self._timer_cb_group)  # map_rate Hz
        else:
            self.get_logger().warn(
                'resource_map_publish_rate is %r; the fused resource map and '
                'the RViz2 overlay will NOT be published.' % (map_rate,))

        # FR-DASH-3. Same convention again: a non-positive rate turns the topic
        # off with a warning instead of dividing by zero.
        if queue_rate and queue_rate > 0.0:
            self.create_timer(1.0 / queue_rate, self._publish_task_queue,
                              callback_group=self._timer_cb_group)
        else:
            self.get_logger().warn(
                'task_queue_publish_rate is %r; /orchestrator/task_queue will '
                'NOT be published and the dashboard task panel will stay '
                'empty.' % (queue_rate,))

        # FR-MAP-3. Same disable-on-non-positive-rate convention as the map
        # publisher above: a rate of 0 is the documented way to fall back to the
        # deterministic lattice, not a crash.
        if replan_rate and replan_rate > 0.0:
            self.create_timer(1.0 / replan_rate, self._adaptive_survey_tick,
                              callback_group=self._timer_cb_group)
        else:
            self.get_logger().warn(
                'adaptive_survey_replan_rate is %r; survey waypoints will stay '
                'on the static hex lattice and FR-MAP-3 is inactive.'
                % (replan_rate,))

        # ---- Generate survey tasks ----
        self._generate_survey_tasks()
        self._audit_mission_geometry()

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
            # FR-DASH-7 energy clause: the robot's own RCDL capacity, so the
            # fleet energy total stops assuming every robot is a 50 Wh scout.
            battery_capacity_wh=float(getattr(msg, 'battery_capacity_wh', 0.0)),
            # D-31. Read DIRECTLY, not through getattr with a default: a
            # default of True would silently restore the fabricated-pose bug
            # against a stale message class, and a default of False would drop
            # every robot out of the distance total and the survey centroid.
            # Appending the field changed the type hash, so a publisher that
            # lacks it cannot connect at all -- an AttributeError here would
            # mean this node is running against a stale generated package, and
            # that should be loud.
            pose_valid=bool(msg.pose_valid),
            # D-30. The ENCODER twist, which is the only motion evidence the
            # orchestrator can see -- it subscribes to no /<rid>/cmd_vel. Until
            # now `_on_robot_state` dropped msg.velocity entirely and the only
            # reader of it in the repository was the dashboard.
            velocity_linear=float(msg.velocity.linear.x),
            velocity_angular=float(msg.velocity.angular.z),
        )

        # FR-DASH-3: mirror the running skill's progress onto the queue entry
        # and promote ASSIGNED -> IN_PROGRESS once the robot is actually
        # working it. Both live in apply_robot_progress so the ROS-free lane
        # can drive the transition from a RobotState-shaped input rather than
        # by calling set_status directly -- which is how IN_PROGRESS came to
        # exist only inside a test fixture in the first place.
        apply_robot_progress(self._task_queue, msg)

        # Detect task completion: robot finished task and returned to idle.
        #
        # THIS IS NOW A FALLBACK. TaskResult (_on_task_result) is authoritative
        # and terminates tasks with an outcome; this positional heuristic
        # cannot tell success from failure at all -- the agent fires
        # FSMEvent.TASK_COMPLETE on skill failure as well as success, so a
        # failed excavate arrived here as RETURNING/IDLE with no task id and
        # was recorded COMPLETED. It survives only for an agent that never
        # sends a TaskResult, and skips anything already terminated.
        if msg.fsm_state in ('RETURNING', 'IDLE') and msg.current_task_id == '':
            task_id = self._task_queue.get_task_for_robot(msg.robot_id)
            if task_id:
                task = self._task_queue.get_task(task_id)
                if task and not task.terminal_reported and task.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                ):
                    self._task_queue.mark_complete(
                        task_id, 'inferred_from_robot_state')
                    self.get_logger().info(
                        f'Task {task_id} completed by {msg.robot_id} '
                        f'(inferred; no TaskResult received)'
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
                    # Rests in INTERRUPTED; get_next_ready re-auctions from
                    # there. The set_status(..., PENDING) that used to follow
                    # is gone (D-03).
                    self._task_queue.interrupt_task(task_id, {
                        'reason': 'robot_error',
                        'robot_id': msg.robot_id,
                    }, reason='robot_error')
                    self._publish_alert(
                        'WARNING', msg.robot_id,
                        f'Task {task_id} interrupted due to robot error, '
                        f're-queued',
                    )

    def _on_material_event(self, msg: MaterialEvent) -> None:
        """Apply one measured mass transfer to the ISRU ledger — D-06."""
        applied = material_event_logic(self._material_ctx, msg)
        if applied:
            self.get_logger().debug(
                'material event %s: %s %.2f kg by %s (task %s)'
                % (msg.event_id, msg.event_type, msg.mass_kg, msg.robot_id,
                   msg.task_id))

    def _on_task_result(self, msg: TaskResult) -> None:
        """Terminate a task on the agent's own report — D-03.

        This is the ONLY way TaskStatus.FAILED becomes reachable. Before it
        existed the orchestrator inferred completion from an idle robot with an
        empty current_task_id, which is true of a failed task as well as a
        successful one, so the queue recorded failures as completions.
        """
        task = self._task_queue.get_task(msg.task_id)
        if task is None:
            self.get_logger().warn(
                f'TaskResult for unknown task {msg.task_id} from '
                f'{msg.robot_id}; ignored')
            return
        # FIRST TERMINAL REPORT WINS. This is the guard 45 lines above in
        # ``_on_robot_state`` -- ``not task.terminal_reported`` -- finally
        # applied by the AUTHORITATIVE path to itself. The fallback defended
        # itself against a task this path had already terminated; this path
        # never defended itself against itself. Without it a second TaskResult
        # rewrote the terminal state, and a COMPLETED task was observed flipping
        # to FAILED on a live stack, which deadlocks every task that depends on
        # it -- ``_ready_tasks`` satisfies a dependency only with COMPLETED.
        #
        # KEYED ON terminal_reported, NEVER ON task.status, and that is the
        # load-bearing choice. The positional fallback above calls
        # ``mark_complete()`` WITHOUT setting this flag, on purpose: the two
        # messages race on different topics with no ordering guarantee, and the
        # authoritative TaskResult is meant to be able to correct an INFERRED
        # completion to FAILED. Guarding on status would block that correction
        # and record a failed excavate as COMPLETED -- D-03's headline defect,
        # reintroduced through a side door.
        #
        # TRANSIENT_LOCAL REPLAY IS SERVED, NOT BROKEN. Both ledger topics are
        # durable on both ends (_ledger_qos), so a re-matched subscription can be
        # handed an agent's history again. Ignoring the repeat is exactly what
        # MaterialEvent's event_id dedupe does for the other ledger topic;
        # TaskResult carries no id, so task_id plus this flag is the only key
        # there is.
        #
        # LOGGED, NOT ALERTED. A duplicate that AGREES with the recorded outcome
        # is transport, not a fleet fault, and a replayed history would flood the
        # bounded operator ring; a duplicate that CONTRADICTS it is two
        # publishers disagreeing about one task -- the second-stack hazard -- and
        # that is worth a warning in the log.
        if task.terminal_reported:
            if bool(msg.success) != (task.status == TaskStatus.COMPLETED):
                self.get_logger().warn(
                    f'duplicate TaskResult for {msg.task_id} from '
                    f'{msg.robot_id} CONTRADICTS the recorded outcome: task '
                    f'is {task.status.name}, second report success='
                    f'{bool(msg.success)}; ignored')
            else:
                self.get_logger().debug(
                    f'duplicate TaskResult for {msg.task_id} from '
                    f'{msg.robot_id}; already terminated, ignored')
            return
        task.terminal_reported = True
        if msg.success:
            self._task_queue.mark_complete(msg.task_id, 'skill_complete')
        else:
            reason = msg.failure_reason or 'skill_failed'
            self._task_queue.mark_failed(msg.task_id, reason)
            self._publish_alert(
                'WARNING', msg.robot_id,
                f'Task {msg.task_id} ({msg.task_type}) FAILED: {reason}')

    def _on_task_status_change(self, task, previous) -> None:
        """TaskQueue status listener — one TaskEvent per real transition."""
        self._events.append(
            kind=KIND_STATUS,
            action=getattr(task.status, 'name', str(task.status)),
            task_id=task.task_id,
            robot_id=task.assigned_robot,
            actor=task.assigned_robot or 'orchestrator',
            detail=task.status_reason,
            target=(task.target_x, task.target_y),
            stamp=task.status_changed,
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

    def _publish_resource_map(self) -> None:
        """Timer entry point for the fused posterior and the RViz2 overlay.

        D-18 — WHY THERE IS A CATCH HERE AND NOWHERE ELSE IN THIS FILE. An
        exception raised in an rclpy timer callback is not confined to the
        frame: it propagates out of `executor.spin()` and ends the process. The
        defect this catch exists for did exactly that — a non-finite cell mean
        raised `ValueError: cannot convert float NaN to integer` from
        `resource_map_viz._js_round` -> `math.floor`, reached through
        `marker_colours` below, while the dashboard drew a plausible dark-blue
        patch from the same posterior.

        Both of the specific paths are now closed upstream — ResourceMap.update
        refuses a non-finite reading, and resource_map_viz is total for every
        float — so this is the third layer and should never fire. It is here
        because of what this callback IS: the only timer whose payload is
        derived arithmetic over a ~250 000-cell grid, and the only one that
        publishes two coupled messages. Losing one frame of a 0.5 Hz overlay is
        a cosmetic fault; losing the orchestrator is a mission one, and the
        exit gate would report it as "the fleet stopped bidding".

        Deliberately NOT silent: every failure is counted and the first is
        logged with its traceback, because an overlay that quietly stops
        updating looks exactly like a fleet that has stopped surveying.
        """
        try:
            self._publish_resource_map_once()
        except Exception as exc:                     # noqa: BLE001 - see above
            self._map_publish_failures += 1
            if (self._map_publish_failures == 1
                    or self._map_publish_failures % 50 == 0):
                self.get_logger().error(
                    f'_publish_resource_map failed '
                    f'({self._map_publish_failures} time(s)): {exc!r}. '
                    f'/orchestrator/resource_map and the RViz2 overlay are '
                    f'STALE; the orchestrator is otherwise unaffected.')

    def _publish_resource_map_once(self) -> None:
        """Publish the fused posterior and its RViz2 overlay.

        FR-MAP-1(e)(f) and FR-MAP-4. Both messages describe the SAME snapshot,
        taken once, so the grid on the wire and the picture in RViz can never
        disagree with each other.

        Only observed cells (count > 0) are emitted. That is not merely an
        optimisation: with prior_mean 0.0, emitting the whole grid would paint
        ~99.7% of the scene the ramp's floor colour, which reads as "we surveyed
        everywhere and found nothing" — the opposite of the truth, and a direct
        violation of FR-MAP-4(b) "matches underlying data".
        """
        mean_grid, var_grid, count_grid = self._resource_map.snapshot()
        geom = self._resource_map.geometry
        prior_var = self._resource_map.prior_variance

        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = self._map_frame_id

        observed = rmviz.select_observed(count_grid)
        flat_mean = mean_grid.reshape(-1)
        flat_var = var_grid.reshape(-1)
        flat_count = count_grid.reshape(-1)

        # ---- FR-MAP-1(e): the posterior, sparse-encoded. ----
        grid_msg = ResourceMapMsg()
        grid_msg.header = header
        grid_msg.resolution = float(geom['resolution'])
        grid_msg.width = int(geom['width'])
        grid_msg.height = int(geom['height'])
        grid_msg.origin = Point(x=float(geom['origin_x']),
                                y=float(geom['origin_y']), z=0.0)
        grid_msg.prior_mean = float(self._resource_map.prior_mean)
        grid_msg.prior_variance = float(prior_var)
        grid_msg.total_observations = int(self._resource_map.get_total_readings())
        grid_msg.cell_index = [int(i) for i in observed]
        grid_msg.cell_mean = [float(flat_mean[i]) for i in observed]
        grid_msg.cell_variance = [float(flat_var[i]) for i in observed]
        grid_msg.cell_observation_count = [int(flat_count[i]) for i in observed]
        self._resource_map_pub.publish(grid_msg)

        # ---- FR-MAP-4: the overlay. ----
        # A single CUBE_LIST rather than one Marker per cell: RViz2 replaces a
        # marker with the same ns+id wholesale on each message, so there is
        # nothing to delete between frames and no DELETEALL is needed.
        shown = rmviz.select_observed(count_grid,
                                      max_cells=self._map_max_marker_cells)
        xs, ys = rmviz.cell_centres(shown, geom['width'], geom['resolution'],
                                    geom['origin_x'], geom['origin_y'])
        colours = rmviz.marker_colours(
            [float(flat_mean[i]) for i in shown],
            [float(flat_var[i]) for i in shown],
            prior_var,
        )

        marker = Marker()
        marker.header = header
        marker.ns = 'resource_map'
        marker.id = 0
        marker.type = Marker.CUBE_LIST
        marker.action = Marker.ADD
        # A zero quaternion is rejected outright by RViz2's MarkerBase.
        marker.pose.orientation.w = 1.0
        # All three scales must be non-zero: CUBE_LIST sets box dimensions from
        # them. Flat in z so the overlay lies on the terrain instead of
        # occluding the robots.
        marker.scale.x = float(geom['resolution'])
        marker.scale.y = float(geom['resolution'])
        marker.scale.z = 0.2
        marker.lifetime = Duration(sec=0, nanosec=0)   # never auto-expire
        # Fallback colour, and it matters. RViz2 uses the per-point `colors`
        # array only while its length matches `points`; on any mismatch it
        # silently falls back to THIS field. Left at the message default of
        # (0,0,0,0) that fallback is transparent black, i.e. the overlay
        # disappears with no error anywhere. An opaque mid-blue degrades to
        # visibly-wrong instead of invisible.
        marker.color = ColorRGBA(r=0.0, g=0.0, b=1.0, a=0.8)
        marker.points = [Point(x=float(x), y=float(y), z=0.0)
                         for x, y in zip(xs, ys)]
        marker.colors = [ColorRGBA(r=r, g=g, b=b, a=a) for r, g, b, a in colours]
        # RViz2 silently ignores per-point colours when the lengths differ — it
        # falls back to the flat marker colour and surfaces no error — so the
        # invariant is asserted here rather than debugged in a GUI later.
        assert len(marker.colors) == len(marker.points), (
            f'{len(marker.colors)} colours for {len(marker.points)} points')

        self._resource_map_marker_pub.publish(MarkerArray(markers=[marker]))

    def _on_map_update(self, msg: ResourceMapUpdate) -> None:
        """Update resource map with a new scout sensor reading.

        D-18: the rejection lives in ResourceMap.update() — the boundary that
        owns the grid — and this method exists to make the rejection VISIBLE.
        A dropped reading is otherwise indistinguishable from a scout that
        never sampled, which is exactly how the hauler load-cell topic mismatch
        (D-11) survived two phases.

        Throttled by count rather than by time: a scout whose sensor has gone
        non-finite publishes at its full prospect rate, and an unthrottled warn
        would bury every other line in the log. The first one is always
        printed, because the first one is the one that dates the fault.
        """
        applied = self._resource_map.update(
            x=msg.location.x,
            y=msg.location.y,
            reading=msg.ice_concentration,
            sensor_uncertainty=msg.sensor_uncertainty,
        )
        if applied:
            return

        self._map_updates_rejected += 1
        if (self._map_updates_rejected == 1
                or self._map_updates_rejected % 100 == 0):
            self.get_logger().warn(
                f'Rejected map update #{self._map_updates_rejected} from '
                f'{msg.scout_id}: unusable reading '
                f'ice_concentration={msg.ice_concentration!r} '
                f'sensor_uncertainty={msg.sensor_uncertainty!r} at '
                f'({msg.location.x!r}, {msg.location.y!r}). The fused map is '
                f'unchanged; check this robot\'s scalar-field sensor and its '
                f'RCDL noise_stddev.')

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
        # D3(b). The loop above runs exactly ONCE per robot; this is the sweep
        # that makes the recovery repeatable.
        self._recover_offline_robot_tasks()
        # D-22. Shares this 1 Hz timer deliberately: the two checks answer the
        # same question -- "is the fleet still alive" -- from opposite sides.
        # The heartbeat sees a process stop; this sees the WORLD stop while
        # every process keeps running.
        self._check_motion_stalls()
        # D-31. Same timer, same reason: a distance increment the accumulator
        # refused is evidence about the position source, and it used to be
        # discarded silently.
        self._report_distance_rejections()

    def _recover_offline_robot_tasks(self) -> None:
        """Re-queue any task still held by an already-OFFLINE robot — D3(b).

        THE HEARTBEAT LOOP ABOVE RUNS ONCE PER ROBOT, EVER. ``check_heartbeats``
        skips a robot it has already declared OFFLINE, so ``mark_offline`` ->
        ``recover_tasks_for_robot`` fires exactly once and whatever that pass
        missed is missed permanently.

        IT CAN MISS, and the two ways are separate. A bid does not refresh a
        heartbeat -- only ``FleetMonitor.update_robot`` does -- so a robot whose
        state stream is lost while its bid traffic survives can be elected AFTER
        its one and only sweep. ``_resolve_auction``'s ``_robot_is_live`` filter
        closes the common case, but it is not atomic with the
        ``assign_to_robot`` that follows it: every timer here shares a
        ``ReentrantCallbackGroup`` under a 4-thread ``MultiThreadedExecutor``, so
        ``_heartbeat_check`` (1 Hz) and ``_auction_tick`` (2 Hz) genuinely
        interleave. This sweep is the backstop, not the alternative.

        SILENT AND FREE WHEN THERE IS NOTHING TO DO. ``recover_tasks_for_robot``
        clears ``assigned_robot``, so a second pass over the same robot returns
        ``[]`` -- no alert, no log line, no event. That is what keeps a 1 Hz
        sweep from becoming D-20's 261-line flood, and it is the same discipline
        ``_report_distance_rejections`` follows on this very timer.

        RESIDUAL, STATED RATHER THAN PAPERED OVER: a task held by a robot the
        fleet monitor has NEVER seen is invisible here, because
        ``get_all_robots`` cannot list it. Reaching that state needs a bid from a
        robot that has never published RobotState, which ``agent_node`` does not
        do -- it publishes at 2 Hz from startup and bids only from IDLE -- so
        this is recorded as an open item rather than defended against with code
        no test can reach.
        """
        for rid, state in self._fleet.get_all_robots().items():
            if state['fsm_state'] != 'OFFLINE':
                continue
            stranded = self._task_queue.recover_tasks_for_robot(
                rid, reason='robot_offline')
            if not stranded:
                continue
            self._publish_alert(
                'ERROR', rid,
                f'{len(stranded)} task(s) were still held by {rid}, which is '
                f'OFFLINE, after its heartbeat recovery had already run. '
                f'Re-queued: {stranded}')
            self.get_logger().warn(
                f'Robot {rid} is OFFLINE and still held {stranded}; re-queued')

    def _check_motion_stalls(self) -> None:
        """Report robots that are expected to be moving and are not — D-30.

        WHAT THIS IS FOR (D-22, originally). At 10 robots (4 scouts / 3
        excavators / 3 haulers -- the fleet
        `selene_sim/config/spawn_positions.yaml` describes for NFR-1.4) Gazebo
        hit an ODE assertion in `collide()` and exited 134 about five minutes
        into a run on 2026-07-31. `ros2 launch` survived. Every agent process
        survived, kept ticking at 10 Hz and kept publishing RobotState, so
        `check_heartbeats` saw a completely healthy fleet. Navigation then
        failed fleet-wide as odom froze, three scouts went to ERROR, and the
        orchestrator kept auctioning into a dead simulation. NOTHING IN THE
        SYSTEM NOTICED.

        WHY HERE AND NOT IN THE AGENT. A single agent cannot tell "the
        simulator died" from "I am parked": it only sees its own odometry, and
        its own odometry standing still is the normal state of a robot that is
        idle, charging, drilling or stuck. The orchestrator is the only place
        that sees every robot at once. It also keeps the agent free of any
        Gazebo-specific dependency: nothing here knows what a simulator is,
        only that the poses on `/<robot>/state` stopped changing while the
        robots that produced them were supposed to be driving.

        WHAT CHANGED ON 2026-07-31, and why the method was renamed (D-30). The
        previous version was called `_check_simulation_stall` and its alert
        said "this is not a robot fault: the simulator, the physics step or the
        odometry bridge has stopped". It could not support that claim. Its
        input was "time since this robot last moved 1 cm", a clock that runs
        while a robot is parked, so parked robots were stalled by construction
        and its all-robots clause was satisfied for free by the nine parked
        members of a ten-robot fleet. Running the shipped predicate on ONE
        wedged scout among a parked fleet and on a DEAD SIMULATOR produced
        identical output. It fired twice on run B of 2026-07-31, each time on a
        robot that had just entered NAVIGATING carrying a 60 s-stale pose clock
        -- zero seconds of actual failure -- and cleared one heartbeat later.

        So this now emits TWO kinds of alert from one observation:

        * PER ROBOT, ERROR, latched per episode. Names the robot, what state it
          is in, how long it has been stationary while expected to move, and
          what its wheels report. That is what would have named the wedged
          scout on run A -- at ~10 s rather than at 408 s, and as the right
          thing.
        * FLEET, CRITICAL, latched, and only when the observation can support a
          fleet-level statement at all: every mover stalled AND at least
          `sim_stall_min_movers` (>= 2) of them. The text states the count and
          WITHHOLDS the cause, because 4 simultaneously wedged robots and a
          stopped physics step look identical from here and this code cannot
          tell them apart. Saying which is which was the defect.

        WHY THIS STILL CATCHES A DEAD SIMULATOR, and catches it sooner. At the
        ODE abort at least three scouts were driving -- they subsequently
        reported "Path blocked, no alternate route", which is reachable only
        from the navigator's FOLLOWING path. Their poses freeze at the abort
        while their FSM stays NAVIGATING, so each accumulates stationary time
        from the freeze instant; all movers stalled and M = 3 >= 2, so the
        CRITICAL fires at 10 s instead of 20 s.

        WHAT IT STILL CANNOT SEE, stated because an alert must not be read as a
        guarantee.

        * A robot that has given up and gone to ERROR with its wheels stopped is
          no longer expected to move, so once the whole fleet has given up this
          goes quiet: the alert dates the failure, it does not track it. The
          wheel-speed clause extends that window past the agent's give-up
          whenever the frozen odometry sample retains a non-zero twist -- which
          is READ from the HAL's caching behaviour (gazebo_hal.py:353-385), NOT
          measured on a run, and should be treated as a hypothesis until one
          confirms it.
        * A ROBOT THAT NEVER ACQUIRES A POSITION FIX IS NOT WATCHED AT ALL, and
          this is a deliberate coverage trade rather than an oversight. There is
          no position measurement for it, so it cannot be called stationary; it
          appears in `report.no_fix` and, if any other robot is driving, in the
          fleet message's count. If the WHOLE fleet lost its fix, nothing here
          would alert. In this system that is a startup-only state -- the HAL's
          cached reading keeps `is_valid` true once the first message has
          arrived, so a mid-run producer death shows up as a frozen VALID pose,
          which is the case above -- but a real localisation stack would not
          behave that way, and a "no fix for too long" alert would need a
          threshold nothing in this repository can currently derive.
        """
        if not (self._sim_stall_timeout > 0.0):
            return

        report = self._fleet.assess_motion(self._sim_stall_timeout)
        self._report_per_robot_stalls(report)
        self._report_fleet_motion_stall(report)

    def _report_per_robot_stalls(self, report: FleetMotionReport) -> None:
        """One ERROR per stall episode, one INFO when it clears."""
        stalled_now = {s.robot_id for s in report.stalled}

        for stall in report.stalled:
            if stall.robot_id in self._stalled_robots:
                continue
            self._stalled_robots.add(stall.robot_id)
            # The yaw rate is included because it separates two failures the
            # forward speed alone cannot: pushing into an obstacle (speed, no
            # yaw) from pivoting against one (yaw, little speed).
            twist = (f'{stall.wheel_speed_mps:.2f} m/s and '
                     f'{stall.wheel_yaw_rate:.2f} rad/s')
            if stall.wheel_speed_mps > WHEEL_MOTION_EPSILON_MPS:
                wheels = (
                    f'its wheels report {twist}, so '
                    f'the wheels are turning and the body is not: either it is '
                    f'physically stuck (slip) or its position source has '
                    f'frozen')
            else:
                wheels = (
                    f'its wheels report {twist}, so it '
                    f'is not being driven either')
            self.get_logger().error(
                'MOTION STALL %s: %.0fs stationary in %s, wheels %.2f m/s '
                '%.2f rad/s'
                % (stall.robot_id, stall.stationary_sec, stall.fsm_state,
                   stall.wheel_speed_mps, stall.wheel_yaw_rate))
            self._publish_alert(
                'ERROR', stall.robot_id,
                f'{stall.robot_id} has not moved in '
                f'{stall.stationary_sec:.0f}s. Its state is {stall.fsm_state} '
                f'and {wheels}. Position unchanged to within '
                f'{POSE_MOTION_EPSILON_M * 100:.0f} cm. '
                f'{len(report.stalled)} of {len(report.movers)} robot(s) '
                f'expected to be moving are in this condition.')

        for rid in sorted(self._stalled_robots - stalled_now):
            self._stalled_robots.discard(rid)
            # Only announce recovery for a robot we can still see. One that has
            # gone OFFLINE or stopped being a mover has not been observed to
            # resume; saying it did would be the same class of unsupported
            # claim this method was rewritten to remove.
            if rid in report.movers:
                self._publish_alert(
                    'INFO', rid,
                    f'{rid} is moving again. Anything it reported while it was '
                    f'stationary -- distance, map readings, task progress -- '
                    f'was produced without its position changing.')

    def _report_fleet_motion_stall(self, report: FleetMotionReport) -> None:
        """The fleet-level claim, gated behind a quorum of witnesses."""
        fleet_wide = report.fleet_wide(self._sim_stall_min_movers)

        if fleet_wide and not self._sim_stalled:
            self._sim_stalled = True
            driven = [s for s in report.stalled
                      if s.wheel_speed_mps > WHEEL_MOTION_EPSILON_MPS]
            fastest = max((s.wheel_speed_mps for s in report.stalled),
                          default=0.0)
            parked = len(report.online) - len(report.movers) - len(
                report.no_fix)
            self.get_logger().error(
                'MOTION STALL, fleet: %d of %d mover(s) stationary for up to '
                '%.0fs (%s)'
                % (len(report.stalled), len(report.movers),
                   report.longest_stationary_sec,
                   ', '.join(sorted(report.stalled_ids))))
            no_fix_note = (
                f' {len(report.no_fix)} online robot(s) have no position fix '
                f'at all and are not evidence either way.'
                if report.no_fix else '')
            self._publish_alert(
                'CRITICAL', '',
                f'MOTION STALL: {len(report.stalled)} of '
                f'{len(report.movers)} robot(s) expected to be moving '
                f'({", ".join(sorted(report.stalled_ids))}) have reported no '
                f'position change for up to '
                f'{report.longest_stationary_sec:.0f}s; {len(driven)} of them '
                f'report wheels turning at up to {fastest:.2f} m/s. '
                f'{parked} other online robot(s) are in states that require no '
                f'motion and are not evidence either way.{no_fix_note} '
                f'OBSERVED, NOT DIAGNOSED: this is what a stopped physics '
                f'step, a dead odometry bridge or a frozen pose source looks '
                f'like from here, and it is also what '
                f'{len(report.stalled)} simultaneously wedged robots look '
                f'like. Check whether the gazebo process is alive first -- an '
                f'ODE assertion in collide() killed it at 10 robots on '
                f'2026-07-31 while ros2 launch survived.')
            return

        if self._sim_stalled and not fleet_wide:
            self._sim_stalled = False
            resumed = sorted(set(report.movers) - set(report.stalled_ids))
            self.get_logger().info(
                'Fleet motion stall cleared; %d mover(s) reporting motion again'
                % (len(resumed),))
            self._publish_alert(
                'INFO', '',
                f'The fleet-wide motion stall has cleared. '
                f'{len(resumed)} robot(s) '
                f'({", ".join(resumed) if resumed else "none"}) are reporting '
                f'position changes again. Anything THOSE robots reported '
                f'during the stall -- distances, map readings, task outcomes '
                f'-- was produced while their position was not changing and '
                f'should not be trusted.')

    def _report_distance_rejections(self) -> None:
        """Log pose increments the distance accumulator refused — D-31.

        A filter whose rejects are silent is how the phantom fleet distance
        survived a full run: `fleet_distance_total` read 1665.37 m against a
        ~753 m ground-truth path integral, and the 500 m guard in FleetMonitor
        discarded whatever it discarded without telling anybody.

        The MAGNITUDE is what matters and is why this logs records rather than
        a count. Eight rejections could be eight small simulator hiccups or
        four ~166 m localisation flips, and the second of those is the
        un-eliminated candidate mechanism for the rest of D-31's excess. The
        per-robot accumulated distance goes on the same line because it is the
        number a reader will want next, and because `get_robot_distance` had
        zero callers anywhere in the repository until this one.

        On CHANGE only. At 1 Hz an unconditional line would be wallpaper.
        """
        total = self._fleet.distance_rejections
        if total <= self._distance_rejections_reported:
            return
        first_unreported = self._distance_rejections_reported
        self._distance_rejections_reported = total

        for rid in self._fleet.get_all_robots():
            for record in self._fleet.get_distance_rejections(rid):
                if record['seq'] <= first_unreported:
                    continue
                self.get_logger().warn(
                    'Rejected a %.1f m pose increment for %s: (%.2f, %.2f) -> '
                    '(%.2f, %.2f). It is above the %.0f m implausible-jump '
                    'guard, so it was NOT added to that robot\'s %.1f m of '
                    'travelled distance. OBSERVED, NOT DIAGNOSED: a respawn, a '
                    'position-source flip and a teleport all look like this '
                    'from here. No robot in this fleet can cover that in one '
                    'sample -- the fastest RCDL max_speed is 0.5 m/s.'
                    % (record['increment_m'], rid,
                       record['prev_pose'][0], record['prev_pose'][1],
                       record['new_pose'][0], record['new_pose'][1],
                       MAX_PLAUSIBLE_POSE_JUMP_M,
                       self._fleet.get_robot_distance(rid)))
        self.get_logger().warn(
            'Fleet distance accumulator has now refused %d pose increment(s) '
            'in total. fleet_distance_total is a lower bound on the distance '
            'actually travelled, not a measurement of it.' % (total,))

    def _auction_tick(self) -> None:
        """Run the auction state machine: start or resolve auctions."""
        now = time.monotonic()

        # D-20: before anything else, notice whether the fleet has changed.
        # Done here rather than in _on_robot_state so the task queue is only
        # ever mutated from the timer callback group, not from a DDS callback
        # thread of the MultiThreadedExecutor while a timer walks it.
        self._wake_on_fleet_change()

        # D2: and give a task a SKILL reported FAILED its next attempt, if it
        # has one left. Here rather than on any other timer for three reasons,
        # and the first is the same one the wake above is here for: this is the
        # timer callback group, so the task queue is not mutated from a DDS
        # callback thread. The second is that a retried task is PENDING before
        # the same tick's ``get_next_ready`` runs, so it re-enters the ordinary
        # auction with no extra latency and no second dispatch path. The third
        # is that this must run BEFORE the early returns below -- a fleet whose
        # only remaining work is a failed task has an idle robot and no ready
        # task, which is exactly the state ``_auction_tick`` returns from.
        self._retry_failed_tasks()

        # If an auction is active, check for timeout
        if self._auction.is_active():
            if self._auction.is_timed_out(now):
                self._resolve_auction()
                # One auction resolves per tick, as before: the next opens on
                # the next tick. Preemption below is what shortens that wait,
                # and only for an emergency.
                return
            if not self._preempt_for_emergency(now):
                return  # Don't start a new auction while one is running
            # PREEMPTED. Fall through into the start-auction path below, in
            # THIS tick rather than the next one, so an already-idle robot is
            # not made to wait another 500 ms for the emergency announcement.
            # The fall-through is GUARANTEED to announce the emergency:
            # _preempt_for_emergency refuses to abort anything until it has
            # confirmed, against the same collaborators the gates below use,
            # that this tick will get as far as _publish_announcement.

        # Check for idle robots and pending tasks.
        idle = self._fleet.get_idle_robots()
        if not idle:
            return

        # D-20: `now` skips any task inside its auction backoff window, which
        # is what stops one unbiddable task holding the single auction slot
        # and starving everything behind it.
        #
        # `servable` SKIPS a task no IDLE robot could bid on, and that is a
        # separate defence from D-20's rather than a duplicate of it. The idle
        # gate above is a bare `if not idle`, so before this a single idle
        # excavator was enough to open -- and immediately waste -- a full
        # auction round for a prospect-only task. Each wasted round is charged
        # to D-20's backoff, and a backed-off task is invisible to this very
        # method, so a task the fleet simply had no idle robot for could bury
        # itself and then watch lower-priority work take the robot that finally
        # arrived. It SKIPS rather than returns: a top-priority emergency
        # excavate with the only excavator busy must not stop ten surveys being
        # auctioned to three idle scouts.
        #
        # Re-queried rather than carried down from _preempt_for_emergency, and
        # the answer on that path is the SAME task, deterministically: the
        # preempted task is strictly lower priority (should_preempt requires
        # it), so putting it back into the ready set cannot outrank the
        # emergency; get_next_ready's tie-break settles an equal-priority peer
        # in the emergency's favour; and the preempt path has already released
        # the emergency's own D-20 backoff and confirmed it is servable and not
        # ledger-blocked. Re-querying keeps one expression of "what runs next"
        # instead of two that can drift.
        #
        # `max_attempts` is D2's soft-quorum bound and it is a NO-OP for every
        # task in this queue but select_site: with no quorum set,
        # ``dependencies_met`` still demands every dependency COMPLETED and
        # never looks at the bound. It is passed so the queue's readiness rule
        # and the planner's ask the same question with the same bound rather
        # than two that drift -- which is exactly how D2 happened.
        next_task = self._task_queue.get_next_ready(
            now, servable=self._servable_by_idle_fleet,
            max_attempts=TASK_MAX_ATTEMPTS)
        if next_task is None:
            return

        # Skip virtual tasks — resolved by the HTN planner, not by robots
        if next_task.task_type == 'select_site':
            return

        # D-06: never open an auction for a haul the ledger cannot cover. The
        # authoritative gate is in _resolve_auction, immediately before the
        # task is marked ASSIGNED; this one exists so the normal case costs
        # nothing rather than announcing, collecting bids, timing out and
        # re-queueing every auction period, which would churn the 32-entry
        # event ring the dashboard replays and make the operator's own history
        # unreadable.
        #
        # Returning here holds up lower-priority work for one tick, exactly as
        # the select_site skip above does. In the shipped decomposition nothing
        # is starved: prospect is priority 5.0 and operator injections 10.0,
        # both above a haul's 3.0, and the only equal-priority task is the next
        # excavate, which depends_on this haul and is not ready anyway.
        blocked = self._authorise_quantity(next_task)[1]
        self._note_haul_block(next_task, blocked)
        if blocked:
            return

        # Start new auction. begin_auction counts the round, which is what
        # decides when a preferred robot's preference expires.
        rounds = self._task_queue.begin_auction(next_task.task_id)
        self._auction.start(next_task.task_id, now)
        self._publish_announcement(next_task)
        self.get_logger().info(
            f'Auction started for {next_task.task_id} ({next_task.task_type}) '
            f'at ({next_task.target_x:.0f}, {next_task.target_y:.0f}) '
            f'round={rounds}'
        )

    def _servable_by_idle_fleet(self, task) -> bool:
        """Could ANY robot that is idle RIGHT NOW bid on *task*?

        The predicate ``_auction_tick`` and ``_preempt_for_emergency`` both hand
        to the task queue. It is capability only -- not energy, not distance,
        not the D-06 ledger -- because capability is the one bid precondition
        the orchestrator can evaluate without asking the robot, AND BECAUSE IT
        IS EVALUATED FROM THE ROBOT'S OWN ANSWER. ``agent_node`` declines an
        announcement whose ``required_capabilities`` its HAL does not cover
        before it computes anything else (agent_node.py:894-895), and the set it
        tests is the same ``self._hal.get_capabilities()`` it publishes in
        ``RobotState.capabilities`` (agent_node.py:1512), which is what
        ``FleetMonitor`` stores. So "no idle robot is capable" is not an
        orchestrator-side guess about the fleet: it is the fleet's own answer,
        and such a round is GUARANTEED to close with no bids.

        Energy and range are deliberately left to the robot. A bid the fleet
        declines for those reasons is real evidence ABOUT the fleet and is
        exactly what D-20's backoff is for; a round no robot could physically
        have bid on is not evidence of anything and should never have been
        opened.

        An empty ``required_capabilities`` matches every idle robot, which is
        every task the HTN planner emits without them.
        """
        return bool(self._fleet.get_idle_robots_with_capabilities(
            getattr(task, 'required_capabilities', ()) or ()))

    def _robot_is_live(self, robot_id: str) -> bool:
        """Has the fleet monitor NOT declared this robot dead? — D3(c).

        The predicate ``_resolve_auction`` hands to
        ``task_feed.resolve_auction_winner``, in the same shape and for the same
        stated reason as ``_servable_by_idle_fleet`` above: the fleet question is
        answered here, the decision stays in the ROS-free module where the gate
        lane can drive it.

        UNKNOWN IS NOT DEAD, and that asymmetry is deliberate. The defect is
        electing a robot the monitor has ALREADY declared OFFLINE; a robot it has
        never heard of is one whose first RobotState has not arrived, and
        refusing its bid would burn an auction round on a fleet that is merely
        still starting up. ``fsm_state != 'OFFLINE'`` is not an invented test:
        it is the same one ``get_robots_with_capability`` and
        ``get_online_count`` already use.
        """
        robot = self._fleet.get_robot(robot_id)
        return robot is None or robot.get('fsm_state') != 'OFFLINE'

    def _preempt_for_emergency(self, now: float) -> bool:
        """Abort the in-flight auction for an operator EMERGENCY. True if aborted.

        A DELIBERATE CHANGE TO AUCTION SEMANTICS, decided by the operator, not a
        defect fix. Until this existed the orchestrator ran one auction at a time
        and nothing interrupted it, at any priority. It still does not interrupt
        for priority: the ONLY thing that opens this path is an operator having
        set ``InjectTask.emergency``. A priority-10 injection without the flag
        waits for the running auction exactly as it always has -- see
        ``task_feed.should_preempt`` for why the line is drawn at the flag and
        not at the number.

        THE VICTIM PAYS AS LITTLE AS THE MECHANISM ALLOWS. Its round is
        refunded, its D-20 backoff and failure count are untouched, and its
        status returns to whatever it was before the auction -- INTERRUPTED
        stays INTERRUPTED. All three live in ``TaskQueue.abort_auction``, which
        is where the reasoning is written. What it DOES lose is any bid already
        collected in that window: ``TaskAuction.reset()`` clears them, and it
        must, because those bids were made for a round that will not resolve.
        A robot that bid is not told (there is no message in this system that
        says "your auction was withdrawn") and returns to IDLE on its own
        ``auction_timeout_sec``.

        Exactly one TaskEvent is produced, by ``abort_auction``'s status change
        firing ``_on_task_status_change``. Nothing is appended here; a second
        event would double-count the transition in the ring the dashboard
        replays.

        ``_auction_failure_logged`` is deliberately NOT cleared for the victim,
        for the same reason ``_wake_on_fleet_change`` does not clear it: a
        preemption tells the operator nothing new about whether the FLEET can
        service that task, which is the only thing that dict's dedupe is about.

        IT IS SPENT ONLY WHEN IT BUYS SOMETHING, AND IT IS SPENT ONLY ONCE.
        Three gates below stand between ``should_preempt`` saying "may" and this
        method saying "did", and all three exist because an abort that is not
        followed by an announcement in the SAME tick is strictly worse than not
        preempting: the auction slot is emptied, a live bid is thrown away, and
        the bidder sits in BIDDING for its own 7.0 s agent timeout, which is
        longer than the 5.0 s the orchestrator's own window had left to run.
        The gates are (a) some IDLE robot is capable of the emergency, (b) the
        D-06 ledger will not block its announcement, and (c) the shot has not
        already been spent. (a) and (b) are the same two questions
        ``_auction_tick`` asks below, asked here in the same order and against
        the same collaborators, so "the fall-through will announce it" is a
        checked fact rather than a hope.
        """
        running_id = self._auction.get_task_id()
        running = self._task_queue.get_task(running_id)
        # Positional `now`, not `now=now`: test_auction_backoff.py AST-walks
        # every get_next_ready call in this module and requires a clock
        # argument, and a keyword argument has an empty `.args`.
        #
        # get_preemption_candidate, NOT get_next_ready, and the difference is
        # the whole reason an emergency can be acted on at all once it has lost
        # a round: get_next_ready hides a task inside its D-20 backoff, and the
        # emergency -- injected into a fleet busy enough to be worth an
        # emergency -- is the likeliest task in the queue to be in one.
        # Reaching through the backoff is bounded to once per injection by
        # `preemption_spent`, which should_preempt reads.
        candidate = self._task_queue.get_preemption_candidate(
            now, servable=self._servable_by_idle_fleet,
            max_attempts=TASK_MAX_ATTEMPTS)
        if not should_preempt(running, candidate):
            return False

        # THE D-06 LEDGER GATE, ASKED BEFORE ANYTHING IS DESTROYED. should_preempt
        # is pure and filters only `select_site`; it cannot know that
        # inject_task_logic accepts a haul the ledger has no material for, which
        # _auction_tick then refuses to announce. Choosing the candidate before
        # that refusal is how a live auction gets taken away and given to
        # nobody -- and, because the blocked emergency stays the queue's answer,
        # never given back. Refusing here leaves the running auction to resolve
        # normally and leaves the shot unspent for a moment when it can be used.
        blocked = self._authorise_quantity(candidate)[1]
        if blocked:
            # NOT reported through _note_haul_block here: this path did not
            # announce anything, and the same task reaches the identical gate in
            # _auction_tick as soon as the slot is free, which is where the
            # operator-facing latched alert belongs. Two callers, one alert.
            self.get_logger().debug(
                f'Emergency {candidate.task_id} did not preempt the auction for '
                f'{running_id or "(no task)"}: the ledger blocks announcing it '
                f'({blocked}). The in-flight auction is left to resolve and the '
                f'preemption is NOT spent.')
            return False

        # Latched BEFORE the abort, so a preemption cannot half-happen and then
        # repeat. See TaskEntry.preemption_spent for why one is the bound.
        self._task_queue.spend_preemption(candidate.task_id)
        # The emergency may have been reached through its own D-20 backoff (see
        # get_preemption_candidate). Release it -- keeping failed_auctions, so
        # the escalation to ABANDONED still terminates -- or the fall-through's
        # get_next_ready would skip the very task this abort was performed for.
        self._task_queue.release_auction_backoff(candidate.task_id)

        # Named BEFORE reset() discards them. Nothing in this system tells a
        # bidder its auction was withdrawn, so these robots stay in BIDDING
        # until their own agent-side timeout and then arrive in IDLE through the
        # one transition FleetMonitor deliberately ignores. Marking them is what
        # lets the capacity a preemption creates wake a task D-20 has parked.
        self._fleet.note_stranded_bidders(
            bid.robot_id for bid in self._auction.get_bids())

        aborted = self._task_queue.abort_auction(running_id, AUCTION_PREEMPTED)
        # The reset is NOT conditional on `aborted`. abort_auction declines when
        # there is nothing to undo -- the auctioned task has left the queue, or
        # has already moved on from AUCTIONING -- and should_preempt has already
        # ruled that the slot may be taken in that case. The TaskAuction object
        # is what actually holds the slot, so leaving it active would strand it
        # until its own timeout for no gain.
        self._auction.reset()

        victim = running_id or '(no task)'
        self.get_logger().info(
            f'Auction {victim} PREEMPTED by emergency task '
            f'{candidate.task_id} (priority {candidate.priority:.1f} > '
            f'{getattr(running, "priority", 0.0):.1f}); the preempted round is '
            f'refunded and its backoff is untouched'
            f'{"" if aborted else " (nothing to restore: it had already left AUCTIONING)"}'
        )
        # WARNING, not INFO: an operator's emergency has just taken work away
        # from another operator's or the planner's task, and the person who did
        # not press the button is the one who needs to see it. source_robot_id
        # is '' — AlertLog.jsx renders that as "system", which is the honest
        # attribution here: no robot did this, the orchestrator did.
        self._publish_alert(
            'WARNING', '',
            f'emergency task {candidate.task_id} preempted the in-flight '
            f'auction for {victim}. {victim} was NOT cancelled: it returns to '
            f'the queue in the status it held before that auction, keeps its '
            f'auction round and its backoff, and is announced again on a later '
            f'tick. Only the emergency injection can do this, only against a '
            f'strictly lower priority, and only ONCE -- '
            f'{candidate.task_id} has now spent its preemption and competes on '
            f'priority alone from here.',
        )
        return True

    def _resolve_auction(self) -> None:
        """Select the auction winner and assign the task (or re-queue).

        D-04: delegates the decision to ``task_feed.resolve_auction_winner``,
        which implements the constrained auction a targeted injection now
        produces. A preferred robot wins regardless of score; if it does not
        bid, the task waits for it up to
        ``inject_preferred_robot_max_rounds`` auctions and then opens up.
        """
        task_id = self._auction.get_task_id()
        task = self._task_queue.get_task(task_id)
        bids = self._auction.get_bids()
        offline_bidders = [b.robot_id for b in bids
                           if not self._robot_is_live(b.robot_id)]
        # The LIVE count. Without the subtraction ``_log_auction_failure`` prints
        # "auction_no_bids (2 bid(s))", which contradicts itself.
        bid_count = len(bids) - len(offline_bidders)
        winner, outcome, reason = resolve_auction_winner(
            task, bids, self._preferred_robot_max_rounds,
            is_live=self._robot_is_live)
        if offline_bidders:
            self.get_logger().warn(
                f'Auction {task_id}: discarded {len(offline_bidders)} bid(s) '
                f'from robot(s) the fleet monitor has declared OFFLINE '
                f'({offline_bidders}). Electing one would assign the task to a '
                f'robot whose heartbeat can never fire again.')

        # D-06, and this is the authoritative gate: re-check the ledger at the
        # moment of assignment, not just when the auction opened. The material
        # can be gone by now -- another hauler loaded it during the auction
        # window, or the excavate's MaterialEvent was dropped after the
        # announcement went out. Re-queued (PENDING, via
        # REQUEUE_STATUS_BY_REASON's default) rather than assigned, because an
        # assignment carrying quantity_kg 0.0 is read by the agent as
        # "unconstrained" and loads the bin to its RCDL capacity.
        if outcome == OUTCOME_ASSIGN and winner is not None:
            blocked = self._authorise_quantity(task)[1]
            if blocked:
                self._note_haul_block(task, blocked)
                winner, outcome, reason = None, OUTCOME_REQUEUE, blocked

        if outcome == OUTCOME_ASSIGN and winner is not None:
            self._task_queue.assign_to_robot(task_id, winner.robot_id, reason)
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
                f'score={winner.bid_score:.3f} bids={bid_count} '
                f'reason={reason or "highest_bid"}'
            )
        else:
            preferred = getattr(task, 'preferred_robot', '') if task else ''
            if outcome == OUTCOME_PREFERENCE_DROPPED and task is not None:
                task.preferred_robot = ''
                self._publish_alert(
                    'WARNING', preferred,
                    f'{task_id}: preferred robot {preferred} did not bid in '
                    f'{self._preferred_robot_max_rounds} auction(s); the '
                    f'preference is dropped and the task is now open to any '
                    f'capable robot',
                )
            elif reason == 'preferred_robot_absent':
                self._publish_alert(
                    'WARNING', preferred,
                    f'{task_id}: preferred robot {preferred} did not bid '
                    f'(round {getattr(task, "auction_rounds", 0)} of '
                    f'{self._preferred_robot_max_rounds}); re-queued',
                )
            # D-20. A no-bid auction is the one failure that used to repeat
            # forever, so it -- and only it -- gets the backoff. The other two
            # requeue reasons already terminate: 'preferred_robot_absent' is
            # bounded by inject_preferred_robot_max_rounds and turns into
            # 'preference_dropped', after which the auction is fully open.
            if reason == AUCTION_NO_BIDS:
                reason = self._back_off_auction(task_id)
            status = REQUEUE_STATUS_BY_REASON.get(reason, TaskStatus.PENDING)
            self._task_queue.set_status(task_id, status, reason)
            self._log_auction_failure(task_id, reason, bid_count, status)

        self._auction.reset()

    # ------------------------------------------------------------------ #
    #  D-20: auction backoff                                              #
    # ------------------------------------------------------------------ #

    def _back_off_auction(self, task_id: str) -> str:
        """Record a no-bid auction and return the status_reason it earns.

        The delay and the give-up decision are both derived from the same
        consecutive-failure count, so a task cannot be held off without also
        moving toward being abandoned -- which is what would happen if the
        backoff were a timer and the bound a separate counter.

        The status is NOT set here. The caller sets it once, with this reason,
        so one round produces exactly one TaskEvent instead of two.
        """
        task = self._task_queue.get_task(task_id)
        # The delay is for the failure that is about to be recorded, hence
        # +1: defer_auction increments and returns the count it lands on.
        next_count = (getattr(task, 'failed_auctions', 0) if task else 0) + 1
        failures = self._task_queue.defer_auction(
            task_id,
            auction_backoff_sec(next_count, self._auction_backoff_base,
                                self._auction_backoff_max),
        )
        reason = auction_failure_reason(
            failures, self._auction_max_failed_rounds)
        if reason == AUCTION_ABANDONED:
            self._task_queue.abandon_auction(task_id)
        return reason

    def _log_auction_failure(self, task_id: str, reason: str, bid_count: int,
                             status) -> None:
        """Log a failed auction ONCE PER STATE, not once per round.

        This is the other half of D-20 and it is not cosmetic. The measured
        flood was 261 INFO lines for one task, all identical, at roughly one
        every 5.5 s -- enough to make the orchestrator log useless for
        diagnosing anything else, which is how the fleet degraded silently in
        the same session (D-22).

        The abandonment additionally raises a WARNING FleetAlert, because it is
        the point at which the orchestrator stops trying and an operator has to
        know. Once: `_auction_failure_logged` is keyed by task and holds the
        last reason emitted, so a task cycling PENDING -> abandoned -> woken ->
        abandoned reports each transition and nothing in between.
        """
        if self._auction_failure_logged.get(task_id) == reason:
            self.get_logger().debug(
                f'Auction {task_id}: {reason} again ({bid_count} bid(s))')
            return
        self._auction_failure_logged[task_id] = reason

        task = self._task_queue.get_task(task_id)
        failures = getattr(task, 'failed_auctions', 0) if task else 0
        if reason == AUCTION_ABANDONED:
            self.get_logger().warn(
                f'Auction {task_id}: no bids in {failures} consecutive '
                f'auction(s); GIVING UP. It stays {status.name} with '
                f'status_reason={reason!r} and will not be announced again '
                f'until a robot arrives in IDLE.')
            self._publish_alert(
                'WARNING', '',
                f'task {task_id} is blocked: no robot bid on it in {failures} '
                f'consecutive auctions, so the orchestrator has stopped '
                f'announcing it. Other queued work is unaffected -- the task '
                f'is no longer holding the auction slot. It re-enters the '
                f'auction automatically when any robot next becomes IDLE. If '
                f'that never happens, no robot in this fleet can service it: '
                f'check its required_capabilities against the fleet, and '
                f'whether any capable robot has the energy to reach it.')
            return

        # The backoff clause is only true for the no-bid reasons. The other two
        # requeue reasons ('preferred_robot_absent', 'preference_dropped')
        # reach here as well and set no deadline, and printing "next attempt in
        # 0s" for them would read as a defect in the mechanism rather than as
        # its absence.
        delay = getattr(task, 'auction_backoff_until', 0.0) if task else 0.0
        remaining = max(0.0, delay - time.monotonic())
        suffix = (f'; next attempt in {remaining:.0f}s '
                  f'(consecutive failures: {failures})' if delay > 0.0 else '')
        self.get_logger().info(
            f'Auction {task_id}: {reason} ({bid_count} bid(s)), re-queued as '
            f'{status.name}{suffix}')

    def _wake_on_fleet_change(self) -> None:
        """Re-open every backed-off auction when a robot arrives in IDLE.

        WITHOUT THIS THE MISSION DEADLOCKS, and that is a worse failure than
        the flood D-20 fixes. A task abandoned because every capable robot was
        busy would stay abandoned after they all finished, and nothing would
        ever announce it again.

        The trigger is ``FleetMonitor.idle_arrivals`` -- a count of robots
        TRANSITIONING into IDLE -- and not the size or contents of
        ``get_idle_robots()``. That distinction is the whole design: in the
        measured failure a robot WAS idle and simply did not bid, so anything
        derived from set membership would have reset the backoff on every tick
        and the mechanism would have done nothing. See
        ``FleetMonitor._note_idle_arrival`` for the two transitions that are
        deliberately not counted.

        Costs an integer comparison per tick in the normal case.
        """
        arrivals = self._fleet.idle_arrivals
        if arrivals == self._last_idle_arrivals:
            return
        self._last_idle_arrivals = arrivals
        woken = self._task_queue.wake_deferred_auctions(AUCTION_FLEET_CHANGED)
        if not woken:
            return
        # `_auction_failure_logged` is deliberately NOT cleared here. A task
        # that was abandoned, woken, and abandoned again has not changed state
        # from the operator's point of view -- it is still blocked -- and
        # re-emitting the WARNING alert once per fleet change would be the
        # 261-line flood with a longer period. The wake itself is the record,
        # logged once, with a count.
        self.get_logger().info(
            f'A robot became IDLE; {len(woken)} backed-off task(s) are '
            f'auctionable again: {sorted(woken)}')

    # ------------------------------------------------------------------ #
    #  D2: the bounded skill retry                                        #
    # ------------------------------------------------------------------ #

    def _retry_failed_tasks(self) -> None:
        """Give a task a skill reported FAILED its next attempt — D2.

        THE SIBLING OF ``_wake_on_fleet_change`` and it runs beside it, because
        the two answer the same question about two different dead ends: a task
        the fleet never bid on, and a task the fleet ran and failed. Before
        this, only the first had an answer. A FAILED task was terminal in
        practice and nothing in ``TaskQueue`` moved one out of FAILED, so --
        measured live -- one failed survey took ``select_site`` with it and
        every excavate and haul behind that, permanently and silently.

        UNGATED, unlike the wake, and that is what ``TaskEntry.failed_attempts``
        buys. ``wake_deferred_auctions`` has to be driven by a fleet change or
        it re-announces forever; this cannot, because ``failed_attempts`` is
        never reset by anything, so a task is retried at most
        ``TASK_MAX_ATTEMPTS - 1`` times in its entire life however often this
        sweep runs. At 2 Hz over a whole mission that is still two re-queues.

        SILENT AND FREE WHEN THERE IS NOTHING TO DO -- ``retry_failed_tasks``
        returns ``[]`` and the exhaustion report is latched -- which is the same
        discipline ``_recover_offline_robot_tasks`` follows on the 1 Hz timer
        and the reason a sweep this frequent is not D-20's 261-line flood.

        The per-task WARNING is bounded by the same arithmetic: two lines per
        task, ever.
        """
        retried = self._task_queue.retry_failed_tasks(
            TASK_MAX_ATTEMPTS, TASK_RETRY_REQUEUED)
        for task_id in retried:
            task = self._task_queue.get_task(task_id)
            attempts = getattr(task, 'failed_attempts', 0) if task else 0
            self.get_logger().warn(
                f'Task {task_id} has failed {attempts} of '
                f'{TASK_MAX_ATTEMPTS} attempt(s); re-queued as PENDING with '
                f'status_reason={TASK_RETRY_REQUEUED!r}. It re-enters the '
                f'ordinary auction -- no robot is reserved for it and its '
                f'previous assignment is cleared.')
        self._report_attempts_exhausted()

    def _report_attempts_exhausted(self) -> None:
        """Say ONCE, and loudly, that a task will not be attempted again — D2.

        THE OTHER HALF OF THE FIX, and it is not cosmetic. A bounded retry on
        its own converts a silent deadlock into a slower silent deadlock: after
        the last attempt the task rests in FAILED forever, and while an ORDINARY
        dependency was satisfied only by COMPLETED the mission then stopped with
        nothing said. That is precisely what was observed -- the dashboard read
        "awaiting first extraction" for the rest of the run. The soft dependency
        quorum added later lets select_site survive exactly this, on partial
        evidence and loudly (``_htn_advance``); it does not make an exhausted
        task any less exhausted, so this alert is unchanged in purpose. This is the
        ``auction_abandoned`` alert's counterpart: the orchestrator has stopped
        trying, so an operator has to know.

        THE BLAST RADIUS IS THE POINT, and it is why
        ``TaskQueue.get_transitive_dependents`` exists rather than
        ``get_dependent_tasks``. A dead survey directly blocks one task
        (select_site) and really blocks every excavate and haul behind it; an
        alert naming "1 blocked task" would understate a mission-fatal event by
        the whole chain.

        THE COUNT IS STRUCTURAL AND IT IS A FLOOR, NOT THE COST. It counts rows
        that EXIST in the queue now. In the shipped decomposition the excavate
        and haul cycles are generated only after ``select_site`` COMPLETES, so
        at the moment a survey exhausts its attempts most of what it has killed
        has not been created yet and cannot be counted here. Understating is
        the failure mode this alert exists to prevent, so it is said in the
        message rather than left for a reader to discover.

        Latched on ``_attempts_exhausted_alerted`` rather than on the status,
        because an exhausted task NEVER leaves FAILED on its own: an unlatched
        sweep would re-alert at 2 Hz for the rest of the mission.
        """
        for task in self._task_queue.get_all_tasks():
            if task.status != TaskStatus.FAILED:
                continue
            # THE SAME predicate ``retry_failed_tasks`` skips a task on and
            # ``TaskQueue._dependency_resolved`` calls a dependency finished on
            # -- one expression now, not three spellings of one bound. It is
            # false for failed_attempts == 0, which is what keeps
            # inject_task_logic._reject's FAILED row -- written through
            # set_status, never counted -- out of this alert.
            if not TaskQueue.attempts_exhausted(task, TASK_MAX_ATTEMPTS):
                continue
            if task.task_id in self._attempts_exhausted_alerted:
                continue
            self._attempts_exhausted_alerted.add(task.task_id)
            blocked = sorted(
                t.task_id
                for t in self._task_queue.get_transitive_dependents(
                    task.task_id))
            last_reason = task.status_reason
            # Through set_status, which finds the task ALREADY FAILED and
            # therefore updates the reason and returns at its
            # ``previous == status`` guard -- no listener, no second TaskEvent,
            # no new status_changed. The same mechanism, for the same reason,
            # as wake_deferred_auctions' direct write.
            self._task_queue.set_status(
                task.task_id, TaskStatus.FAILED, TASK_ATTEMPTS_EXHAUSTED)
            if blocked:
                # THE "can NEVER become ready" CLAUSE THAT STOOD HERE IS NO
                # LONGER TRUE OF EVERY DEPENDENT, and leaving it would make the
                # loudest message this node emits assert a deadlock the same
                # change removes. A dependent carrying a SOFT dependency quorum
                # (TaskEntry.depends_on_quorum -- select_site does) becomes
                # ready once every dependency is RESOLVED, and a task that has
                # spent every attempt IS resolved. So the set below is the blast
                # radius of the edge; whether each member is genuinely dead is
                # TaskQueue.dependencies_met's answer, and this says so.
                impact = (
                    f'{len(blocked)} task(s) already in the queue depend on '
                    f'it, directly or transitively: {blocked}. An ORDINARY '
                    f'dependency is satisfied only by COMPLETED, so those can '
                    f'never become ready while it stays FAILED. The exception '
                    f'is a dependent carrying a SOFT dependency quorum '
                    f'(select_site carries one): every dependency of it is now '
                    f'RESOLVED, so it may still run on PARTIAL EVIDENCE, and a '
                    f'separate WARNING will say so if it does. That count is a '
                    f'FLOOR: work the HTN planner has not decomposed yet is '
                    f'not in it.')
            else:
                impact = 'No task currently in the queue depends on it.'
            self.get_logger().error(
                f'Task {task.task_id} ({task.task_type}) has FAILED '
                f'{task.failed_attempts} time(s); GIVING UP. It stays FAILED '
                f'with status_reason={TASK_ATTEMPTS_EXHAUSTED!r} and will not '
                f'be retried again. Last failure: {last_reason!r}. '
                f'Blocked: {blocked}')
            self._publish_alert(
                'CRITICAL' if blocked else 'WARNING', task.assigned_robot,
                f'task {task.task_id} ({task.task_type}) has FAILED '
                f'{task.failed_attempts} time(s) and the orchestrator has '
                f'STOPPED retrying it (last failure: {last_reason}). '
                f'{impact} Nothing in the orchestrator will clear this by '
                f'itself: re-inject the work, or cancel what depends on it.')

    def _publish_mission_progress(self) -> None:
        """Publish aggregated mission progress metrics — FR-DASH-7.

        Distance and energy totals come from FleetMonitor's per-update deltas.
        The masses come from MaterialInventory, which as of 2026-07-30 has real
        production writers: ``_on_material_event`` feeds it from
        ``/orchestrator/material_event``, and every kilogram in it is a
        difference of two sensor readings measured by a skill on a robot.

        WHAT WAS HERE BEFORE, and why the note is gone rather than edited: this
        method carried an "HONESTY NOTE (not yet wired)" recording that
        ``register_site`` / ``record_extraction`` / ``record_load`` /
        ``record_unload`` had no callers anywhere, so extracted / in_transit /
        deposited were structurally 0.0 in every live run. That was true and
        the note was right to exist. It is now false, and leaving it standing
        would be worse than never having written it. What replaced it:

          agent skill reads its fill sensor  (mass = level x RCDL capacity_kg)
            -> MaterialEvent on /orchestrator/material_event
            -> material_event_logic       (dedupe, resolve site from task_id)
            -> MaterialInventory          (extract / load / unload)
            -> here.

        Two honesty caveats remain and are NOT fixed by this change:
        - ``elapsed_sim_time`` is orchestrator WALL CLOCK since node start, not
          Gazebo simulation time. ``use_sim_time`` has zero code occurrences
          repo-wide and /clock is not bridged. The field keeps its name because
          renaming a published field breaks the dashboard and PRD MSG-7;
          ``fleet_uptime_sec`` beside it is the honestly-labelled companion,
          measured from the FIRST ROBOT HEARTBEAT rather than from node start.
        - ``deposited`` is a measured mass only because the HTN planner is
          constructed with ``deposited_source``; ``get_mission_status()``
          exposes ``deposited_is_measured`` for anyone who needs to check.
        """
        # MissionProgress.target_quantity is documented in kg at
        # docs/PRD.md:685 (MSG-7). It previously carried
        # TaskQueue.get_total_count() — a task count — which the dashboard then
        # rendered through a kg formatter. It is sourced from the HTN planner's
        # _target_kg, set by decompose_collect_ice(quantity_kg=100.0).
        mission_status = self._htn_planner.get_mission_status()
        elapsed = (self.get_clock().now() - self._start_time).nanoseconds / 1e9
        msg = build_mission_progress(
            MissionProgress(),
            objective_description='PSR Ice Prospecting Survey',
            target_kg=float(mission_status.get('target_kg', 0.0)),
            ledger=self._inventory.get_mission_progress(),
            fleet_distance_m=self._fleet.get_total_distance(),
            fleet_energy_wh=self._fleet.get_total_energy_consumed(),
            elapsed_sec=elapsed,
            fleet_uptime_sec=self._fleet.get_uptime_sec(),
            material_events_applied=self._material_ctx.events_applied,
        )
        self._progress_pub.publish(msg)

    def _publish_task_queue(self) -> None:
        """Publish the complete task table plus the event ring — FR-DASH-3.

        A COMPLETE SNAPSHOT, never a delta, for the same reason ResourceMap is:
        a subscriber that joins late or drops a message is fully correct from
        the next one, with no durability negotiation. A browser loaded
        mid-mission is right within 500 ms.

        Replaces ~75 lines of client-side lifecycle inference in
        ``useFleetState.js``, which reconstructed the panel from
        ``RobotState.current_task_id`` edges and could therefore only ever
        produce PENDING / ASSIGNED / IN_PROGRESS / COMPLETED -- making FAILED
        and INTERRUPTED unreachable, and rendering a cancelled task as done.
        """
        msg = TaskQueueState()
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = ''
        msg.header = header

        rows = []
        for row in task_rows(self._task_queue):
            entry = TaskStatusMsg()
            entry.task_id = row['task_id']
            entry.task_type = row['task_type']
            entry.status = row['status']
            entry.assigned_robot = row['assigned_robot']
            entry.preferred_robot = row['preferred_robot']
            entry.priority = row['priority']
            entry.progress = row['progress']
            entry.quantity_kg = row['quantity_kg']
            entry.target_location = Point(x=row['target_location'][0],
                                          y=row['target_location'][1], z=0.0)
            entry.parent_task_id = row['parent_task_id']
            entry.depends_on = row['depends_on']
            entry.required_capabilities = row['required_capabilities']
            entry.status_reason = row['status_reason']
            entry.status_changed = _epoch_to_time(row['status_changed'])
            entry.auction_rounds = row['auction_rounds']
            entry.emergency = row['emergency']
            rows.append(entry)
        msg.tasks = rows

        events = []
        for record in self._events.snapshot():
            event = TaskEventMsg()
            event.seq = record['seq']
            event.stamp = _epoch_to_time(record['stamp'])
            event.kind = record['kind']
            event.task_id = record['task_id']
            event.robot_id = record['robot_id']
            event.actor = record['actor']
            event.action = record['action']
            event.detail = record['detail']
            event.accepted = record['accepted']
            event.target = Point(x=record['target'][0],
                                 y=record['target'][1], z=0.0)
            events.append(event)
        msg.events = events
        msg.event_seq_next = self._events.seq_next
        msg.events_dropped = self._events.dropped
        self._task_queue_pub.publish(msg)

    def _adaptive_survey_tick(self) -> None:
        """FR-MAP-3: re-target PENDING survey waypoints from the fused map.

        This is the call site the adaptive planner never had. It runs on a timer
        rather than at decomposition because the planner's whole input -- the
        posterior in ResourceMap -- is empty until scouts start reporting.

        It rewrites the targets of PENDING survey tasks and never creates or
        removes one. Three consequences, all deliberate:

        - Termination is structural. The waypoint budget is fixed by
          HTNPlanner.decompose_collect_ice(); this cannot raise it. Once every
          survey task has left PENDING the call is a permanent no-op.
        - The HTN dependency graph survives. ``select_site.depends_on`` lists
          exactly the task_ids created at decomposition, so SelectSite still
          resolves when the survey finishes -- and now resolves on a posterior
          built from waypoints that chased the ice.
        - Nothing already announced or assigned is touched. See
          COMMITTED_STATUSES in adaptive_survey.py for why that is not optional.
        """
        completed = sum(
            1 for t in self._task_queue.get_all_tasks()
            if t.task_type == SURVEY_TASK_TYPE
            and t.status == TaskStatus.COMPLETED
        )
        total_readings = self._resource_map.get_total_readings()
        peak = zone_peak_mean(
            self._resource_map, SURVEY_ZONE_CENTER, SURVEY_ZONE_RADIUS)

        if not should_replan(
                completed_surveys=completed,
                total_readings=total_readings,
                last_replan_readings=self._adaptive_last_readings,
                peak_mean=peak,
                seed_waypoints=self._adaptive_seed_waypoints,
                min_signal_wt=self._adaptive_min_signal_wt):
            return

        self._adaptive_last_readings = total_readings
        reference = self._survey_reference_position()
        moves = replan_pending_survey_targets(
            self._adaptive_survey, self._task_queue, reference,
            task_type=SURVEY_TASK_TYPE,
        )
        if not moves:
            return

        # INFO because this IS the SC-3 evidence: the sequence of these lines is
        # the record that waypoints moved toward the ice, and the only such
        # record if nobody is watching RViz.
        first_id, first_old, first_new = moves[0]
        self.get_logger().info(
            'FR-MAP-3 adaptive survey: %d pending waypoint(s) re-targeted '
            '(peak %.2f wt%%, %d readings, ref (%.1f, %.1f)); '
            '%s (%.1f, %.1f) -> (%.1f, %.1f)'
            % (len(moves), peak, total_readings, reference[0], reference[1],
               first_id, first_old[0], first_old[1],
               first_new[0], first_new[1])
        )

    def _survey_reference_position(self) -> tuple[float, float]:
        """Distance datum for waypoint scoring: the scout centroid.

        FR-MAP-3(b) says "distance_to_robot", but a PENDING waypoint has no
        robot: the auction decides who services it, and the auction does not run
        until the waypoint is announced, which is after this. So the per-robot
        distance the PRD names is not knowable at re-plan time. The centroid of
        the online prospect-capable robots is the fleet-level stand-in, and
        w_distance (0.3) is the smallest of the three weights.

        Falls back to the zone centre before any scout has reported.

        FRAME: world metres, the same frame ``ResourceMapUpdate.location`` is
        in. This said "dead-reckoned odom poses (see D-08) ... self-consistent
        even though neither is world-true" until 2026-07-31; both are now
        world-referenced, converted once by
        ``selene_sim/selene_sim/world_odometry_node.py``. The self-consistency
        argument still holds and is no longer all that holds: the centroid this
        returns and the map cells it is scored against are now the same places
        the robots physically occupy.
        """
        positions = [
            self._fleet.get_robot_position(rid)
            for rid in self._fleet.get_robots_with_capability(SURVEY_TASK_TYPE)
        ]
        positions = [p for p in positions if p is not None]
        if not positions:
            return SURVEY_ZONE_CENTER
        return (sum(p[0] for p in positions) / len(positions),
                sum(p[1] for p in positions) / len(positions))

    def _htn_advance(self) -> None:
        """Advance the HTN planner, and open a ledger site when one resolves.

        Registration happens here, immediately after ``check_and_advance()``,
        and that ORDERING IS GUARANTEED to precede any excavate event: every
        excavate task ``depends_on`` the select_site task
        (htn_planner._generate_cycles), and ``get_next_ready`` will not auction
        a task whose dependencies are not COMPLETED — select_site is marked
        COMPLETED in the same call that allocates the site id. So no
        MaterialEvent can arrive for a site the ledger has not heard of. That
        argument survives D2's soft quorum untouched, because the quorum is on
        select_site's OWN dependencies and every excavate's dependency on
        select_site is a HARD edge with no quorum at all.

        It is also where the operator is told, once, that the site was chosen on
        PARTIAL survey evidence -- see the WARNING at the end.
        """
        self._htn_planner.check_and_advance()

        site_id = self._htn_planner.get_site_id()
        if not site_id or site_id in self._registered_sites:
            return
        position = self._htn_planner.get_site_position()
        if position is None:
            return
        status = self._htn_planner.get_mission_status()
        # estimated_kg is the mission's PLAN figure (decompose_collect_ice's
        # quantity_kg), not a survey estimate of what is actually in the
        # ground. Nothing gates on it: get_site_remaining() is the only reader
        # and no code path consults that. It is registered so the site record
        # is complete rather than carrying a fabricated zero.
        self._inventory.register_site(
            site_id, position, estimated_kg=float(status.get('target_kg', 0.0)))
        self._registered_sites.add(site_id)
        self.get_logger().info(
            'ISRU ledger: registered site %s at (%.1f, %.1f), mission plan '
            '%.1f kg' % (site_id, position[0], position[1],
                         float(status.get('target_kg', 0.0))))

        # D2, the soft-quorum half: the site was chosen on PARTIAL evidence.
        # SAY SO, ONCE, and to the operator rather than only to the log.
        #
        # HERE rather than in the planner because ``HTNPlanner`` is pure Python
        # with no publisher and no clock by construction -- the same split as
        # ``task_feed`` and ``resource_map_viz``. AFTER the registration because
        # this block is already latched exactly once per site by the
        # ``site_id in self._registered_sites`` early return above, so no second
        # latch flag is needed and a 1 Hz re-alert is impossible.
        #
        # WARNING and not CRITICAL, and the line is drawn where D2 already drew
        # it: CRITICAL in this node means "the orchestrator has STOPPED and
        # nothing will clear it". This says the opposite -- it PROCEEDED,
        # degraded. The dead surveys that caused it have each already raised
        # their own CRITICAL from ``_report_attempts_exhausted``, so an operator
        # sees the cause at CRITICAL and the consequence at WARNING, in that
        # order.
        #
        # ``0 < surveyed`` is documenting rather than reachable: with a quorum
        # of 1 a select_site with zero COMPLETED surveys can never resolve, so
        # this can never fire claiming "0 of 10". ``surveyed == planned`` is the
        # ordinary case and says nothing at all.
        surveyed, planned = self._htn_planner.get_site_evidence()
        if 0 < surveyed < planned:
            missing = planned - surveyed
            self.get_logger().warn(
                'HTN: extraction site %s was chosen on PARTIAL EVIDENCE -- %d '
                'of %d survey waypoints COMPLETED. The other %d exhausted all '
                '%d attempt(s) and stay FAILED, so the fused posterior this '
                'site was picked from is missing their cells.'
                % (site_id, surveyed, planned, missing, TASK_MAX_ATTEMPTS))
            self._publish_alert(
                'WARNING', '',
                f'extraction site {site_id} at ({position[0]:.1f}, '
                f'{position[1]:.1f}) was chosen on PARTIAL EVIDENCE: only '
                f'{surveyed} of {planned} survey task(s) COMPLETED. The other '
                f'{missing} exhausted all {TASK_MAX_ATTEMPTS} attempt(s) and '
                f'stay FAILED. The mission is PROCEEDING rather than '
                f'deadlocking, which is the change; the site is the best cell '
                f'of a SMALLER surveyed area than was planned, it will not be '
                f're-selected, and every excavate and haul in this mission '
                f'targets it.')

    # ------------------------------------------------------------------ #
    #  Operator service handlers (FR-DASH-5 / FR-DASH-6)                   #
    # ------------------------------------------------------------------ #

    def _handle_inject_task(self, request, response):
        """Handle InjectTask service requests from the dashboard.

        Delegates to the pure-Python ``inject_task_logic`` helper so the
        decision tree can be unit-tested without instantiating the ROS node.
        Side effects (publish, log) happen here, in the Node-bound wrapper.
        """
        preferred = (request.assigned_robot_id or '').strip()
        ctx = _InjectTaskContext(
            task_queue=self._task_queue,
            fleet_monitor=self._fleet,
            next_task_id=self._next_manual_task_id,
            now_stamp=self.get_clock().now().to_msg(),
            # FleetAlert.source_robot_id used to be '' for every operator
            # action, so AlertLog.jsx attributed all of them to "system".
            publish_alert=lambda sev, msg: self._publish_alert(
                sev, preferred, msg),
            # The mission's ledger site, so an injected excavate/haul produces
            # MaterialEvents the ledger can credit instead of dropping. '' until
            # SelectSite resolves, which inject_task_logic turns into an
            # explicit rejection rather than a siteless task.
            site_id=self._htn_planner.get_site_id(),
            # The terrain box. An operator can click anywhere on the fleet map,
            # and with the frame defect fixed those coordinates are now real
            # world metres — one off the heightfield takes Gazebo down.
            terrain=self._terrain,
        )
        out = inject_task_logic(ctx, request, response)
        # FR-DASH-6(d): every operator action, accepted or rejected, enters the
        # event ring so it appears in the dashboard's task history. `detail` is
        # the exact response.message the operator's own toast shows, so the two
        # cannot disagree.
        self._events.append(
            kind=KIND_OPERATOR, action='inject_task',
            task_id=out.task_id, robot_id=preferred, actor='operator',
            detail=out.message, accepted=bool(out.success),
            target=(request.target_location.x, request.target_location.y),
        )
        return out

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
                                task_type: str, target_location,
                                quantity_kg: float = 0.0) -> None:
        """Publish a TaskAssignment built from loose fields, not a TaskEntry.

        NO LONGER ON THE INJECT PATH. It existed to serve the force-assign
        branch of ``inject_task_logic``, which D-04 deleted: a targeted
        injection is now a constrained auction and goes out through
        ``_publish_assignment`` like every other task. Kept as the one place a
        direct assignment can be published from without a queue entry.
        """
        msg = TaskAssignment()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task_type
        msg.target_location = target_location
        msg.parameters = []
        msg.assigned_at = self.get_clock().now().to_msg()
        msg.quantity_kg = float(quantity_kg)
        msg.depot_location = self._depot_point(task_type)
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
            # D-05: attribute the alert to the robot the operator acted on.
            # This was '' for every override, so AlertLog.jsx showed "system".
            publish_alert=lambda sev, msg: self._publish_alert(
                sev, request.robot_id, msg),
            set_command_factory=SetRobotCommand.Request,
            # Bounds `send_to_location`. The agent refuses the same box in
            # AStarPlanner.plan; this one exists so the operator is told why at
            # the moment they can retype the coordinate.
            terrain=self._terrain,
        )
        out = override_robot_logic(ctx, request, response)
        # FR-DASH-6(d). Logged whether or not it was accepted: "robot in ERROR,
        # override rejected" is often the more interesting record, and an
        # override on an idle robot touches no task at all, so a status table
        # cannot carry it.
        self._events.append(
            kind=KIND_OPERATOR, action=request.command,
            task_id='', robot_id=request.robot_id, actor='operator',
            detail=out.message, accepted=bool(out.success),
            target=(request.target.x, request.target.y),
        )
        return out

    def _next_operator_sequence(self) -> int:
        self._operator_command_seq += 1
        return self._operator_command_seq

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _generate_survey_tasks(self) -> None:
        """Decompose the initial ISRU mission objective via HTN planner."""
        self._htn_planner.decompose_collect_ice(
            zone_center=SURVEY_ZONE_CENTER,
            zone_radius=SURVEY_ZONE_RADIUS,
            quantity_kg=100.0,
            depot=self._depot,
        )
        self.get_logger().info(
            f'HTN decomposed mission: {self._task_queue.get_total_count()} tasks'
        )

    def _audit_mission_geometry(self) -> None:
        """Say out loud, once, whether the mission's own geometry is on the map.

        Runs after ``_generate_survey_tasks`` so it sees the real waypoints
        rather than the constants they were derived from.

        AN AUDIT, NOT A GATE. It refuses nothing and moves nothing: the survey
        zone, the depot and the extraction site are the mission definition, and
        an orchestrator that silently relocated them would be lying about what
        it is doing. What it removes is the ability for an off-map mission
        constant to be discovered only when Gazebo dies — which is how the frame
        defect this guard accompanies was found. If this ever logs an ERROR, fix
        the constant; do not raise the margin.

        It is cheap to keep correct and it is the only thing in the system that
        looks at the mission's coordinates as a set. FR-SIM-7(d) makes the world
        file configurable, so a world smaller than the shipped 500 m square is a
        supported configuration in which these constants really could fall off
        the edge.
        """
        offenders = [
            (name, x, y)
            for name, x, y in (
                ('survey zone centre', *SURVEY_ZONE_CENTER),
                ('depot', *self._depot),
            )
            if not self._terrain.contains(x, y)
        ]
        offenders.extend(
            (f'survey waypoint {task.task_id}', task.target_x, task.target_y)
            for task in self._task_queue.get_all_tasks()
            if task.task_type == SURVEY_TASK_TYPE
            and not self._terrain.contains(task.target_x, task.target_y)
        )
        if not offenders:
            self.get_logger().info(
                'mission geometry is on the terrain: %s'
                % (self._terrain.describe(),))
            return
        detail = ', '.join('%s (%.1f, %.1f)' % item for item in offenders)
        self.get_logger().error(
            'MISSION GEOMETRY IS OFF THE TERRAIN: %s. %s. A robot sent there '
            'leaves the heightfield and falls, which aborts Gazebo — the agent '
            'will refuse the goal, so these tasks will fail rather than crash '
            'the simulator, but the mission cannot complete as configured.'
            % (detail, self._terrain.describe()))
        self._publish_alert(
            'ERROR', '',
            'mission geometry is off the terrain: %s (%s)'
            % (detail, self._terrain.describe()))

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
        # FR-DASH-5. Announced as well as assigned so a bidder can see the size
        # of the job; no bid weight uses it today (agent_node scores distance,
        # energy and capability only).
        msg.quantity_kg = float(getattr(task, 'quantity_kg', 0.0))
        # Operator emergency. No bidder reads it -- agent_node scores distance,
        # energy and capability -- so it changes no bid. Its reader is the
        # exit-gate probe: ProbeNode._on_announcement records it and check 6
        # asserts that an injection made with emergency=True produced an
        # announcement carrying it, which is what makes this hop verified on a
        # live wire rather than the eighth "declared and never read" field in
        # this repository. TaskAnnouncement.msg names the same reader.
        msg.emergency = bool(getattr(task, 'emergency', False))
        self._announce_pub.publish(msg)

    def _authorise_quantity(self, task) -> tuple[float, str]:
        """``(kg, block_reason)`` for one task — see authorise_task_quantity.

        NOT clamped against any robot's capacity — the orchestrator has no HAL
        and no RCDL. The agent clamps against selene_hal/config/<type>.yaml.
        """
        return authorise_task_quantity(
            task, self._inventory.get_site_available)

    def _note_haul_block(self, task, reason: str) -> None:
        """Alert once per (task, reason) that a haul cannot be dispatched.

        Once, not once per tick: ``_auction_tick`` runs at 2 Hz and a haul
        whose excavate reported no measured mass stays blocked indefinitely, so
        an alert per tick would bury everything else in AlertLog.jsx. A reason
        that CHANGES is re-alerted, which is how "no site" becoming "no
        material" stays visible, and clearing the block re-arms it so a second
        stall is reported too.
        """
        task_id = getattr(task, 'task_id', '') or ''
        if not reason:
            self._haul_block_alerted.pop(task_id, None)
            return
        if self._haul_block_alerted.get(task_id) == reason:
            return
        self._haul_block_alerted[task_id] = reason
        detail = ('no extraction site is associated with it'
                  if reason == HAUL_BLOCK_NO_SITE
                  else 'the ledger has no extracted mass waiting at its site')
        self._publish_alert(
            'WARNING', getattr(task, 'assigned_robot', '') or '',
            f'haul {task_id} is not being dispatched ({reason}): {detail}. '
            f'Assigning it would publish quantity_kg 0.0, which the agent '
            f'reads as "fill to capacity" and would load a bin of material no '
            f'excavator extracted. It stays queued until an excavate reports '
            f'measured mass there; an HTN excavate/haul chain cannot advance '
            f'past it until then.')
        self.get_logger().warn(
            'haul %s withheld from auction: %s' % (task_id, reason))

    def _publish_assignment(self, task_id: str, robot_id: str, task) -> None:
        """Publish a TaskAssignment to the winning robot."""
        quantity, blocked = self._authorise_quantity(task)
        if blocked:
            # Belt and braces. Both callers of this method gate on the same
            # predicate before assigning, so reaching here means a third caller
            # was added without one -- which must not silently publish a 0.0
            # that the agent reads as "fill the bin to capacity".
            self.get_logger().error(
                'refusing to publish assignment for %s to %s: %s'
                % (task_id, robot_id, blocked))
            return
        msg = TaskAssignment()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task.task_type if task else 'prospect'
        # For a haul this is the PICKUP, not the depot — the depot travels
        # separately in depot_location below. Since D-22 the pickup is
        # HAUL_PICKUP_OFFSET_M from the extraction site rather than on it, so
        # that a plan never sends a hauler onto the coordinate an excavator is
        # parked on; the agent then stops HaulSkill.PICKUP_STANDOFF_M short of
        # even that. Neither displacement touches the ledger, which keys on
        # TaskEntry.site_id and never on a coordinate (material_event_logic
        # step 4, :747-761).
        msg.target_location = Point(
            x=task.target_x if task else 0.0,
            y=task.target_y if task else 0.0,
            z=0.0,
        )
        msg.parameters = []
        msg.assigned_at = self.get_clock().now().to_msg()
        msg.quantity_kg = quantity
        msg.depot_location = self._depot_point(
            task.task_type if task else '')
        self._assign_pub.publish(msg)

    def _depot_point(self, task_type: str) -> Point:
        """Depot for a haul, zero for everything else.

        Zero (0, 0, 0) is the agent's signal to fall back to its own recharge
        station, which is what it did unconditionally before this field
        existed — and why a haul used to dump its load at a charger.
        """
        if task_type == 'haul':
            return Point(x=self._depot[0], y=self._depot[1], z=0.0)
        return Point()

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
