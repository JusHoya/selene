"""The resource-map overlay maths — FR-MAP-1(e)(f) and FR-MAP-4.

Pure numpy in, plain tuples out, so every one of these runs in the fast CI lane
with no ROS workspace. What is covered is the part that can actually be wrong
and that a running system would not obviously reveal: row order, the observed
predicate, the decimation, and the two mappings the PRD specifies by name.
"""

import math

import numpy as np
import pytest

from selene_orchestrator import resource_map_viz as rmviz
from selene_orchestrator.resource_map import ResourceMap


# --------------------------------------------------------------- observed set

def test_observed_is_count_not_value():
    """A sampled cell reading 0.0 wt% is evidence and must survive.

    Selecting on `mean != 0` would erase exactly the negative evidence a survey
    exists to produce — the cells where a scout looked and found nothing.
    """
    count = np.zeros((4, 4), dtype=np.int32)
    count[2, 1] = 3                      # observed, and its mean will be 0.0
    observed = rmviz.select_observed(count)
    assert observed.tolist() == [2 * 4 + 1]


def test_observed_is_empty_before_any_reading():
    assert rmviz.select_observed(np.zeros((10, 10), dtype=np.int32)).size == 0


def test_flat_index_is_row_major_with_row_zero_at_min_y():
    """cell_index == row * width + col, row 0 = southern edge.

    The .msg documents this and a consumer that assumes column-major, or that
    flips rows the way the heightmap pipeline does, gets silently mirrored
    geometry. This is the assertion that catches it.
    """
    count = np.zeros((3, 5), dtype=np.int32)
    count[0, 1] = 1        # row 0, col 1  -> 1
    count[2, 0] = 1        # row 2, col 0  -> 10
    assert rmviz.select_observed(count).tolist() == [1, 10]


def test_decimation_thins_evenly_and_never_truncates():
    """Over the cap, the whole field must stay represented.

    Truncating to the first N would show a solid block of the southern edge and
    nothing north of it — wrong in a way that looks right.
    """
    count = np.ones((100, 100), dtype=np.int32)      # 10 000 observed
    shown = rmviz.select_observed(count, max_cells=500)
    assert shown.size <= 500
    # Spans essentially the whole index range, rather than the first 500.
    assert shown[0] < 100
    assert shown[-1] > 9_000


def test_decimation_is_deterministic():
    count = np.ones((60, 60), dtype=np.int32)
    a = rmviz.select_observed(count, max_cells=250)
    b = rmviz.select_observed(count, max_cells=250)
    assert a.tolist() == b.tolist()


def test_no_cap_returns_everything():
    count = np.ones((20, 20), dtype=np.int32)
    assert rmviz.select_observed(count, max_cells=None).size == 400


# ------------------------------------------------------------ colour (b)

def test_colour_ramp_is_blue_at_zero_and_red_at_max():
    """FR-MAP-4(b): blue (low / no ice) -> red (high)."""
    r0, g0, b0 = rmviz.concentration_to_rgb(0.0)
    assert b0 > r0 and b0 > g0, 'zero concentration must read blue'
    r1, g1, b1 = rmviz.concentration_to_rgb(rmviz.MAX_CONCENTRATION_WT)
    assert (r1, g1, b1) == (255, 0, 0), 'the top of the ramp must be pure red'


def test_colour_ramp_clamps_outside_range():
    assert rmviz.concentration_to_rgb(-5.0) == rmviz.concentration_to_rgb(0.0)
    assert rmviz.concentration_to_rgb(1e6) == (255, 0, 0)


def test_zero_reading_is_visible_not_black():
    """A "sampled here, found nothing" cell must not vanish into the scene.

    Ported deliberately from the dashboard, which hit this: at pure black the
    'screen' composite makes a real zero reading indistinguishable from terrain
    nobody ever visited.
    """
    assert rmviz.concentration_to_rgb(0.0) == rmviz.ICE_FLOOR_RGB
    assert sum(rmviz.ICE_FLOOR_RGB) > 0


