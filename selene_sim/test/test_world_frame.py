"""The odom -> world transform, and the terrain box, checked without Gazebo.

WHY THIS EXISTS
Robot position was expressed in each robot's dead-reckoned odom frame and
consumed everywhere as if it were world. Gazebo's DiffDrive integrates wheel
encoders from a pose of (0, 0, 0), so odom (0, 0) is wherever the robot spawned
and the odom x-axis points along its SPAWN HEADING; every spawn in
``spawn_positions.yaml`` carries ``yaw: -2.33``. The system therefore mis-indexed
the resource map, tested solar shadow at the wrong place, and drove robots
toward coordinates a long way from the ones it named.

WHAT IT ASSERTS
  * the transform is a full SE(2) composition, pinned to hand-computed values
  * DROPPING THE ROTATION IS CAUGHT. This is the point of the file: a
    translation-only transform agrees exactly at the spawn point and diverges
    with range, so a test that only checks near the origin passes on the wrong
    arithmetic.
  * world -> odom -> world round trips to machine precision, over the real
    spawns and real mission coordinates
  * heading composition wraps into (-pi, pi]
  * velocities are frame-invariant (they are body-frame, and re-parenting the
    pose frame must not touch them)
  * EVERY robot in the ten-robot fleet, targeting every deposit in
    ``ice_deposits.yaml``, the depot, the recharge station and every generated
    survey waypoint, stays inside the terrain bound
  * the terrain box refuses what it must, including non-finite coordinates

WHAT IT CANNOT ASSERT
Which frame Gazebo's DiffDrive actually publishes in. That is read off the
plugin's API (``gz::math::DiffDriveOdometry::Init`` zeroes the pose, and
``Update`` is given joint positions only, so it cannot see the model's world
orientation) and is MEASURED by ``scripts/check_drive.sh``, which compares the
bearing of the world displacement against the bearing of the odom displacement
on a real drive and fails if the difference is closer to 0 than to the spawn
yaw. Nothing here runs Gazebo.
"""

import math
import os
import sys

import pytest
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_REPO = os.path.dirname(_PKG)
sys.path.insert(0, _PKG)

from selene_sim.world_frame import (          # noqa: E402
    DEFAULT_SAFETY_MARGIN_M,
    WORLD_ODOM_TOPIC,
    SpawnPose,
    TerrainBounds,
    odom_to_world,
    world_to_odom,
    wrap_angle,
    yaw_to_quaternion,
    quaternion_multiply,
)

SPAWNS_YAML = os.path.join(_PKG, 'config', 'spawn_positions.yaml')
ICE_YAML = os.path.join(_PKG, 'config', 'ice_deposits.yaml')
WORLD_YAML = os.path.join(_PKG, 'config', 'world_params.yaml')

#: The shipped spawn heading. Not a magic number: it is
#: ``atan2(-150 - -92, -100 - -45) = -2.3300``, the world bearing from the spawn
#: ring to the PSR centre, which is why every entry in spawn_positions.yaml
#: carries it.
SHIPPED_YAW = -2.33


@pytest.fixture(scope='module')
def spawns():
    """``[(robot_id, SpawnPose)]`` for the whole ten-robot fleet."""
    with open(SPAWNS_YAML) as handle:
        config = yaml.safe_load(handle)
    fleet = []
    for group, robot_type in (('scouts', 'scout'), ('excavators', 'excavator'),
                              ('haulers', 'hauler')):
        for index, entry in enumerate(config[group], start=1):
            fleet.append((f'{robot_type}_{index:02d}',
                          SpawnPose.from_mapping(entry)))
    return fleet


@pytest.fixture(scope='module')
def bounds():
    return TerrainBounds.from_world_params(WORLD_YAML)


