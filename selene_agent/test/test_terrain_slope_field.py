"""Pins for ``selene_agent.terrain_slope``: the decode, the two sampling
methods, and the shape the terrain has under a 15 degree limit.

WHY THIS EXISTS
---------------
``selene_agent/config/nav_params.yaml:21`` declared
``navigation.max_traversable_slope_deg: 15.0`` and nothing in production read it
(D-28). ``terrain_slope.py`` is the module that made reading it possible, and
these are the assertions that make its numbers quotable.

WHAT CHANGED ON 2026-08-01, because it changes how every number below should be
read. The limit is now a MEASURED 20.0 (a 54-trial Gazebo campaign,
``docs/slope_capability_2026-08-01.json``) and the planner enforces it PER STEP
-- against the grade along a path's own direction of travel -- not per cell.
Everything in this file is still a per-CELL reading of the terrain, which is the
right question for "how steep is the ground here" and the WRONG one for "can a
route cross it". The per-step consequences live in
``test_navigator_slope_enforcement.py``; ``DECLARED_LIMIT_DEG`` below is kept at
15.0 as a fixed probe of the terrain's shape, not because 15 is enforced
anywhere.

Three claims are worth stating up front, because each is one somebody will
otherwise rediscover the expensive way:

  * THE TWO SAMPLING METHODS ARE NOT INTERCHANGEABLE, and the difference is not
    small. At a cell centre they agree to float32 precision. Half a cell away
    they can differ by 8.83 degrees -- measured, at (138.10, -110.05), where a
    point reads 13.88 native and its own cell centre reads 22.71. The 0.6
    degree figure that circulates for this is what three particular landmarks
    happen to show, NOT a bound.
  * UNDER A 15 DEGREE PER-CELL CUT THE WORLD IS DISCONNECTED. The passable set
    splits into a plain of 227,185 cells holding all ten spawns and the recharge
    pad and a crater basin of 3,531 cells holding the depot and all four ice
    deposits, with no route between them. Enforcing that as a hard cut would
    refuse every spawn-to-depot route and break a mission that demonstrably
    works, which is why the campaign in
    ``scripts/measure_slope_capability.sh`` exists -- and, in the end, why the
    rule that shipped is per step and not per cell. Measured 2026-08-01, the
    per-step rule at 20 degrees puts all 250,000 cells in ONE component.
  * ``mission.recharge_position: [-75, -100]``, which was in the same
    nav_params.yaml until 2026-08-01, sits on 37.08 degree ground and is in NO
    per-cell passable component at all. It is deleted (D-32); the assertions
    about it below are kept because they are what justified deleting it.

WHAT THESE TESTS ARE NOT
------------------------
Arithmetic on a committed PNG. Nothing here measures what a vehicle can climb;
that is the campaign's job and it needs Gazebo. A green run here says the field
is decoded correctly and its shape has not changed underneath anyone.

NO CROSS-PACKAGE IMPORT, DELIBERATELY. This file runs in any lane that has
``selene_agent`` on the path, including one that does not have ``selene_sim``.
The traversability gate's radial algorithm is therefore RE-IMPLEMENTED below
from ``selene_sim/test/test_mission_traversability.py`` rather than imported --
a bare cross-package import in the analogous position is register D-36, and the
module under test locates the heightmap through its own search path. The copy
is checked against the gate's own published figures, so it cannot drift
silently.
"""

import json
import math
import os
import shutil

import numpy as np
import pytest

from selene_agent.navigator import OccupancyGrid
from selene_agent.terrain_slope import (
    DEFAULT_BASELINE_M,
    IMPASSABLE_LABEL,
    SAMPLING_NATIVE,
    SAMPLING_RESAMPLED,
    SlopeLattice,
    TerrainDataUnavailable,
    TerrainSlopeField,
    decode_png_greyscale,
    describe_sampling,
)

