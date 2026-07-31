"""The agent refuses to drive off the terrain. The last guard before motion.

WHY THIS EXISTS
Past the edge of the 500 m heightfield there is no collision surface. A robot
commanded there does not fail a task -- it falls, and the falling body's AABB
eventually leaves the integer range ODE's broadphase converts it into:

    ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact &&
    aabbBound < dMaxIntExact" failed in collide() [collision_space.cpp:460]

which takes Gazebo down and every robot with it. The operator measured that
three times on 2026-07-30/31. One bad coordinate must not be able to do that.

The orchestrator refuses an operator-supplied target where there is a human to
tell (``selene_orchestrator/terrain_guard.py``). This is the other half: every
commanded motion in the agent -- prospect, excavate, haul, recharge and an
operator ``send_to_location`` -- goes through ``Navigator.plan_to`` and
therefore through ``AStarPlanner.plan``, so a single check there covers targets
nobody typed: a stale one, a NaN, or one from a future planner.

WHY IT NEEDED THE FRAME FIX FIRST
The bound is not new; ``is_in_bounds`` has always rejected a goal off the grid.
It was applied in the WRONG FRAME. Every pose reaching the planner was
dead-reckoned ``/odom``, so a goal well inside the grid in odom metres could be
two hundred metres off the map in world metres, and the check passed it. What
makes the check mean something is that position is now world-referenced
(``selene_sim/selene_sim/world_frame.py``); what makes it survive contact with
a robot is the margin.
"""

import math
import os

import pytest
import yaml

from selene_agent.navigator import (
    DEFAULT_TERRAIN_MARGIN_M,
    AStarPlanner,
    OccupancyGrid,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
NAV_YAML = os.path.join(_REPO, 'selene_agent', 'config', 'nav_params.yaml')


@pytest.fixture(scope='module')
def nav_config():
    with open(NAV_YAML) as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope='module')
def shipped_grid(nav_config):
    """The grid an agent really builds, from the file an agent really reads."""
    return OccupancyGrid.from_config(nav_config)


def test_the_shipped_grid_takes_its_margin_from_the_config(shipped_grid,
                                                           nav_config):
    x_min, x_max, y_min, y_max = shipped_grid.terrain_safe_area()
    margin = float(nav_config['navigation']['terrain_margin_m'])
    assert margin > 0.0, 'nav_params.yaml must declare a positive margin'
    assert (x_min, x_max) == pytest.approx((-250.0 + margin, 250.0 - margin))
    assert (y_min, y_max) == pytest.approx((-250.0 + margin, 250.0 - margin))


def test_a_config_without_the_key_still_gets_a_margin():
    """A forgotten key must not silently disarm the guard.

    ``from_config`` defaults to DEFAULT_TERRAIN_MARGIN_M rather than to the
    constructor's 0.0. The constructor default is 0 for the benefit of the
    20 x 20 m grids unit tests build, where a 10 m inset leaves nothing
    admissible; the config path is the one production uses.
    """
    grid = OccupancyGrid.from_config({'navigation': {
        'grid_width': 500, 'grid_height': 500, 'grid_resolution': 1.0,
        'origin_x': -250.0, 'origin_y': -250.0,
    }})
    x_min, x_max, _y_min, _y_max = grid.terrain_safe_area()
    assert (x_min, x_max) == pytest.approx(
        (-250.0 + DEFAULT_TERRAIN_MARGIN_M, 250.0 - DEFAULT_TERRAIN_MARGIN_M))


@pytest.mark.parametrize('wx,wy,expected', [
    (0.0, 0.0, True),
    (-100.0, -150.0, True),        # PSR centre
    (-80.0, -140.0, True),         # deposit_alpha
    (50.0, 50.0, True),            # depot
    (-30.0, -100.0, True),         # recharge station
    (240.0, 240.0, True),          # exactly on the safe edge
    (-240.0, -240.0, True),
    (240.5, 0.0, False),
    (0.0, -241.0, False),
    (-159.0, -248.0, False),       # the coordinate the operator's abort names
    (-145.0, -255.0, False),       # off the heightfield outright
    (600.0, 0.0, False),
])
def test_is_on_terrain(shipped_grid, wx, wy, expected):
    assert shipped_grid.is_on_terrain(wx, wy) is expected


