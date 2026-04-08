"""Unit tests for the FSM operator-override transitions.

Phase 5 / Wave 1 / Agent 2 — verifies the OPERATOR_CANCEL,
OPERATOR_GOTO, and OPERATOR_RECHARGE wildcard transitions added in
``selene_agent.fsm``. The transitions follow the same idiom as the
existing FAULT wildcard rule but with slightly different exclusion
sets:

  * OPERATOR_CANCEL — every state except OFFLINE → IDLE
                      (intentionally allowed from ERROR so the operator
                      can clear a fault and resume).
  * OPERATOR_GOTO — every state except OFFLINE and ERROR → NAVIGATING
  * OPERATOR_RECHARGE — every state except OFFLINE and ERROR → RECHARGING

The transition table is exposed via the module-private
``_TRANSITION_TABLE`` constant in ``selene_agent.fsm``; we read it
directly so the assertions stay independent of any future helper API.
"""
from __future__ import annotations

import os
import sys

import pytest

# Make the agent package importable when running pytest from /tmp.
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

from selene_agent.fsm import (  # noqa: E402
    AgentFSM,
    AgentState,
    FSMEvent,
    InvalidTransitionError,
    _TRANSITION_TABLE,
)


# --------------------------------------------------------------------------- #
#  OPERATOR_CANCEL coverage                                                     #
# --------------------------------------------------------------------------- #