# --------------------------------------------------------------------------
# Coordinates, and where each one comes from. Copied as literals rather than
# read from another package's config so this file has no cross-package file
# dependency; the authority that reads those files is
# selene_sim/test/test_mission_traversability.py.
# --------------------------------------------------------------------------
#: ``world.depot.position`` (selene_sim/config/world_params.yaml) and
#: ``depot_x``/``depot_y`` (selene_orchestrator/config/orchestrator_params.yaml).
DEPOT = (-100.0, -150.0)
#: The ``recharge_pad`` <include> in selene_sim/worlds/lunar_psr.sdf, and
#: agent_node.py's default recharge station.
RECHARGE_PAD = (-30.0, -100.0)
#: ``mission.recharge_position`` in selene_agent/config/nav_params.yaml until
#: 2026-08-01 -- a THIRD position, and the one that is on the crater wall. The
#: key is DELETED (D-32); the coordinate is kept here as the literal these
#: measurements are about.
NAV_RECHARGE = (-75.0, -100.0)
#: All ten poses in selene_sim/config/spawn_positions.yaml.
SPAWNS = [(-45.0, -92.0), (-45.0, -85.0), (-45.0, -78.0), (-52.0, -109.0),
          (-45.0, -105.0), (-52.0, -88.0), (-52.0, -95.0), (-45.0, -112.0),
          (-45.0, -119.0), (-52.0, -102.0)]
#: The four ``center`` values in selene_sim/config/ice_deposits.yaml.
DEPOSITS = [(-80.0, -140.0), (-110.0, -170.0), (-90.0, -130.0), (-120.0, -155.0)]
#: ``CRATER`` in selene_sim/scripts/generate_heightmap.py.
CRATER_CENTRE = (-100.0, -150.0)

#: The limit nav_params.yaml and world_params.yaml declared until 2026-08-01.
#: SUPERSEDED AS A LIMIT -- both files now say 20.0, measured -- and RETAINED
#: HERE AS A PROBE. Every component figure below was measured at this value and
#: describes the terrain's shape at it; re-pointing the constant at whatever the
#: config currently says would silently invalidate all of them and turn a set of
#: pinned measurements into a moving target. Nothing in production reads 15.
DECLARED_LIMIT_DEG = 15.0

#: Justified by the matched-azimuth cross-check below: the gate's exact-3.0 m
#: radial profile and this module's lattice-realised 2.93 m 2-D gradient differ
#: by 0.02 deg at 24 azimuths and 0.06 deg at 72. See the module docstring of
#: terrain_slope.py.
GATE_AGREEMENT_TOL_DEG = 0.5


@pytest.fixture(scope='module')
def field():
    """The shipped 513-sample visual layer. Located by the module's own search."""
    return TerrainSlopeField.load()


@pytest.fixture(scope='module')
def lattice(field):
    """The nav_params.yaml planning geometry: 500 x 500 at 1.0 m from -250."""
    return field.resample(500, 500, 1.0, -250.0, -250.0)


@pytest.fixture(scope='module')
def components(lattice):
    return lattice.components(DECLARED_LIMIT_DEG, connectivity=4)


# ---------------------------------------------------------------------- decode

def test_the_bundled_png_decoder_reproduces_pillow(field):
    """The dependency-free decoder is not a fallback nobody runs.

    ``selene_agent/package.xml`` does not declare Pillow, so the module ships
    its own PNG reader and uses Pillow only as a speed-up. A fallback path with
    no test is the "wired but never called" pattern with the polarity
    reversed -- it runs only where nobody is looking. This calls it directly.
    """
    pil = pytest.importorskip(
        'PIL.Image',
        reason='Pillow absent; nothing to cross-check the decoder against')
    path = field.source['image']
    with pil.open(path) as img:
        reference = np.asarray(img).astype(np.int64)
    mine = decode_png_greyscale(path).astype(np.int64)
    assert mine.shape == reference.shape
    assert np.array_equal(mine, reference), (
        f'the bundled PNG decoder disagrees with Pillow on {path} at '
        f'{int(np.count_nonzero(mine != reference))} of {mine.size} pixels')


