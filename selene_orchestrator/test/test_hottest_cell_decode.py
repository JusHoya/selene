"""The arithmetic the Phase 5 exit gate's check 10 rests on, without ROS.

WHY THIS FILE EXISTS
--------------------
Check 10 of ``scripts/validate_phase5.sh`` claims the PRD's FR-MAP-4(b)
acceptance criterion, "matches underlying data" (``docs/PRD.md:451``). The way
it claims it is one sentence of arithmetic: take the hottest cell of the fused
posterior on the wire, decode its flat row-major index to a world coordinate,
and show that coordinate sits on the ice.

That sentence went unexecuted for the whole life of the check. It was guarded by
``total_observations >= 200``, and a gate-length run cannot reach 200 — a scout
drives ~100 m at 0.3 m/s to its first waypoint and ``agent_node.py:771`` sends it
home to recharge after every task, so the operator measured 155 readings after
~10 minutes and 316 after ~21. Two live gate runs on 2026-07-31 therefore
reported **check 10 PASS on a map with zero cells in it**, with the correctness
half noted as skipped in the same breath.

The live fix is in ``scripts/phase5_probe.py``: the probe now seeds the fused map
through the real ``/orchestrator/map_update`` topic so the assertion can run, and
the assertion is a condition of the PASS rather than a footnote to one. This file
is the other half of the fix. The arithmetic that assertion rests on should not
be provable only by booting Gazebo, ten robots and a rosbridge — and until now it
was, because the probe open-coded ``divmod(index, width)`` in a script no test
imports.

WHAT IS ASSERTED
----------------
1. ``resource_map_viz.cell_centres`` — the one decode the publisher and the probe
   now share — agrees with ``ResourceMap.grid_to_world`` on a NON-SQUARE grid
   with an asymmetric origin at a cell whose row and column differ. Those three
   conditions together are what makes a row/column transpose visible; on a square
   grid at a symmetric origin at a diagonal cell, a transposed decode gives the
   right answer.
2. The row-major convention itself, against hand-computed literals rather than
   against another function in this repository. A shared bug in ``cell_centres``
   and ``grid_to_world`` would satisfy assertion 1 and fail this one.
3. ``origin`` is the OUTER CORNER of cell (0, 0), not its centre — the half-cell
   offset ``ResourceMap.msg`` documents and an off-by-one would drop.
4. End to end, in the ROS-free lane: readings shaped like
   ``selene_sim/config/ice_deposits.yaml``, on the lattice
   ``scripts/phase5_probe.py`` declares, fused by the real ``ResourceMap``,
   sparse-encoded the way ``_publish_resource_map_once`` encodes, rounded to
   float32 the way the wire rounds, decode to within one cell of the deposit
   centre — and do so by a margin that is not a numerical coin flip.

Assertion 4 is what pins the live check: it re-derives, in CI, the number check
10 asserts on the running system. Change ``SEED_LATTICE_PITCH_M`` or
``SEED_LATTICE_HALF_EXTENT_M`` to a pair that puts the fused peak two cells out —
5.0/15.0 passes at 0.707 m, 4.0/12.0 lands at 2.121 m and 2.0/4.0 at 2.915 m —
and this fails here rather than on WSL2 twenty minutes later.

DELIBERATE NON-ASSERTIONS. Nothing here proves a ``ResourceMapUpdate`` published
by the probe reaches the orchestrator, that the two messages share a header
stamp, or that RViz2 draws anything. Those need a live system and they are what
check 10 is for.

ROS-FREE BY CONSTRUCTION. The probe's constants are read with ``ast`` and never
imported: ``scripts/phase5_probe.py`` imports ``rclpy`` at call time, and
``test_phase5_gate_coverage.py`` set the precedent that no test in this lane
imports it. ``ResourceMap`` and ``resource_map_viz`` are pure numpy.
"""

import ast
import math
import os

import numpy as np
import pytest
import yaml

from selene_orchestrator import resource_map_viz as rmviz
from selene_orchestrator.resource_map import ResourceMap

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

PROBE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'phase5_probe.py')
ICE_CONFIG = os.path.join(_REPO_ROOT, 'selene_sim', 'config',
                          'ice_deposits.yaml')

#: Constants pulled out of the probe. Named here so a rename over there fails
#: loudly with "not a module-level assignment" rather than silently skipping.
_WANTED = ('SEED_LATTICE_PITCH_M', 'SEED_LATTICE_HALF_EXTENT_M',
           'SEED_SENSOR_SIGMA_WT', 'MIN_MAP_OBSERVATIONS')