@pytest.mark.parametrize('wx,wy', [
    (float('nan'), 0.0),
    (0.0, float('nan')),
    (float('inf'), float('inf')),
    (0.0, float('-inf')),
])
def test_non_finite_goals_are_off_terrain(shipped_grid, wx, wy):
    """A NaN goal is exactly what produces the unbounded AABB ODE aborts on.

    ``world_to_grid`` would turn one into an ``int()`` of NaN, which raises --
    so without this the failure would be an unhandled ValueError inside the
    planner rather than a refusal the FSM can act on.
    """
    assert shipped_grid.is_on_terrain(wx, wy) is False


def test_planner_refuses_a_goal_off_the_terrain(shipped_grid):
    planner = AStarPlanner(shipped_grid)
    result = planner.plan((-45.0, -92.0), (-159.0, -248.0))
    assert not result.success
    assert 'terrain safe area' in result.failure_reason
    # The message must name the offending coordinate and the box: this reason
    # reaches the agent log and, through TaskResult, the operator.
    assert '-159.0' in result.failure_reason
    assert '-240.0' in result.failure_reason


def test_planner_refuses_a_goal_inside_the_grid_but_inside_the_margin(
        shipped_grid):
    """The margin is the point. (-245, 0) is a legal grid cell and no ground.

    Without the margin this goal plans successfully, the robot arrives within
    ``PathFollower``'s 1.0 m tolerance of a coordinate 3 m from the last
    collision sample, and the outcome depends on which way it overshoots.
    """
    planner = AStarPlanner(shipped_grid)
    gx, gy = shipped_grid.world_to_grid(-245.0, 0.0)
    assert shipped_grid.is_in_bounds(gx, gy), (
        'the premise of this test is that the goal is a legal GRID cell')
    assert not planner.plan((-45.0, -92.0), (-245.0, 0.0)).success


def test_planner_accepts_every_mission_target(shipped_grid):
    """The guard must not refuse the mission it was added to protect.

    A bound that also blocks the depot is not a safety feature; it is an outage.
    Only the goal admissibility is asserted here, not that a route exists --
    rocks and the crater are a different question, and A* over a 500 x 500 grid
    is slow enough that planning ten routes belongs in an integration test.
    """
    for wx, wy in [(-100.0, -150.0), (-80.0, -140.0), (-110.0, -170.0),
                   (-90.0, -130.0), (-120.0, -155.0), (50.0, 50.0),
                   (-30.0, -100.0), (-45.0, -92.0), (-45.0, -119.0),
                   (-52.0, -109.0)]:
        assert shipped_grid.is_on_terrain(wx, wy), (
            f'({wx}, {wy}) is a mission coordinate and the guard rejects it')


def test_a_short_plan_near_the_spawn_still_works(shipped_grid):
    """Regression: the guard must not have broken ordinary planning."""
    planner = AStarPlanner(shipped_grid)
    result = planner.plan((-45.0, -92.0), (-45.0, -85.0))
    assert result.success, result.failure_reason
    assert result.path
    end = result.path[-1]
    assert math.hypot(end[0] + 45.0, end[1] + 85.0) < 1.5


def test_the_margin_covers_the_arrival_tolerance(nav_config):
    """The margin has to exceed what the follower may overshoot by.

    ``PathFollower`` declares a waypoint reached inside ``waypoint_tolerance``
    while steering toward a point ``lookahead_distance`` beyond it, so the body
    can sit roughly their sum past a commanded coordinate. A margin smaller than
    that would let a legal goal produce an illegal body position, which is the
    whole failure this guard exists to prevent.
    """
    nav = nav_config['navigation']
    follower = nav_config['path_follower']
    overshoot = (float(follower['waypoint_tolerance'])
                 + float(follower['lookahead_distance']))
    assert float(nav['terrain_margin_m']) > overshoot, (
        f"terrain_margin_m {nav['terrain_margin_m']} must exceed the "
        f'{overshoot} m a path follower can overshoot a goal by')