def _survey_zone():
    """``(centre, radius)`` read out of ``orchestrator_node.py`` by AST.

    PARSED, NOT IMPORTED. ``orchestrator_node`` imports rclpy at module scope
    and this lane has no ROS; ``htn_planner`` does not, which is why the
    waypoint generator below is imported normally. Copying the two numbers here
    instead was the obvious alternative and is exactly the failure mode the
    constants' own comment describes -- they used to be written out twice and
    only coincidence kept them equal.
    """
    import ast

    path = os.path.join(_REPO, 'selene_orchestrator', 'selene_orchestrator',
                        'orchestrator_node.py')
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target in ('SURVEY_ZONE_CENTER', 'SURVEY_ZONE_RADIUS'):
            found[target] = ast.literal_eval(node.value)
    assert set(found) == {'SURVEY_ZONE_CENTER', 'SURVEY_ZONE_RADIUS'}, (
        f'could not read the survey zone out of {path}; found {sorted(found)}')
    return found['SURVEY_ZONE_CENTER'], float(found['SURVEY_ZONE_RADIUS'])


@pytest.fixture(scope='module')
def mission_targets():
    """Every world coordinate the mission commands a robot to drive to.

    The survey waypoints come from the orchestrator's own generator rather than
    a copy of it, so a change to the lattice is covered here automatically.
    """
    sys.path.insert(0, os.path.join(_REPO, 'selene_orchestrator'))
    from selene_orchestrator.htn_planner import _generate_survey_waypoints

    SURVEY_ZONE_CENTER, SURVEY_ZONE_RADIUS = _survey_zone()

    with open(ICE_YAML) as handle:
        ice = yaml.safe_load(handle)

    targets = [(d['id'], (float(d['center'][0]), float(d['center'][1])))
               for d in ice['deposits']]
    # READ, not copied. This was the literal (50.0, 50.0) with the comment
    # "orchestrator depot_x/_y" beside it, which is a copy of a config value
    # and therefore a thing that can go stale silently -- and did, the moment
    # the depot moved to the crater floor on 2026-07-31. Read the file the
    # orchestrator reads.
    with open(os.path.join(_REPO, 'selene_orchestrator', 'config',
                           'orchestrator_params.yaml')) as handle:
        orch = yaml.safe_load(handle)['orchestrator_node']['ros__parameters']
    targets.append(('depot', (float(orch['depot_x']), float(orch['depot_y']))))
    targets.append(('recharge_station', (-30.0, -100.0)))
    targets.append(('survey_zone_centre', SURVEY_ZONE_CENTER))
    for i, point in enumerate(
            _generate_survey_waypoints(SURVEY_ZONE_CENTER, SURVEY_ZONE_RADIUS)):
        targets.append((f'survey_waypoint_{i}', point))
    return targets


# ------------------------------------------------------------------ the SE(2)

def test_spawn_is_the_odom_origin():
    """odom (0, 0, 0) is the spawn pose, by construction and in every robot."""
    spawn = SpawnPose(x=-45.0, y=-92.0, z=1.75, yaw=SHIPPED_YAW)
    x, y, theta = odom_to_world(0.0, 0.0, 0.0, spawn)
    assert (x, y) == pytest.approx((-45.0, -92.0), abs=1e-12)
    assert theta == pytest.approx(SHIPPED_YAW, abs=1e-12)


@pytest.mark.parametrize('odom_xy,expected', [
    ((10.0, 0.0), (-51.883440, -99.253844)),
    ((0.0, 10.0), (-37.746156, -98.883440)),
    ((-100.0, -150.0), (-84.973256, 83.790042)),
    ((50.0, 50.0), (-43.147982, -162.686420)),
])
def test_transform_is_pinned_to_hand_computed_values(odom_xy, expected):
    """Four points through scout_01's spawn, computed by hand off cos/sin(-2.33).

    cos(-2.33) = -0.6883440204, sin(-2.33) = -0.7253843875, so
    ``x_w = -45 + cos*x_o - sin*y_o`` and ``y_w = -92 + sin*x_o + cos*y_o``.
    Pinned rather than re-derived in the assertion, because a test that recomputes
    the implementation cannot disagree with it.
    """
    spawn = SpawnPose(x=-45.0, y=-92.0, z=1.75, yaw=SHIPPED_YAW)
    x, y, _ = odom_to_world(odom_xy[0], odom_xy[1], 0.0, spawn)
    assert (x, y) == pytest.approx(expected, abs=1e-6)


