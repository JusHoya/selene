"""An operator cannot send a robot off the map.

WHY THIS EXISTS
FR-DASH-5 lets an operator inject a task at any coordinate they click and
FR-DASH-6 lets them send a robot to any coordinate, and until 2026-07-31 nothing
bounded either number: ``inject_task_logic`` validated ``task_type`` and
``quantity`` and passed ``target_location`` straight onto the queue.

That was survivable only while every pose in the system was dead-reckoned odom
and no coordinate meant anything physical. It means something now. Past the edge
of the 500 m heightfield there is no collision surface: the robot falls, and the
falling body's AABB leaves the integer range ODE's broadphase converts it into --

    ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact &&
    aabbBound < dMaxIntExact" failed in collide() [collision_space.cpp:460]

-- which the operator measured three times on 2026-07-30/31, each time taking
Gazebo, the whole fleet and the gate down with it. A typo in one field must not
be able to do that.

WHAT IT ASSERTS
  * the box comes from configuration and is centred, square and margined
  * an off-terrain injection is REFUSED, with the coordinate and the box in the
    message, and leaves NO task behind (not even a FAILED one)
  * an off-terrain ``send_to_location`` is refused before any state is touched
  * ``cancel_task`` and ``force_recharge`` are NOT bounded -- they ignore
    ``request.target``, and refusing them on a field they never read would be a
    lie about why
  * every real mission coordinate is still accepted
"""
from __future__ import annotations

import math
import types
from unittest.mock import MagicMock

import pytest

from selene_orchestrator.orchestrator_node import (  # noqa: E402
    _InjectTaskContext,
    _OverrideRobotContext,
    inject_task_logic,
    override_robot_logic,
)
from selene_orchestrator.task_queue import TaskQueue  # noqa: E402
from selene_orchestrator.terrain_guard import (  # noqa: E402
    DEFAULT_TERRAIN_GUARD,
    DEFAULT_TERRAIN_HALF_EXTENT_M,
    DEFAULT_TERRAIN_MARGIN_M,
    TerrainGuard,
)


#: Coordinates the mission really uses. None of them may be refused.
MISSION_POINTS = [
    (-100.0, -150.0),   # PSR / survey zone centre
    (-80.0, -140.0),    # deposit_alpha
    (-110.0, -170.0),   # deposit_beta
    (-90.0, -130.0),    # deposit_gamma
    (-120.0, -155.0),   # deposit_delta
    (50.0, 50.0),       # depot_x / depot_y
    (-30.0, -100.0),    # recharge station
    (-45.0, -92.0),     # scout_01 spawn
]

#: Coordinates that must be refused. The first two are what the operator's
#: measured abort names; the rest are ordinary typos.
OFF_MAP_POINTS = [
    (-159.0, -248.0),
    (-145.0, -255.0),
    (400.0, 400.0),
    (0.0, -1000.0),
    (-2360.0, -100.0),
    (float('nan'), 0.0),
    (float('inf'), float('inf')),
]


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


class _FakeOverrideRequest:
    def __init__(self, robot_id='scout_01', command='send_to_location',
                 x=0.0, y=0.0):
        self.robot_id = robot_id
        self.command = command
        self.target = types.SimpleNamespace(x=x, y=y, z=0.0)


class _FakeOverrideResponse:
    def __init__(self):
        self.success = False
        self.message = ''


@pytest.fixture
def task_queue():
    return TaskQueue()


@pytest.fixture
def fleet_monitor():
    fm = MagicMock()
    fm._robots = {'scout_01': {
        'robot_id': 'scout_01', 'fsm_state': 'IDLE',
        'capabilities': ['prospect'], 'current_task_id': '',
    }}
    fm.get_robot.side_effect = lambda rid: fm._robots.get(rid)
    return fm


@pytest.fixture
def inject_ctx(task_queue, fleet_monitor):
    counter = {'n': 0}

    def _next_id():
        counter['n'] += 1
        return f'manual_{counter["n"]:04d}'

    return _InjectTaskContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        next_task_id=_next_id,
        now_stamp=None,
        publish_alert=MagicMock(),
        site_id='site_alpha',
    )


@pytest.fixture
def override_ctx(task_queue, fleet_monitor):
    client = MagicMock()
    client.wait_for_service.return_value = True
    future = MagicMock()
    future.done.return_value = True
    future.result.return_value = types.SimpleNamespace(
        accepted=True, reason='ok')
    client.call_async.return_value = future
    return _OverrideRobotContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        set_command_clients={'scout_01': client},
        next_sequence=lambda: 1,
        spin_until_complete=lambda fut: None,
        publish_alert=MagicMock(),
        set_command_factory=lambda: types.SimpleNamespace(
            command='', target=None, sequence=0),
    )


# --------------------------------------------------------------------- the box

def test_the_default_guard_is_the_shipped_world():
    assert DEFAULT_TERRAIN_GUARD.half_extent == DEFAULT_TERRAIN_HALF_EXTENT_M
    assert DEFAULT_TERRAIN_GUARD.margin == DEFAULT_TERRAIN_MARGIN_M
    assert DEFAULT_TERRAIN_GUARD.limit == pytest.approx(240.0)