def test_the_decoded_field_reproduces_the_generator_datum(field):
    """Decoding the PNG must return the field the datum was derived from.

    ``terrain_datum.json`` records the generator's own min/max/mean in METRIC
    height. The module returns WORLD z, so the datum's base elevation goes back
    on. MEASURED agreement against ``build_field()`` itself: max|err|
    1.85e-4 m, rms 1.07e-4 m -- one 16-bit level over 24.25 m is 3.7e-4 m, so
    the residual is half a quantisation step and nothing else.
    """
    with open(field.source['datum']) as handle:
        datum = json.load(handle)
    base = float(datum['base_elevation_m'])
    metric = np.asarray(field.elevation_grid_m) + base
    stats = datum['field']
    assert float(metric.min()) == pytest.approx(stats['min_m'], abs=4e-4)
    assert float(metric.max()) == pytest.approx(stats['max_m'], abs=4e-4)
    assert float(metric.mean()) == pytest.approx(stats['mean_m'], abs=4e-4)


def test_the_visual_and_collision_layers_are_different_surfaces(field):
    """Loading a layer is an explicit choice, and the choice changes the answer.

    The 129-sample collision map is what a wheel contacts and is quantised at
    0.094 m; the 513-sample visual map is the terrain's true relief. Asserting
    they differ stops ``layer=`` becoming decoration.
    """
    coarse = TerrainSlopeField.load(layer='collision')
    assert coarse.grid_size == 129
    assert field.grid_size == 513
    assert coarse.spacing_m > field.spacing_m
    fine_slope = field.slope_deg_native(*DEPOSITS[0])
    coarse_slope = coarse.slope_deg_native(*DEPOSITS[0])
    assert coarse_slope != pytest.approx(fine_slope, abs=1e-6), (
        'the two layers returned an identical slope; one of them is not being '
        'read')


def test_a_missing_heightmap_raises_rather_than_assuming_flat_ground(tmp_path):
    """The failure mode this module must never have.

    A silent fallback to zero slope would make every point traversable and
    reproduce D-28 exactly: a system that believes the ground is fine because
    it cannot see it.
    """
    with pytest.raises(TerrainDataUnavailable) as excinfo:
        TerrainSlopeField.load(heightmap_dir=str(tmp_path))
    assert str(tmp_path) in str(excinfo.value), (
        'the error must name the directory it tried, or it gets worked around '
        'instead of fixed')


# -------------------------------------------------------------------- baseline

def test_the_baseline_is_the_lattice_realisation_of_three_metres(field):
    """3.0 m requested becomes 2.9297 m on the 513 lattice, and says so.

    ``selene_sim/test/test_mission_traversability.py:75`` uses BASELINE_M = 3.0
    exactly, over a 0.5 m radial resample. This module differences whole
    lattice cells, so it cannot hit 3.0 and must publish what it did hit --
    a gate comparing against an exact-3.0 m reference needs to know the
    difference is 2.3 percent rather than zero.
    """
    assert field.requested_baseline_m == DEFAULT_BASELINE_M == 3.0
    assert field.spacing_m == pytest.approx(500.0 / 512.0, abs=1e-9)
    assert field.effective_baseline_m == pytest.approx(3 * 500.0 / 512.0, abs=1e-9)
    assert field.effective_baseline_m == pytest.approx(2.9297, abs=1e-4)


# ------------------------------------------------ agreement with the gate

def _gate_gentlest_exit_deg(field, azimuths):
    """``test_the_crater_is_a_one_way_trip``'s algorithm, re-implemented.

    From selene_sim/test/test_mission_traversability.py:253-262: for each
    azimuth take the elevation profile out to 95 m at 0.5 m, difference it over
    a 6-sample (3.0 m) window, take the steepest ASCENT on that azimuth, and
    report the gentlest such maximum over all azimuths. Elevations come from
    this module rather than from the generator, which is the whole point of the
    comparison.
    """
    cx, cy = CRATER_CENTRE
    radii = np.arange(0.0, 95.0, 0.5)
    window = int(round(3.0 / 0.5))
    gentlest = 90.0
    for index in range(azimuths):
        az = 2.0 * math.pi * index / azimuths
        zs = np.array([field.elevation_native_m(cx + r * math.cos(az),
                                                cy + r * math.sin(az))
                       for r in radii])
        grad = (zs[window:] - zs[:-window]) / (radii[window:] - radii[:-window])
        gentlest = min(gentlest, math.degrees(math.atan(float(grad.max()))))
    return gentlest


