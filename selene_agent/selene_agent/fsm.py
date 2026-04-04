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
    FAULT = "FAULT"
    RECOVERY = "RECOVERY"
    SHUTDOWN = "SHUTDOWN"


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

    # FAULT from any state except OFFLINE
    for state in AgentState:
        if state != AgentState.OFFLINE:
            table[(state, FSMEvent.FAULT)] = AgentState.ERROR

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