def test_red_channel_is_monotonic_in_concentration():
    reds = [rmviz.concentration_to_rgb(v)[0] for v in np.linspace(2.5, 10.0, 40)]
    assert reds == sorted(reds)


def test_ramp_matches_the_dashboard_at_the_segment_boundaries():
    """Same posterior, same colour in RViz2 and the dashboard.

    The boundary values are the ones colors.js pins by construction; if this
    port drifts, the PRD's side-by-side comparison (docs/PRD.md:1504) compares
    two different palettes.
    """
    assert rmviz.concentration_to_rgb(2.5) == (0, 0, 255)       # pure blue
    assert rmviz.concentration_to_rgb(5.0) == (0, 255, 255)     # cyan
    assert rmviz.concentration_to_rgb(7.5) == (255, 255, 0)     # yellow
    assert rmviz.concentration_to_rgb(10.0) == (255, 0, 0)      # red


# ------------------------------------------------------------ alpha (c)

def test_alpha_is_minimal_at_the_prior_and_maximal_when_certain():
    """FR-MAP-4(c): transparent = uncertain, opaque = confident."""
    assert rmviz.variance_to_alpha(100.0, 100.0) == pytest.approx(rmviz.ALPHA_MIN)
    assert rmviz.variance_to_alpha(rmviz.VARIANCE_FLOOR, 100.0) == \
        pytest.approx(rmviz.ALPHA_MAX)


def test_alpha_increases_as_variance_falls():
    alphas = [rmviz.variance_to_alpha(v, 100.0)
              for v in (100.0, 10.0, 1.0, 0.1, 0.01)]
    assert alphas == sorted(alphas)
    assert len(set(alphas)) == len(alphas), 'each step must be distinguishable'


def test_alpha_never_reaches_zero_for_an_observed_cell():
    """RViz2 warns on a CUBE_LIST whose every alpha is 0.0, and an observed
    cell is evidence even when uncertain. Unobserved cells are not emitted."""
    for v in (1e9, 100.0, 50.0):
        assert rmviz.variance_to_alpha(v, 100.0) >= rmviz.ALPHA_MIN > 0.0


def test_alpha_stays_below_one_so_rviz_enables_per_point_blending():
    """RViz2's PointsMarker only turns on per-point alpha when some colour has
    a != 1.0. An all-opaque overlay silently falls back to flat marker colour.
    """
    assert rmviz.ALPHA_MAX < 1.0
    assert rmviz.variance_to_alpha(1e-12, 100.0) < 1.0


def test_alpha_is_log_scaled_so_repeat_readings_still_move_it():
    """One reading takes variance 100 -> ~0.09. On a linear map that is alpha
    0.999 and every later reading is lost in the last 0.1% of the range."""
    one = rmviz.variance_to_alpha(0.09, 100.0)
    two = rmviz.variance_to_alpha(0.045, 100.0)
    assert 0.3 < one < 0.8, f'a single reading should not saturate; got {one}'
    assert two - one > 0.01, 'a second reading must be visible'


# ------------------------------------------------------- geometry round-trip

def test_cell_centres_round_trip_through_the_real_grid():
    """The publisher's geometry must agree with ResourceMap.grid_to_world()."""
    rm = ResourceMap(width=40, height=30, resolution=2.0,
                     origin_x=-40.0, origin_y=-30.0)
    geom = rm.geometry
    for gx, gy in ((0, 0), (39, 29), (7, 11)):
        flat = gy * geom['width'] + gx
        xs, ys = rmviz.cell_centres([flat], geom['width'], geom['resolution'],
                                    geom['origin_x'], geom['origin_y'])
        assert (xs[0], ys[0]) == pytest.approx(rm.grid_to_world(gx, gy))