def _two_d_gentlest_exit_deg(field, azimuths):
    """The same sweep read through this module's 2-D slope instead."""
    cx, cy = CRATER_CENTRE
    radii = np.arange(0.0, 95.0, 0.5)
    gentlest = 90.0
    for index in range(azimuths):
        az = 2.0 * math.pi * index / azimuths
        steepest = max(field.slope_deg_native(cx + r * math.cos(az),
                                              cy + r * math.sin(az))
                       for r in radii)
        gentlest = min(gentlest, steepest)
    return gentlest


@pytest.mark.parametrize('azimuths,published', [(24, 34.26), (72, 34.09)])
def test_the_gate_algorithm_still_gives_its_published_figures(field, azimuths,
                                                              published):
    """Run the gate's own method on this module's field, get the gate's numbers.

    34.26 and 34.09 are what ``test_mission_traversability.py`` prints and what
    the deviation register quotes. Recomputed here from the decoded PNG they
    come out 34.26 and 34.10; the 0.01 is the 1.85e-4 m encode residual, not a
    disagreement. This is the assertion that fails if anyone regrades the
    terrain.
    """
    measured = _gate_gentlest_exit_deg(field, azimuths)
    assert measured == pytest.approx(published, abs=0.05), (
        f'the gentlest crater exit over {azimuths} azimuths is now '
        f'{measured:.2f} deg, published {published:.2f}. Either the terrain '
        f'changed or the decode did.')


@pytest.mark.parametrize('azimuths', [24, 72])
def test_two_d_slope_agrees_with_the_gate_within_half_a_degree(field, azimuths):
    """The justification for quoting either number as "the slope".

    The gate takes a 1-D directional derivative along a radius over an exact
    3.0 m baseline; this module takes the 2-D gradient magnitude over 2.93 m of
    lattice. They are different quantities and are entitled to differ. MEASURED
    at matched azimuth counts: 34.26 vs 34.28 at 24, 34.10 vs 34.03 at 72 --
    0.02 and 0.06 deg, which is what makes 0.5 a justified tolerance rather
    than a chosen one.
    """
    gate = _gate_gentlest_exit_deg(field, azimuths)
    two_d = _two_d_gentlest_exit_deg(field, azimuths)
    assert abs(gate - two_d) <= GATE_AGREEMENT_TOL_DEG, (
        f'{azimuths} azimuths: gate {gate:.2f} deg, 2-D gradient '
        f'{two_d:.2f} deg, apart by {abs(gate - two_d):.2f} deg. The two '
        f'measures of "the crater rim" have diverged; one of them changed.')


# ------------------------------------------------------------------ landmarks

@pytest.mark.parametrize('point,expected', [
    ((-60.0, -120.0), 36.80),
    ((-75.0, -100.0), 37.26),
    (DEPOT, 1.80),
])
def test_native_landmarks(field, point, expected):
    """SAMPLING_NATIVE figures. Do not compare these against the table below.

    (-60, -120) and (-75, -100) are on the PSR crater wall and are over 36 deg;
    the depot on the crater floor is under 2. Every number is the bilinear
    reading of the native slope grid AT THAT EXACT POINT.
    """
    measured = field.slope_deg_native(*point)
    assert measured == pytest.approx(expected, abs=0.05), (
        f'native slope at {point} is {measured:.2f} deg, pinned {expected:.2f}')


@pytest.mark.parametrize('point,expected', [
    ((-60.0, -120.0), 37.36),
    ((-75.0, -100.0), 37.08),
    (DEPOT, 1.76),
])
def test_resampled_landmarks(lattice, point, expected):
    """SAMPLING_RESAMPLED figures, at the same three points.

    Each is the slope at the CELL CENTRE containing the query -- (-59.5,
    -119.5), (-74.5, -99.5), (-99.5, -149.5) -- because a planner acts per cell
    and cannot address a point. Every one of these differs from the native
    figure above and the difference is the subject of the next test.
    """
    measured = lattice.slope_deg_at(*point)
    assert measured == pytest.approx(expected, abs=0.05), (
        f'resampled slope at {point} is {measured:.2f} deg, pinned '
        f'{expected:.2f}')