def test_a_context_built_without_a_guard_is_still_guarded(task_queue,
                                                          fleet_monitor):
    """The default is a real guard, never None.

    A guard that switches itself off when a caller forgets to configure it is
    worse than no guard: it reads as protection. Every ``_InjectTaskContext``
    and ``_OverrideRobotContext`` in the tree gets the shipped box unless one is
    passed explicitly.
    """
    ctx = _InjectTaskContext(
        task_queue=task_queue, fleet_monitor=fleet_monitor,
        next_task_id=lambda: 'manual_0001', now_stamp=None,
        publish_alert=MagicMock(),
    )
    assert ctx.terrain is DEFAULT_TERRAIN_GUARD
    response = inject_task_logic(
        ctx, _FakeInjectRequest(x=-159.0, y=-248.0), _FakeInjectResponse())
    assert response.success is False


def test_a_degenerate_guard_refuses_everything_rather_than_nothing():
    """A margin larger than the world must not invert into 'anything goes'."""
    guard = TerrainGuard(half_extent=5.0, margin=50.0)
    assert guard.limit == 0.0
    assert guard.contains(0.0, 0.0) is True
    assert guard.contains(0.1, 0.0) is False


# ------------------------------------------------------------------ injection

@pytest.mark.parametrize('x,y', OFF_MAP_POINTS)
def test_off_terrain_injection_is_refused(inject_ctx, task_queue, x, y):
    response = inject_task_logic(
        inject_ctx, _FakeInjectRequest(task_type='prospect', x=x, y=y),
        _FakeInjectResponse())
    assert response.success is False
    assert 'off the terrain' in response.message
    assert '240' in response.message


@pytest.mark.parametrize('x,y', OFF_MAP_POINTS)
def test_a_refused_injection_leaves_no_row_behind(inject_ctx, task_queue, x, y):
    """Not even a FAILED one.

    The other rejections in this handler that run AFTER ``add_task`` have to
    mark their phantom row FAILED; this one is checked before, so the queue is
    untouched. A rejected coordinate never existed as a task and the task panel
    should not imply it did.
    """
    before = task_queue.get_total_count()
    inject_task_logic(inject_ctx, _FakeInjectRequest(x=x, y=y),
                      _FakeInjectResponse())
    assert task_queue.get_total_count() == before
    assert not task_queue.get_all_tasks()


@pytest.mark.parametrize('task_type', ['prospect', 'excavate', 'haul'])
def test_every_task_type_is_bounded(inject_ctx, task_type):
    """A survey waypoint off the map drives a scout off the map.

    The check is before the task-type-specific validation on purpose, so
    ``prospect`` -- which needs no ledger site and is the type
    ``scripts/phase5_probe.py`` injects -- is covered too.
    """
    response = inject_task_logic(
        inject_ctx, _FakeInjectRequest(task_type=task_type, x=0.0, y=-999.0),
        _FakeInjectResponse())
    assert response.success is False
    assert 'off the terrain' in response.message


@pytest.mark.parametrize('x,y', MISSION_POINTS)
def test_mission_coordinates_are_accepted(inject_ctx, x, y):
    response = inject_task_logic(
        inject_ctx, _FakeInjectRequest(task_type='prospect', x=x, y=y),
        _FakeInjectResponse())
    assert response.success is True, response.message


def test_the_boundary_itself_is_admissible(inject_ctx):
    """Exactly on the safe edge is in. The margin already carries the slack."""
    response = inject_task_logic(
        inject_ctx, _FakeInjectRequest(x=240.0, y=-240.0),
        _FakeInjectResponse())
    assert response.success is True, response.message


def test_the_message_names_the_coordinate_back(inject_ctx):
    """The usual cause is one extra digit, and an operator shown it sees it."""
    response = inject_task_logic(
        inject_ctx, _FakeInjectRequest(x=-2360.0, y=-100.0),
        _FakeInjectResponse())
    assert '-2360.0' in response.message
    assert '-100.0' in response.message


# ------------------------------------------------------------------- override

@pytest.mark.parametrize('x,y', OFF_MAP_POINTS)
def test_off_terrain_send_to_location_is_refused(override_ctx, x, y):
    response = override_robot_logic(
        override_ctx, _FakeOverrideRequest(command='send_to_location', x=x, y=y),
        _FakeOverrideResponse())
    assert response.success is False
    assert 'off the terrain' in response.message


def test_a_refused_override_never_reaches_the_agent(override_ctx):
    """Checked before the robot lookup, so nothing half-applies.

    The commands that interrupt a task do so partway down this function. A
    target rejection that happened later could requeue the robot's work and then
    refuse -- an operator error costing a running task.
    """
    client = override_ctx.set_command_clients['scout_01']
    override_robot_logic(
        override_ctx,
        _FakeOverrideRequest(command='send_to_location', x=0.0, y=-9000.0),
        _FakeOverrideResponse())
    client.call_async.assert_not_called()
    override_ctx.fleet_monitor.get_robot.assert_not_called()


