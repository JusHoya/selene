"""Unit tests for ``override_robot_logic`` (OrchestratorNode operator service).

Uses the same sys.modules-stubbing approach as
``test_inject_task_handler.py`` so the test can run standalone via
``pytest`` from ``/tmp`` without a built ROS workspace.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
#  sys.modules stubs — must run before importing orchestrator_node            #
# --------------------------------------------------------------------------- #

def _ensure_stub(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_ros_stubs() -> None:
    rclpy_mod = _ensure_stub('rclpy')
    rclpy_mod.spin_until_future_complete = lambda *a, **k: None
    rclpy_mod.init = lambda *a, **k: None
    rclpy_mod.shutdown = lambda *a, **k: None

    rclpy_node = _ensure_stub('rclpy.node')

    class _FakeNode:
        def __init__(self, *a, **k): pass
        def declare_parameter(self, *a, **k):
            class _P:
                value = a[1] if len(a) > 1 else None
            return _P()
        def get_parameter(self, name):
            class _P:
                value = None
            return _P()
        def create_subscription(self, *a, **k): return MagicMock()
        def create_publisher(self, *a, **k): return MagicMock()
        def create_timer(self, *a, **k): return MagicMock()
        def create_service(self, *a, **k): return MagicMock()
        def create_client(self, *a, **k): return MagicMock()
        def get_clock(self):
            clk = MagicMock()
            now = MagicMock()
            now.to_msg.return_value = MagicMock()
            now.nanoseconds = 0
            clk.now.return_value = now
            return clk
        def get_logger(self): return MagicMock()
        def destroy_node(self): pass

    rclpy_node.Node = _FakeNode

    gm = _ensure_stub('geometry_msgs')
    gm_msg = _ensure_stub('geometry_msgs.msg')

    class _Point:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)
    gm_msg.Point = _Point
    gm.msg = gm_msg

    smsgs = _ensure_stub('selene_msgs')
    smsgs_msg = _ensure_stub('selene_msgs.msg')

    def _make_msg_class(name, fields):
        def __init__(self):
            for f, default in fields.items():
                setattr(self, f, default() if callable(default) else default)
        return type(name, (), {'__init__': __init__})

    smsgs_msg.BidResponse = _make_msg_class('BidResponse', {
        'task_id': '', 'robot_id': '', 'bid_score': 0.0,
        'estimated_arrival_time': 0.0, 'energy_after_task': 0.0,
    })
    smsgs_msg.FleetAlert = _make_msg_class('FleetAlert', {
        'alert_id': '', 'severity': '', 'source_robot_id': '',
        'message': '', 'stamp': lambda: MagicMock(),
    })
    smsgs_msg.MissionProgress = _make_msg_class('MissionProgress', {
        'objective_description': '', 'target_quantity': 0.0,
        'extracted_quantity': 0.0, 'in_transit_quantity': 0.0,
        'deposited_quantity': 0.0, 'fleet_distance_total': 0.0,
        'fleet_energy_total': 0.0, 'elapsed_sim_time': 0.0,
    })
    smsgs_msg.ResourceMapUpdate = _make_msg_class('ResourceMapUpdate', {
        'location': lambda: _Point(), 'ice_concentration': 0.0,
        'sensor_uncertainty': 0.0,
    })
    smsgs_msg.RobotState = _make_msg_class('RobotState', {
        'robot_id': '', 'robot_type': '', 'fsm_state': '',
        'pose': lambda: _Point(), 'battery_level': 1.0,
        'current_task_id': '', 'capabilities': lambda: [],
    })
    smsgs_msg.TaskAnnouncement = _make_msg_class('TaskAnnouncement', {
        'task_id': '', 'task_type': '', 'target_location': lambda: _Point(),
        'estimated_energy_cost': 0.0, 'required_capabilities': lambda: [],
        'priority': 0.0, 'estimated_duration': 0.0, 'parent_task_id': '',
        'deadline': lambda: MagicMock(),
    })
    smsgs_msg.TaskAssignment = _make_msg_class('TaskAssignment', {
        'task_id': '', 'robot_id': '', 'task_type': '',
        'target_location': lambda: _Point(), 'parameters': lambda: [],
        'assigned_at': lambda: MagicMock(),
    })

    smsgs_srv = _ensure_stub('selene_msgs.srv')

    class _InjectTaskSrv:
        class Request:
            def __init__(self):
                self.task_type = ''
                self.target_location = _Point()
                self.quantity = 0.0
                self.assigned_robot_id = ''
        class Response:
            def __init__(self):
                self.success = False
                self.task_id = ''
                self.message = ''
    smsgs_srv.InjectTask = _InjectTaskSrv

    class _OverrideRobotSrv:
        class Request:
            def __init__(self):
                self.robot_id = ''
                self.command = ''
                self.target = _Point()
        class Response:
            def __init__(self):
                self.success = False
                self.message = ''
    smsgs_srv.OverrideRobot = _OverrideRobotSrv

    class _SetRobotCommandSrv:
        class Request:
            def __init__(self):
                self.command = ''
                self.target = _Point()
                self.sequence = 0
        class Response:
            def __init__(self):
                self.accepted = False
                self.reason = ''
    smsgs_srv.SetRobotCommand = _SetRobotCommandSrv

    smsgs.msg = smsgs_msg
    smsgs.srv = smsgs_srv

    sisru = _ensure_stub('selene_isru')
    sisru_inv = _ensure_stub('selene_isru.inventory')

    class _MaterialInventory:
        def get_mission_progress(self):
            return {'extracted': 0.0, 'in_transit': 0.0, 'deposited': 0.0}
    sisru_inv.MaterialInventory = _MaterialInventory
    sisru.inventory = sisru_inv


_install_ros_stubs()

import os  # noqa: E402
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

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

    def test_override_robot_in_error(self, task_queue, fleet_monitor,
                                      publish_alert):
        _add_robot(fleet_monitor, 'scout_01', fsm_state='ERROR')
        clients = {'scout_01': _make_client()}
        ctx = _build_ctx(task_queue, fleet_monitor, clients, publish_alert)

        req = _FakeOverrideRequest(robot_id='scout_01', command='cancel_task')
        resp = _FakeOverrideResponse()
        out = override_robot_logic(ctx, req, resp)

        assert out.success is False
        assert 'ERROR' in out.message
        # Agent client should NOT have been invoked when the robot is rejected.
        clients['scout_01'].call_async.assert_not_called()

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
        # Task was interrupted + re-PENDING so the auction loop can
        # re-auction it after the robot becomes available.
        task = task_queue.get_task('task_42')
        assert task.status == TaskStatus.PENDING
        assert task.progress_metadata == {'reason': 'operator_cancel_task'}

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
        assert task.status == TaskStatus.PENDING
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