def test_the_two_landmark_sets_actually_disagree(field, lattice):
    """The named landmarks differ by 0.02 to 0.56 deg. Guards the pinning.

    If a refactor ever made ``slope_deg_at`` interpolate at the point instead
    of reading the cell, every figure in the two tests above would collapse
    onto one set and both would still pass at abs=0.05 for two of the three
    points. This asserts the wall points remain measurably apart.
    """
    for point in ((-60.0, -120.0), (-75.0, -100.0)):
        gap = abs(field.slope_deg_native(*point) - lattice.slope_deg_at(*point))
        assert gap > 0.1, (
            f'native and resampled now agree to {gap:.4f} deg at {point}; the '
            f'two methods have become the same method')


def test_the_sampling_methods_agree_exactly_at_cell_centres(field, lattice):
    """WHERE the difference comes from, asserted rather than asserted about.

    The resampled lattice IS the native slope evaluated at cell centres, so at
    a cell centre the two methods must agree to float32 precision. Everything
    in the next test is therefore a POSITION offset of up to half a cell
    diagonal, not a different way of computing slope.
    """
    worst = 0.0
    for gy in range(0, 500, 37):
        for gx in range(0, 500, 41):
            wx, wy = lattice.grid_to_world(gx, gy)
            worst = max(worst, abs(field.slope_deg_native(wx, wy)
                                   - lattice.slope_deg_at(wx, wy)))
    assert worst < 1e-4, (
        f'the two methods disagree by {worst:.2e} deg at cell centres, where '
        f'they are the same computation. The resample is not what it claims.')


def test_the_sampling_difference_is_bounded_and_is_not_small(field, lattice):
    """THE DOCUMENTED PROPERTY, and it is worse than the landmarks suggest.

    Over 4000 pseudo-random points (seed 7, so this is reproducible and not a
    sample that moves) the native-versus-resampled difference is 0.08 deg at
    the median and 1.29 deg at the 99th percentile, but its MAXIMUM is
    8.83 deg -- at (138.097, -110.048), which reads 13.88 native while its own
    cell centre 0.606 m away reads 22.71, on the rim of the secondary crater at
    (150, -120).

    So the 0.6 deg figure that circulates for this discrepancy describes three
    particular landmarks and is not a bound. A planner reading the resampled
    lattice near a sharp rim can be nine degrees away from the native field --
    which is an argument for the planner acting on the lattice it plans on, and
    against quoting a native figure to justify a lattice decision.

    The bound below is 12 deg: comfortably above the measured 8.83 so ordinary
    float noise cannot trip it, comfortably below the 36-degree readings the
    landmarks show so a genuine regrade cannot hide under it.
    """
    rng = np.random.default_rng(7)
    xs = rng.uniform(-240.0, 240.0, 4000)
    ys = rng.uniform(-240.0, 240.0, 4000)
    diffs = np.array([abs(field.slope_deg_native(x, y) - lattice.slope_deg_at(x, y))
                      for x, y in zip(xs, ys)])
    worst = float(diffs.max())
    index = int(diffs.argmax())
    assert worst < 12.0, (
        f'native vs resampled now differs by {worst:.2f} deg at '
        f'({xs[index]:.3f}, {ys[index]:.3f}); it was 8.83 deg at '
        f'(138.097, -110.048). The lattice has stopped tracking the field.')
    assert worst > 3.0, (
        f'the worst native-vs-resampled difference has fallen to {worst:.2f} '
        f'deg from 8.83. That is good news, but it means the resample or the '
        f'terrain changed and this test and its docstring are now wrong.')
    assert float(np.median(diffs)) == pytest.approx(0.08, abs=0.03)


# ------------------------------------------------------------- refusing reads

def test_off_lattice_and_non_finite_reads_refuse_rather_than_admit(lattice):
    """``inf`` off the map, so an unguarded ``<= limit`` says no.

    NaN is rejected explicitly rather than by comparison accident: NaN compares
    false against everything, so a guard written as ``slope < limit`` would
    return the right answer for the wrong reason and stop doing so the moment
    somebody inverted it.
    """
    for wx, wy in ((-260.0, 0.0), (260.0, 0.0), (0.0, -260.0), (0.0, 260.0),
                   (float('nan'), 0.0), (0.0, float('inf'))):
        assert lattice.slope_deg_at(wx, wy) == float('inf')
        assert not lattice.is_traversable(wx, wy, 89.0)
    assert math.isnan(lattice.elevation_at_m(float('nan'), 0.0))
    assert lattice.slope_deg_cell(-1, 0) == float('inf')
    assert lattice.slope_deg_cell(0, 500) == float('inf')


