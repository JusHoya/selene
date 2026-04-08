"""Unit tests for ``operator_command_logic`` (AgentNode operator service).

These tests exercise the pure-Python decision tree behind the
per-robot ``/{robot_id}/set_command`` ROS 2 service. The helper lives
in ``selene_agent.operator_command`` (extracted from
``selene_agent.agent_node`` so it has zero ROS / selene_hal / skill
imports), which means we can drive every code path with plain
MagicMock spies — no rclpy, no real HAL, no skill instantiation.

Wave 1 Agent 1 used the same ``inject_task_logic`` /
``override_robot_logic`` context-dataclass pattern in
``selene_orchestrator/test/test_inject_task_handler.py``; this file
mirrors that idiom for the per-robot side.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# Make the agent package importable when running pytest from /tmp.
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

from selene_agent.operator_command import (  # noqa: E402
    operator_command_logic,
    _OperatorCommandContext,
    VALID_OPERATOR_COMMANDS,
)
from selene_agent.fsm import AgentState, FSMEvent  # noqa: E402


# --------------------------------------------------------------------------- #
#  Test fixtures                                                                #
# --------------------------------------------------------------------------- #

class _FakeRequest:
    def __init__(self, command='cancel_task', x=0.0, y=0.0, z=0.0, sequence=1):
        self.command = command
        self.target = types.SimpleNamespace(x=x, y=y, z=z)
        self.sequence = sequence


class _FakeResponse:
    def __init__(self):
        self.accepted = False
        self.reason = ''


class _AgentSpy:
    """Stand-in for the AgentNode mutable state used by the operator logic.

    Stores everything the helper reads or writes so individual tests can
    inspect/assert on it without dealing with ROS attribute aliases.
    """

    def __init__(self, state=AgentState.IDLE,
                 current_skill=None, current_task_id='',
                 pending_task_id='', last_seq=-1):
        self.state = state
        self.current_skill = current_skill
        self.current_task_id = current_task_id
        self.pending_task_id = pending_task_id
        self.last_seq = last_seq
        self.operator_target = None
        self.fired_events: list[FSMEvent] = []
        self.bid_publishes: list[tuple[str, str]] = []
        self.nav_starts: list[tuple[float, float]] = []
        self.recharge_calls = 0
        self.warn_logs: list[str] = []

    def fire_event(self, event):
        self.fired_events.append(event)
        # Mirror the FSM transition table for the events the helper fires.
        if event == FSMEvent.OPERATOR_CANCEL:
            self.state = AgentState.IDLE
        elif event == FSMEvent.OPERATOR_GOTO:
            self.state = AgentState.NAVIGATING
        elif event == FSMEvent.OPERATOR_RECHARGE:
            self.state = AgentState.RECHARGING

    def publish_bid_withdrawal(self, task_id, robot_id):
        self.bid_publishes.append((task_id, robot_id))

    def start_navigation(self, x, y):
        self.nav_starts.append((float(x), float(y)))

    def start_recharge(self):
        self.recharge_calls += 1

    def log_warn(self, msg):
        self.warn_logs.append(msg)


def _make_ctx(agent: _AgentSpy, robot_id='scout_01') -> _OperatorCommandContext:
    return _OperatorCommandContext(
        robot_id=robot_id,
        get_state=lambda: agent.state,
        fire_event=agent.fire_event,
        get_current_skill=lambda: agent.current_skill,
        set_current_skill=lambda s: setattr(agent, 'current_skill', s),
        set_current_task_id=lambda t: setattr(agent, 'current_task_id', t),
        get_pending_task_id=lambda: agent.pending_task_id,
        set_pending_task_id=lambda t: setattr(agent, 'pending_task_id', t),
        publish_bid_withdrawal=agent.publish_bid_withdrawal,
        start_navigation=agent.start_navigation,
        set_operator_target=lambda t: setattr(agent, 'operator_target', t),
        start_recharge=agent.start_recharge,
        get_last_seq=lambda: agent.last_seq,
        set_last_seq=lambda s: setattr(agent, 'last_seq', s),
        log_warn=agent.log_warn,
    )


def _make_skill(running=True):
    skill = MagicMock()
    skill.is_running.return_value = running
    skill.abort = MagicMock()
    return skill


# --------------------------------------------------------------------------- #
#  Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestOperatorCallbackDedupe:

    def test_dedupe_seq_returns_accepted(self):
        agent = _AgentSpy(last_seq=5)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=5)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is True
        assert out.reason == 'duplicate_sequence'
        # Helper must NOT touch any state on a duplicate.
        assert agent.fired_events == []
        assert agent.last_seq == 5

    def test_dedupe_lower_seq_rejected(self):
        agent = _AgentSpy(last_seq=10)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=3)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is True
        assert out.reason == 'duplicate_sequence'
        assert agent.fired_events == []

    def test_increments_last_operator_seq(self):
        agent = _AgentSpy(last_seq=-1)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=42)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        assert agent.last_seq == 42


class TestOperatorCallbackStateGuards:

    def test_offline_rejects_cancel(self):
        agent = _AgentSpy(state=AgentState.OFFLINE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is False
        assert 'OFFLINE' in out.reason
        assert agent.fired_events == []
        assert agent.last_seq == -1  # not bumped on rejection

    def test_offline_rejects_goto(self):
        agent = _AgentSpy(state=AgentState.OFFLINE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='send_to_location', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is False
        assert 'OFFLINE' in out.reason

    def test_offline_rejects_recharge(self):
        agent = _AgentSpy(state=AgentState.OFFLINE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='force_recharge', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is False
        assert 'OFFLINE' in out.reason

    def test_error_state_allows_cancel(self):
        agent = _AgentSpy(state=AgentState.ERROR,
                          current_skill=_make_skill(running=True))
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is True
        assert out.reason == ''
        # Cancel from ERROR must still tear down any leftover skill.
        assert FSMEvent.OPERATOR_CANCEL in agent.fired_events
        assert agent.current_skill is None
        assert agent.current_task_id == ''

    def test_error_state_rejects_goto(self):
        agent = _AgentSpy(state=AgentState.ERROR)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='send_to_location', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is False
        assert 'ERROR' in out.reason
        assert agent.fired_events == []

    def test_error_state_rejects_recharge(self):
        agent = _AgentSpy(state=AgentState.ERROR)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='force_recharge', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is False
        assert 'ERROR' in out.reason
        assert agent.fired_events == []


class TestOperatorCallbackCancel:

    def test_cancel_aborts_skill_and_clears_task(self):
        skill = _make_skill(running=True)
        agent = _AgentSpy(state=AgentState.WORKING, current_skill=skill,
                          current_task_id='manual_0001')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        skill.abort.assert_called_once()
        assert agent.current_skill is None
        assert agent.current_task_id == ''
        assert FSMEvent.OPERATOR_CANCEL in agent.fired_events
        assert agent.last_seq == 1

    def test_cancel_when_no_skill_running(self):
        agent = _AgentSpy(state=AgentState.IDLE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)
        assert out.accepted is True
        assert FSMEvent.OPERATOR_CANCEL in agent.fired_events

    def test_cancel_does_not_abort_already_finished_skill(self):
        skill = _make_skill(running=False)
        agent = _AgentSpy(state=AgentState.IDLE, current_skill=skill)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        skill.abort.assert_not_called()
        assert agent.current_skill is None


class TestOperatorCallbackSendToLocation:

    def test_send_to_location_starts_navigation(self):
        agent = _AgentSpy(state=AgentState.IDLE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='send_to_location', x=12.5, y=-30.0,
                           sequence=7)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        assert out.reason == ''
        assert agent.operator_target == (12.5, -30.0)
        assert agent.nav_starts == [(12.5, -30.0)]
        assert agent.current_task_id == 'override_goto_7'
        assert agent.current_task_id.startswith('override_goto_')
        assert FSMEvent.OPERATOR_GOTO in agent.fired_events
        assert agent.last_seq == 7

    def test_send_to_location_aborts_existing_skill(self):
        skill = _make_skill(running=True)
        agent = _AgentSpy(state=AgentState.WORKING, current_skill=skill,
                          current_task_id='auto_0001')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='send_to_location', x=1.0, y=2.0,
                           sequence=2)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        skill.abort.assert_called_once()
        assert agent.current_skill is None
        assert agent.current_task_id == 'override_goto_2'


class TestOperatorCallbackForceRecharge:

    def test_force_recharge_calls_start_recharge(self):
        agent = _AgentSpy(state=AgentState.WORKING)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='force_recharge', sequence=3)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        assert agent.recharge_calls == 1
        assert FSMEvent.OPERATOR_RECHARGE in agent.fired_events
        assert agent.last_seq == 3

    def test_force_recharge_aborts_skill(self):
        skill = _make_skill(running=True)
        agent = _AgentSpy(state=AgentState.WORKING, current_skill=skill,
                          current_task_id='manual_0001')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='force_recharge', sequence=1)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        skill.abort.assert_called_once()
        # The recharge skill is started AFTER the abort + clear cycle so
        # the helper leaves current_skill at None and start_recharge is
        # responsible for assigning the new skill.
        assert agent.recharge_calls == 1


class TestOperatorCallbackBidding:

    def test_bidding_state_withdraws_bid(self):
        agent = _AgentSpy(state=AgentState.BIDDING,
                          pending_task_id='auto_0042')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        assert agent.bid_publishes == [('auto_0042', 'scout_01')]
        # The pending bid id must be cleared so we don't double-withdraw.
        assert agent.pending_task_id == ''
        assert FSMEvent.OPERATOR_CANCEL in agent.fired_events

    def test_bidding_state_no_pending_id_no_publish(self):
        agent = _AgentSpy(state=AgentState.BIDDING, pending_task_id='')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        assert agent.bid_publishes == []
        assert FSMEvent.OPERATOR_CANCEL in agent.fired_events

    def test_bidding_force_recharge_withdraws_then_recharges(self):
        agent = _AgentSpy(state=AgentState.BIDDING,
                          pending_task_id='auto_0007')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='force_recharge', sequence=4)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is True
        assert agent.bid_publishes == [('auto_0007', 'scout_01')]
        assert agent.recharge_calls == 1
        assert FSMEvent.OPERATOR_RECHARGE in agent.fired_events


class TestOperatorCallbackUnknownCommand:

    def test_unknown_command(self):
        agent = _AgentSpy(state=AgentState.IDLE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='self_destruct', sequence=1)
        resp = _FakeResponse()
        out = operator_command_logic(ctx, req, resp)

        assert out.accepted is False
        assert 'self_destruct' in out.reason
        assert agent.fired_events == []
        # Sequence counter must NOT advance on rejection.
        assert agent.last_seq == -1

    def test_unknown_command_does_not_abort_skill(self):
        skill = _make_skill(running=True)
        agent = _AgentSpy(state=AgentState.WORKING, current_skill=skill,
                          current_task_id='auto_0001')
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='garbage', sequence=2)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        skill.abort.assert_not_called()
        assert agent.current_task_id == 'auto_0001'


class TestOperatorCallbackInvariants:

    def test_valid_commands_constant(self):
        assert set(VALID_OPERATOR_COMMANDS) == {
            'cancel_task', 'send_to_location', 'force_recharge',
        }

    def test_log_warn_called_on_accepted_path(self):
        agent = _AgentSpy(state=AgentState.IDLE)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=1)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        assert any('Operator command' in m for m in agent.warn_logs)

    def test_no_log_on_dedupe(self):
        agent = _AgentSpy(state=AgentState.IDLE, last_seq=10)
        ctx = _make_ctx(agent)
        req = _FakeRequest(command='cancel_task', sequence=10)
        resp = _FakeResponse()
        operator_command_logic(ctx, req, resp)
        assert agent.warn_logs == []