def test_dropping_the_rotation_is_caught():
    """THE test in this file. A translation-only transform must not pass.

    It is the plausible wrong implementation: it is exact at the spawn point, it
    produces smooth trajectories, and it agrees with the right answer to within
    a metre for the first ~0.4 m of travel. It is wrong by up to 2 * r at range
    r, and the first survey leg is 180 m.

    Asserted at three ranges so a partial rotation (a wrong sign, a half angle,
    degrees for radians) is caught too: the gap must GROW with range, which no
    rotation-free form can do.
    """
    spawn = SpawnPose(x=-45.0, y=-92.0, z=1.75, yaw=SHIPPED_YAW)
    previous = -1.0
    for radius, minimum_gap in ((1.0, 1.0), (10.0, 15.0), (180.0, 280.0)):
        wx, wy, _ = odom_to_world(radius, 0.0, 0.0, spawn)
        translation_only = (spawn.x + radius, spawn.y)
        gap = math.hypot(wx - translation_only[0], wy - translation_only[1])
        assert gap > minimum_gap, (
            f'at odom ({radius}, 0) the SE(2) transform lands at '
            f'({wx:.3f}, {wy:.3f}) and a translation-only one at '
            f'{translation_only}; they differ by only {gap:.3f} m, so this test '
            f'would not notice the rotation being dropped')
        assert gap > previous
        previous = gap


def test_heading_composes_and_wraps(spawns):
    """theta_world = wrap(spawn_yaw + theta_odom), inside (-pi, pi].

    Wrapping is load-bearing: at the shipped -2.33 rad spawn, a robot that has
    turned more than about 0.81 rad leaves the principal range, and
    ``PathFollower`` compares headings by subtraction -- an unwrapped value
    produces a robot convinced it must spin a full turn to face a bearing it is
    already on.
    """
    spawn = SpawnPose(yaw=SHIPPED_YAW)
    for theta_odom in (0.0, -0.5, -0.81, -2.16, -3.0, 3.0, 6.28):
        _, _, theta = odom_to_world(0.0, 0.0, theta_odom, spawn)
        assert -math.pi < theta <= math.pi
        assert math.cos(theta) == pytest.approx(
            math.cos(SHIPPED_YAW + theta_odom), abs=1e-12)
        assert math.sin(theta) == pytest.approx(
            math.sin(SHIPPED_YAW + theta_odom), abs=1e-12)


def test_the_quaternion_route_agrees_with_the_yaw_route(spawns):
    """The node composes quaternions; this module composes yaws. Same answer.

    ``world_odometry_node`` multiplies the spawn quaternion into the message's
    orientation rather than adding yaws, so that it stays correct if an odometry
    source ever reports roll or pitch. For the yaw-only case DiffDrive actually
    publishes, the two must be identical -- otherwise the pose and the heading
    in the same message would disagree.
    """
    for _rid, spawn in spawns:
        spawn_q = yaw_to_quaternion(spawn.yaw)
        for theta_odom in (0.0, -2.16, 1.4, 3.0, -3.1):
            qx, qy, qz, qw = quaternion_multiply(
                spawn_q, yaw_to_quaternion(theta_odom))
            from_quaternion = math.atan2(
                2.0 * (qw * qz + qx * qy),
                1.0 - 2.0 * (qy * qy + qz * qz),
            )
            _, _, from_yaw = odom_to_world(0.0, 0.0, theta_odom, spawn)
            assert from_quaternion == pytest.approx(from_yaw, abs=1e-12)


# ------------------------------------------------------------------ round trip

