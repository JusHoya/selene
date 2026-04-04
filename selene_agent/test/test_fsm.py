"""Comprehensive tests for the SELENE agent finite state machine."""

import pytest

from selene_agent.fsm import AgentFSM, AgentState, FSMEvent, InvalidTransitionError


@pytest.fixture
def fsm():
    """Fresh FSM with a no-op logger."""
    return AgentFSM("test_bot", logger=lambda msg: None)


# ---- Initial state ----------------------------------------------------------

def test_initial_state_is_idle(fsm):
    assert fsm.state is AgentState.IDLE


# ---- Normal task lifecycle (Phase 2 -- direct waypoint) ----------------------

def test_waypoint_assigned_transitions_to_navigating(fsm):
    new = fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    assert new is AgentState.NAVIGATING
    assert fsm.state is AgentState.NAVIGATING


def test_arrived_transitions_to_working(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    new = fsm.handle_event(FSMEvent.ARRIVED)
    assert new is AgentState.WORKING


def test_task_complete_transitions_to_returning(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    new = fsm.handle_event(FSMEvent.TASK_COMPLETE)
    assert new is AgentState.RETURNING


def test_at_base_need_charge_transitions_to_recharging(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    fsm.handle_event(FSMEvent.TASK_COMPLETE)
    new = fsm.handle_event(FSMEvent.AT_BASE_NEED_CHARGE)
    assert new is AgentState.RECHARGING


def test_at_base_charged_transitions_to_idle(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    fsm.handle_event(FSMEvent.TASK_COMPLETE)
    new = fsm.handle_event(FSMEvent.AT_BASE_CHARGED)
    assert new is AgentState.IDLE


def test_charge_complete_transitions_to_idle(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    fsm.handle_event(FSMEvent.TASK_COMPLETE)
    fsm.handle_event(FSMEvent.AT_BASE_NEED_CHARGE)
    new = fsm.handle_event(FSMEvent.CHARGE_COMPLETE)
    assert new is AgentState.IDLE


# ---- ENERGY_CRITICAL overrides -----------------------------------------------

def test_energy_critical_from_navigating(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    assert fsm.state is AgentState.NAVIGATING
    new = fsm.handle_event(FSMEvent.ENERGY_CRITICAL)
    assert new is AgentState.RETURNING


def test_energy_critical_from_working(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    assert fsm.state is AgentState.WORKING
    new = fsm.handle_event(FSMEvent.ENERGY_CRITICAL)
    assert new is AgentState.RETURNING


def test_energy_critical_from_idle(fsm):
    new = fsm.handle_event(FSMEvent.ENERGY_CRITICAL)
    assert new is AgentState.RETURNING


def test_energy_critical_not_from_recharging(fsm):
    # Drive into RECHARGING state
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    fsm.handle_event(FSMEvent.TASK_COMPLETE)
    fsm.handle_event(FSMEvent.AT_BASE_NEED_CHARGE)
    assert fsm.state is AgentState.RECHARGING
    with pytest.raises(InvalidTransitionError):
        fsm.handle_event(FSMEvent.ENERGY_CRITICAL)


def test_energy_critical_not_from_offline(fsm):
    fsm.handle_event(FSMEvent.SHUTDOWN)
    assert fsm.state is AgentState.OFFLINE
    with pytest.raises(InvalidTransitionError):
        fsm.handle_event(FSMEvent.ENERGY_CRITICAL)


# ---- FAULT / RECOVERY -------------------------------------------------------

def test_fault_from_any_state(fsm):
    # FAULT should work from every state except OFFLINE
    non_offline_states = [s for s in AgentState if s is not AgentState.OFFLINE]
    for target_state in non_offline_states:
        local_fsm = AgentFSM("fault_test", logger=lambda m: None)
        _drive_to_state(local_fsm, target_state)
        new = local_fsm.handle_event(FSMEvent.FAULT)
        assert new is AgentState.ERROR, (
            f"FAULT from {target_state.value} should go to ERROR"
        )


def test_recovery_from_error(fsm):
    fsm.handle_event(FSMEvent.FAULT)
    assert fsm.state is AgentState.ERROR
    new = fsm.handle_event(FSMEvent.RECOVERY)
    assert new is AgentState.IDLE


# ---- SHUTDOWN ----------------------------------------------------------------

def test_shutdown_from_any_state(fsm):
    for target_state in AgentState:
        local_fsm = AgentFSM("shutdown_test", logger=lambda m: None)
        _drive_to_state(local_fsm, target_state)
        new = local_fsm.handle_event(FSMEvent.SHUTDOWN)
        assert new is AgentState.OFFLINE, (
            f"SHUTDOWN from {target_state.value} should go to OFFLINE"
        )


# ---- Invalid transitions ----------------------------------------------------

def test_invalid_transition_raises_error(fsm):
    # ARRIVED from IDLE makes no sense
    with pytest.raises(InvalidTransitionError):
        fsm.handle_event(FSMEvent.ARRIVED)


# ---- Transition log ---------------------------------------------------------

def test_transition_log_records_all(fsm):
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    fsm.handle_event(FSMEvent.ARRIVED)
    log = fsm.get_transition_log()
    assert len(log) == 2
    entry = log[0]
    assert entry["from_state"] is AgentState.IDLE
    assert entry["event"] is FSMEvent.WAYPOINT_ASSIGNED
    assert entry["to_state"] is AgentState.NAVIGATING
    assert entry["robot_id"] == "test_bot"
    assert "timestamp" in entry


# ---- Error count & escalation -----------------------------------------------

def test_error_count_increments(fsm):
    assert fsm.get_error_count() == 0
    fsm.handle_event(FSMEvent.FAULT)
    assert fsm.get_error_count() == 1
    fsm.handle_event(FSMEvent.RECOVERY)
    assert fsm.get_error_count() == 0


def test_error_escalation_after_3_faults(fsm):
    warnings: list[str] = []

    def capture(msg: str):
        if "ESCALATION" in msg:
            warnings.append(msg)

    local_fsm = AgentFSM("esc_bot", logger=capture)
    for _ in range(3):
        local_fsm.handle_event(FSMEvent.FAULT)
        local_fsm.handle_event(FSMEvent.RECOVERY)
        local_fsm.handle_event(FSMEvent.FAULT)

    # Each cycle: FAULT(+1), RECOVERY(reset), FAULT(+1) -- never reaches 3 in
    # a row.  So drive 3 consecutive faults:
    local_fsm2 = AgentFSM("esc_bot2", logger=capture)
    # Need 3 consecutive faults.  After the first FAULT we're in ERROR;
    # another FAULT from ERROR goes to ERROR again (table allows it).
    local_fsm2.handle_event(FSMEvent.FAULT)  # count=1
    local_fsm2.handle_event(FSMEvent.FAULT)  # count=2, ERROR->ERROR
    local_fsm2.handle_event(FSMEvent.FAULT)  # count=3 -> escalation
    assert local_fsm2.get_error_count() >= 3
    assert len(warnings) >= 1


# ---- Phase 3 bidding flow ---------------------------------------------------

def test_bidding_flow(fsm):
    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
    assert fsm.state is AgentState.BIDDING
    fsm.handle_event(FSMEvent.AUCTION_WON)
    assert fsm.state is AgentState.ASSIGNED
    fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
    assert fsm.state is AgentState.NAVIGATING


def test_auction_lost(fsm):
    fsm.handle_event(FSMEvent.TASK_ANNOUNCED)
    assert fsm.state is AgentState.BIDDING
    new = fsm.handle_event(FSMEvent.AUCTION_LOST)
    assert new is AgentState.IDLE


# ---- ENERGY_CRITICAL from ERROR overrides ------------------------------------

def test_energy_critical_overrides_error_state(fsm):
    """ENERGY_CRITICAL should take precedence even in ERROR state."""
    fsm.handle_event(FSMEvent.FAULT)
    assert fsm.state is AgentState.ERROR
    new = fsm.handle_event(FSMEvent.ENERGY_CRITICAL)
    assert new is AgentState.RETURNING


# ---- Reset -------------------------------------------------------------------

def test_reset_clears_state_and_errors(fsm):
    fsm.handle_event(FSMEvent.FAULT)
    fsm.handle_event(FSMEvent.FAULT)
    assert fsm.state is AgentState.ERROR
    assert fsm.get_error_count() == 2
    fsm.reset()
    assert fsm.state is AgentState.IDLE
    assert fsm.get_error_count() == 0


# ---- Helpers -----------------------------------------------------------------

def _drive_to_state(fsm: AgentFSM, target: AgentState) -> None:
    """Drive *fsm* into *target* state via the shortest valid path."""
    if fsm.state is target:
        return

    routes = {
        AgentState.IDLE: [],
        AgentState.BIDDING: [FSMEvent.TASK_ANNOUNCED],
        AgentState.ASSIGNED: [FSMEvent.TASK_ANNOUNCED, FSMEvent.AUCTION_WON],
        AgentState.NAVIGATING: [FSMEvent.WAYPOINT_ASSIGNED],
        AgentState.WORKING: [FSMEvent.WAYPOINT_ASSIGNED, FSMEvent.ARRIVED],
        AgentState.RETURNING: [
            FSMEvent.WAYPOINT_ASSIGNED,
            FSMEvent.ARRIVED,
            FSMEvent.TASK_COMPLETE,
        ],
        AgentState.RECHARGING: [
            FSMEvent.WAYPOINT_ASSIGNED,
            FSMEvent.ARRIVED,
            FSMEvent.TASK_COMPLETE,
            FSMEvent.AT_BASE_NEED_CHARGE,
        ],
        AgentState.ERROR: [FSMEvent.FAULT],
        AgentState.OFFLINE: [FSMEvent.SHUTDOWN],
    }
    for event in routes[target]:
        fsm.handle_event(event)
