"""Event-driven finite state machine for SELENE agent autonomy.

Pure Python -- zero ROS dependencies. Manages the lifecycle of a single
lunar surface robot through states from IDLE through task execution,
recharging, and error handling.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable, Optional


class AgentState(str, Enum):
    """Robot lifecycle states (str-based for RobotState.msg compatibility)."""

    IDLE = "IDLE"
    BIDDING = "BIDDING"
    ASSIGNED = "ASSIGNED"
    NAVIGATING = "NAVIGATING"
    WORKING = "WORKING"
    RETURNING = "RETURNING"
    RECHARGING = "RECHARGING"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class FSMEvent(str, Enum):
    """Events that drive state transitions."""

    TASK_ANNOUNCED = "TASK_ANNOUNCED"
    AUCTION_WON = "AUCTION_WON"
    AUCTION_LOST = "AUCTION_LOST"
    WAYPOINT_ASSIGNED = "WAYPOINT_ASSIGNED"
    ARRIVED = "ARRIVED"
    TASK_COMPLETE = "TASK_COMPLETE"
    HOPPER_FULL = "HOPPER_FULL"
    AT_BASE_NEED_CHARGE = "AT_BASE_NEED_CHARGE"
    AT_BASE_CHARGED = "AT_BASE_CHARGED"
    CHARGE_COMPLETE = "CHARGE_COMPLETE"
    ENERGY_CRITICAL = "ENERGY_CRITICAL"
    # ---- The recharge DECISION, added 2026-07-31 closing D-19. ----
    #
    # Before these two the agent had no decision to make: every task ended
    # with TASK_COMPLETE followed by an unconditional _start_recharge(), so
    # RETURNING always meant "going home to charge" and there was no event
    # that could mean anything else.
    #
    # RECHARGE_NEEDED is deliberately NOT ENERGY_CRITICAL. Reusing that name
    # for "below the 30% floor" would make the transition log say a robot at
    # 29% hit an emergency it did not hit, and ENERGY_CRITICAL is the one
    # event whose meaning is pinned to EnergyManager.is_critical().
    RECHARGE_NEEDED = "RECHARGE_NEEDED"
    RECHARGE_NOT_NEEDED = "RECHARGE_NOT_NEEDED"
    FAULT = "FAULT"
    RECOVERY = "RECOVERY"
    SHUTDOWN = "SHUTDOWN"
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    OPERATOR_GOTO = "OPERATOR_GOTO"
    OPERATOR_RECHARGE = "OPERATOR_RECHARGE"


class InvalidTransitionError(Exception):
    """Raised when an event is not valid for the current state."""


# ---- Transition table -------------------------------------------------------
# Key: (from_state, event) -> to_state
# Wildcard entries are expanded at class init time.

_EXPLICIT_TRANSITIONS: dict[tuple[AgentState, FSMEvent], AgentState] = {
    (AgentState.IDLE, FSMEvent.WAYPOINT_ASSIGNED): AgentState.NAVIGATING,
    (AgentState.IDLE, FSMEvent.TASK_ANNOUNCED): AgentState.BIDDING,
    (AgentState.BIDDING, FSMEvent.AUCTION_WON): AgentState.ASSIGNED,
    (AgentState.BIDDING, FSMEvent.AUCTION_LOST): AgentState.IDLE,
    (AgentState.ASSIGNED, FSMEvent.WAYPOINT_ASSIGNED): AgentState.NAVIGATING,
    (AgentState.NAVIGATING, FSMEvent.ARRIVED): AgentState.WORKING,
    (AgentState.WORKING, FSMEvent.TASK_COMPLETE): AgentState.RETURNING,
    (AgentState.WORKING, FSMEvent.HOPPER_FULL): AgentState.RETURNING,
    (AgentState.RETURNING, FSMEvent.AT_BASE_NEED_CHARGE): AgentState.RECHARGING,
    (AgentState.RETURNING, FSMEvent.AT_BASE_CHARGED): AgentState.IDLE,
    # D-19. The robot finished a task, does NOT need to charge, and stays in
    # the field. Fired in the same tick as the TASK_COMPLETE above it.
    #
    # THIS COMMENT USED TO SAY "so RETURNING is never observed by the 2 Hz
    # state publisher and the orchestrator never sees a robot that is not
    # actually returning". That is no longer true and was never a good thing to
    # rely on. Since D-34, ``AgentNode`` publishes a ``RobotState`` from
    # ``on_transition`` as well as from its 0.5 s timer, so BOTH edges are on
    # the wire: a RETURNING sample and, microseconds later, an IDLE one. The
    # design that depended on the aliasing is unchanged and still correct --
    # the robot really is in RETURNING for that interval, and saying so out
    # loud is more honest than a state no consumer could see. What changed is
    # that a consumer must now treat RETURNING as possibly transient rather
    # than as "this robot is driving home"; the durable signal for that is a
    # RETURNING sample that is still there on the next 2 Hz tick.
    #
    # RETURNING -> IDLE rather than a second WORKING -> IDLE event: the
    # WORKING/TASK_COMPLETE cell is already taken, and a parallel event out of
    # WORKING would give one concept two names. AT_BASE_CHARGED above is the
    # nearest existing transition and was NOT reused -- it has no production
    # caller at all (grep: fsm.py and one test), and it asserts the robot is
    # at base, which is precisely what this event denies.
    (AgentState.RETURNING, FSMEvent.RECHARGE_NOT_NEEDED): AgentState.IDLE,
    (AgentState.RECHARGING, FSMEvent.CHARGE_COMPLETE): AgentState.IDLE,
    (AgentState.ERROR, FSMEvent.RECOVERY): AgentState.IDLE,
}


def _build_full_table() -> dict[tuple[AgentState, FSMEvent], AgentState]:
    """Expand wildcard rules into the complete transition table."""
    table = dict(_EXPLICIT_TRANSITIONS)

    # ENERGY_CRITICAL from any state except OFFLINE and RECHARGING
    for state in AgentState:
        if state not in (AgentState.OFFLINE, AgentState.RECHARGING):
            table[(state, FSMEvent.ENERGY_CRITICAL)] = AgentState.RETURNING

    # RECHARGE_NEEDED from any state that is not already going or gone.
    #
    # Excludes RETURNING (already on its way), RECHARGING (already there),
    # OFFLINE, and ERROR -- the last for the same reason OPERATOR_RECHARGE
    # excludes it: a faulted robot must not be given a navigation goal, and
    # FSMEvent.RECOVERY is the only way out of ERROR.
    for state in AgentState:
        if state not in (AgentState.OFFLINE, AgentState.RECHARGING,
                         AgentState.RETURNING, AgentState.ERROR):
            table[(state, FSMEvent.RECHARGE_NEEDED)] = AgentState.RETURNING

    # FAULT from any state except OFFLINE
    for state in AgentState:
        if state != AgentState.OFFLINE:
            table[(state, FSMEvent.FAULT)] = AgentState.ERROR

    # OPERATOR_CANCEL from any state except OFFLINE
    # (allowed from ERROR so the operator can clear errors back to IDLE)
    for state in AgentState:
        if state != AgentState.OFFLINE:
            table[(state, FSMEvent.OPERATOR_CANCEL)] = AgentState.IDLE

    # OPERATOR_GOTO from any state except OFFLINE and ERROR
    # (cannot navigate a faulted robot)
    for state in AgentState:
        if state not in (AgentState.OFFLINE, AgentState.ERROR):
            table[(state, FSMEvent.OPERATOR_GOTO)] = AgentState.NAVIGATING

    # OPERATOR_RECHARGE from any state except OFFLINE and ERROR
    # (cannot recharge a faulted robot)
    for state in AgentState:
        if state not in (AgentState.OFFLINE, AgentState.ERROR):
            table[(state, FSMEvent.OPERATOR_RECHARGE)] = AgentState.RECHARGING

    # SHUTDOWN from any state
    for state in AgentState:
        table[(state, FSMEvent.SHUTDOWN)] = AgentState.OFFLINE

    return table


_TRANSITION_TABLE: dict[tuple[AgentState, FSMEvent], AgentState] = _build_full_table()

# Maximum consecutive faults before escalation warning
_FAULT_ESCALATION_THRESHOLD = 3


#: Signature of the transition observer: ``(prev_state, event, new_state)``.
TransitionObserver = Callable[[AgentState, FSMEvent, AgentState], None]


class AgentFSM:
    """Event-driven finite state machine for a single lunar robot.

    Parameters
    ----------
    robot_id:
        Unique identifier for the robot this FSM belongs to.
    logger:
        Optional callable(str) for logging.  Defaults to ``print``.
    on_transition:
        Optional ``callable(prev_state, event, new_state)`` invoked once per
        successful transition.  See :meth:`set_transition_observer` for the
        contract; passing it here and setting it later are equivalent, and
        the setter exists because the production caller cannot supply it at
        construction time.

        NO PRODUCTION CALLER USES THIS PARAMETER, and that is not an
        oversight -- it is the direct consequence of the sentence above.
        ``AgentNode`` wires the observer through
        :meth:`set_transition_observer` (agent_node.py:266), after
        ``self._state_pub`` exists, and
        ``test_agent_state_publish_wiring.py`` actively FORBIDS it from
        using this argument. Recorded here because a grep for orphaned
        surfaces will find this parameter with one test-only caller, and
        this repository has been bitten five times by exactly that shape;
        the answer is that it is an optional convenience for a caller that
        can supply the observer up front, not a mission parameter that is
        silently doing nothing.
    """

    def __init__(self, robot_id: str, logger: Optional[Callable[[str], None]] = None,
                 on_transition: Optional[TransitionObserver] = None):
        self._robot_id = robot_id
        self._logger = logger if logger is not None else print
        self._state = AgentState.IDLE
        self._error_count = 0
        self._transition_log: list[dict] = []
        self._on_transition: Optional[TransitionObserver] = on_transition
        # See _notify_transition for exactly what this guards -- it is NOT a
        # lock and it is NOT thread safety.
        self._notifying = False

    # -- Properties -----------------------------------------------------------

    @property
    def state(self) -> AgentState:
        """Current agent state."""
        return self._state

    # -- Public API -----------------------------------------------------------

    def set_transition_observer(
        self, callback: Optional[TransitionObserver],
    ) -> None:
        """Install (or clear, with ``None``) the per-transition observer.

        WHY A SETTER AND NOT JUST THE CONSTRUCTOR ARGUMENT. ``AgentNode``
        builds its FSM at ``agent_node.py:210`` but does not create
        ``self._state_pub`` until ``:248`` and does not set
        ``self._current_skill`` / ``self._current_task_id`` until ``:222-223``
        -- all of which the observer reads. Wiring at construction makes
        ``AgentNode.__init__`` order-sensitive: any transition fired between
        those lines would raise ``AttributeError`` out of a constructor. The
        setter lets the node attach the observer only once everything the
        callback touches exists, which it does at ``agent_node.py:266``,
        immediately below the publisher. (The node's callback is defensive too;
        belt and braces, because this is the exact shape of failure the
        constructor ordering would produce and it would surface at runtime,
        not in a test.)

        CONTRACT FOR THE CALLBACK:

        * it is called AFTER ``self._state``, the transition log and the log
          line are all updated, so ``fsm.state is new_state`` when it runs;
        * it is NOT called when the transition is rejected -- an
          ``InvalidTransitionError`` propagates with no notification;
        * it MUST NOT raise. One that does is caught and logged here rather
          than allowed to escape, because ``handle_event`` is called from
          timer and DDS callbacks and an exception there kills the node;
        * it SHOULD NOT fire further events. One that does still transitions
          the FSM, but emits no nested notification (see
          ``_notify_transition``).
        """
        self._on_transition = callback

    def handle_event(self, event: FSMEvent, **context) -> AgentState:
        """Process *event* and transition if the move is legal.

        Parameters
        ----------
        event:
            The FSMEvent to handle.
        **context:
            Arbitrary metadata attached to the transition log entry.

        Returns
        -------
        AgentState
            The state after the transition.

        Raises
        ------
        InvalidTransitionError
            If no transition exists for ``(current_state, event)``.
        """
        key = (self._state, event)
        if key not in _TRANSITION_TABLE:
            raise InvalidTransitionError(
                f"[{self._robot_id}] No transition from {self._state.value} "
                f"on event {event.value}"
            )

        prev_state = self._state
        new_state = _TRANSITION_TABLE[key]

        # Track error count
        if event is FSMEvent.FAULT:
            self._error_count += 1
            if self._error_count >= _FAULT_ESCALATION_THRESHOLD:
                self._logger(
                    f"[{self._robot_id}] ESCALATION: {self._error_count} "
                    f"consecutive FAULTs without RECOVERY"
                )
        elif event is FSMEvent.RECOVERY:
            self._error_count = 0

        self._state = new_state

        # Build log entry
        ts = time.time()
        entry = {
            "timestamp": ts,
            "from_state": prev_state,
            "event": event,
            "to_state": new_state,
            "robot_id": self._robot_id,
        }
        if context:
            entry["context"] = context
        self._transition_log.append(entry)

        self._logger(
            f"[{self._robot_id}] {prev_state.value} --({event.value})--> "
            f"{new_state.value}"
        )

        # LAST, deliberately: everything the observer can read is already
        # settled, so a publisher hanging off this hook reports the state the
        # FSM is actually in and the transition log it can actually see.
        self._notify_transition(prev_state, event, new_state)

        return new_state

    # -- Internals ------------------------------------------------------------

    def _notify_transition(self, prev_state: AgentState, event: FSMEvent,
                           new_state: AgentState) -> None:
        """Call the transition observer, swallowing anything it throws.

        WHAT ``_notifying`` GUARDS, STATED HONESTLY. It is a LOGICAL
        re-entrancy guard and nothing more: it stops an observer that itself
        fires an event from producing a nested notification (and, with a
        careless observer, unbounded recursion). The nested ``handle_event``
        still transitions normally -- the FSM is not frozen, only the
        notification is suppressed -- so the observer sees the first edge of
        such a chain and not the ones it caused.

        IT IS NOT THREAD SAFETY, and must not be read as any. ``main()`` calls
        ``rclpy.spin(node)`` (``agent_node.py:1390``), i.e. a
        SingleThreadedExecutor, and there is not one ``callback_group=``
        argument anywhere in ``agent_node.py``, so every timer, subscription
        and service on the agent runs in the node's default
        MutuallyExclusiveCallbackGroup and cannot overlap. A plain boolean is
        sufficient exactly while that stays true. **If the agent ever gains a
        MultiThreadedExecutor or a second callback group, this needs a real
        lock and this paragraph is the trigger to add one.**

        The try/except is not defensive decoration. ``handle_event`` is called
        from timer callbacks, DDS subscription callbacks and a service
        handler; an exception escaping any of those takes the node down, and a
        state publisher failing to serialise is not a reason to stop a robot's
        FSM. The failure is logged, not hidden.
        """
        callback = self._on_transition
        if callback is None or self._notifying:
            return

        self._notifying = True
        try:
            callback(prev_state, event, new_state)
        except Exception as exc:  # noqa: BLE001 - see docstring
            self._logger(
                f"[{self._robot_id}] transition observer raised on "
                f"{prev_state.value} --({event.value})--> {new_state.value}: "
                f"{exc!r}"
            )
        finally:
            self._notifying = False

    def get_transition_log(self) -> list[dict]:
        """Return a copy of the full transition history."""
        return list(self._transition_log)

    def get_error_count(self) -> int:
        """Number of consecutive FAULTs since last RECOVERY or reset."""
        return self._error_count

    def reset(self) -> None:
        """Reset FSM to IDLE and clear error tracking."""
        self._state = AgentState.IDLE
        self._error_count = 0