def test_a_refused_override_is_alerted(override_ctx):
    """It goes in the event ring and the alert log like every other override."""
    override_robot_logic(
        override_ctx,
        _FakeOverrideRequest(command='send_to_location', x=900.0, y=0.0),
        _FakeOverrideResponse())
    override_ctx.publish_alert.assert_called_once()
    severity, message = override_ctx.publish_alert.call_args[0]
    assert severity == 'WARNING'
    assert 'off the terrain' in message


@pytest.mark.parametrize('command', ['cancel_task', 'force_recharge'])
def test_commands_that_ignore_the_target_are_not_bounded(override_ctx, command):
    """Deliberate. Neither reads ``request.target``.

    The dashboard sends whatever is in the coordinate boxes on every override,
    so a bound applied to all three would refuse a perfectly valid
    ``force_recharge`` because of a stale number in a field the command does not
    use -- and, worse, would refuse ``cancel_task``, which is the operator's only
    way out of ERROR (see OVERRIDE_BLOCKED_STATE_EXEMPT_COMMANDS).
    """
    response = override_robot_logic(
        override_ctx, _FakeOverrideRequest(command=command, x=0.0, y=-9000.0),
        _FakeOverrideResponse())
    assert response.success is True, response.message


@pytest.mark.parametrize('x,y', MISSION_POINTS)
def test_send_to_location_accepts_mission_coordinates(override_ctx, x, y):
    response = override_robot_logic(
        override_ctx, _FakeOverrideRequest(command='send_to_location', x=x, y=y),
        _FakeOverrideResponse())
    assert response.success is True, response.message


# ----------------------------------------------------- agreement with the agent

def test_the_orchestrator_and_the_agent_refuse_the_same_box():
    """Two guards, one box. A disagreement is worse than either alone.

    A wider orchestrator box accepts targets the agent then refuses, which
    presents to the operator as a task that was accepted and then failed for no
    stated reason. A narrower one refuses targets that are perfectly drivable.
    The values are pinned across the four configuration files by
    ``selene_sim/test/test_world_extent_agrees.py``; this pins the two
    IMPLEMENTATIONS against each other on the same numbers.

    D-36. This import used to be unguarded, and it made THE GATE LANE red --
    ``PYTHONPATH="selene_orchestrator;selene_isru" pytest selene_orchestrator/test
    selene_isru/test``, which is the lane CI's ``e2e-integration`` job declares
    and the one this register calls the gate. ``selene_agent`` is not on that
    path, so a cross-package agreement test cannot run there and must say so
    rather than error. It DOES run on the cross-package lane, which is where the
    agreement is actually checked.

    This is D-14 from the opposite direction: that deviation was a stub leaking
    ACROSS packages and aborting collection; this one is a test reaching across
    packages on a lane that deliberately has only two. Both are invisible unless
    some job runs the narrow lane and some other job runs the wide one -- CI now
    does both (``e2e-integration`` and ``cross-package-tests``), which is what
    makes this skip safe rather than a hiding place.
    """
    navigator = pytest.importorskip(
        'selene_agent.navigator',
        reason='cross-package agreement check; selene_agent is not on the gate '
               'lane PYTHONPATH (D-36). Runs on the cross-package lane.',
    )
    OccupancyGrid = navigator.OccupancyGrid

    grid = OccupancyGrid(
        width=int(2 * DEFAULT_TERRAIN_HALF_EXTENT_M),
        height=int(2 * DEFAULT_TERRAIN_HALF_EXTENT_M),
        resolution=1.0,
        origin_x=-DEFAULT_TERRAIN_HALF_EXTENT_M,
        origin_y=-DEFAULT_TERRAIN_HALF_EXTENT_M,
        terrain_margin=DEFAULT_TERRAIN_MARGIN_M,
    )
    guard = TerrainGuard()
    probes = MISSION_POINTS + [
        (239.9, 0.0), (240.0, 0.0), (240.1, 0.0),
        (0.0, -239.9), (0.0, -240.0), (0.0, -240.1),
        (-159.0, -248.0), (1000.0, 1000.0),
        (float('nan'), 0.0), (0.0, float('inf')),
    ]
    for x, y in probes:
        assert guard.contains(x, y) is grid.is_on_terrain(x, y), (
            f'({x}, {y}): orchestrator says {guard.contains(x, y)}, agent says '
            f'{grid.is_on_terrain(x, y)}')


def test_the_guard_leaves_the_working_area_alone():
    """Every mission coordinate is far inside, so the bound is not marginal."""
    guard = TerrainGuard()
    worst = min(guard.limit - max(abs(x), abs(y)) for x, y in MISSION_POINTS)
    assert worst > 40.0, (
        f'the tightest mission coordinate is only {worst:.1f} m inside the '
        f'{guard.limit:.0f} m box')
    assert math.isfinite(worst)