class TestOperatorCancelTransitions:
    """OPERATOR_CANCEL must reach IDLE from every state except OFFLINE."""

    def test_all_non_offline_states_have_entry(self):
        for state in AgentState:
            if state == AgentState.OFFLINE:
                continue
            key = (state, FSMEvent.OPERATOR_CANCEL)
            assert key in _TRANSITION_TABLE, (
                f"OPERATOR_CANCEL missing transition from {state.value}"
            )
            assert _TRANSITION_TABLE[key] is AgentState.IDLE, (
                f"OPERATOR_CANCEL from {state.value} should land in IDLE"
            )

    def test_offline_has_no_entry(self):
        assert (AgentState.OFFLINE, FSMEvent.OPERATOR_CANCEL) \
            not in _TRANSITION_TABLE

    def test_offline_rejects_runtime(self):
        fsm = AgentFSM('shutdown_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.SHUTDOWN)
        assert fsm.state is AgentState.OFFLINE
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.OPERATOR_CANCEL)

    def test_error_state_allows_cancel(self):
        """ERROR → IDLE is the recovery path the operator can force."""
        fsm = AgentFSM('error_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.FAULT)
        assert fsm.state is AgentState.ERROR
        new = fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        assert new is AgentState.IDLE

    def test_idempotent_cancel_from_idle(self):
        """OPERATOR_CANCEL from IDLE keeps the FSM in IDLE."""
        fsm = AgentFSM('idle_bot', logger=lambda m: None)
        new1 = fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        new2 = fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        assert new1 is AgentState.IDLE
        assert new2 is AgentState.IDLE
        assert fsm.state is AgentState.IDLE

    def test_cancel_from_navigating_returns_to_idle(self):
        fsm = AgentFSM('nav_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        assert fsm.state is AgentState.NAVIGATING
        new = fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        assert new is AgentState.IDLE


# --------------------------------------------------------------------------- #
#  OPERATOR_GOTO coverage                                                       #
# --------------------------------------------------------------------------- #

class TestOperatorGotoTransitions:
    """OPERATOR_GOTO must reach NAVIGATING from every state except
    OFFLINE and ERROR."""

    def test_all_eligible_states_have_entry(self):
        excluded = {AgentState.OFFLINE, AgentState.ERROR}
        for state in AgentState:
            if state in excluded:
                continue
            key = (state, FSMEvent.OPERATOR_GOTO)
            assert key in _TRANSITION_TABLE, (
                f"OPERATOR_GOTO missing transition from {state.value}"
            )
            assert _TRANSITION_TABLE[key] is AgentState.NAVIGATING

    def test_offline_has_no_entry(self):
        assert (AgentState.OFFLINE, FSMEvent.OPERATOR_GOTO) \
            not in _TRANSITION_TABLE

    def test_error_has_no_entry(self):
        assert (AgentState.ERROR, FSMEvent.OPERATOR_GOTO) \
            not in _TRANSITION_TABLE

    def test_offline_rejects_runtime(self):
        fsm = AgentFSM('off_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.SHUTDOWN)
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.OPERATOR_GOTO)

    def test_error_rejects_runtime(self):
        fsm = AgentFSM('err_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.FAULT)
        assert fsm.state is AgentState.ERROR
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.OPERATOR_GOTO)

    def test_goto_from_idle(self):
        fsm = AgentFSM('idle_bot', logger=lambda m: None)
        new = fsm.handle_event(FSMEvent.OPERATOR_GOTO)
        assert new is AgentState.NAVIGATING

    def test_goto_from_working(self):
        fsm = AgentFSM('work_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        fsm.handle_event(FSMEvent.ARRIVED)
        assert fsm.state is AgentState.WORKING
        new = fsm.handle_event(FSMEvent.OPERATOR_GOTO)
        assert new is AgentState.NAVIGATING

    def test_goto_from_recharging(self):
        fsm = AgentFSM('rch_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        fsm.handle_event(FSMEvent.ARRIVED)
        fsm.handle_event(FSMEvent.TASK_COMPLETE)
        fsm.handle_event(FSMEvent.AT_BASE_NEED_CHARGE)
        assert fsm.state is AgentState.RECHARGING
        new = fsm.handle_event(FSMEvent.OPERATOR_GOTO)
        assert new is AgentState.NAVIGATING


# --------------------------------------------------------------------------- #
#  OPERATOR_RECHARGE coverage                                                   #
# --------------------------------------------------------------------------- #

class TestOperatorRechargeTransitions:
    """OPERATOR_RECHARGE must reach RECHARGING from every state except
    OFFLINE and ERROR."""

    def test_all_eligible_states_have_entry(self):
        excluded = {AgentState.OFFLINE, AgentState.ERROR}
        for state in AgentState:
            if state in excluded:
                continue
            key = (state, FSMEvent.OPERATOR_RECHARGE)
            assert key in _TRANSITION_TABLE, (
                f"OPERATOR_RECHARGE missing transition from {state.value}"
            )
            assert _TRANSITION_TABLE[key] is AgentState.RECHARGING

    def test_offline_has_no_entry(self):
        assert (AgentState.OFFLINE, FSMEvent.OPERATOR_RECHARGE) \
            not in _TRANSITION_TABLE

    def test_error_has_no_entry(self):
        assert (AgentState.ERROR, FSMEvent.OPERATOR_RECHARGE) \
            not in _TRANSITION_TABLE

    def test_offline_rejects_runtime(self):
        fsm = AgentFSM('off_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.SHUTDOWN)
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.OPERATOR_RECHARGE)

    def test_error_rejects_runtime(self):
        fsm = AgentFSM('err_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.FAULT)
        with pytest.raises(InvalidTransitionError):
            fsm.handle_event(FSMEvent.OPERATOR_RECHARGE)

    def test_recharge_from_idle(self):
        fsm = AgentFSM('idle_bot', logger=lambda m: None)
        new = fsm.handle_event(FSMEvent.OPERATOR_RECHARGE)
        assert new is AgentState.RECHARGING

    def test_recharge_from_working(self):
        fsm = AgentFSM('work_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        fsm.handle_event(FSMEvent.ARRIVED)
        new = fsm.handle_event(FSMEvent.OPERATOR_RECHARGE)
        assert new is AgentState.RECHARGING

    def test_recharge_from_navigating(self):
        fsm = AgentFSM('nav_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.WAYPOINT_ASSIGNED)
        new = fsm.handle_event(FSMEvent.OPERATOR_RECHARGE)
        assert new is AgentState.RECHARGING


# --------------------------------------------------------------------------- #
#  Cross-event invariants                                                       #
# --------------------------------------------------------------------------- #

class TestOperatorEventInvariants:

    def test_all_three_events_exist(self):
        # Verify the enum members made it onto FSMEvent at all.
        assert hasattr(FSMEvent, 'OPERATOR_CANCEL')
        assert hasattr(FSMEvent, 'OPERATOR_GOTO')
        assert hasattr(FSMEvent, 'OPERATOR_RECHARGE')
        assert FSMEvent.OPERATOR_CANCEL.value == 'OPERATOR_CANCEL'
        assert FSMEvent.OPERATOR_GOTO.value == 'OPERATOR_GOTO'
        assert FSMEvent.OPERATOR_RECHARGE.value == 'OPERATOR_RECHARGE'

    @pytest.mark.parametrize('event', [
        FSMEvent.OPERATOR_CANCEL,
        FSMEvent.OPERATOR_GOTO,
        FSMEvent.OPERATOR_RECHARGE,
    ])
    def test_offline_blocks_all_operator_events(self, event):
        assert (AgentState.OFFLINE, event) not in _TRANSITION_TABLE

    def test_dedupe_safety_idempotent_cancel(self):
        """Two cancels in a row from IDLE leave the FSM in IDLE."""
        fsm = AgentFSM('dup_bot', logger=lambda m: None)
        fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        fsm.handle_event(FSMEvent.OPERATOR_CANCEL)
        assert fsm.state is AgentState.IDLE

    def test_existing_fault_pattern_preserved(self):
        """Sanity check that we did not break the FAULT wildcard logic."""
        for state in AgentState:
            if state == AgentState.OFFLINE:
                continue
            key = (state, FSMEvent.FAULT)
            assert _TRANSITION_TABLE[key] is AgentState.ERROR