def test_lattice_geometry_matches_the_occupancy_grid_it_will_plan_on():
    """Same cells, same centres, as the grid the planner already builds.

    ``resample_to_grid`` is duck-typed so this module never imports the
    navigation stack, which means nothing but a test can catch the two
    conventions drifting apart.
    """
    grid = OccupancyGrid(width=500, height=500, resolution=1.0,
                         origin_x=-250.0, origin_y=-250.0)
    field = TerrainSlopeField.load()
    lat = field.resample_to_grid(grid)
    assert (lat.width, lat.height) == (grid.width, grid.height)
    assert lat.resolution == grid.resolution
    assert (lat.origin_x, lat.origin_y) == (grid.origin_x, grid.origin_y)
    for gx, gy in ((0, 0), (13, 401), (250, 250), (499, 499)):
        assert lat.grid_to_world(gx, gy) == grid.grid_to_world(gx, gy)
        wx, wy = lat.grid_to_world(gx, gy)
        assert lat.world_to_grid(wx, wy) == grid.world_to_grid(wx, wy) == (gx, gy)


def test_cost_grid_is_usable_as_a_planner_cost(lattice):
    """0 on the flat, *weight* at the limit, impassable above it.

    ``AStarPlanner`` used to multiply ``slope_penalty_weight`` by an
    OccupancyGrid cost that no terrain had ever written to, so its slope term
    was identically zero. This is the array that ended that -- though
    ``OccupancyGrid.load_terrain`` writes a FINITE cost above the limit rather
    than the ``inf`` this method defaults to, because an infinite per-cell cost
    is a per-cell refusal and a per-cell refusal at the measured limit
    disconnects the depot from every spawn. Both behaviours are exercised here;
    the choice is the caller's, which is what the ``impassable_cost`` argument
    is for.
    """
    cost = lattice.cost_grid(DECLARED_LIMIT_DEG, weight=2.0)
    slope = np.asarray(lattice.slope_deg)
    passable = slope <= np.float32(DECLARED_LIMIT_DEG)
    assert np.all(np.isinf(cost[~passable])), 'over-limit cells must be refused'
    assert np.all(np.isfinite(cost[passable]))
    assert float(cost[passable].min()) == pytest.approx(
        2.0 * float(slope[passable].min()) / DECLARED_LIMIT_DEG, abs=1e-6)
    assert float(cost[passable].max()) <= 2.0 + 1e-6
    finite = lattice.cost_grid(DECLARED_LIMIT_DEG, weight=2.0,
                               impassable_cost=1e6)
    assert np.all(np.isfinite(finite)), (
        'a finite impassable_cost must produce a finite grid, so a caller can '
        'choose "expensive" over "unreachable"')
    with pytest.raises(ValueError):
        lattice.cost_grid(0.0)


def test_sampling_methods_are_named_and_describable():
    """The tags exist so a number can carry its method. Cheap, and load-bearing
    for every report that quotes one."""
    assert SAMPLING_NATIVE != SAMPLING_RESAMPLED
    assert 'native' in describe_sampling(SAMPLING_NATIVE)
    assert 'cell centre' in describe_sampling(SAMPLING_RESAMPLED)
    with pytest.raises(ValueError):
        describe_sampling('whatever')


