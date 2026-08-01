"""The planner reads ``max_traversable_slope_deg``, and what it does with it.

WHY THIS EXISTS
---------------
Deviation D-28. ``selene_agent/config/nav_params.yaml`` declared
``navigation.max_traversable_slope_deg`` from Phase 2 to 2026-08-01 and nothing
in production read it -- the fifth instance of this repository's "wired but
never called" pattern, and the one that let a hauler be routed at a 34 degree
crater wall where it pinned, kept turning its wheels, and reported success.

THE ONE THING TO UNDERSTAND BEFORE READING ANY ASSERTION HERE. The limit is
enforced PER STEP -- against the grade along the path's own direction of travel,
``atan(|dz| / step_length)`` -- and NOT per cell. Those are different rules and
the difference decides whether the mission is possible at all. On a uniform
slope of 26.57 degrees every cell is over a 20 degree limit, so a per-cell rule
refuses the whole map; but a diagonal step across that same slope climbs at
19.47 degrees and is admissible, so the per-step rule leaves it fully connected.
That is not a loophole, it is the geometry a vehicle actually experiences: a
path crossing slope S at heading theta off the fall line climbs at
``atan(tan(S) * cos(theta))``. ``test_a_uniform_slope_admits_the_diagonal_and_
refuses_the_cardinal`` is that sentence as arithmetic.

MEASURED ON THE SHIPPED TERRAIN, 2026-08-01, over the 500 x 500 / 1.0 m lattice
with the collision heightmap: the per-cell reading leaves the depot unreachable
from every spawn at 10, 15, 20 AND 25 degrees, while the per-step rule at
20 degrees puts all 250,000 cells in one component.

MUTATIONS RUN AGAINST THIS FILE (house rule 2). Each was applied to
``selene_agent/selene_agent/navigator.py``, the file run, then reverted, on
2026-08-01. Counts are MEASURED and are of THIS file alone, whose baseline is
19 passed.

* ``is_step_traversable`` -> ``return True`` unconditionally
  -> 5 failed, 14 passed.
* delete the ``is_step_traversable`` call from ``_get_neighbors`` (the cardinal
  one; the diagonal ``continue`` stays), leaving ``_line_of_sight``'s intact
  -> 4 failed, 15 passed.
* delete the ``is_step_traversable`` call from ``_line_of_sight`` ONLY, leaving
  the search fully guarded -> 2 failed, 17 passed. This is the mutation that
  matters most: the search refuses to climb the wall and the simplifier
  straightens the switchback straight back across it, so a guard that is
  perfectly implemented and fully tested at the search level is defeated by the
  line after it.
* delete the goal-slope guard in ``plan`` -> 2 failed, 17 passed.
* ``load_terrain``'s cost write -> ``self._cost_grid[:] = 0.0`` (i.e. restore
  the pre-D-28 behaviour exactly) -> 3 failed, 16 passed.
* ``step_grade_deg``'s ``run`` -> ``self._resolution`` (i.e. price a diagonal as
  one cell, dropping the sqrt(2)) -> 3 failed, 16 passed.
* ``_simplify_path`` stops pricing its shortcuts -> 1 failed, 18 passed.
* ``per_step_components`` ignores elevation -> 1 failed, 18 passed here, and
  2 failed in ``test_startup_reachability_audit.py``.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest
import yaml

from selene_agent.navigator import (
    AStarPlanner,
    OccupancyGrid,
    PATH_FOLLOWER_KEYS,
    audit_terrain_reachability,
    path_follower_kwargs,
    per_step_components,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
NAV_PARAMS = os.path.join(REPO, 'selene_agent', 'config', 'nav_params.yaml')

#: All ten poses in selene_sim/config/spawn_positions.yaml pick from this
#: cluster; scout_01's is used as the representative start.
SPAWN = (-45.0, -92.0)
#: ``world.depot.position`` / the orchestrator's ``depot_x``, ``depot_y``.
DEPOT = (-100.0, -150.0)
#: The ``recharge_pad`` <include> in selene_sim/worlds/lunar_psr.sdf.
RECHARGE_PAD = (-30.0, -100.0)
#: ``mission.prospect_waypoints[0]`` BEFORE 2026-08-01. On 37.24 deg ground.
OLD_FIRST_WAYPOINT = (-60.0, -120.0)
#: ``mission.recharge_position`` before it was deleted. On 33.91 deg ground.
DELETED_NAV_RECHARGE = (-75.0, -100.0)


# ---------------------------------------------------------------------------
# Synthetic terrain
# ---------------------------------------------------------------------------

class FakeLattice:
    """The duck type ``OccupancyGrid.load_terrain`` consumes.

    Elevation and slope are supplied INDEPENDENTLY, which is not a cheat: the
    real ``SlopeLattice`` derives its slope from a 2.93 m gradient baseline and
    its elevation from the lattice sample, so the two genuinely are different
    readings of the ground and a test that forced them to agree could not
    isolate either rule.
    """

    def __init__(self, elevation, slope, resolution=1.0,
                 origin_x=0.0, origin_y=0.0):
        self.elevation_m = np.asarray(elevation, dtype=np.float64)
        self.slope_deg = np.asarray(slope, dtype=np.float64)
        self.height, self.width = self.elevation_m.shape
        self.resolution = resolution
        self.origin_x = origin_x
        self.origin_y = origin_y


def _uniform_slope_grid(rise_per_cell=0.5, size=21, limit=20.0):
    """A plane tilted in +x, with the per-cell slope stated honestly.

    ``rise_per_cell`` 0.5 m over 1.0 m cells is a 26.565 degree plane: over the
    limit in every cell, admissible on every diagonal.
    """
    gx = np.arange(size, dtype=np.float64)[None, :]
    elevation = np.repeat(gx * rise_per_cell, size, axis=0)
    slope = np.full((size, size), math.degrees(math.atan(rise_per_cell)))
    grid = OccupancyGrid(width=size, height=size, resolution=1.0,
                         origin_x=0.0, origin_y=0.0)
    grid.load_terrain(FakeLattice(elevation, slope), limit)
    return grid


def _walled_valley_grid(limit=20.0):
    """Flat -- 26.57 degree wall -- flat, so a goal is admissible and the ROUTE
    is the thing under test.

    Columns 0..10 at z = 0, columns 10..20 rising 0.5 m per cell, columns 20+ at
    z = 5. Per-cell slope is 0 on the flats and 26.57 on the wall band, so a
    per-cell rule would refuse to cross while the per-step rule admits a
    45 degree traverse.
    """
    size = 40
    column_z = np.array([0.0 if gx <= 10 else
                         (5.0 if gx >= 20 else 0.5 * (gx - 10))
                         for gx in range(size)])
    elevation = np.repeat(column_z[None, :], size, axis=0)
    column_slope = np.array([math.degrees(math.atan(0.5)) if 10 < gx < 20
                             else 0.0 for gx in range(size)])
    slope = np.repeat(column_slope[None, :], size, axis=0)
    grid = OccupancyGrid(width=size, height=size, resolution=1.0,
                         origin_x=-20.0, origin_y=-20.0)
    grid.load_terrain(FakeLattice(elevation, slope, origin_x=-20.0,
                                  origin_y=-20.0), limit)
    return grid


def _cliff_grid(limit=20.0):
    """The same valley with the wall collapsed into one cell: genuinely closed."""
    size = 30
    column_z = np.array([0.0 if gx < 15 else 5.0 for gx in range(size)])
    elevation = np.repeat(column_z[None, :], size, axis=0)
    slope = np.zeros((size, size))
    grid = OccupancyGrid(width=size, height=size, resolution=1.0,
                         origin_x=-15.0, origin_y=-15.0)
    grid.load_terrain(FakeLattice(elevation, slope, origin_x=-15.0,
                                  origin_y=-15.0), limit)
    return grid


def _steps_along(grid, path):
    """Every cell-to-cell step a PathFollower would drive along *path*.

    An INDEPENDENT consumer of the planner's output: it re-walks each simplified
    segment with its own Bresenham rather than trusting the search's internal
    bookkeeping, which is the only way to catch ``_simplify_path`` straightening
    a switchback back across the wall the search refused.
    """
    steps = []
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        x0, y0 = grid.world_to_grid(ax, ay)
        x1, y1 = grid.world_to_grid(bx, by)
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while not (x0 == x1 and y0 == y1):
            px, py = x0, y0
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
            steps.append((px, py, x0, y0))
    return steps


def _path_length(path):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(path, path[1:]))


# ---------------------------------------------------------------------------
# The geometry the whole design rests on
# ---------------------------------------------------------------------------

def test_a_uniform_slope_admits_the_diagonal_and_refuses_the_cardinal():
    """``atan(tan(S) * cos(theta))``, as arithmetic, on a 26.565 degree plane.

    Straight up the fall line is 26.565 degrees and refused at a 20 degree
    limit. The same plane crossed at 45 degrees climbs 0.5 m over 1.414 m --
    19.471 degrees -- and is admitted. Nothing about the ground changed; the
    heading did.

    This is the entire justification for the per-step rule, and it is why the
    fleet delivered 94.85 kg into a crater whose rim the capability campaign
    says it cannot climb.
    """
    grid = _uniform_slope_grid()
    east = grid.step_grade_deg(5, 5, 6, 5)
    diagonal = grid.step_grade_deg(5, 5, 6, 6)
    north = grid.step_grade_deg(5, 5, 5, 6)
    assert east == pytest.approx(26.5651, abs=1e-3)
    assert diagonal == pytest.approx(19.4712, abs=1e-3)
    assert north == pytest.approx(0.0, abs=1e-9)
    # The closed form, independently: theta = 45 deg off the fall line.
    assert diagonal == pytest.approx(math.degrees(math.atan(
        math.tan(math.radians(east)) * math.cos(math.radians(45.0)))), abs=1e-9)

    assert not grid.is_step_traversable(5, 5, 6, 5)
    assert grid.is_step_traversable(5, 5, 6, 6)
    assert grid.is_step_traversable(5, 5, 5, 6)
    # Descent is refused on the same terms as ascent. The campaign measured
    # descent limits of 25 deg against ascent limits of 20, i.e. close, not
    # unbounded -- so dropping the sign would be wrong, not conservative.
    assert not grid.is_step_traversable(6, 5, 5, 5)

    neighbours = {(nx, ny) for nx, ny, _ in
                  AStarPlanner(grid)._get_neighbors(5, 5)}
    assert (6, 5) not in neighbours and (4, 5) not in neighbours, (
        'the planner still offers a step straight up the fall line')
    assert {(6, 6), (6, 4), (4, 6), (4, 4), (5, 6), (5, 4)} <= neighbours


def test_the_per_cell_reading_would_refuse_this_entire_map():
    """The counterfactual, stated so the choice of rule is visible.

    Every cell of the 26.565 degree plane is over the 20 degree limit, so a
    per-cell rule has NO passable cells at all -- while the per-step rule leaves
    the map one connected component. This is the shipped terrain's situation in
    miniature: measured 2026-08-01, the per-cell reading cuts the depot off from
    every spawn at 10, 15, 20 and 25 degrees.
    """
    grid = _uniform_slope_grid()
    assert grid.cell_slope_deg(5, 5) == pytest.approx(26.5651, abs=1e-3)
    assert grid.cell_slope_deg(5, 5) > grid.max_slope_deg
    over = sum(1 for gy in range(grid.height) for gx in range(grid.width)
               if grid.cell_slope_deg(gx, gy) > grid.max_slope_deg)
    assert over == grid.width * grid.height, 'no cell should pass a per-cell cut'

    labels = per_step_components(grid)
    assert int(np.unique(labels).size) == 1, (
        'the per-step rule has split a plane that is uniformly diagonal-'
        'traversable; the two rules have become the same rule')


# ---------------------------------------------------------------------------
# Refusal at the three places it has to happen
# ---------------------------------------------------------------------------

def test_the_route_across_the_wall_is_a_switchback_and_stays_admissible():
    """THE END-TO-END PROPERTY, and the one that catches ``_simplify_path``.

    A robot on the west flat is asked for the east flat. Both endpoints are on
    0 degree ground, so the goal guard has nothing to say; the 10-cell,
    26.57 degree wall between them is the whole problem. The planner must return
    a path that (a) exists, (b) is longer than the straight line, and (c) whose
    every driven step is inside the limit AFTER simplification.

    (c) is the assertion that fails when ``_line_of_sight`` stops checking
    slope: the search zig-zags correctly and the simplifier immediately replaces
    the zig-zag with the straight segment the search refused.
    """
    grid = _walled_valley_grid()
    planner = AStarPlanner(grid, slope_penalty_weight=2.0)
    start, goal = (-18.0, 0.0), (10.0, 0.0)
    result = planner.plan(start, goal)
    assert result.success, result.failure_reason

    straight = math.hypot(goal[0] - start[0], goal[1] - start[1])
    length = _path_length(result.path)
    assert length > straight * 1.05, (
        f'the path is {length:.1f} m against a {straight:.1f} m straight line; '
        f'crossing a 26.57 deg wall at 20 deg costs at least a 1.414x detour '
        f'over the wall band, so this route did not detour at all')

    steps = _steps_along(grid, result.path)
    assert steps, 'the simplified path collapsed to a single point'
    worst = max(grid.step_grade_deg(*step) for step in steps)
    assert worst <= grid.max_slope_deg + 1e-9, (
        f'a driven step climbs {worst:.2f} deg against a '
        f'{grid.max_slope_deg:.1f} deg limit. The search refused these steps '
        f'and something put them back -- look at _simplify_path/_line_of_sight.')


def test_the_route_crosses_cells_a_per_cell_rule_would_have_refused():
    """The switchback is not an evasion of the wall, it is a traverse OF it.

    If the returned path avoided the over-limit band entirely, every assertion
    above would pass for the wrong reason and the per-step rule would be doing
    nothing that a per-cell rule could not. It does not: the route crosses cells
    whose own gradient is 26.57 degrees.
    """
    grid = _walled_valley_grid()
    result = AStarPlanner(grid).plan((-18.0, 0.0), (10.0, 0.0))
    assert result.success
    crossed = [grid.cell_slope_deg(ax, ay)
               for ax, ay, _bx, _by in _steps_along(grid, result.path)]
    assert max(crossed) > grid.max_slope_deg, (
        'the route stayed on ground a per-cell rule would have passed, so this '
        'fixture no longer distinguishes the two rules')


def test_a_genuine_cliff_is_still_refused():
    """The rule REFUSES things, and the switchback licence has a floor.

    Collapse the same 5 m rise into one cell and no heading helps: every step
    across it is 78.7 degrees. The planner must fail, and the component labelling
    must agree that the two flats are separate worlds.
    """
    grid = _cliff_grid()
    result = AStarPlanner(grid).plan((-10.0, 0.0), (10.0, 0.0))
    assert not result.success
    assert result.failure_reason == 'no path found'
    labels = per_step_components(grid)
    assert int(np.unique(labels).size) == 2, (
        'a 5 m step in one cell did not split the map; the per-step rule is '
        'admitting something it cannot admit')


def test_a_goal_on_over_limit_ground_is_refused_by_name():
    """Separate from the per-step rule, and it catches different defects.

    A route may CROSS a 34 degree slope by switchbacking. A goal is somewhere a
    robot has to arrive, hold station, run a skill and set off again, with no
    choice of heading left -- so the steepest slope at that spot is the right
    quantity, and it is checked per cell.

    The refusal must name the coordinate and the two numbers: the usual cause is
    a configured position nobody ever evaluated against terrain, and that is
    precisely what nav_params.yaml shipped for four phases.
    """
    grid = _uniform_slope_grid()
    result = AStarPlanner(grid).plan((2.5, 2.5), (15.5, 15.5))
    assert not result.success
    assert '26.6 deg ground' in result.failure_reason
    assert '20.0 deg' in result.failure_reason
    assert '15.5' in result.failure_reason

    # And the guard is inert where there is no terrain, so every pre-D-28 test
    # that plans on a bare 20 x 20 grid behaves exactly as it did.
    bare = OccupancyGrid(width=20, height=20, resolution=1.0,
                         origin_x=-10.0, origin_y=-10.0)
    assert not bare.has_terrain
    assert bare.max_slope_deg is None
    assert AStarPlanner(bare).plan((0.0, 0.0), (5.0, 0.0)).success


# ---------------------------------------------------------------------------
# The cost term, which is a different thing from the refusal
# ---------------------------------------------------------------------------

def test_the_slope_cost_term_is_no_longer_identically_zero():
    """``grid.get_cost(nx, ny) * self._slope_w`` had a zero left factor.

    ``_cost_grid`` was allocated all-zero and ``set_cost`` had exactly one
    caller repo-wide -- ``test_navigator.py``'s round-trip. So the planner's
    slope term existed, was multiplied by a configured weight, and contributed
    nothing. ``load_terrain`` writes ``slope / limit`` into it: 0 on the flat,
    1.0 at the limit, ~1.33 on this fixture's 26.57 degree plane.
    """
    grid = _uniform_slope_grid()
    assert grid.get_cost(5, 5) == pytest.approx(26.5651 / 20.0, abs=1e-4)
    flat = _walled_valley_grid()
    assert flat.get_cost(2, 2) == pytest.approx(0.0, abs=1e-9)
    assert flat.get_cost(15, 2) == pytest.approx(26.5651 / 20.0, abs=1e-4)

    # FINITE ABOVE THE LIMIT, deliberately. An infinite cost would make the
    # cost term a second, per-cell refusal, and a per-cell refusal at the
    # measured limit disconnects the depot from every spawn.
    assert math.isfinite(grid.get_cost(5, 5))

    # Exact arithmetic on a straight run: 5 cardinal moves entering 5 cells.
    plain = OccupancyGrid(width=10, height=10, resolution=1.0,
                          origin_x=0.0, origin_y=0.0)
    plain.load_terrain(
        FakeLattice(np.zeros((10, 10)), np.full((10, 10), 10.0)), 20.0)
    unweighted = AStarPlanner(plain, slope_penalty_weight=0.0)
    weighted = AStarPlanner(plain, slope_penalty_weight=2.0)
    a = unweighted.plan((0.5, 0.5), (5.5, 0.5))
    b = weighted.plan((0.5, 0.5), (5.5, 0.5))
    assert a.success and b.success
    assert a.cost == pytest.approx(5.0, abs=1e-6)
    assert b.cost == pytest.approx(5.0 + 5 * 2.0 * 0.5, abs=1e-6)


def test_the_weight_changes_the_route_it_chooses():
    """The cost term is not merely non-zero, it decides something.

    A 19 degree corridor runs straight from start to goal, inside the limit and
    therefore never refused; gentler ground lies two rows away. With no weight
    the planner takes the short steep line. With the shipped weight of 2.0 it
    pays extra distance to get off it.

    THIS TEST FAILED WHEN IT WAS FIRST WRITTEN, and the reason is worth keeping.
    A* did prefer the gentle route -- and then ``_simplify_path`` collapsed it
    straight back onto the 19 degree corridor, because ``_line_of_sight`` had no
    objection to a line that is perfectly drivable and merely expensive. The
    cost term was real inside the search and discarded on the way out, so the
    two weights produced identical output. ``_simplify_path`` now prices each
    shortcut with the search's own cost function and refuses one that is dearer
    than the run it replaces.
    """
    height, width = 5, 11
    slope = np.zeros((height, width))
    slope[2, :] = 19.0
    grid = OccupancyGrid(width=width, height=height, resolution=1.0,
                         origin_x=0.0, origin_y=0.0)
    grid.load_terrain(FakeLattice(np.zeros((height, width)), slope), 20.0)

    start, goal = (0.5, 2.5), (10.5, 2.5)
    cheap = AStarPlanner(grid, slope_penalty_weight=0.0).plan(start, goal)
    dear = AStarPlanner(grid, slope_penalty_weight=2.0).plan(start, goal)
    assert cheap.success and dear.success

    def rows(result):
        return {grid.world_to_grid(x, y)[1] for x, y in result.path}

    assert rows(cheap) == {2}, (
        f'with zero weight the straight line is optimal, got {rows(cheap)}')
    assert rows(dear) != {2}, (
        'the shipped slope_penalty_weight did not move the route off a '
        '19 degree corridor; the cost term is reaching the search but is not '
        'affecting the decision')


# ---------------------------------------------------------------------------
# Loading, and the ways it must refuse to load
# ---------------------------------------------------------------------------

def test_load_terrain_refuses_a_lattice_that_describes_different_ground():
    """Geometry is checked, not assumed.

    A lattice on another origin or resolution indexes perfectly well and answers
    about the wrong place -- which is register D-33 (a pose read in the wrong
    frame) with the terrain instead of the robot, and just as silent.
    """
    grid = OccupancyGrid(width=10, height=10, resolution=1.0,
                         origin_x=-5.0, origin_y=-5.0)
    ok = FakeLattice(np.zeros((10, 10)), np.zeros((10, 10)),
                     origin_x=-5.0, origin_y=-5.0)
    grid.load_terrain(ok, 20.0)

    for bad in (
        FakeLattice(np.zeros((10, 10)), np.zeros((10, 10)), resolution=2.0,
                    origin_x=-5.0, origin_y=-5.0),
        FakeLattice(np.zeros((10, 10)), np.zeros((10, 10)), origin_x=0.0,
                    origin_y=-5.0),
        FakeLattice(np.zeros((12, 12)), np.zeros((12, 12)), origin_x=-5.0,
                    origin_y=-5.0),
    ):
        with pytest.raises(ValueError):
            grid.load_terrain(bad, 20.0)

    for limit in (0.0, -5.0, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            grid.load_terrain(ok, limit)


def test_unknown_terrain_answers_unknown_and_never_flat():
    """The failure mode this must not have.

    A grid with no terrain answers ``nan`` -- not 0.0 -- to every elevation and
    slope query, so a caller comparing against a limit gets something that
    propagates as unknown rather than something that reads as level ground.
    ``is_step_traversable`` is the deliberate exception and says so: it is a
    guard, and a guard that refused everything it could not see would stop every
    unit test and strand a fleet whose heightmap failed to install. The loud
    version of that failure is at the LOAD site, which is the next test.
    """
    bare = OccupancyGrid(width=10, height=10)
    assert math.isnan(bare.elevation(1, 1))
    assert math.isnan(bare.cell_slope_deg(1, 1))
    assert math.isnan(bare.step_grade_deg(1, 1, 2, 2))
    assert bare.is_step_traversable(1, 1, 2, 2)

    loaded = _uniform_slope_grid()
    assert math.isnan(loaded.elevation(-1, 0))
    assert math.isnan(loaded.cell_slope_deg(0, 999))
    assert math.isnan(loaded.step_grade_deg(0, 0, -1, 0))
    assert not loaded.is_step_traversable(0, 0, -1, 0), (
        'a step off the edge of the known world must be refused, not admitted')


def test_from_config_loads_terrain_iff_the_limit_is_declared_and_raises_otherwise():
    """The coupling that makes "a limit with no ground" unrepresentable.

    Present key -> terrain is loaded, or the load RAISES. Absent key -> no
    terrain, which is the only way to get a planner with no slope enforcement
    and is what the pre-D-28 unit tests rely on. There is deliberately no third
    state in which a limit is configured and quietly not applied.
    """
    from selene_agent.terrain_slope import TerrainDataUnavailable

    geometry = {'navigation': {'grid_width': 20, 'grid_height': 20,
                               'grid_resolution': 1.0,
                               'origin_x': -10.0, 'origin_y': -10.0}}
    assert not OccupancyGrid.from_config(geometry).has_terrain

    with_limit = {'navigation': dict(geometry['navigation'],
                                     max_traversable_slope_deg=20.0)}
    with pytest.raises(TerrainDataUnavailable):
        OccupancyGrid.from_config(with_limit, heightmap_dir=str(REPO))


def test_the_planner_no_longer_takes_a_hazard_weight():
    """``hazard_penalty_weight`` is deleted, not defaulted.

    It was assigned to ``self._hazard_w`` and read by nothing, while
    nav_params.yaml carried a value for it that reached no constructor -- D-28's
    own shape, one frame smaller. Accepting and ignoring the keyword would have
    preserved exactly the property that made it worthless.
    """
    grid = OccupancyGrid(width=10, height=10)
    with pytest.raises(TypeError):
        AStarPlanner(grid, hazard_penalty_weight=10.0)
    assert not hasattr(AStarPlanner(grid), '_hazard_w')


def test_path_follower_config_is_translated_explicitly():
    """Six more keys that had no reader, and the one that cannot be splatted.

    ``stall_timeout_s`` in the file is ``stall_timeout`` in the constructor, so
    a ``**block`` splat would have raised on that key and silently accepted a
    misspelling of any of the other five. An unknown key raises BY NAME.
    """
    assert PATH_FOLLOWER_KEYS['stall_timeout_s'] == 'stall_timeout'
    assert path_follower_kwargs(None) == {}
    assert path_follower_kwargs({}) == {}
    assert path_follower_kwargs({'stall_timeout_s': 7.0}) == {'stall_timeout': 7.0}
    with pytest.raises(KeyError) as excinfo:
        path_follower_kwargs({'waypoint_tolerence': 1.0})
    assert 'waypoint_tolerence' in str(excinfo.value)


# ---------------------------------------------------------------------------
# The shipped terrain
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def nav_config():
    with open(NAV_PARAMS) as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope='module')
def shipped_grid(nav_config):
    """The real thing: nav_params.yaml through the production factory."""
    return OccupancyGrid.from_config(nav_config)


def test_the_shipped_configuration_actually_loads_terrain(shipped_grid):
    """The wiring, end to end, on the file production reads.

    If ``max_traversable_slope_deg`` is ever deleted from nav_params.yaml this
    fails -- which matters because its absence is not a relaxed limit, it is NO
    limit, and every other assertion in this file would keep passing.
    """
    assert shipped_grid.has_terrain
    assert shipped_grid.max_slope_deg == 20.0
    assert shipped_grid.get_cost(*shipped_grid.world_to_grid(*OLD_FIRST_WAYPOINT)) > 1.0
    assert shipped_grid.get_cost(*shipped_grid.world_to_grid(*DEPOT)) < 0.2


def test_the_two_coordinates_the_config_shipped_are_now_refused(shipped_grid):
    """Both were places a robot could not have stopped, and both are fixed.

    ``mission.prospect_waypoints[0]`` was (-60, -120), on 37.24 degree ground
    (SAMPLING_RESAMPLED, collision layer), and ``mission.recharge_position`` was
    (-75, -100), on 33.91. Neither had ever been evaluated against terrain
    because nothing read a limit. They are asserted as REFUSED rather than
    merely absent from the file, so restoring either one fails the build here
    with the reason attached.
    """
    planner = AStarPlanner(shipped_grid)
    for point, slope in ((OLD_FIRST_WAYPOINT, 37.2), (DELETED_NAV_RECHARGE, 33.9)):
        assert shipped_grid.cell_slope_deg(
            *shipped_grid.world_to_grid(*point)) == pytest.approx(slope, abs=0.1)
        result = planner.plan(SPAWN, point)
        assert not result.success
        assert 'over the 20.0 deg traversable limit' in result.failure_reason


def test_every_shipped_prospect_waypoint_is_somewhere_a_robot_can_stop(
        nav_config, shipped_grid):
    """The standalone survey is drivable, station by station.

    ``_handle_idle`` walks ``mission.prospect_waypoints`` in order and each is a
    goal, so each has to pass the per-cell goal guard. Measured 2026-08-01 on
    the collision layer: 12.20, 4.71, 1.72, 6.11, 5.00 degrees.
    """
    planner = AStarPlanner(shipped_grid)
    waypoints = [(float(a), float(b))
                 for a, b in nav_config['mission']['prospect_waypoints']]
    assert len(waypoints) == 5
    for point in waypoints:
        slope = shipped_grid.cell_slope_deg(*shipped_grid.world_to_grid(*point))
        assert slope <= shipped_grid.max_slope_deg, (
            f'survey station {point} is on {slope:.2f} deg ground; the robot '
            f'has to hold position there to take a reading')
        assert planner.plan(SPAWN, point).success, (
            f'no route from the spawn cluster to survey station {point}')


def test_the_depot_and_the_recharge_pad_are_both_reachable_from_a_spawn(
        shipped_grid):
    """D-32'S PREMISE, TESTED. It does not hold.

    The register says the recharge pad is "behind an unclimbable wall" because
    the pad is on the plain and the depot is on the crater floor with a 34 deg
    rim between them. That reading treats the limit as a bound on the ground a
    robot may cross. It is not -- and under the rule the planner enforces, the
    routes exist.

    MEASURED HERE, and the length ratios are the switchback made visible: the
    spawn-to-depot route is ~1.5x its straight line and the depot-to-pad route
    ~1.5x its own. A route that came out at 1.0x would mean the fixture never
    crossed the rim and this test was passing vacuously.
    """
    planner = AStarPlanner(shipped_grid, slope_penalty_weight=2.0)
    for name, start, goal in (('spawn->depot', SPAWN, DEPOT),
                              ('spawn->pad', SPAWN, RECHARGE_PAD),
                              ('depot->pad', DEPOT, RECHARGE_PAD),
                              ('pad->depot', RECHARGE_PAD, DEPOT)):
        result = planner.plan(start, goal)
        assert result.success, f'{name}: {result.failure_reason}'
        worst = max((shipped_grid.step_grade_deg(*step)
                     for step in _steps_along(shipped_grid, result.path)),
                    default=0.0)
        assert worst <= shipped_grid.max_slope_deg + 1e-9, (
            f'{name} drives a {worst:.2f} deg step')

    crater = planner.plan(SPAWN, DEPOT)
    straight = math.hypot(DEPOT[0] - SPAWN[0], DEPOT[1] - SPAWN[1])
    ratio = _path_length(crater.path) / straight
    assert ratio > 1.2, (
        f'the spawn-to-depot route is {ratio:.2f}x its straight line. Crossing '
        f'a 34 deg rim at 20 deg costs at least 1.85x over the rim band, so a '
        f'route this direct did not cross a rim -- either the terrain changed '
        f'or the slope rule is not being applied.')


def test_the_component_labelling_and_the_planner_agree(shipped_grid):
    """A SECOND OPINION ON THE SAME QUESTION, computed a different way.

    ``per_step_components`` labels the navigable set with iterated minimum-label
    propagation over numpy; ``AStarPlanner`` searches it with a heap and a
    heuristic. They share the admissibility rule and nothing else, so they are
    entitled to disagree if either has a bug -- which is the point. The startup
    audit reports the first and the robot drives the second, and an audit that
    said "REACHABLE" about somewhere the planner refuses would be worse than no
    audit.
    """
    labels = per_step_components(shipped_grid)
    planner = AStarPlanner(shipped_grid)
    probes = [SPAWN, DEPOT, RECHARGE_PAD, (-80.0, -140.0), (-110.0, -170.0),
              (-52.0, -114.0), (0.0, 0.0), (150.0, 120.0), (-200.0, 200.0)]
    sx, sy = shipped_grid.world_to_grid(*SPAWN)
    start_label = int(labels[sy, sx])
    for point in probes:
        gx, gy = shipped_grid.world_to_grid(*point)
        labelled = int(labels[gy, gx]) == start_label
        planned = planner.plan(SPAWN, point).success
        assert labelled == planned, (
            f'{point}: component labelling says '
            f'{"reachable" if labelled else "unreachable"} and the planner says '
            f'{"reachable" if planned else "unreachable"}')


def test_the_audit_sees_one_component_over_the_whole_shipped_world(shipped_grid):
    """The finding, pinned. 20 degrees per step connects everything.

    250,000 cells minus the 208 the 26 mapped rocks occupy, in ONE component.
    Pinned as a number rather than as "more than one" so that a regrade of the
    terrain, a change to the rock list, or a change to the limit lands here.
    """
    audit = audit_terrain_reachability(
        shipped_grid, SPAWN,
        {'depot': DEPOT, 'recharge_pad': RECHARGE_PAD})
    assert audit.limit_deg == 20.0
    assert audit.total_cells == 250000
    assert audit.occupied_cells == 208
    assert audit.over_limit_cells == 8729, (
        'the number of cells over the limit BY THE PER-CELL READING changed; '
        'that reading is not the rule in force but it is the one the log '
        'reports, and a change means the terrain or the limit moved')
    assert audit.component_count == 1
    assert audit.start_component_cells == 250000 - 208
    assert audit.unreachable_landmarks == []