def test_a_reading_lands_where_it_was_taken():
    """End to end over the real Bayesian update: update at a world point, and
    the observed cell centres must surround that point, not its mirror."""
    rm = ResourceMap(width=100, height=100, resolution=1.0,
                     origin_x=-50.0, origin_y=-50.0)
    rm.update(x=-20.0, y=30.0, reading=6.0, sensor_uncertainty=0.5)
    geom = rm.geometry
    observed = rmviz.select_observed(rm.get_count_grid())
    assert observed.size > 0
    xs, ys = rmviz.cell_centres(observed, geom['width'], geom['resolution'],
                                geom['origin_x'], geom['origin_y'])
    assert xs.mean() == pytest.approx(-20.0, abs=1.0)
    assert ys.mean() == pytest.approx(30.0, abs=1.0)


# ------------------------------------------------------------- colour arrays

def test_marker_colours_are_one_per_cell_and_normalised():
    """RViz2 discards per-point colours entirely when the lengths differ, with
    no error surfaced, so length equality is the invariant that matters."""
    means = [0.0, 4.0, 9.0]
    variances = [100.0, 1.0, 0.05]
    cols = rmviz.marker_colours(means, variances, 100.0)
    assert len(cols) == len(means)
    for r, g, b, a in cols:
        assert all(0.0 <= c <= 1.0 for c in (r, g, b, a))


def test_marker_colours_track_their_inputs():
    cols = rmviz.marker_colours([0.0, 10.0], [100.0, 0.01], 100.0)
    assert cols[0][2] > cols[0][0], 'low concentration is blue-dominant'
    assert cols[1][0] > cols[1][2], 'high concentration is red-dominant'
    assert cols[1][3] > cols[0][3], 'the better-observed cell is more opaque'


def test_empty_input_yields_empty_output():
    assert rmviz.marker_colours([], [], 100.0) == []


# ------------------------------------------------- the message-sized picture

def test_a_realistic_survey_stays_sparse():
    """The sparse encoding is only justified while occupancy is low. Ten
    prospect readings touch ~800 of 250 000 cells; assert the shape of that
    claim rather than the exact number, which depends on the waypoints."""
    rm = ResourceMap()          # the production 500x500 default
    for i in range(10):
        rm.update(x=-100.0 + 20.0 * i, y=-150.0, reading=4.0,
                  sensor_uncertainty=0.5)
    observed = rmviz.select_observed(rm.get_count_grid())
    total = rm.geometry['width'] * rm.geometry['height']
    assert 0 < observed.size < total * 0.01, (
        f'{observed.size} of {total} cells observed — sparse encoding assumes '
        f'far below 1%; re-check the ResourceMap.msg size note if this fails')


def test_snapshot_returns_three_consistent_grids():
    # Origin matters: the default is (-250,-250), so world (0,0) is outside a
    # 20x20 grid and nothing would be observed.
    rm = ResourceMap(width=20, height=20, origin_x=-10.0, origin_y=-10.0)
    rm.update(x=0.0, y=0.0, reading=5.0, sensor_uncertainty=0.5)
    mean, var, count = rm.snapshot()
    assert mean.shape == var.shape == count.shape
    observed = count > 0
    assert observed.any()
    # Every observed cell must have moved off the prior in both channels.
    assert (var[observed] < rm.prior_variance).all()


def test_prior_is_reported_for_the_alpha_datum():
    rm = ResourceMap(prior_variance=64.0, prior_mean=1.5)
    assert rm.prior_variance == 64.0
    assert rm.prior_mean == 1.5
    # alpha normalises against whatever prior the map was built with
    assert rmviz.variance_to_alpha(64.0, rm.prior_variance) == \
        pytest.approx(rmviz.ALPHA_MIN)


def test_log_scaling_uses_the_supplied_prior_not_a_constant():
    """A map built with a different prior must still map its own prior to the
    transparent end."""
    for prior in (10.0, 100.0, 1000.0):
        assert rmviz.variance_to_alpha(prior, prior) == \
            pytest.approx(rmviz.ALPHA_MIN)
    assert math.isfinite(rmviz.variance_to_alpha(0.0, 100.0))