def _probe_constants():
    """Module-level literals from scripts/phase5_probe.py, without importing it."""
    if not os.path.isfile(PROBE_SCRIPT):
        pytest.skip('scripts/phase5_probe.py is not present in this checkout')
    with open(PROBE_SCRIPT, 'r', encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in _WANTED:
                found[target.id] = ast.literal_eval(node.value)
    missing = sorted(set(_WANTED) - set(found))
    assert not missing, (
        '%s are not module-level assignments in scripts/phase5_probe.py. Check '
        '10 reads them to build its seed; this test reads them to re-derive '
        'what that seed must produce, and the two must not drift.' % (missing,))
    return found


def _ice_config():
    """The ground-truth deposit field, as selene_sim configures it."""
    if not os.path.isfile(ICE_CONFIG):
        pytest.skip('selene_sim/config/ice_deposits.yaml is not present')
    with open(ICE_CONFIG, 'r', encoding='utf-8') as handle:
        config = yaml.safe_load(handle) or {}
    deposits = config.get('deposits') or []
    assert deposits, 'ice_deposits.yaml declares no deposits'
    sensor = ((config.get('sensor_parameters') or {})
              .get('neutron_spectrometer') or {})
    return deposits, float(sensor.get('max_detection_range', 10.0))


def _field(x, y, deposits, max_range):
    """Ground-truth concentration at (x, y), wt%.

    Ported from ``NeutronSpectrometerNode._compute_concentration``
    (``selene_sim/selene_sim/neutron_spectrometer_node.py:72-92``), range gate
    included. ``scripts/phase5_probe.py`` ports the same eight lines; both port
    from the sim node, which is the ground truth for what a scout would report.
    If the two ports ever diverge, the live check fails and this test does not —
    a false FAIL on the gate, never a false PASS, which is the direction this
    whole change is trying to move errors in.
    """
    total = 0.0
    for deposit in deposits:
        cx, cy = deposit['center']
        dist = math.hypot(x - cx, y - cy)
        if dist <= deposit.get('radius', 20.0) + max_range:
            total += deposit.get('peak_concentration', 5.0) * math.exp(
                -(dist ** 2) / (2 * deposit.get('sigma', 10.0) ** 2))
    return total


# ======================================================================
# 1-3. The decode itself.
# ======================================================================

def test_decode_agrees_with_grid_to_world_on_an_asymmetric_grid():
    """cell_centres(row * width + col) == grid_to_world(col, row).

    NON-SQUARE (40 x 30), ASYMMETRIC ORIGIN (-11.5, +7.25) and row != col, all
    three on purpose. A transposed decode — ``divmod(index, height)``, or
    swapping the returned pair — agrees with the correct one on a square grid,
    and an origin error cancels when origin_x == origin_y. The cells below are
    chosen so neither excuse is available.
    """
    grid = ResourceMap(width=40, height=30, resolution=2.0,
                       origin_x=-11.5, origin_y=7.25)
    geom = grid.geometry
    for col, row in ((0, 0), (39, 29), (7, 11), (11, 7), (39, 0), (0, 29)):
        flat = row * geom['width'] + col
        xs, ys = rmviz.cell_centres([flat], geom['width'], geom['resolution'],
                                    geom['origin_x'], geom['origin_y'])
        assert (float(xs[0]), float(ys[0])) == pytest.approx(
            grid.grid_to_world(col, row)), (
                'flat index %d (row %d, col %d) decoded to (%.4f, %.4f) but '
                'ResourceMap.grid_to_world puts it at %r'
                % (flat, row, col, xs[0], ys[0], grid.grid_to_world(col, row)))


def test_decode_is_row_major_and_a_transpose_is_visible():
    """Against literals, not against another function in this repository.

    ``cell_index = row * width + col`` (ResourceMap.msg), row 0 at minimum y.
    On a 40-wide grid at 2.0 m with origin (-11.5, 7.25):

        row 11, col 7  -> flat 447 -> x = -11.5 + (7 + 0.5) * 2 = 3.5
                                      y =   7.25 + (11 + 0.5) * 2 = 30.25
        row 7,  col 11 -> flat 291 -> x = -11.5 + (11 + 0.5) * 2 = 11.5
                                      y =   7.25 + (7 + 0.5) * 2 = 22.25

    Both cells exist, both are in bounds, and they decode to different points.
    A column-major reader, or one that swapped x and y, would map one onto the
    other and pass every round-trip test that only ever asks two functions to
    agree with each other.
    """
    width, resolution, origin_x, origin_y = 40, 2.0, -11.5, 7.25

    xs, ys = rmviz.cell_centres([11 * width + 7], width, resolution,
                                origin_x, origin_y)
    assert float(xs[0]) == pytest.approx(3.5)
    assert float(ys[0]) == pytest.approx(30.25)

    xs, ys = rmviz.cell_centres([7 * width + 11], width, resolution,
                                origin_x, origin_y)
    assert float(xs[0]) == pytest.approx(11.5)
    assert float(ys[0]) == pytest.approx(22.25)


def test_origin_is_the_outer_corner_not_a_cell_centre():
    """The half-cell offset, which an off-by-one origin would drop.

    ``ResourceMap.msg`` documents ``origin`` as the lower-left OUTER CORNER of
    cell (0, 0), the same convention as nav_msgs/MapMetaData. Cell 0's centre is
    therefore half a cell in from it on both axes, and the last cell's centre is
    half a cell in from the far corner — not at either corner. Getting this
    wrong shifts every cube in the RViz2 overlay by half a cell, which is
    invisible on screen and exactly the size of the error check 10's one-cell
    tolerance is meant to catch.
    """
    width, height, resolution = 40, 30, 2.0
    origin_x, origin_y = -11.5, 7.25

    xs, ys = rmviz.cell_centres([0], width, resolution, origin_x, origin_y)
    assert float(xs[0]) == pytest.approx(origin_x + resolution / 2.0)
    assert float(ys[0]) == pytest.approx(origin_y + resolution / 2.0)
    assert float(xs[0]) != pytest.approx(origin_x)

    far = width * height - 1
    xs, ys = rmviz.cell_centres([far], width, resolution, origin_x, origin_y)
    assert float(xs[0]) == pytest.approx(
        origin_x + width * resolution - resolution / 2.0)
    assert float(ys[0]) == pytest.approx(
        origin_y + height * resolution - resolution / 2.0)


def test_argmax_over_parallel_arrays_indexes_through_cell_index():
    """The step between "hottest" and "decode" — and it is easy to skip.

    ResourceMap.msg's four arrays are PARALLEL and sparse: position i in
    ``cell_mean`` describes the cell whose flat index is ``cell_index[i]``, and
    the two numbers are unrelated. Feeding ``argmax(cell_mean)`` straight into
    the decode — instead of through ``cell_index`` — is a decode of the wrong
    cell that still returns a plausible coordinate inside the grid.
    """
    width = 40
    cell_index = [5, 447, 900]
    cell_mean = [1.0, 9.0, 2.0]
    hot = int(np.argmax(cell_mean))
    assert hot == 1
    assert cell_index[hot] == 447

    right = rmviz.cell_centres([cell_index[hot]], width, 2.0, -11.5, 7.25)
    wrong = rmviz.cell_centres([hot], width, 2.0, -11.5, 7.25)
    assert (float(right[0][0]), float(right[1][0])) == pytest.approx(
        (3.5, 30.25))
    assert (float(wrong[0][0]), float(wrong[1][0])) != pytest.approx(
        (3.5, 30.25))


# ======================================================================
# 4. The whole of check 10's correctness half, re-derived without ROS.
# ======================================================================

def _fuse_the_probe_seed(resolution, width):
    """Run the probe's seed through the real fusion and sparse encoder.

    Mirrors, in order: ``seed_resource_map``'s lattice, the orchestrator's
    ``ResourceMap`` construction (``orchestrator_node.py:999-1005``, which
    passes no footprint and takes the class defaults, and centres the origin),
    ``_publish_resource_map_once``'s ``select_observed`` encoding, and
    ResourceMap.msg's float32 ``cell_mean``.
    """
    constants = _probe_constants()
    deposits, max_range = _ice_config()
    strongest = max(deposits, key=lambda d: d.get('peak_concentration', 5.0))
    peak_x, peak_y = (float(strongest['center'][0]),
                      float(strongest['center'][1]))

    pitch = constants['SEED_LATTICE_PITCH_M']
    steps = int(round(constants['SEED_LATTICE_HALF_EXTENT_M'] / pitch))
    points = [(peak_x + i * pitch, peak_y + j * pitch)
              for i in range(-steps, steps + 1)
              for j in range(-steps, steps + 1)]

    grid = ResourceMap(width=width, height=width, resolution=resolution,
                       origin_x=-width * resolution / 2.0,
                       origin_y=-width * resolution / 2.0)
    for x, y in points:
        assert grid.update(x, y, _field(x, y, deposits, max_range),
                           constants['SEED_SENSOR_SIGMA_WT']), (
            'ResourceMap.update rejected a seeded reading at (%.1f, %.1f); its '
            'guard only rejects non-finite values and sigma <= 0' % (x, y))

    mean_grid, _var_grid, count_grid = grid.snapshot()
    observed = rmviz.select_observed(count_grid)
    flat_mean = mean_grid.reshape(-1)
    # float32 exactly where the wire applies it: ResourceMap.msg's cell_mean.
    # The argmax is taken over the ROUNDED values because that is what a
    # subscriber — check 10 included — actually sees.
    wire_mean = np.asarray([np.float32(flat_mean[i]) for i in observed],
                           dtype=np.float64)
    return {
        'constants': constants,
        'peak': (peak_x, peak_y),
        'deposit_id': strongest.get('id', '?'),
        'readings': len(points),
        'observations': int(grid.get_total_readings()),
        'observed': observed,
        'wire_mean': wire_mean,
        'geometry': grid.geometry,
    }


def test_the_seeded_hottest_cell_decodes_onto_the_deposit():
    """The live assertion, re-derived in CI. 0.707 m at 1.0 m cells.

    This is the number D-08 measured independently from a real 256-reading
    survey ("the hottest cell, 7.877 wt%, decodes row-major to world
    (-80.5, -140.5) - 0.7 m from the ice_deposits.yaml deposit centred
    (-80, -140)"). 0.707 m is the half-diagonal of a 1.0 m cell: the deposit
    centre falls on a cell CORNER, so the nearest cell centre to it is exactly
    that far away and no decode can do better.
    """
    fused = _fuse_the_probe_seed(resolution=1.0, width=500)
    geom = fused['geometry']
    peak_x, peak_y = fused['peak']

    assert fused['observations'] >= fused['constants']['MIN_MAP_OBSERVATIONS'], (
        'the seed produces %d observations, below the %d check 10 requires '
        'before it will make the hottest-cell assertion at all'
        % (fused['observations'], fused['constants']['MIN_MAP_OBSERVATIONS']))

    hot = int(np.argmax(fused['wire_mean']))
    flat = int(fused['observed'][hot])
    xs, ys = rmviz.cell_centres([flat], geom['width'], geom['resolution'],
                                geom['origin_x'], geom['origin_y'])
    distance = math.hypot(float(xs[0]) - peak_x, float(ys[0]) - peak_y)

    assert distance <= geom['resolution'], (
        'the hottest cell of the seeded posterior decodes to (%.2f, %.2f), '
        '%.3f m from %s at (%.1f, %.1f) — more than one %.2f m cell. Check 10 '
        'FAILS on the running system with this seed geometry (pitch %.1f, '
        'half-extent %.1f).'
        % (xs[0], ys[0], distance, fused['deposit_id'], peak_x, peak_y,
           geom['resolution'], fused['constants']['SEED_LATTICE_PITCH_M'],
           fused['constants']['SEED_LATTICE_HALF_EXTENT_M']))
    assert distance == pytest.approx(0.707, abs=0.01), (
        'expected the half-diagonal of a 1.0 m cell, measured %.3f m' % (
            distance,))


def test_the_hottest_cell_wins_by_a_margin_not_a_rounding_accident():
    """A correct answer reached by a tie is a coin flip, not a measurement.

    The fused posterior is a 5 m Gaussian smoothing (ResourceMap's default
    footprint) of a field whose own sigma is 12 m, so its top is nearly flat and
    a badly chosen lattice produces a plateau where the argmax is decided by the
    last bit of a float32. MEASURED over a sweep of geometries while choosing
    the shipped one: pitch 6.0 / half-extent 18.0 lands in the right cell with a
    margin of exactly 0.0, and pitch 2.0 / half-extent 4.0 has ten cells within
    0.003 wt% of each other spread over 0.7-4.9 m. Both would pass the distance
    assertion above on some runs and not others.
    """
    fused = _fuse_the_probe_seed(resolution=1.0, width=500)
    ordered = np.sort(fused['wire_mean'])[::-1]
    margin = float(ordered[0] - ordered[1])
    # float32 near 7.8 wt% has a quantum of ~4.8e-7; 1e-3 is three orders above
    # it and four below the 0.0389 measured for the shipped geometry.
    assert margin > 1e-3, (
        'the hottest cell leads the runner-up by only %.3g wt%%. The seed '
        'geometry has produced a plateau, so which cell check 10 decodes is a '
        'rounding accident even when the answer is right.' % (margin,))


@pytest.mark.parametrize('resolution,width,expected', [
    (0.5, 1000, 0.354),
    (1.0, 500, 0.707),
    (2.0, 250, 1.414),
])
def test_the_one_cell_tolerance_holds_at_every_shipped_resolution(
        resolution, width, expected):
    """Check 10 bounds the error by ``resolution``, not by a metre count.

    That is only honest if the error really does scale with the cell. It does:
    the deposit centre sits on a cell corner at every resolution the grid can
    take, so the nearest cell centre is always half a diagonal away — 0.707 x
    resolution — and the bound holds with 29% headroom rather than by luck.
    """
    fused = _fuse_the_probe_seed(resolution=resolution, width=width)
    geom = fused['geometry']
    peak_x, peak_y = fused['peak']
    hot = int(np.argmax(fused['wire_mean']))
    xs, ys = rmviz.cell_centres([int(fused['observed'][hot])], geom['width'],
                                geom['resolution'], geom['origin_x'],
                                geom['origin_y'])
    distance = math.hypot(float(xs[0]) - peak_x, float(ys[0]) - peak_y)
    assert distance == pytest.approx(expected, abs=0.01)
    assert distance <= geom['resolution']