def test_world_odom_world_round_trip(spawns, mission_targets):
    """world -> odom -> world, over every spawn and every mission coordinate.

    An inverse that is merely 'the forward one with minus signs' is easy to get
    subtly wrong -- transposing the rotation and negating the translation in the
    wrong order gives an inverse that is exact only when the yaw is 0, which is
    exactly the case a hand-written unit test tends to pick.
    """
    headings = (0.0, -2.16, 1.9, -3.0)
    for _rid, spawn in spawns:
        for _name, (wx, wy) in mission_targets:
            for theta in headings:
                ox, oy, otheta = world_to_odom(wx, wy, theta, spawn)
                bx, by, btheta = odom_to_world(ox, oy, otheta, spawn)
                assert (bx, by) == pytest.approx((wx, wy), abs=1e-9)
                assert wrap_angle(btheta - theta) == pytest.approx(0.0, abs=1e-12)


def test_round_trip_holds_for_a_yaw_of_zero_too():
    """The degenerate case, kept because it is the one an inverse bug survives."""
    spawn = SpawnPose(x=17.0, y=-3.5, yaw=0.0)
    ox, oy, otheta = world_to_odom(100.0, -40.0, 1.0, spawn)
    assert (ox, oy) == pytest.approx((83.0, -36.5), abs=1e-12)
    assert odom_to_world(ox, oy, otheta, spawn)[:2] == pytest.approx(
        (100.0, -40.0), abs=1e-12)


# -------------------------------------------------- the fleet stays on terrain

def test_every_fleet_target_is_on_the_terrain(spawns, bounds, mission_targets):
    """Every robot, every deposit, the depot and every survey waypoint.

    This is the acceptance statement for the frame fix: with position
    world-referenced, a task target IS where the robot goes, so checking the
    targets against the terrain box checks the missions. Before the fix the two
    were different questions and only one of them was ever asked.
    """
    assert mission_targets, 'no targets were collected; the test is vacuous'
    off = [(name, x, y) for name, (x, y) in mission_targets
           if not bounds.contains(x, y)]
    assert not off, (
        'mission coordinates outside %s:\n' % bounds.describe()
        + '\n'.join(f'  {name} ({x:.1f}, {y:.1f})' for name, x, y in off))

    off_spawns = [(rid, s.x, s.y) for rid, s in spawns
                  if not bounds.contains(s.x, s.y)]
    assert not off_spawns, f'spawn poses off the terrain: {off_spawns}'


def test_every_target_has_real_clearance(bounds, mission_targets):
    """Not merely inside: comfortably inside.

    A mission coordinate one metre inside the bound would pass the test above
    and still be reached by a robot that overshoots. Recorded as a number so
    that moving a deposit toward an edge is a visible decision.
    """
    limit_x = bounds.safe_x
    limit_y = bounds.safe_y
    worst = min(
        min(x - limit_x[0], limit_x[1] - x, y - limit_y[0], limit_y[1] - y)
        for _name, (x, y) in mission_targets
    )
    assert worst > 40.0, (
        f'the tightest mission coordinate is only {worst:.1f} m inside '
        f'{bounds.describe()}')


def test_the_old_frame_sent_robots_somewhere_else(spawns, mission_targets):
    """What the defect actually did, pinned so it cannot quietly come back.

    Before the fix a task target in world metres was consumed as odom metres, so
    the robot physically ended up at ``spawn (+) target`` instead of at
    ``target``. This asserts that error was LARGE for every robot and every
    mission coordinate -- it was never a rounding matter -- and reports the
    worst case.

    It also records what the alternative reading of the odom convention implies.
    If the odom frame were world-aligned rather than rotated into the spawn
    heading, the same defect would put robots straight off the 500 m heightfield
    -- which is the ODE abort the operator measured three times. Both readings
    agree the old behaviour was badly wrong; ``scripts/check_drive.sh`` is what
    decides between them, on a running simulator.
    """
    worst = 0.0
    for _rid, spawn in spawns:
        for _name, (tx, ty) in mission_targets:
            px, py, _ = odom_to_world(tx, ty, 0.0, spawn)
            error = math.hypot(px - tx, py - ty)
            assert error > 50.0, (
                f'{_rid} targeting {_name} ({tx:.1f}, {ty:.1f}) would have '
                f'physically reached ({px:.1f}, {py:.1f}), only {error:.1f} m '
                f'away -- if this is ever small the defect description is wrong')
            worst = max(worst, error)
    assert worst > 250.0, f'worst old-frame position error was only {worst:.1f} m'


