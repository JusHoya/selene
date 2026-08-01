"""Shared test setup for ``selene_orchestrator`` — scoped ROS 2 stubs.

Why this file exists
--------------------
``selene_orchestrator.orchestrator_node`` imports ``rclpy``,
``selene_msgs.*`` and ``geometry_msgs.msg`` at module-import time. Those
only exist inside a built ROS 2 workspace, so to unit-test the
pure-Python decision logic outside one we install minimal stand-ins in
``sys.modules``.

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

The second bug this replaces (deviation D-14)
---------------------------------------------
Consolidating the stubs here fixed the ``selene_isru`` collision but kept
the shape that caused it: the stubs were installed at conftest-import
time and stayed in ``sys.modules`` for the whole session. pytest imports
the conftest of every initial argument's directory *before* collection,
so a run naming both ``selene_orchestrator/test`` and ``selene_hal/test``
had a half-``rclpy`` in place before ``selene_hal`` was imported.
``selene_hal/selene_hal/gazebo_hal.py`` does
``from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy``;
the stub had ``QoSReliabilityPolicy`` but not the ``ReliabilityPolicy``
alias, so that import raised ``ImportError`` — which is *not*
``ModuleNotFoundError``, so ``pytest.importorskip`` (pytest >= 9.1
defaults to ``exc_type=ModuleNotFoundError``) re-raised it and the whole
run aborted at collection.

Filling in the two missing aliases only moved the failure to
``std_msgs.msg.Float32``, because the real defect is not which names are
missing. It is that a stub shaped for one package was visible to every
other package in the process. Completing the stubs would have been worse
than the disease: ``selene_hal``'s Gazebo tests would then have *run*
against hand-written fakes, silently, in one invocation and skipped in
another.

Four rules make the stubbing order-independent
----------------------------------------------
1. **Never shadow something real.** A module is stubbed only when the
   real one cannot be imported (or imports but is an empty implicit
   namespace package, which is what ``selene_msgs``' directory of
   ``.msg`` files looks like from the repo root). Attributes are only
   ever written on modules created here.
2. **Never stub ``selene_isru.inventory``.** It is pure Python and always
   present in the checkout, so the real ``MaterialInventory`` is used.
   The fallback stub only applies if the file is genuinely absent.
3. **Reversible.** Every ``sys.modules`` entry this file replaces is
   recorded and put back.
4. **Never visible outside this directory.** Rule 3 used to mean
   "restored at ``pytest_sessionfinish``", which is far too late. The
   stubs are now *scoped*: they are inserted into ``sys.modules`` only
   for the duration of

     * collecting a node under this directory — which is where a test
       module's ``from selene_orchestrator.orchestrator_node import ...``
       actually runs (``pytest_make_collect_report`` hook wrapper); and
     * running a test under this directory (autouse fixture).

   Both windows are ``try``/``finally``-safe, and both are confined to
   this conftest's own directory, so no other package ever observes a
   stub. ``selene_hal/test/test_ros_stub_isolation.py`` is the executable
   guard on that.

Note what rule 4 does *not* do: nothing is stubbed lazily or on demand.
The stub objects are still built once, eagerly, at conftest import — that
step is pure stdlib and pulls in no third-party package, which matters
because the ``gate-coverage`` CI job installs pytest and nothing else.
Only their *installation* is scoped.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------------------- #
#  Import paths                                                               #
# --------------------------------------------------------------------------- #
# Make the repo's pure-Python packages importable without a colcon install
# and without depending on the caller's cwd or PYTHONPATH.
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_TEST_DIR_KEY = os.path.normcase(_TEST_DIR)
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

#: Stub modules, built once at import. Empty for every name whose real
#: module is importable, so a sourced ROS 2 workspace ends up with {}.
_STUB_MODULES: dict = {}

#: sys.modules keys currently displaced by a stub -> their previous value
#: (or _MISSING). Non-empty only while the stubs are installed.
_ORIGINAL_MODULES: dict = {}

#: Nesting depth of :func:`ros_stubs`, so the collect-time and run-time
#: windows can overlap without the inner one uninstalling early.
_DEPTH = 0


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


def _new_stub(name: str) -> types.ModuleType:
    """Build a fresh empty stub for *name* and register it.

    Nothing is written to ``sys.modules`` here — see :func:`ros_stubs`.
    """
    module = types.ModuleType(name)
    module.__selene_test_stub__ = True
    module.__path__ = []               # behave like a package
    _STUB_MODULES[name] = module
    return module


def _stub_module(name: str, probe: str | None = None):
    """Return a stub module for *name*, or ``None`` if the real one exists.

    ``None`` is the signal to callers to leave the real module completely
    alone — no attribute writes, no replacement.
    """
    existing = _STUB_MODULES.get(name)
    if existing is not None:
        return existing                # our own stub, from an earlier call
    if _real_module(name, probe) is not None:
        return None
    return _new_stub(name)


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
    stub_parent = _STUB_MODULES.get(name) or _new_stub(name)
    for child in children:
        child_module = _STUB_MODULES.get(child)
        if child_module is not None:
            setattr(stub_parent, child.rpartition('.')[2], child_module)


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

    # QoS. orchestrator_node builds an explicit RELIABLE + TRANSIENT_LOCAL
    # profile for the two ledger topics (MaterialEvent, TaskResult), so the
    # names have to resolve at import even with no ROS present. Enum values are
    # spelled out to match rclpy's rather than left as MagicMocks, which would
    # compare equal to nothing and silently pass a wrong-policy assertion.
    #
    # Real rclpy.qos also exports ReliabilityPolicy / DurabilityPolicy /
    # HistoryPolicy as aliases of the QoS*-prefixed names, and selene_hal's
    # Gazebo backend imports those. They are deliberately NOT added here: this
    # stub is not a substitute for rclpy for anybody but the orchestrator, and
    # rule 4 (scoping) is what keeps that from mattering. Adding the aliases
    # would let selene_hal.gazebo_hal import against fakes instead of skipping.
    rclpy_qos = _stub_module('rclpy.qos', probe='QoSProfile')
    if rclpy_qos is not None:
        class _QoSProfile:
            def __init__(self, **kwargs):
                self.depth = kwargs.pop('depth', 10)
                for key, value in kwargs.items():
                    setattr(self, key, value)

        class _QoSReliabilityPolicy:
            SYSTEM_DEFAULT = 0
            RELIABLE = 1
            BEST_EFFORT = 2

        class _QoSDurabilityPolicy:
            SYSTEM_DEFAULT = 0
            TRANSIENT_LOCAL = 1
            VOLATILE = 2

        class _QoSHistoryPolicy:
            SYSTEM_DEFAULT = 0
            KEEP_LAST = 1
            KEEP_ALL = 2

        rclpy_qos.QoSProfile = _QoSProfile
        rclpy_qos.QoSReliabilityPolicy = _QoSReliabilityPolicy
        rclpy_qos.QoSDurabilityPolicy = _QoSDurabilityPolicy
        rclpy_qos.QoSHistoryPolicy = _QoSHistoryPolicy

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

    _ensure_stub_parent('rclpy', ('rclpy.callback_groups', 'rclpy.executors',
                                  'rclpy.qos', 'rclpy.node'))


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


def _stub_std_and_viz_msgs() -> None:
    """Stub the std_msgs / visualization_msgs / builtin_interfaces surface.

    orchestrator_node imports these for the FR-MAP-4 overlay. They are ordinary
    ROS 2 interface packages, so on a machine with a sourced workspace the real
    ones win and none of this runs; in the pure-Python CI lane, where the e2e
    test imports orchestrator_node with no ROS at all, these keep the import
    graph resolvable.

    Only the names orchestrator_node uses are here. ``Float32`` / ``Bool`` /
    ``String``, which selene_hal and selene_sim import from ``std_msgs.msg``,
    are deliberately absent — see the note in ``_stub_rclpy``.
    """
    std_msg = _stub_module('std_msgs.msg', probe='Header')
    if std_msg is not None:
        class _Header:
            def __init__(self, stamp=None, frame_id=''):
                self.stamp = stamp if stamp is not None else MagicMock()
                self.frame_id = frame_id

        class _ColorRGBA:
            def __init__(self, r=0.0, g=0.0, b=0.0, a=0.0):
                self.r, self.g, self.b, self.a = (
                    float(r), float(g), float(b), float(a))

        std_msg.Header = _Header
        std_msg.ColorRGBA = _ColorRGBA
        _ensure_stub_parent('std_msgs', ('std_msgs.msg',))

    bi_msg = _stub_module('builtin_interfaces.msg', probe='Duration')
    if bi_msg is not None:
        class _Duration:
            def __init__(self, sec=0, nanosec=0):
                self.sec = int(sec)
                self.nanosec = int(nanosec)

        class _Time:
            def __init__(self, sec=0, nanosec=0):
                self.sec = int(sec)
                self.nanosec = int(nanosec)

        bi_msg.Duration = _Duration
        bi_msg.Time = _Time
        _ensure_stub_parent('builtin_interfaces', ('builtin_interfaces.msg',))

    viz_msg = _stub_module('visualization_msgs.msg', probe='Marker')
    if viz_msg is not None:
        class _Vec3:
            def __init__(self):
                self.x = self.y = self.z = 0.0

        class _Quat:
            def __init__(self):
                self.x = self.y = self.z = 0.0
                self.w = 0.0

        class _Pose:
            def __init__(self):
                self.position = _Vec3()
                self.orientation = _Quat()

        class _Marker:
            # The constants orchestrator_node names. CUBE_LIST is 6; 8 is
            # POINTS. Getting these wrong renders the wrong primitive, so they
            # are spelled out rather than left as MagicMock attributes, which
            # would compare equal to nothing and silently pass.
            ARROW = 0
            CUBE = 1
            SPHERE = 2
            CYLINDER = 3
            LINE_STRIP = 4
            LINE_LIST = 5
            CUBE_LIST = 6
            SPHERE_LIST = 7
            POINTS = 8
            ADD = 0
            DELETE = 2
            DELETEALL = 3

            def __init__(self):
                self.header = MagicMock()
                self.ns = ''
                self.id = 0
                self.type = 0
                self.action = 0
                self.pose = _Pose()
                self.scale = _Vec3()
                self.color = None
                self.lifetime = None
                self.points = []
                self.colors = []

        class _MarkerArray:
            def __init__(self, markers=None):
                self.markers = list(markers) if markers else []

        viz_msg.Marker = _Marker
        viz_msg.MarkerArray = _MarkerArray
        _ensure_stub_parent('visualization_msgs', ('visualization_msgs.msg',))


class _Twist:
    """``geometry_msgs/Twist``-shaped stand-in for ``RobotState.velocity``.

    A ``MagicMock`` until 2026-07-31, which was fine only while nothing read
    it. The orchestrator now does: ``_on_robot_state`` passes
    ``msg.velocity.linear.x`` and ``msg.velocity.angular.z`` into
    ``FleetMonitor.update_robot`` for D-30's wheels-turning-body-not clause,
    and ``float(MagicMock())`` raises ``TypeError``. Real floats here mean a
    test that drives that path fails on its assertion rather than on the stub.
    """

    class _Vec3:
        def __init__(self):
            self.x = self.y = self.z = 0.0

    def __init__(self):
        self.linear = _Twist._Vec3()
        self.angular = _Twist._Vec3()


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
            ('MaterialEvent', {
                'event_id': '', 'robot_id': '', 'task_id': '',
                'event_type': '', 'mass_kg': 0.0, 'residual_mass_kg': 0.0,
                'stamp': lambda: MagicMock(),
            }),
            ('MissionProgress', {
                'objective_description': '', 'target_quantity': 0.0,
                'extracted_quantity': 0.0, 'in_transit_quantity': 0.0,
                'deposited_quantity': 0.0, 'fleet_distance_total': 0.0,
                'fleet_energy_total': 0.0, 'elapsed_sim_time': 0.0,
                # Appended 2026-07-30 closing D-06.
                'fleet_uptime_sec': 0.0, 'material_events_applied': 0,
                'at_site_quantity': 0.0, 'unaccounted_quantity': 0.0,
            }),
            ('ResourceMap', {
                # FR-MAP-1(e). Sparse snapshot: four parallel per-cell arrays
                # plus the geometry needed to place them.
                'header': lambda: MagicMock(), 'resolution': 0.0,
                'width': 0, 'height': 0, 'origin': point_cls,
                'prior_mean': 0.0, 'prior_variance': 0.0,
                'total_observations': 0,
                'cell_index': list, 'cell_mean': list,
                'cell_variance': list, 'cell_observation_count': list,
            }),
            ('ResourceMapUpdate', {
                # scout_id and stamp were missing here from the start; they are
                # in the .msg and test_conftest_mirrors_msgs.py now enforces it.
                'scout_id': '', 'location': point_cls,
                'ice_concentration': 0.0, 'sensor_uncertainty': 0.0,
                'stamp': lambda: MagicMock(),
            }),
            ('RobotState', {
                'robot_id': '', 'robot_type': '', 'fsm_state': '',
                'pose': point_cls, 'velocity': _Twist,
                'battery_level': 1.0, 'current_task_id': '',
                'task_progress': 0.0, 'capabilities': list,
                'stamp': lambda: MagicMock(),
                # Appended 2026-07-30 closing D-06 (FR-DASH-7 energy clause).
                'battery_capacity_wh': 0.0,
                # Appended 2026-07-31 closing D-31. TRUE HERE, FALSE ON THE
                # WIRE, and the disagreement is deliberate. ROS 2
                # default-initialises bool to false, which is the fail-safe
                # direction for a real publisher that has not set it. This stub
                # is used to BUILD messages inside tests, where every existing
                # construction means "a robot with a pose"; defaulting it false
                # here would silently drop those robots out of the distance
                # total and the survey centroid and every affected test would
                # go green on the wrong reason. A test that wants the no-fix
                # case sets it explicitly.
                'pose_valid': True,
            }),
            ('TaskAnnouncement', {
                'task_id': '', 'task_type': '', 'target_location': point_cls,
                'estimated_energy_cost': 0.0, 'required_capabilities': list,
                'priority': 0.0, 'estimated_duration': 0.0,
                'parent_task_id': '', 'deadline': lambda: MagicMock(),
                # Appended 2026-07-30 closing D-04.
                'quantity_kg': 0.0,
            }),
            ('TaskAssignment', {
                'task_id': '', 'robot_id': '', 'task_type': '',
                'target_location': point_cls, 'parameters': list,
                'assigned_at': lambda: MagicMock(),
                # Appended 2026-07-30 closing D-04 and D-06.
                'quantity_kg': 0.0, 'depot_location': point_cls,
            }),
            ('TaskEvent', {
                'seq': 0, 'stamp': lambda: MagicMock(), 'kind': '',
                'task_id': '', 'robot_id': '', 'actor': '', 'action': '',
                'detail': '', 'accepted': False, 'target': point_cls,
            }),
            ('TaskQueueState', {
                'header': lambda: MagicMock(), 'tasks': list, 'events': list,
                'event_seq_next': 0, 'events_dropped': 0,
            }),
            ('TaskResult', {
                'task_id': '', 'robot_id': '', 'task_type': '',
                'success': False, 'failure_reason': '',
                'stamp': lambda: MagicMock(),
            }),
            # NB the class name TaskStatus collides with
            # selene_orchestrator.task_queue.TaskStatus, the enum. Nothing here
            # can prevent that; orchestrator_node.py imports the message as
            # ``TaskStatus as TaskStatusMsg``, mirroring the existing
            # ``ResourceMap as ResourceMapMsg`` aliasing.
            ('TaskStatus', {
                'task_id': '', 'task_type': '', 'status': '',
                'assigned_robot': '', 'preferred_robot': '', 'priority': 0.0,
                'progress': 0.0, 'quantity_kg': 0.0,
                'target_location': point_cls, 'parent_task_id': '',
                'depends_on': list, 'required_capabilities': list,
                'status_reason': '', 'status_changed': lambda: MagicMock(),
                'auction_rounds': 0,
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
            return {'extracted': 0.0, 'at_site': 0.0, 'in_transit': 0.0,
                    'deposited': 0.0, 'unaccounted': 0.0}

        def get_total_deposited(self):
            return 0.0

        def get_unaccounted_kg(self):
            return 0.0

        def check_conservation(self, tolerance=0.01):
            return True

    sisru_inv.MaterialInventory = _MaterialInventory
    _ensure_stub_parent('selene_isru', ('selene_isru.inventory',))


def build_ros_stubs() -> dict:
    """Build every stub needed to import ``orchestrator_node``.

    Idempotent, and a no-op for any module that is really available — on a
    sourced ROS 2 workspace this returns ``{}``. Nothing is written to
    ``sys.modules``; see :func:`ros_stubs` for that.
    """
    _stub_rclpy()
    point_cls = _stub_geometry_msgs()
    _stub_std_and_viz_msgs()
    _stub_selene_msgs(point_cls)
    _stub_selene_isru_if_missing()
    return _STUB_MODULES


# --------------------------------------------------------------------------- #
#  Scoped installation (rule 4)                                               #
# --------------------------------------------------------------------------- #

def _install() -> None:
    global _DEPTH
    _DEPTH += 1
    if _DEPTH > 1:
        return                         # already in force; keep the outer window
    for name, module in _STUB_MODULES.items():
        _ORIGINAL_MODULES[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = module


def _uninstall() -> None:
    global _DEPTH
    _DEPTH = max(0, _DEPTH - 1)
    if _DEPTH:
        return
    for name, original in _ORIGINAL_MODULES.items():
        if sys.modules.get(name) is not _STUB_MODULES.get(name):
            continue                   # someone replaced it; leave it be
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    _ORIGINAL_MODULES.clear()


@contextlib.contextmanager
def ros_stubs():
    """Make the stubs visible in ``sys.modules`` for the enclosed block only."""
    _install()
    try:
        yield
    finally:
        _uninstall()


build_ros_stubs()


def _is_ours(collector) -> bool:
    """True when *collector* lives under this conftest's directory.

    ``pytest_make_collect_report`` is a global hook: once this conftest is
    loaded it fires for every collector in the session, including
    ``selene_hal``'s. The path filter is what keeps rule 4 true.
    """
    path = getattr(collector, 'path', None) or getattr(collector, 'fspath', None)
    if path is None:
        return False
    key = os.path.normcase(os.path.abspath(str(path)))
    return key == _TEST_DIR_KEY or key.startswith(_TEST_DIR_KEY + os.sep)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    """Window 1 — importing a test module in this directory.

    ``Module.collect()`` is what runs a test module's top-level
    ``from selene_orchestrator.orchestrator_node import ...``, and pytest
    calls it from inside this hook. Wrapping the hook rather than importing
    eagerly at conftest time keeps this file free of any third-party
    dependency: the ``gate-coverage`` CI job installs pytest alone and
    collects ``test_phase5_gate_coverage.py`` through this conftest, so an
    eager ``import orchestrator_node`` here would drag numpy in and break it.
    """
    if _is_ours(collector):
        with ros_stubs():
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def _ros_stubs_in_force():
    """Window 2 — running a test in this directory.

    Autouse fixtures declared in a conftest apply to that directory only, so
    this never fires for ``selene_hal`` / ``selene_agent`` / ``selene_sim`` /
    ``selene_isru``. ``test_conftest_mirrors_msgs.py`` reads
    ``sys.modules['selene_msgs.msg']`` at call time and needs the stub to be
    in force then, not merely to have been.
    """
    with ros_stubs():
        yield


# --------------------------------------------------------------------------- #
#  Teardown                                                                   #
# --------------------------------------------------------------------------- #

def pytest_sessionfinish(session, exitstatus):
    """Backstop. Both windows are ``try``/``finally``-scoped, so by here
    ``_ORIGINAL_MODULES`` is already empty; this only matters if a future
    edit introduces a third window that leaks."""
    global _DEPTH
    _DEPTH = 1
    _uninstall()
