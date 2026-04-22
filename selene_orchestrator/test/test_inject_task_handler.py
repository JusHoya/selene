"""Unit tests for ``inject_task_logic`` (OrchestratorNode operator service).

These tests exercise the pure-Python decision tree underlying the
``/orchestrator/inject_task`` service handler. They avoid standing up a
real ROS node by:

  1. Stubbing ``rclpy``, ``selene_msgs.*``, ``selene_isru.*`` and
     ``geometry_msgs.msg`` in ``sys.modules`` before importing
     ``orchestrator_node``. Inside a colcon workspace the real modules
     take precedence, so the same file runs both under ``pytest`` from
     ``/tmp`` and under ``colcon test``.

  2. Driving ``inject_task_logic`` directly with an ``_InjectTaskContext``
     wrapping a real ``TaskQueue`` + a mocked ``FleetMonitor`` +
     ``MagicMock`` publishers.
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
    # rclpy + rclpy.node: only Node class and spin_until_future_complete are
    # touched at import time.
    rclpy_mod = _ensure_stub('rclpy')
    rclpy_mod.spin_until_future_complete = lambda *a, **k: None
    rclpy_mod.init = lambda *a, **k: None
    rclpy_mod.shutdown = lambda *a, **k: None

    rclpy_node = _ensure_stub('rclpy.node')

    # rclpy.callback_groups + rclpy.executors: orchestrator_node imports
    # ReentrantCallbackGroup + MultiThreadedExecutor at module import time
    # for the override-robot service path (D8 fix).
    rclpy_cb = _ensure_stub('rclpy.callback_groups')

    class _ReentrantCallbackGroup:
        def __init__(self, *a, **k): pass
    rclpy_cb.ReentrantCallbackGroup = _ReentrantCallbackGroup

    rclpy_exec = _ensure_stub('rclpy.executors')

    class _MultiThreadedExecutor:
        def __init__(self, *a, **k): pass
        def add_node(self, *a, **k): pass
        def spin(self): pass
        def shutdown(self): pass
    rclpy_exec.MultiThreadedExecutor = _MultiThreadedExecutor

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

    # geometry_msgs.msg.Point
    gm = _ensure_stub('geometry_msgs')
    gm_msg = _ensure_stub('geometry_msgs.msg')

    class _Point:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)
    gm_msg.Point = _Point
    gm.msg = gm_msg

    # selene_msgs.msg.*
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

    # selene_msgs.srv.*
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

    # selene_isru.inventory.MaterialInventory
    sisru = _ensure_stub('selene_isru')
    sisru_inv = _ensure_stub('selene_isru.inventory')

    class _MaterialInventory:
        def get_mission_progress(self):
            return {'extracted': 0.0, 'in_transit': 0.0, 'deposited': 0.0}
    sisru_inv.MaterialInventory = _MaterialInventory
    sisru.inventory = sisru_inv


_install_ros_stubs()

# Ensure the orchestrator package is importable from the repo layout even
# when pytest is run from /tmp. The package __init__.py is at
# selene_orchestrator/selene_orchestrator/__init__.py — the parent dir
# (selene_orchestrator/) must be on sys.path.
import os  # noqa: E402
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

from selene_orchestrator.orchestrator_node import (  # noqa: E402
    inject_task_logic,
    _InjectTaskContext,
    MANUAL_TASK_CAPABILITIES,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus  # noqa: E402


# --------------------------------------------------------------------------- #
#  Fixtures                                                                     #
# --------------------------------------------------------------------------- #

class _FakeInjectRequest:
    def __init__(self, task_type='prospect', x=0.0, y=0.0,
                 quantity=0.0, assigned_robot_id=''):
        self.task_type = task_type
        self.target_location = types.SimpleNamespace(x=x, y=y, z=0.0)
        self.quantity = quantity
        self.assigned_robot_id = assigned_robot_id


class _FakeInjectResponse:
    def __init__(self):
        self.success = False
        self.task_id = ''
        self.message = ''


@pytest.fixture
def task_queue():
    return TaskQueue()


@pytest.fixture
def fleet_monitor():
    """Mock FleetMonitor with a ``get_robot`` that returns dicts."""
    fm = MagicMock()
    fm._robots = {}

    def _get(rid):
        return fm._robots.get(rid)
    fm.get_robot.side_effect = _get
    return fm


def _add_robot(fm, robot_id, fsm_state='IDLE', capabilities=None,
               current_task_id=''):
    fm._robots[robot_id] = {
        'robot_id': robot_id,
        'fsm_state': fsm_state,
        'capabilities': list(capabilities or []),
        'current_task_id': current_task_id,
        'battery_level': 0.9,
        'pose': (0.0, 0.0, 0.0),
    }


@pytest.fixture
def publish_assignment():
    return MagicMock()


@pytest.fixture
def publish_alert():
    return MagicMock()


@pytest.fixture
def inject_ctx(task_queue, fleet_monitor, publish_assignment, publish_alert):
    # Monotonic id generator delegates to the real TaskQueue helper so
    # collisions against any pre-existing ids are impossible.
    return _InjectTaskContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        next_task_id=lambda: task_queue.make_unique_task_id('manual'),
        now_stamp=MagicMock(),
        publish_assignment=publish_assignment,
        publish_alert=publish_alert,
    )


# --------------------------------------------------------------------------- #
#  Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestInjectTaskHandler:

    def test_inject_valid_task_no_assignment(self, inject_ctx, task_queue,
                                              publish_alert):
        req = _FakeInjectRequest(task_type='prospect', x=30.0, y=-110.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert out.task_id.startswith('manual_')
        assert out.message == 'queued'

        task = task_queue.get_task(out.task_id)
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.task_type == 'prospect'
        assert task.target_x == 30.0
        assert task.target_y == -110.0
        assert task.priority == 10.0
        assert task.required_capabilities == \
            MANUAL_TASK_CAPABILITIES['prospect']
        publish_alert.assert_called_once()
        severity, msg = publish_alert.call_args[0]
        assert severity == 'INFO'
        assert 'queued' in msg

    def test_inject_invalid_task_type(self, inject_ctx, task_queue):
        req = _FakeInjectRequest(task_type='dance')
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'invalid' in out.message
        # No task should have been added on the failure path.
        assert task_queue.get_total_count() == 0

    def test_inject_force_assign_unknown_robot(self, inject_ctx, task_queue):
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='ghost_99',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'unknown' in out.message
        # Task was added before validation, then marked FAILED.
        task = task_queue.get_task(out.task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED

    def test_inject_force_assign_robot_in_error(self, inject_ctx, task_queue,
                                                 fleet_monitor):
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='ERROR',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'ERROR' in out.message
        assert task_queue.get_task(out.task_id).status == TaskStatus.FAILED

    def test_inject_force_assign_robot_recharging_rejected(
            self, inject_ctx, task_queue, fleet_monitor):
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='RECHARGING',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'RECHARGING' in out.message

    def test_inject_force_assign_capability_mismatch(
            self, inject_ctx, task_queue, fleet_monitor):
        # Haul task requires 'haul' capability, scout only has 'prospect'.
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='IDLE',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='haul', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'capabilities' in out.message
        assert 'haul' in out.message
        assert task_queue.get_task(out.task_id).status == TaskStatus.FAILED

    def test_inject_force_assign_happy_path(
            self, inject_ctx, task_queue, fleet_monitor,
            publish_assignment, publish_alert):
        _add_robot(
            fleet_monitor, 'hauler_01',
            fsm_state='IDLE',
            capabilities=['haul'],
        )
        req = _FakeInjectRequest(
            task_type='haul', x=-80.0, y=-140.0,
            assigned_robot_id='hauler_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert out.message == 'force-assigned'

        task = task_queue.get_task(out.task_id)
        assert task.status == TaskStatus.ASSIGNED
        assert task.assigned_robot == 'hauler_01'

        # A TaskAssignment was published immediately.
        publish_assignment.assert_called_once()
        args = publish_assignment.call_args[0]
        assert args[0] == out.task_id
        assert args[1] == 'hauler_01'
        assert args[2] == 'haul'

        # A single INFO alert announcing the force assignment.
        infos = [c for c in publish_alert.call_args_list if c[0][0] == 'INFO']
        assert any('force-assigned' in c[0][1] for c in infos)

    def test_inject_force_assign_preempts_existing_task(
            self, inject_ctx, task_queue, fleet_monitor, publish_alert):
        # Pre-seed the queue with an existing task assigned to the target.
        task_queue.add_task('auto_0001', 'haul', 0.0, 0.0, priority=5.0,
                            required_capabilities=['haul'])
        task_queue.assign_to_robot('auto_0001', 'hauler_01')

        _add_robot(
            fleet_monitor, 'hauler_01',
            fsm_state='WORKING',
            capabilities=['haul'],
            current_task_id='auto_0001',
        )
        req = _FakeInjectRequest(
            task_type='haul', x=10.0, y=20.0,
            assigned_robot_id='hauler_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        # The displaced task is now PENDING with its metadata populated.
        old = task_queue.get_task('auto_0001')
        assert old.status == TaskStatus.PENDING
        assert old.progress_metadata == {'reason': 'operator_reassign'}
        assert old.assigned_robot == ''
        # The new task is freshly assigned.
        assert task_queue.get_task(out.task_id).assigned_robot == 'hauler_01'

        # A WARNING alert was emitted about the preemption.
        warnings = [c for c in publish_alert.call_args_list
                    if c[0][0] == 'WARNING']
        assert len(warnings) == 1
        assert 'preempted' in warnings[0][0][1]

    def test_inject_monotonic_task_ids(self, inject_ctx, task_queue):
        req1 = _FakeInjectRequest(task_type='prospect')
        resp1 = _FakeInjectResponse()
        inject_task_logic(inject_ctx, req1, resp1)

        req2 = _FakeInjectRequest(task_type='prospect')
        resp2 = _FakeInjectResponse()
        inject_task_logic(inject_ctx, req2, resp2)

        assert resp1.task_id != resp2.task_id
        assert resp1.task_id.startswith('manual_')
        assert resp2.task_id.startswith('manual_')
        # IDs should be numerically ordered.
        n1 = int(resp1.task_id.split('_')[-1])
        n2 = int(resp2.task_id.split('_')[-1])
        assert n2 > n1

    def test_inject_excavate_capability_mismatch(
            self, inject_ctx, task_queue, fleet_monitor):
        _add_robot(
            fleet_monitor, 'excavator_01',
            fsm_state='IDLE',
            capabilities=['prospect'],  # wrong capability for excavate
        )
        req = _FakeInjectRequest(
            task_type='excavate', assigned_robot_id='excavator_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'excavate' in out.message
