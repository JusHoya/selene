"""Unit tests for ``override_robot_logic`` (OrchestratorNode operator service).

Relies on the scoped ROS 2 stubs installed by ``test/conftest.py`` (same
arrangement as ``test_inject_task_handler.py``) so the test runs under
plain ``pytest`` without a built ROS workspace, and under ``colcon test``
against the real ROS modules.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
#  ROS 2 stubs + sys.path setup live in test/conftest.py so they are           #
#  installed exactly once, only for modules that are really missing, and       #
#  torn down at session end (no cross-package sys.modules pollution).          #
# --------------------------------------------------------------------------- #

from selene_orchestrator.orchestrator_node import (  # noqa: E402
    override_robot_logic,
    _OverrideRobotContext,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus  # noqa: E402


# --------------------------------------------------------------------------- #
#  Helpers                                                                      #
# --------------------------------------------------------------------------- #

class _FakeOverrideRequest:
    def __init__(self, robot_id='scout_01', command='cancel_task',
                 x=0.0, y=0.0):
        self.robot_id = robot_id
        self.command = command
        self.target = types.SimpleNamespace(x=x, y=y, z=0.0)


class _FakeOverrideResponse:
    def __init__(self):
        self.success = False
        self.message = ''


class _FakeSetRobotCommandRequest:
    def __init__(self):
        self.command = ''
        self.target = None
        self.sequence = 0


class _FakeAgentResponse:
    def __init__(self, accepted=True, reason=''):
        self.accepted = accepted
        self.reason = reason


class _FakeFuture:
    """Immediately-completed future wrapping a mock agent response."""
    def __init__(self, result):
        self._result = result
        self._done = True

    def done(self):
        return self._done

    def result(self):
        return self._result


class _TimeoutFuture:
    """Future that never completes — forces the timeout branch."""
    def done(self):
        return False

    def result(self):
        return None


def _make_client(agent_response=None, service_ready=True, timeout=False):
    """Build a MagicMock matching the rclpy client interface."""
    client = MagicMock()
    client.wait_for_service.return_value = service_ready
    if timeout:
        client.call_async.return_value = _TimeoutFuture()
    else:
        resp = agent_response or _FakeAgentResponse(accepted=True)
        client.call_async.return_value = _FakeFuture(resp)
    return client


def _add_robot(fm, robot_id, fsm_state='IDLE', current_task_id='',
               capabilities=None):
    fm._robots[robot_id] = {
        'robot_id': robot_id,
        'fsm_state': fsm_state,
        'current_task_id': current_task_id,
        'capabilities': list(capabilities or []),
        'battery_level': 0.9,
        'pose': (0.0, 0.0, 0.0),
    }


# --------------------------------------------------------------------------- #
#  Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def task_queue():
    return TaskQueue()


@pytest.fixture
def fleet_monitor():
    fm = MagicMock()
    fm._robots = {}

    def _get(rid):
        return fm._robots.get(rid)
    fm.get_robot.side_effect = _get
    return fm


@pytest.fixture
def publish_alert():
    return MagicMock()


def _build_ctx(task_queue, fleet_monitor, clients, publish_alert,
               sequence_start=0):
    seq = {'n': sequence_start}

    def _next_seq():
        seq['n'] += 1
        return seq['n']

    return _OverrideRobotContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        set_command_clients=clients,
        next_sequence=_next_seq,
        spin_until_complete=lambda fut: None,
        publish_alert=publish_alert,
        set_command_factory=_FakeSetRobotCommandRequest,
    )


# --------------------------------------------------------------------------- #
#  Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestOverrideRobotHandler:

    def test_override_unknown_robot(self, task_queue, fleet_monitor,
                                    publish_alert):
        ctx = _build_ctx(task_queue, fleet_monitor, {}, publish_alert)
        req = _FakeOverrideRequest(robot_id='ghost_99', command='cancel_task')
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'unknown' in out.message
        # Alert is published on failure too, so the operator sees the message.
        publish_alert.assert_called()

    def test_override_error_state_rejects_non_exempt_command(
            self, task_queue, fleet_monitor, publish_alert):
        # ERROR is in OVERRIDE_BLOCKED_STATES, and send_to_location is not
        # in OVERRIDE_BLOCKED_STATE_EXEMPT_COMMANDS, so it is rejected.
        _add_robot(fleet_monitor, 'scout_01', fsm_state='ERROR')
        clients = {'scout_01': _make_client()}
        ctx = _build_ctx(task_queue, fleet_monitor, clients, publish_alert)

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='send_to_location', x=5.0, y=5.0,
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'ERROR' in out.message
        # Agent client should NOT have been invoked when the robot is rejected.
        clients['scout_01'].call_async.assert_not_called()

    def test_override_error_state_allows_cancel_task(
            self, task_queue, fleet_monitor, publish_alert):
        """cancel_task is the operator's escape hatch out of ERROR.

        ``cancel_task`` is listed in
        ``OVERRIDE_BLOCKED_STATE_EXEMPT_COMMANDS`` precisely so a faulted
        robot can be cleared from the dashboard; the agent FSM allows
        OPERATOR_CANCEL from ERROR -> IDLE. Only OFFLINE is a hard block.
        """
        task_queue.add_task('task_err', 'prospect', 0.0, 0.0)
        task_queue.assign_to_robot('task_err', 'scout_01')
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='ERROR', current_task_id='task_err',
        )
        client = _make_client(_FakeAgentResponse(accepted=True))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(robot_id='scout_01', command='cancel_task')
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is True
        client.call_async.assert_called_once()
        assert client.call_async.call_args[0][0].command == 'cancel_task'
        # The stranded task rests in INTERRUPTED, which get_next_ready
        # re-auctions from directly (REQUEUEABLE_STATUSES). Before D-03 this
        # was immediately overwritten with PENDING, which is what made a
        # cancelled task indistinguishable from a fresh queue entry.
        task = task_queue.get_task('task_err')
        assert task.status == TaskStatus.INTERRUPTED
        assert task.status_reason == 'operator_cancel_task'
        assert task.progress_metadata == {'reason': 'operator_cancel_task'}

    def test_override_robot_offline_rejected(self, task_queue, fleet_monitor,
                                             publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='OFFLINE')
        clients = {'scout_01': _make_client()}
        ctx = _build_ctx(task_queue, fleet_monitor, clients, publish_alert)

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='force_recharge',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'OFFLINE' in out.message

    def test_override_invalid_command(self, task_queue, fleet_monitor,
                                      publish_alert):
        _add_robot(fleet_monitor, 'scout_01')
        clients = {'scout_01': _make_client()}
        ctx = _build_ctx(task_queue, fleet_monitor, clients, publish_alert)

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='eject_warp_core',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'invalid' in out.message
        clients['scout_01'].call_async.assert_not_called()

    def test_override_cancel_task_with_active_task(
            self, task_queue, fleet_monitor, publish_alert):
        # Set up a running task on the robot.
        task_queue.add_task('task_42', 'prospect', 0.0, 0.0)
        task_queue.assign_to_robot('task_42', 'scout_01')
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='WORKING', current_task_id='task_42',
        )
        client = _make_client(_FakeAgentResponse(accepted=True, reason='ok'))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(robot_id='scout_01', command='cancel_task')
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is True
        # Task rests in INTERRUPTED and the auction loop re-dispatches it from
        # there once a robot is available (D-03: INTERRUPTED is a resting
        # status and is in REQUEUEABLE_STATUSES).
        task = task_queue.get_task('task_42')
        assert task.status == TaskStatus.INTERRUPTED
        assert task.status_reason == 'operator_cancel_task'
        assert task.progress_metadata == {'reason': 'operator_cancel_task'}
        assert task.assigned_robot == ''

        # Agent client was called with the right command + monotonic seq.
        client.call_async.assert_called_once()
        cmd_req = client.call_async.call_args[0][0]
        assert cmd_req.command == 'cancel_task'
        assert cmd_req.sequence == 1

    def test_override_send_to_location(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        client = _make_client(_FakeAgentResponse(accepted=True))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='send_to_location',
            x=100.0, y=-50.0,
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is True
        client.call_async.assert_called_once()
        cmd_req = client.call_async.call_args[0][0]
        assert cmd_req.command == 'send_to_location'
        # Target was forwarded verbatim.
        assert cmd_req.target.x == 100.0
        assert cmd_req.target.y == -50.0

    def test_override_send_to_location_does_not_interrupt_task(
            self, task_queue, fleet_monitor, publish_alert):
        # D5: send_to_location does NOT touch the task_queue.
        task_queue.add_task('task_99', 'prospect', 0.0, 0.0)
        task_queue.assign_to_robot('task_99', 'scout_01')
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='NAVIGATING', current_task_id='task_99',
        )
        client = _make_client(_FakeAgentResponse(accepted=True))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='send_to_location',
            x=1.0, y=2.0,
        )
        resp = _FakeOverrideResponse()
        override_robot_logic(ctx, req, resp)

        # The old task remains ASSIGNED — send_to_location does not requeue it.
        # (The agent will abort its current skill independently.)
        assert task_queue.get_task('task_99').status == TaskStatus.ASSIGNED

    def test_override_force_recharge_with_active_task(
            self, task_queue, fleet_monitor, publish_alert):
        task_queue.add_task('task_7', 'haul', 0.0, 0.0)
        task_queue.assign_to_robot('task_7', 'hauler_01')
        _add_robot(
            fleet_monitor, 'hauler_01',
            fsm_state='NAVIGATING', current_task_id='task_7',
        )
        client = _make_client(_FakeAgentResponse(accepted=True))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'hauler_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='hauler_01', command='force_recharge',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is True
        task = task_queue.get_task('task_7')
        assert task.status == TaskStatus.INTERRUPTED
        assert task.status_reason == 'operator_force_recharge'
        assert task.progress_metadata == {'reason': 'operator_force_recharge'}
        client.call_async.assert_called_once()
        cmd_req = client.call_async.call_args[0][0]
        assert cmd_req.command == 'force_recharge'

    def test_override_agent_service_timeout(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        client = _make_client(timeout=True)
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='cancel_task',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'timed out' in out.message

    def test_override_agent_not_reachable(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        client = _make_client(service_ready=False)
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='cancel_task',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'not reachable' in out.message

    def test_override_no_client_for_robot(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        ctx = _build_ctx(task_queue, fleet_monitor, {}, publish_alert)

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='cancel_task',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'not reachable' in out.message

    def test_override_agent_rejects_command(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        client = _make_client(
            _FakeAgentResponse(accepted=False, reason='busy'),
        )
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        req = _FakeOverrideRequest(
            robot_id='scout_01', command='cancel_task',
        )
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert out.message == 'busy'

    def test_override_sequence_monotonic(
            self, task_queue, fleet_monitor, publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='IDLE')
        client = _make_client(_FakeAgentResponse(accepted=True))
        ctx = _build_ctx(
            task_queue, fleet_monitor, {'scout_01': client}, publish_alert,
        )

        for _ in range(3):
            req = _FakeOverrideRequest(
                robot_id='scout_01', command='cancel_task',
            )
            resp = _FakeOverrideResponse()
            override_robot_logic(ctx, req, resp)

        sequences = [
            call.args[0].sequence for call in client.call_async.call_args_list
        ]
        assert sequences == [1, 2, 3]
