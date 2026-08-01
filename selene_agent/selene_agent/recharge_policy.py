"""Pure-Python recharge policy for the SELENE agent — deviation D-19.

WHAT WAS WRONG. ``agent_node`` had no recharge policy at all. ``_handle_working``
ended every task — success or failure — with

    self._fsm.handle_event(FSMEvent.TASK_COMPLETE)
    self._start_recharge()

and ``_start_recharge`` simply built a ``RechargeSkill`` and drove to the
station. There was no battery test anywhere on that path. Measured live on
2026-07-31 on ROS 2 Jazzy + Gazebo: scouts returned to base and charged after
every single survey waypoint at **88-93% battery**, spent the majority of two
runs in RECHARGING, and reached only 155 map observations in 10 minutes and 316
in 21. Because the HTN's ``SelectSite`` cannot resolve until every survey
waypoint is COMPLETE, and no excavate or haul task exists until it does, this
one defect is what kept the D-06 material ledger at zero in every live run.

Meanwhile ``recharge_threshold`` — the parameter that names exactly this
decision — was declared by the ORCHESTRATOR, set in
``selene_orchestrator/config/orchestrator_params.yaml``, and read by nobody.
It was one of two entries on ``test_no_orphan_parameters.py``'s allow-list,
annotated "the agent decides recharge locally (selene_agent battery logic)".
The first half was the right design; the second half described logic that did
not exist.

WHY THIS MODULE EXISTS SEPARATELY. Exactly the reason ``operator_command.py``
gives: ``agent_node`` imports ``rclpy``, ``selene_msgs`` and ``selene_hal`` at
module scope, so nothing in it can be imported in the ROS-free pytest lane, and
anything that can be wrong has to live outside the node or it is untested.
Zero ROS, zero selene_hal, zero skill imports here.

WHAT LIVES WHERE. The energy question — "is this robot short of energy" — is
``EnergyManager.recharge_reason()``, because it is arithmetic over battery
state and it belongs beside the model that produces it. This module holds the
consequences: which FSM event that answer implies, and the two guards
(configuration validation, and the refusal counter) that keep the answer from
stranding a robot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from selene_agent.fsm import AgentState, FSMEvent


#: Consecutive task announcements a robot may decline purely for want of
#: energy before it stops waiting and goes to charge.
#:
#: WHY A COUNT AND NOT A SINGLE REFUSAL. ``can_afford_task`` measures ONE
#: task. A scout at 60% that cannot afford a waypoint on the far side of the
#: survey zone can very likely afford the next one announced; recharging on the
#: first refusal would reintroduce D-19 in a subtler form — a robot driven home
#: by the geometry of a task it was never going to win.
#:
#: WHY A COUNT AND NOT NOTHING. This is the one way the D-19 fix could strand a
#: robot. Before it, an agent that skipped a bid was on its way to a full
#: battery anyway. Now it stays IDLE; if it sits above the floor but below what
#: the offered work costs, it bids on nothing and waits for the idle draw to
#: walk it down to the floor. For a scout that is 10 W out of 50 Wh — roughly
#: 90 minutes of a robot doing nothing while the orchestrator auctions around
#: it.
#:
#: NOT A ROS PARAMETER, deliberately: it is a shape of behaviour rather than a
#: tuning knob, and every parameter this repository added without a reader has
#: cost it a register entry.
UNAFFORDABLE_PASSES_BEFORE_RECHARGE = 3


@dataclass
class _RechargeContext:
    """Injected dependencies for the helpers below.

    Same shape and same purpose as ``_OperatorCommandContext``: every
    interaction with agent state goes through a callable, so a test can drive
    each branch with spies and no ROS node.
    """
    robot_id: str
    get_state: Callable[[], AgentState]
    fire_event: Callable[[FSMEvent], None]
    #: ``AgentNode._recharge_reason`` — '' when no recharge is warranted.
    recharge_reason: Callable[[], str]
    start_recharge: Callable[[], None]
    get_charge_fraction: Callable[[], float]
    #: The configured floor, for the log line only.
    recharge_threshold: float
    log_info: Callable[[str], None]
    #: Abort whatever skill is running, if any. Called only on the
    #: ``begin_recharge_cycle`` path, where the robot may be mid-task.
    abort_current_skill: Callable[[], None]


def settle_after_task_logic(ctx: _RechargeContext) -> str:
    """In RETURNING immediately after TASK_COMPLETE: go home, or stay out.

    Returns the recharge reason acted on, or '' when the robot stayed in the
    field. THE RETURN VALUE IS THE TEST SURFACE — a caller that ignores it is
    fine; a test that asserts on it is asserting on the decision rather than on
    a log line.

    The FSM is already in RETURNING when this is called, because
    ``(WORKING, TASK_COMPLETE) -> RETURNING`` is the only transition out of a
    finished task and this module does not get to choose it. So the two
    outcomes are:

    * recharge needed  -> stay in RETURNING and start the RechargeSkill. This
      is what the node did unconditionally before D-19.
    * recharge not needed -> ``RECHARGE_NOT_NEEDED`` takes RETURNING to IDLE.

    Fired in the SAME tick as the TASK_COMPLETE above it.

    THIS PARAGRAPH USED TO CLAIM the agent's 2 Hz state publisher "never
    observes RETURNING", so the orchestrator was never told a robot is heading
    home when it is not. Since D-34 that is false: ``AgentNode`` publishes a
    ``RobotState`` on every FSM transition as well as on the 0.5 s timer, so a
    RETURNING sample and an IDLE sample are both emitted, microseconds apart,
    on this path. Nothing here changes -- the robot genuinely passes through
    RETURNING and a consumer is better off seeing it than being protected from
    it by an aliasing artefact -- but a consumer must read RETURNING as
    "possibly transient" and take a RETURNING that survives to the next timer
    tick as the durable "this robot is driving home" signal.
    """
    reason = ctx.recharge_reason()
    charge = ctx.get_charge_fraction()
    if reason:
        ctx.log_info(
            f'[{ctx.robot_id}] Task done at {charge:.1%} battery; returning '
            f'to recharge ({reason})'
        )
        ctx.start_recharge()
        return reason

    ctx.log_info(
        f'[{ctx.robot_id}] Task done at {charge:.1%} battery; staying in the '
        f'field (floor {ctx.recharge_threshold:.0%}, return margin OK)'
    )
    ctx.fire_event(FSMEvent.RECHARGE_NOT_NEEDED)
    return ''


def begin_recharge_cycle_logic(ctx: _RechargeContext, reason: str) -> bool:
    """Send a robot home to charge from a state that is not already RETURNING.

    Returns True if the cycle was started. Refuses — returning False without
    touching anything — from the four states ``FSMEvent.RECHARGE_NEEDED`` has
    no transition for, rather than letting ``AgentFSM`` raise
    ``InvalidTransitionError`` out of a timer callback and take the node down:

    * RETURNING  — already on its way;
    * RECHARGING — already there;
    * ERROR      — a faulted robot must not be given a navigation goal, the
      same rule ``OPERATOR_RECHARGE`` follows; ``FSMEvent.RECOVERY`` is the
      only way out;
    * OFFLINE    — nothing to command.

    The skill abort comes BEFORE the FSM event so a robot interrupted
    mid-navigation cannot leave a latched velocity driving the wheels while the
    RechargeSkill plans its own path.
    """
    state = ctx.get_state()
    if state in (AgentState.RETURNING, AgentState.RECHARGING,
                 AgentState.ERROR, AgentState.OFFLINE):
        return False

    charge = ctx.get_charge_fraction()
    ctx.log_info(
        f'[{ctx.robot_id}] Returning to recharge at {charge:.1%} battery '
        f'({reason})'
    )
    ctx.abort_current_skill()
    ctx.fire_event(FSMEvent.RECHARGE_NEEDED)
    ctx.start_recharge()
    return True


def should_recharge_after_refusals(
    passes: int, state: AgentState, in_startup_grace: bool,
) -> bool:
    """Has this robot declined enough affordable work to justify charging?

    Split out from the counter itself so the threshold arithmetic is testable
    without a node. All three conditions are load-bearing:

    * ``passes`` — see ``UNAFFORDABLE_PASSES_BEFORE_RECHARGE``.
    * ``state`` — only from IDLE. A robot that is working, bidding or already
      returning has not been stranded by anything, and an announcement it
      ignores says nothing about its energy.
    * ``in_startup_grace`` — the HAL reports a phantom 0% charge until DDS has
      delivered the first real battery sample, so ``can_afford_task`` refuses
      EVERYTHING for the first few seconds. Without this the whole fleet would
      drive to the charging station in the first second of the mission.
    """
    if in_startup_grace:
        return False
    if state != AgentState.IDLE:
        return False
    return passes >= UNAFFORDABLE_PASSES_BEFORE_RECHARGE


def validated_recharge_threshold(
    threshold: float, critical: float, target: float,
) -> tuple[float, str]:
    """``(usable floor, complaint)`` for a configured ``recharge_threshold``.

    The complaint is '' when there is nothing to say; otherwise it is a
    human-readable sentence the node logs. Returned rather than logged here so
    this module keeps its "no I/O" property and so the text itself is pinned by
    a test.

    Two orderings are configuration errors rather than preferences, and both
    are completely silent at runtime unless something says so:

    * ``threshold >= target`` makes a robot that has just charged to *target*
      immediately want to charge again — an IDLE -> RETURNING -> RECHARGING ->
      IDLE busy loop at the tick rate, navigating nowhere because it is already
      at the station. **Clamped**, because a fleet that limps beats a fleet
      that spins.
    * ``threshold <= critical`` makes the floor unreachable: ``_tick``'s
      ENERGY_CRITICAL branch always fires first, which restores exactly the
      pre-D-19 "only ever charge in an emergency" behaviour. **Not clamped** —
      it is a legitimate way to ask for emergency-only recharging and it
      strands nothing — but it is complained about, so it cannot be mistaken
      for the default.

    A non-finite or non-positive threshold falls back to the declared default
    rather than being clamped to something arbitrary.
    """
    try:
        value = float(threshold)
    except (TypeError, ValueError):
        value = float('nan')

    if value != value or value in (float('inf'), float('-inf')) or value <= 0.0:
        return 0.30, (
            f'recharge_threshold {threshold!r} is not a usable charge '
            f'fraction; falling back to 0.30.'
        )

    if value >= target:
        clamped = max(0.0, target - 0.05)
        return clamped, (
            f'recharge_threshold {value} is at or above '
            f'energy_recharge_target {target}, which makes a freshly-charged '
            f'robot immediately want to charge again — an IDLE/RETURNING/'
            f'RECHARGING busy loop at the tick rate. Clamped to {clamped}.'
        )

    if value <= critical:
        return value, (
            f'recharge_threshold {value} is at or below '
            f'energy_critical_threshold {critical}, so the floor is '
            f'unreachable: this robot will only ever recharge on the '
            f'ENERGY_CRITICAL path or when it runs out of margin to get home. '
            f'That is a valid emergency-only policy but it is almost certainly '
            f'not what was intended.'
        )

    return value, ''