def test_profile_along_walks_the_ground_it_says_it_walks(field):
    """The campaign's corridor check: is this grade SUSTAINED over a drive?

    Uphill from a wall point the elevation must rise monotonically enough that
    a 4.8 m run is really a climb, not a one-cell feature.
    """
    start = (-60.0, -120.0)
    azimuth = field.uphill_azimuth_rad_native(*start)
    profile = field.profile_along(start[0], start[1], azimuth, 4.8, step_m=0.5)
    assert profile['sampling'] == SAMPLING_NATIVE
    assert len(profile['s']) == len(profile['slope_deg']) == 11
    assert profile['elevation_m'][-1] > profile['elevation_m'][0], (
        'the uphill azimuth did not go uphill')
    downhill = field.profile_along(start[0], start[1], azimuth + math.pi, 4.8,
                                   step_m=0.5)
    assert downhill['elevation_m'][-1] < downhill['elevation_m'][0]
    rise = profile['elevation_m'][-1] - profile['elevation_m'][0]
    assert math.degrees(math.atan(rise / 4.8)) == pytest.approx(
        field.slope_deg_native(*start), abs=6.0), (
        'the mean grade over the corridor is nowhere near the grade at its '
        'start, so this site would not measure what it claims to')


# --------------------------------------------------- the shape of the world

def test_fifteen_degrees_splits_the_world_into_two_large_components(components):
    """PINNED, NOT ASSERTED AS DESIRABLE. This is a recorded world property.

    MEASURED on the shipped seed-42 terrain, 4-connected: 7 components, of
    which two matter -- a plain of 227,185 cells and a crater basin of 3,531.
    (An earlier independent analysis reported 227,060 for the plain; that
    figure does NOT reproduce here and the basin's 3,531 does. See the report
    accompanying this file.)

    If this fails with different sizes somebody regraded the terrain, and the
    slope constant the campaign is about to commit was measured on a world that
    no longer exists.
    """
    assert components.limit_deg == DECLARED_LIMIT_DEG
    assert components.connectivity == 4
    assert components.count == 7
    sizes = [size for _, size in components.sizes_sorted()]
    assert sizes[0] == pytest.approx(227185, rel=0.005)
    assert sizes[1] == pytest.approx(3531, rel=0.005)
    assert sizes[2] < 500, (
        'a third large component appeared; the two-basin description of this '
        'world is no longer complete')
    assert components.passable_cells() == sum(sizes)
    assert sum(sizes) < 500 * 500, 'some ground must be over the limit'


def test_the_fleet_and_the_depot_are_in_different_components(components):
    """The finding that makes enforcing 15 degrees break a working mission.

    All ten spawns and the recharge pad are on the plain; the depot and all
    four ice deposits are in the crater basin. A hard 15 degree cut refuses
    every spawn-to-depot route.
    """
    spawn_labels = {components.label_at(*p) for p in SPAWNS}
    assert spawn_labels != {IMPASSABLE_LABEL}
    assert len(spawn_labels) == 1, (
        f'the ten spawns are spread over components {sorted(spawn_labels)}; '
        f'they were all in one')
    plain = spawn_labels.pop()
    assert components.label_at(*RECHARGE_PAD) == plain

    basin = components.label_at(*DEPOT)
    assert basin != IMPASSABLE_LABEL, 'the depot is on impassable ground'
    assert basin != plain, (
        'the depot is now in the same component as the fleet. That is good '
        'news and it means a 15 degree limit no longer breaks the mission -- '
        'update this test, D-28 and the campaign together.')
    for deposit in DEPOSITS:
        assert components.label_at(*deposit) == basin, (
            f'ice deposit at {deposit} is not in the depot basin')

    for spawn in SPAWNS:
        assert not components.same_component(spawn, DEPOT)
    unreachable = components.unreachable_pairs(
        {'depot': DEPOT, 'recharge_pad': RECHARGE_PAD, 'spawn': SPAWNS[0]})
    assert len(unreachable) == 2


def test_the_configured_recharge_position_is_on_impassable_ground(lattice,
                                                                  components):
    """``mission.recharge_position: [-75, -100]`` was on a 37 degree wall.

    Not a lint of the config -- a fact about it, and the fact that got the key
    DELETED on 2026-08-01 (D-32). It was a third recharge position, disagreeing
    with both the ``recharge_pad`` marker and the depot, read by nothing, and in
    no per-cell passable component at all at the probe limit. The coordinate is
    still measured here because "it was deleted for a reason" is only worth
    anything if the reason stays checkable; that the KEY is gone is asserted by
    ``test_startup_reachability_audit.py``, and that the planner would now
    REFUSE it as a goal by ``test_navigator_slope_enforcement.py``.
    """
    assert lattice.slope_deg_at(*NAV_RECHARGE) == pytest.approx(37.08, abs=0.05)
    assert components.label_at(*NAV_RECHARGE) == IMPASSABLE_LABEL, (
        'the configured recharge position is now reachable. Good news; say so '
        'in the register.')
    assert NAV_RECHARGE != RECHARGE_PAD != DEPOT


