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
    # the field. Fired in the same tick as the TASK_COMPLETE above it, so
    # RETURNING is never observed by the 2 Hz state publisher and the
    # orchestrator never sees a robot that is not actually returning.
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


class AgentFSM:
    """Event-driven finite state machine for a single lunar robot.

    Parameters
    ----------
    robot_id:
        Unique identifier for the robot this FSM belongs to.
    logger:
        Optional callable(str) for logging.  Defaults to ``print``.
    """

    def __init__(self, robot_id: str, logger: Optional[Callable[[str], None]] = None):
        self._robot_id = robot_id
        self._logger = logger if logger is not None else print
        self._state = AgentState.IDLE
        self._error_count = 0
        self._transition_log: list[dict] = []

    # -- Properties -----------------------------------------------------------

    @property
    def state(self) -> AgentState:
        """Current agent state."""
        return self._state

    # -- Public API -----------------------------------------------------------

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

        return new_state

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
