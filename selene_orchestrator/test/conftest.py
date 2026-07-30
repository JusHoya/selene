"""Shared test setup for ``selene_orchestrator`` — scoped ROS 2 stubs.

Why this file exists
--------------------
``selene_orchestrator.orchestrator_node`` imports ``rclpy``,
``selene_msgs.*`` and ``geometry_msgs.msg`` at module-import time. Those
only exist inside a built ROS 2 workspace, so to unit-test the
pure-Python decision logic outside one we install minimal stand-ins in
``sys.modules``. pytest imports a directory's ``conftest.py`` before any
test module in that directory, which is the only hook that runs early
enough for import-time stubbing.

The bug this replaces
---------------------
``test_inject_task_handler.py``, ``test_override_robot_handler.py`` and
``test_e2e_integration.py`` each used to run their own module-level
``_install_ros_stubs()``. Two of them did an unconditional
``selene_isru.inventory.MaterialInventory = _MaterialInventory``, which
overwrote the *real* class on the *real* module for the rest of the
pytest process and never restored it. Running the orchestrator suite
before ``selene_isru/test/test_inventory.py`` in one process therefore
produced 8 failures of the form::

    AttributeError: '_MaterialInventory' object has no attribute
                    'register_site'

Three rules here make the stubbing order-independent:

1. **Never shadow something real.** A module is stubbed only when the
   real one cannot be imported (or imports but is an empty implicit
   namespace package, which is what ``selene_msgs``' directory of
   ``.msg`` files looks like from the repo root). Attributes are only
   ever written on modules created here.
2. **Never stub ``selene_isru.inventory``.** It is pure Python and always
   present in the checkout, so the real ``MaterialInventory`` is used.
   The fallback stub only applies if the file is genuinely absent.
3. **Reversible.** Every ``sys.modules`` entry this file replaces or
   creates is recorded and restored in ``pytest_sessionfinish``, so no
   stub outlives the session.
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from unittest.mock import MagicMock

# --------------------------------------------------------------------------- #
#  Import paths                                                               #
# --------------------------------------------------------------------------- #
# Make the repo's pure-Python packages importable without a colcon install
# and without depending on the caller's cwd or PYTHONPATH.
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.dirname(_TEST_DIR)              # .../selene_orchestrator
_REPO_ROOT = os.path.dirname(_PKG_PARENT)
_ISRU_PARENT = os.path.join(_REPO_ROOT, 'selene_isru')
_ISRU_INVENTORY_FILE = os.path.join(_ISRU_PARENT, 'selene_isru', 'inventory.py')

for _path in (_PKG_PARENT, _ISRU_PARENT):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)


# --------------------------------------------------------------------------- #
#  Stub registry                                                              #
# --------------------------------------------------------------------------- #

_MISSING = object()

#: sys.modules keys this file replaced -> their previous value (or _MISSING).
_ORIGINAL_MODULES: dict = {}


def _real_module(name: str, probe: str | None = None):
    """Return the genuinely-importable module for *name*, else ``None``.

    A module that imports but lacks *probe* does not count as real — that
    is how an implicit namespace package (e.g. ``selene_msgs.msg`` seen
    from the repo root, where ``msg/`` holds ``.msg`` files and no Python)
    is distinguished from the generated ROS 2 package.
    """
    module = sys.modules.get(name)
    if module is not None and getattr(module, '__selene_test_stub__', False):
        return None
    if module is None:
        try:
            module = importlib.import_module(name)
        except ImportError:
            return None
    if probe is not None and not hasattr(module, probe):
        return None
    return module


def _replace_with_stub(name: str) -> types.ModuleType:
    """Install a fresh empty stub at ``sys.modules[name]``, recording what
    was there before so ``pytest_sessionfinish`` can put it back."""
    if name not in _ORIGINAL_MODULES:
        _ORIGINAL_MODULES[name] = sys.modules.get(name, _MISSING)
    module = types.ModuleType(name)
    module.__selene_test_stub__ = True
    module.__path__ = []               # behave like a package
    sys.modules[name] = module
    return module


def _stub_module(name: str, probe: str | None = None):
    """Return a stub module for *name*, or ``None`` if the real one exists.

    ``None`` is the signal to callers to leave the real module completely
    alone — no attribute writes, no replacement.
    """
    if _real_module(name, probe) is not None:
        return None
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, '__selene_test_stub__', False):
        return existing                # our own stub, from an earlier call
    return _replace_with_stub(name)


def _ensure_stub_parent(name: str, children: tuple) -> None:
    """Expose stubbed *children* as attributes of parent package *name*.

    ``from X.Y import Z`` resolves through ``sys.modules['X.Y']`` and does
    not strictly need this, but keeping the parent consistent avoids
    surprises for anything that does ``import X`` then ``X.Y.Z``.

    Only touches a parent that is absent, already our stub, or an empty
    implicit namespace package (``__file__ is None`` — which is what the
    repo's ``selene_msgs/`` directory of ``.msg`` files looks like from the
    repo root). A real installed package is never modified.
    """
    parent = sys.modules.get(name)
    if parent is not None and getattr(parent, '__file__', None) is not None:
        return
    if parent is None or not getattr(parent, '__selene_test_stub__', False):
        parent = _replace_with_stub(name)
    for child in children:
        child_module = sys.modules.get(child)
        if child_module is not None:
            setattr(parent, child.rpartition('.')[2], child_module)


def _make_msg_class(name: str, fields: dict) -> type:
    """Build a plain-Python stand-in for a generated ROS 2 message class."""
    def __init__(self) -> None:
        for field, default in fields.items():
            setattr(self, field, default() if callable(default) else default)

    return type(name, (), {'__init__': __init__})


# --------------------------------------------------------------------------- #
#  Individual stub groups                                                     #
# --------------------------------------------------------------------------- #

def _stub_rclpy() -> None:
    rclpy_mod = _stub_module('rclpy', probe='init')
    if rclpy_mod is not None:
        rclpy_mod.spin_until_future_complete = lambda *a, **k: None
        rclpy_mod.init = lambda *a, **k: None
        rclpy_mod.shutdown = lambda *a, **k: None

    rclpy_cb = _stub_module('rclpy.callback_groups',
                            probe='ReentrantCallbackGroup')
    if rclpy_cb is not None:
        class _ReentrantCallbackGroup:
            def __init__(self, *a, **k):
                pass

        rclpy_cb.ReentrantCallbackGroup = _ReentrantCallbackGroup

    rclpy_exec = _stub_module('rclpy.executors',
                              probe='MultiThreadedExecutor')
    if rclpy_exec is not None:
        class _MultiThreadedExecutor:
            def __init__(self, *a, **k):
                pass

            def add_node(self, *a, **k):
                pass

            def spin(self):
                pass

            def shutdown(self):
                pass

        rclpy_exec.MultiThreadedExecutor = _MultiThreadedExecutor

    rclpy_node = _stub_module('rclpy.node', probe='Node')
    if rclpy_node is not None:
        class _FakeNode:
            """Only the surface orchestrator_node touches is implemented."""

            def __init__(self, *a, **k):
                pass

            def declare_parameter(self, *a, **k):
                default = a[1] if len(a) > 1 else None
                return types.SimpleNamespace(value=default)

            def get_parameter(self, name):
                return types.SimpleNamespace(value=None)

            def create_subscription(self, *a, **k):
                return MagicMock()

            def create_publisher(self, *a, **k):
                return MagicMock()

            def create_timer(self, *a, **k):
                return MagicMock()

            def create_service(self, *a, **k):
                return MagicMock()

            def create_client(self, *a, **k):
                return MagicMock()

            def get_clock(self):
                clock = MagicMock()
                now = MagicMock()
                now.to_msg.return_value = MagicMock()
                now.nanoseconds = 0
                clock.now.return_value = now
                return clock

            def get_logger(self):
                return MagicMock()

            def destroy_node(self):
                pass

        rclpy_node.Node = _FakeNode


def _stub_geometry_msgs() -> type:
    """Stub ``geometry_msgs.msg`` if needed; return the ``Point`` in force."""
    gm_msg = _stub_module('geometry_msgs.msg', probe='Point')
    if gm_msg is None:
        return sys.modules['geometry_msgs.msg'].Point

    class _Point:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    gm_msg.Point = _Point
    _ensure_stub_parent('geometry_msgs', ('geometry_msgs.msg',))
    return _Point


def _stub_selene_msgs(point_cls: type) -> None:
    smsgs_msg = _stub_module('selene_msgs.msg', probe='BidResponse')
    if smsgs_msg is not None:
        for msg_name, fields in (
            ('BidResponse', {
                'task_id': '', 'robot_id': '', 'bid_score': 0.0,
                'estimated_arrival_time': 0.0, 'energy_after_task': 0.0,
            }),
            ('FleetAlert', {
                'alert_id': '', 'severity': '', 'source_robot_id': '',
                'message': '', 'stamp': lambda: MagicMock(),
            }),
            ('MissionProgress', {
                'objective_description': '', 'target_quantity': 0.0,
                'extracted_quantity': 0.0, 'in_transit_quantity': 0.0,
                'deposited_quantity': 0.0, 'fleet_distance_total': 0.0,
                'fleet_energy_total': 0.0, 'elapsed_sim_time': 0.0,
            }),
            ('ResourceMapUpdate', {
                'location': point_cls, 'ice_concentration': 0.0,
                'sensor_uncertainty': 0.0,
            }),
            ('RobotState', {
                'robot_id': '', 'robot_type': '', 'fsm_state': '',
                'pose': point_cls, 'battery_level': 1.0,
                'current_task_id': '', 'capabilities': list,
            }),
            ('TaskAnnouncement', {
                'task_id': '', 'task_type': '', 'target_location': point_cls,
                'estimated_energy_cost': 0.0, 'required_capabilities': list,
                'priority': 0.0, 'estimated_duration': 0.0,
                'parent_task_id': '', 'deadline': lambda: MagicMock(),
            }),
            ('TaskAssignment', {
                'task_id': '', 'robot_id': '', 'task_type': '',
                'target_location': point_cls, 'parameters': list,
                'assigned_at': lambda: MagicMock(),
            }),
        ):
            setattr(smsgs_msg, msg_name, _make_msg_class(msg_name, fields))

    smsgs_srv = _stub_module('selene_msgs.srv', probe='InjectTask')
    if smsgs_srv is not None:
        class _InjectTask:
            Request = _make_msg_class('InjectTask_Request', {
                'task_type': '', 'target_location': point_cls,
                'quantity': 0.0, 'assigned_robot_id': '',
            })
            Response = _make_msg_class('InjectTask_Response', {
                'success': False, 'task_id': '', 'message': '',
            })

        class _OverrideRobot:
            Request = _make_msg_class('OverrideRobot_Request', {
                'robot_id': '', 'command': '', 'target': point_cls,
            })
            Response = _make_msg_class('OverrideRobot_Response', {
                'success': False, 'message': '',
            })

        class _SetRobotCommand:
            Request = _make_msg_class('SetRobotCommand_Request', {
                'command': '', 'target': point_cls, 'sequence': 0,
            })
            Response = _make_msg_class('SetRobotCommand_Response', {
                'accepted': False, 'reason': '',
            })

        smsgs_srv.InjectTask = _InjectTask
        smsgs_srv.OverrideRobot = _OverrideRobot
        smsgs_srv.SetRobotCommand = _SetRobotCommand

    if smsgs_msg is not None or smsgs_srv is not None:
        _ensure_stub_parent('selene_msgs',
                            ('selene_msgs.msg', 'selene_msgs.srv'))


def _stub_selene_isru_if_missing() -> None:
    """Fallback stub for ``selene_isru.inventory`` — normally a no-op.

    ``inventory.py`` is pure Python and always present in a checkout, so
    the real ``MaterialInventory`` is what ``orchestrator_node`` gets and
    what ``selene_isru/test/test_inventory.py`` keeps seeing afterwards.
    Replacing it with a stub is exactly the bug this file exists to
    prevent, so if the file is there we do nothing at all and let a
    genuine import failure surface loudly.
    """
    if os.path.isfile(_ISRU_INVENTORY_FILE):
        return

    sisru_inv = _stub_module('selene_isru.inventory',
                             probe='MaterialInventory')
    if sisru_inv is None:
        return

    class _MaterialInventory:
        def get_mission_progress(self):
            return {'extracted': 0.0, 'in_transit': 0.0, 'deposited': 0.0}

    sisru_inv.MaterialInventory = _MaterialInventory
    _ensure_stub_parent('selene_isru', ('selene_isru.inventory',))


def install_ros_stubs() -> None:
    """Install every stub needed to import ``orchestrator_node``.

    Idempotent, and a no-op for any module that is really available.
    """
    _stub_rclpy()
    point_cls = _stub_geometry_msgs()
    _stub_selene_msgs(point_cls)
    _stub_selene_isru_if_missing()


install_ros_stubs()


# --------------------------------------------------------------------------- #
#  Teardown                                                                   #
# --------------------------------------------------------------------------- #

def pytest_sessionfinish(session, exitstatus):
    """Restore ``sys.modules`` so no stub outlives this pytest session."""
    for name, original in _ORIGINAL_MODULES.items():
        current = sys.modules.get(name)
        if not getattr(current, '__selene_test_stub__', False):
            continue                   # someone replaced it; leave it be
        if original is _MISSING:
            del sys.modules[name]
        else:
            sys.modules[name] = original
    _ORIGINAL_MODULES.clear()