def test_eight_connectivity_is_available_and_changes_nothing_here(lattice):
    """A coarse lattice can pinch a real corridor into a diagonal.

    It does not here -- the plain and the basin stay separate under 8
    connectivity too -- so the two-component finding is a property of the
    terrain and not of the connectivity choice. That is the whole reason the
    option exists.
    """
    assert lattice.components(DECLARED_LIMIT_DEG).connectivity == 4, (
        'the DEFAULT connectivity is 4 on purpose: a robot cannot squeeze '
        'through a diagonal contact between two cells any more than a wheel '
        'can, and a silently 8-connected default would report the world more '
        'connected than it is')
    eight = lattice.components(DECLARED_LIMIT_DEG, connectivity=8)
    assert eight.connectivity == 8
    assert eight.label_at(*DEPOT) != eight.label_at(*SPAWNS[0])
    assert not eight.same_component(SPAWNS[0], DEPOT)
    assert eight.passable_cells() == lattice.components(
        DECLARED_LIMIT_DEG, connectivity=4).passable_cells(), (
        'connectivity changes how cells are grouped, never which cells pass')
    with pytest.raises(ValueError):
        lattice.components(DECLARED_LIMIT_DEG, connectivity=6)


def test_a_forty_degree_limit_reconnects_the_world(lattice):
    """The complement of the finding above, and the campaign's premise.

    The fleet demonstrably crossed the rim on 2026-07-31. Under a limit above
    the rim's 34 degrees the plain and the basin are one component, which is
    what makes "measure the real capability and enforce that" a coherent plan
    rather than a way of writing off a wall.
    """
    wide = lattice.components(40.0, connectivity=4)
    assert wide.limit_deg == 40.0
    assert wide.same_component(SPAWNS[0], DEPOT), (
        'a 40 degree limit still does not connect the fleet to the depot; the '
        'campaign cannot fix this by measuring a bigger number')
    narrow = lattice.components(DECLARED_LIMIT_DEG, connectivity=4)
    assert wide.count < narrow.count
    assert wide.passable_cells() > narrow.passable_cells(), (
        'raising the limit admitted no extra cells, so the limit argument is '
        'not reaching the mask')


def test_the_lattice_is_a_slopelattice_and_declares_its_sampling(lattice):
    assert isinstance(lattice, SlopeLattice)
    assert lattice.sampling == SAMPLING_RESAMPLED
    assert lattice.slope_deg.shape == (500, 500)
    assert lattice.slope_deg.dtype == np.float32
    with pytest.raises(ValueError):
        np.asarray(lattice.slope_deg)[0, 0] = 0.0


def test_the_environment_variable_really_steers_the_load(
        field, monkeypatch, tmp_path):
    """The path the campaign script uses: explicit, no ament index needed.

    ``scripts/measure_slope_capability.sh`` exports the installed share
    directory rather than relying on a search, so the campaign cannot silently
    measure a different checkout's terrain from the one it reports under a git
    commit. Pointing the variable at a COPY and asserting the load followed it
    there is the only version of this assertion that can fail -- setting it to
    the directory the search would have found anyway proves nothing.
    """
    directory = field.source['directory']
    assert os.path.isdir(directory)
    for name in ('terrain_datum.json', os.path.basename(field.source['image'])):
        shutil.copy(os.path.join(directory, name), str(tmp_path / name))
    monkeypatch.setenv('SELENE_TERRAIN_HEIGHTMAPS', str(tmp_path))
    other = TerrainSlopeField.load()
    assert os.path.normcase(other.source['directory']) == os.path.normcase(
        str(tmp_path)), (
        'the load ignored $SELENE_TERRAIN_HEIGHTMAPS and found its own '
        'terrain; the campaign could then report a different world than the '
        'one it measured')
    assert other.slope_deg_native(*DEPOT) == pytest.approx(
        field.slope_deg_native(*DEPOT), abs=1e-9)