def test_under_a_world_aligned_odom_frame_the_old_code_left_the_map(
        spawns, bounds, mission_targets):
    """The abort mechanism, as arithmetic rather than as a story.

    Reading the old behaviour as a pure translation -- the reading under which
    the operator's measured ODE abort at +/-248 m is explained -- some
    (robot, target) pairs land off the heightfield entirely. Asserted so the
    magnitude of what was at stake is recorded in a runnable form; it says
    nothing about which convention gz-sim uses.
    """
    escapes = [
        (rid, name, spawn.x + tx, spawn.y + ty)
        for rid, spawn in spawns
        for name, (tx, ty) in mission_targets
        if not bounds.contains(spawn.x + tx, spawn.y + ty)
    ]
    assert escapes, (
        'no (robot, target) pair leaves the terrain under the translation-only '
        'reading; the operator measured an ODE heightfield abort, so if this '
        'is ever empty the explanation of that abort needs revisiting')


# ------------------------------------------------------------ the terrain box

def test_bounds_come_from_the_config_and_not_from_this_module(bounds):
    assert (bounds.x_min, bounds.x_max) == (-250.0, 250.0)
    assert (bounds.y_min, bounds.y_max) == (-250.0, 250.0)
    assert bounds.margin == DEFAULT_SAFETY_MARGIN_M
    assert bounds.safe_x == (-240.0, 240.0)
    assert bounds.safe_y == (-240.0, 240.0)


def test_missing_world_params_raises_rather_than_guessing():
    """A guard that defaults to a guessed extent certifies nothing."""
    with pytest.raises(FileNotFoundError):
        TerrainBounds.from_world_params('')
    with pytest.raises(FileNotFoundError):
        TerrainBounds.from_world_params(os.path.join(_PKG, 'no_such_file.yaml'))


def test_world_params_without_bounds_raises(tmp_path):
    path = tmp_path / 'world.yaml'
    path.write_text('world:\n  name: empty\n')
    with pytest.raises(KeyError):
        TerrainBounds.from_world_params(str(path))


@pytest.mark.parametrize('x,y,inside', [
    (0.0, 0.0, True),
    (240.0, 240.0, True),          # exactly on the safe edge
    (-240.0, -240.0, True),
    (240.001, 0.0, False),
    (0.0, -240.001, False),
    (-159.0, -248.0, False),       # the operator's measured abort coordinate
    (-145.0, -255.0, False),       # off the heightfield entirely
    (400.0, 400.0, False),         # a plausible operator typo
])
def test_bounds_accept_and_refuse(bounds, x, y, inside):
    assert bounds.contains(x, y) is inside


@pytest.mark.parametrize('x,y', [
    (float('nan'), 0.0),
    (0.0, float('nan')),
    (float('inf'), 0.0),
    (0.0, float('-inf')),
])
def test_non_finite_coordinates_are_outside(bounds, x, y):
    """A NaN target is exactly what produces the unbounded AABB ODE aborts on."""
    assert bounds.contains(x, y) is False
    cx, cy = bounds.clamp(x, y)
    assert math.isfinite(cx) and math.isfinite(cy)
    assert bounds.contains(cx, cy)


def test_clamp_returns_the_nearest_safe_point(bounds):
    assert bounds.clamp(0.0, 0.0) == (0.0, 0.0)
    assert bounds.clamp(400.0, -900.0) == (240.0, -240.0)
    assert bounds.clamp(-159.0, -248.0) == (-159.0, -240.0)


def test_the_topic_name_is_not_the_raw_one():
    """A rename that lands on 'odom' would silently restore the defect."""
    assert WORLD_ODOM_TOPIC == 'odom_world'
