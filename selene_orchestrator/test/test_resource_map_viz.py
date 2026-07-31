"""The resource-map overlay maths — FR-MAP-1(e)(f) and FR-MAP-4.

Pure numpy in, plain tuples out, so every one of these runs in the fast CI lane
with no ROS workspace. What is covered is the part that can actually be wrong
and that a running system would not obviously reveal: row order, the observed
predicate, the decimation, and the two mappings the PRD specifies by name.
"""

import math
import pathlib

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
    """Variance 0.09 is about where the THIRD reading at a cell lands (0.0833
    measured against the shipped RCDL — see
    test_the_shipped_scout_cannot_reach_zero_certainty). On a linear map it is
    alpha 0.999 and every later reading is lost in the last 0.1% of the range.

    This docstring used to say 0.09 was where the FIRST reading landed. It is
    not: one reading gives 0.2494 at the footprint centre and 0.9926 at its
    edge. The assertions were always about the value, not the reading count.
    """
    one = rmviz.variance_to_alpha(0.09, 100.0)
    two = rmviz.variance_to_alpha(0.045, 100.0)
    assert 0.3 < one < 0.8, f'a few readings should not saturate; got {one}'
    assert two - one > 0.01, 'a further reading must be visible'


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


# ------------------------------------------- certainty, the shared definition

def test_certainty_endpoints():
    """0.0 at the prior, 1.0 at the variance floor. Both renderers normalise
    against the map's OWN prior, not a constant."""
    assert rmviz.variance_to_certainty(100.0, 100.0) == pytest.approx(0.0)
    assert rmviz.variance_to_certainty(rmviz.VARIANCE_FLOOR, 100.0) == \
        pytest.approx(1.0)
    for prior in (10.0, 100.0, 1000.0):
        assert rmviz.variance_to_certainty(prior, prior) == pytest.approx(0.0)


def test_certainty_is_monotonic_in_falling_variance():
    values = [rmviz.variance_to_certainty(v, 100.0)
              for v in (100.0, 10.0, 1.0, 0.1, 0.01)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_certainty_is_log_scaled_not_linear():
    """A linear map puts a cell at variance 0.09 — roughly three readings from
    the shipped scout — at 0.9991, and everything beyond it in the last 0.1%
    of the range. On this log scale it reads 0.76 and keeps moving."""
    three = rmviz.variance_to_certainty(0.09, 100.0)
    assert 0.6 < three < 0.85, three
    assert three == pytest.approx(0.76, abs=0.02)
    linear = 1.0 - 0.09 / 100.0
    assert linear > 0.999, linear


def test_certainty_clamps_outside_its_domain():
    assert rmviz.variance_to_certainty(1e9, 100.0) == 0.0
    assert rmviz.variance_to_certainty(0.0, 100.0) == pytest.approx(1.0)
    assert math.isfinite(rmviz.variance_to_certainty(-5.0, 100.0))


def test_variance_to_alpha_is_unchanged_by_the_certainty_refactor():
    """A pinned table. variance_to_alpha was rewritten in terms of
    variance_to_certainty and its outputs must be bit-identical."""
    expected = {
        (100.0, 100.0): rmviz.ALPHA_MIN,
        (rmviz.VARIANCE_FLOOR, 100.0): rmviz.ALPHA_MAX,
        (10.0, 100.0): 0.05 + 0.8 * 0.25,
        (1.0, 100.0): 0.05 + 0.8 * 0.50,
        (0.1, 100.0): 0.05 + 0.8 * 0.75,
    }
    for (variance, prior), alpha in expected.items():
        assert rmviz.variance_to_alpha(variance, prior) == pytest.approx(alpha)
    assert rmviz.variance_to_alpha(1e-12, 100.0) == pytest.approx(
        rmviz.ALPHA_MAX)


# ----------------------------------------------------- the gray tier, D-02

def test_low_confidence_gray_is_cool():
    """b > g > r is REQUIRED, not aesthetic: a cell at certainty 0 renders as
    pure LOW_CONFIDENCE_GRAY, and test_marker_colours_track_their_inputs
    asserts such a cell is blue-dominant. A neutral gray breaks it."""
    r, g, b = rmviz.LOW_CONFIDENCE_GRAY
    assert b > g > r


def test_certainty_to_rgb_endpoints():
    """Full ramp colour when certain, pure gray when not."""
    assert rmviz.certainty_to_rgb(8.0, rmviz.VARIANCE_FLOOR, 100.0) == \
        rmviz.concentration_to_rgb(8.0)
    assert rmviz.certainty_to_rgb(8.0, 100.0, 100.0) == rmviz.LOW_CONFIDENCE_GRAY
    # And the gray is reached regardless of concentration — that is the point:
    # "we barely looked" must not read as "we are confident there is nothing".
    assert rmviz.certainty_to_rgb(0.0, 100.0, 100.0) == rmviz.LOW_CONFIDENCE_GRAY


def test_certainty_to_rgb_desaturates_monotonically():
    hot = rmviz.concentration_to_rgb(10.0)          # (255, 0, 0)
    reds = [rmviz.certainty_to_rgb(10.0, v, 100.0)[0]
            for v in (100.0, 10.0, 1.0, 0.1, 0.01)]
    assert reds == sorted(reds)
    assert reds[0] == rmviz.LOW_CONFIDENCE_GRAY[0]
    assert reds[-1] == hot[0]


def test_certainty_to_rgb_stays_in_range():
    for mean in (0.0, 2.5, 5.0, 7.5, 10.0, 25.0):
        for var in (1e-9, 0.01, 1.0, 100.0, 1e9):
            rgb = rmviz.certainty_to_rgb(mean, var, 100.0)
            assert len(rgb) == 3
            assert all(0 <= c <= 255 and isinstance(c, int) for c in rgb), rgb


#: Pinned (mean_wt, variance) -> (r, g, b, a) against prior_variance 100.0.
#: colors.js reproduces this table as a comment. That copy IS machine-checked
#: across the language boundary as of 2026-07-31 — test_dashboard_colour_parity
#: parses the JS table and recomputes every row — so the two are a check on
#: each other rather than, as this comment used to say, a diff by eye.
PINNED_POSTERIOR_COLOURS = [
    # mean   variance   r    g    b     alpha
    (0.0,    100.0,     90,  96,  110,  0.050),
    (0.0,    0.01,      20,  55,  150,  0.850),
    (2.5,    0.01,      0,   0,   255,  0.850),
    (5.0,    1.0,       45,  176, 183,  0.450),
    (7.5,    0.09,      216, 217, 26,   0.659),
    (10.0,   0.01,      255, 0,   0,    0.850),
]


@pytest.mark.parametrize('mean,variance,r,g,b,alpha',
                         PINNED_POSTERIOR_COLOURS)
def test_pinned_posterior_colours(mean, variance, r, g, b, alpha):
    assert rmviz.certainty_to_rgb(mean, variance, 100.0) == (r, g, b)
    assert rmviz.variance_to_alpha(variance, 100.0) == pytest.approx(
        alpha, abs=0.001)


# ------------------------------------ what the shipped fleet can actually reach

def _scalar_field_sigmas():
    """Every noise_stddev declared on a scalar_field sensor in the RCDLs.

    The RCDL is the only source of the sigma that reaches ResourceMap.update:
    GazeboScalarFieldSensor reports it, ProspectSkill averages it, and
    agent_node._publish_map_update DROPS any reading whose sigma is
    non-finite or <= 0 — so the inf sentinel never reaches the map and cannot
    supply a certainty-0 cell either.
    """
    yaml = pytest.importorskip('yaml')
    config_dir = (pathlib.Path(__file__).resolve().parents[2]
                  / 'selene_hal' / 'config')
    if not config_dir.is_dir():
        pytest.skip(f'{config_dir} not present in this checkout')
    sigmas = {}
    for path in sorted(config_dir.glob('*.yaml')):
        rcdl = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        for sensor in rcdl.get('sensors') or []:
            if sensor.get('type') == 'scalar_field' and 'noise_stddev' in sensor:
                sigmas[f"{path.name}:{sensor.get('name')}"] = float(
                    sensor['noise_stddev'])
    return sigmas


def test_the_shipped_scout_cannot_reach_zero_certainty():
    """The bottom of the certainty axis is UNREACHABLE, and that is documented.

    A cell only appears in a snapshot once count >= 1, i.e. once at least one
    Bayesian update has run against it. With the sigmas the RCDLs actually
    declare, the very first update already moves the posterior far enough that
    certainty can never be near 0 — so pure LOW_CONFIDENCE_GRAY and ALPHA_MIN
    are the anchors of the mapping and not colours any cube or pixel will have
    on a shipped run.

    This is a PIN ON THE DOCUMENTATION, not on the design. Four places state
    these numbers — variance_to_certainty()'s docstring, the matching comment
    in selene_dashboard/src/utils/colors.js, the normaliseCertaintyBand comment
    in ResourceLegend.jsx (which was the certainty-sweep comment until D-17
    replaced the two bars with one 2-D swatch), and D-02 in
    docs/phase5_deviation_register.md. If a sensor's noise_stddev changes or the
    mapping is recalibrated, this test fails and all four must be re-derived
    rather than left quietly false.
    """
    sigmas = _scalar_field_sigmas()
    assert sigmas, 'no scalar_field sensor declares a noise_stddev'
    worst_sigma = max(sigmas.values())

    # Run the real update, at a cell centre, on the production geometry.
    rm = ResourceMap()
    rm.update(x=0.5, y=0.5, reading=3.5, sensor_uncertainty=worst_sigma)
    variances = rm.get_variance_grid()[rm.get_count_grid() > 0]
    assert variances.size > 0

    floor = rmviz.variance_to_certainty(float(variances.max()), rm.prior_variance)
    peak = rmviz.variance_to_certainty(float(variances.min()), rm.prior_variance)

    assert floor == pytest.approx(0.5008, abs=0.0005), (
        f'the certainty of a single {worst_sigma} wt% reading at the footprint '
        f'edge is now {floor:.4f}, not the documented 0.5008 ({sigmas}). '
        f'Update variance_to_certainty()\'s docstring, colors.js and register '
        f'entry D-02 together.')
    assert peak == pytest.approx(0.6508, abs=0.0005), (
        f'the certainty of a single reading at the footprint centre is now '
        f'{peak:.4f}, not the documented 0.6508. Same three places.')

    # The consequences the two renderers' comments claim.
    assert rmviz.variance_to_alpha(float(variances.max()), rm.prior_variance) \
        == pytest.approx(0.4506, abs=0.0005)
    assert floor > 0.5, 'more than half the alpha ramp is below any real cell'

    # The gray lerp never gets closer than halfway to LOW_CONFIDENCE_GRAY, in
    # any channel — the register's "desaturated toward cool gray" is at most a
    # half-step for a once-observed cell, not the full one.
    hot = rmviz.concentration_to_rgb(3.5)
    faintest = rmviz.certainty_to_rgb(3.5, float(variances.max()),
                                      rm.prior_variance)
    for channel, gray, hot_channel in zip(faintest, rmviz.LOW_CONFIDENCE_GRAY,
                                          hot):
        assert abs(channel - hot_channel) <= abs(gray - hot_channel) * 0.5 + 1


def test_a_noisier_sensor_would_reach_the_gray_end():
    """The endpoints are not dead by construction — only by configuration.

    Kept beside the test above so "unreachable" is never read as "the mapping
    is wrong". At sigma 2.0 wt% — four times the scout's — a single
    footprint-edge reading lands at certainty 0.2148 / alpha 0.2219, well down
    into the range no shipped cell can occupy.
    """
    rm = ResourceMap()
    rm.update(x=0.5, y=0.5, reading=3.5, sensor_uncertainty=2.0)
    variances = rm.get_variance_grid()[rm.get_count_grid() > 0]
    worst = float(variances.max())
    assert rmviz.variance_to_certainty(worst, rm.prior_variance) == \
        pytest.approx(0.2148, abs=0.0005)
    assert rmviz.variance_to_alpha(worst, rm.prior_variance) == \
        pytest.approx(0.2219, abs=0.0005)


def test_js_round_matches_javascript_at_exact_halves():
    """Python's round() is banker's rounding; Math.round is half-up. MEASURED:
    5 of 1201 samples over 0-12 wt% diverged before this helper existed."""
    assert rmviz._js_round(0.5) == 1 and round(0.5) == 0
    assert rmviz._js_round(1.5) == 2 and round(1.5) == 2
    assert rmviz._js_round(160.5) == 161 and round(160.5) == 160
    assert rmviz.concentration_to_rgb(0.25) == (18, 50, 161)


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


# ----------------------------------------- the non-finite domain, D-18

#: Every way a cell's posterior can fail to be a number. `-inf` variance is in
#: here because it is the one case that used to render at FULL confidence:
#: `max(-inf, VARIANCE_FLOOR)` is VARIANCE_FLOOR, so a nonsense variance became
#: the most certain cell on the map.
NON_FINITE_CELLS = [
    (float('nan'), 1.0),
    (float('inf'), 1.0),
    (float('-inf'), 1.0),
    (float('nan'), rmviz.VARIANCE_FLOOR),
    (2.5, float('nan')),
    (2.5, float('inf')),
    (2.5, float('-inf')),
    (float('nan'), float('nan')),
]


@pytest.mark.parametrize('mean,variance', NON_FINITE_CELLS)
def test_a_non_finite_cell_renders_as_no_information(mean, variance):
    """Pure LOW_CONFIDENCE_GRAY at ALPHA_MIN, in both languages.

    This raised ``ValueError: cannot convert float NaN to integer`` out of
    ``_js_round`` -> ``math.floor`` for every row with a NaN in it, from inside
    the orchestrator's publish timer, while colors.js returned
    ``[55, 76, 130, 0.45]`` — the ramp floor at half confidence — for the first
    one. Same posterior, two different pictures, in exactly the side-by-side
    comparison docs/PRD.md:1504 asks for.

    Gray-at-ALPHA_MIN rather than the ramp floor because the two mean different
    things and must not look alike: the floor is "we sampled here and found no
    ice", this is "this cell's posterior is not a number". The reading is
    unambiguous on the drawn set — ResourceMap.update now refuses any reading
    that is not finite with a strictly positive sigma, so every emitted cell
    has had at least one strictly-positive-precision update and no REAL cell
    can reach certainty 0.
    """
    r, g, b, a = rmviz.posterior_cell_rgba(mean, variance, 100.0)
    assert (r, g, b) == rmviz.LOW_CONFIDENCE_GRAY
    assert a == pytest.approx(rmviz.ALPHA_MIN)


@pytest.mark.parametrize('mean,variance', NON_FINITE_CELLS)
def test_marker_colours_cannot_raise_on_a_non_finite_cell(mean, variance):
    """The failure mode was not a wrong colour; it was NO OVERLAY AT ALL.

    ``marker_colours`` is called from ``_publish_resource_map`` inside the
    ``resource_map_publish_rate`` timer callback, and an exception in an rclpy
    timer propagates out of the executor. One poisoned cell in a 250 000-cell
    grid stopped the RViz2 overlay — and, in a real run, the node.
    """
    cols = rmviz.marker_colours([0.0, mean, 9.0],
                                [0.05, variance, 0.05], 100.0)
    assert len(cols) == 3
    for r, g, b, a in cols:
        assert all(math.isfinite(c) and 0.0 <= c <= 1.0 for c in (r, g, b, a))


def test_a_non_finite_prior_does_not_raise_either():
    """`prior_variance` comes off the ResourceMap, not the wire, but the
    mapping is only total if every argument is covered."""
    for prior in (float('nan'), float('inf'), float('-inf')):
        assert rmviz.variance_to_certainty(1.0, prior) == 0.0
        assert rmviz.variance_to_alpha(1.0, prior) == pytest.approx(
            rmviz.ALPHA_MIN)
        assert rmviz.certainty_to_rgb(5.0, 1.0, prior) == \
            rmviz.LOW_CONFIDENCE_GRAY


def test_concentration_ramp_is_total_and_clamps_non_finite_to_the_floor():
    """The ramp alone maps a non-finite mean to 0 wt%, mirroring colors.js.

    Note this is only half the answer — certainty_to_rgb overrides it to gray —
    but the halves are separately ported and separately tested, because the JS
    has the same split (iceConcentrationRGB, then certaintyRGB).
    """
    for mean in (float('nan'), float('inf'), float('-inf')):
        assert rmviz.concentration_to_rgb(mean) == rmviz.ICE_FLOOR_RGB
    # +inf USED to render pure red on both sides. It is not a 10 wt% reading.
    assert rmviz.concentration_to_rgb(float('inf')) != (255, 0, 0)


def test_posterior_cell_rgba_is_the_two_halves_taken_together():
    """The finite domain is unchanged: this is a refactor, not a recolouring.

    marker_colours used to call certainty_to_rgb and variance_to_alpha
    separately. That is identical for every finite cell and diverges only when
    the mean is non-finite — gray hue at a confident alpha — which is why the
    single entry point exists.
    """
    for mean in (0.0, 2.5, 5.0, 7.5, 10.0, 25.0, -3.0):
        for variance in (100.0, 1.0, 0.2494, 0.09, 0.01, 1e-9):
            r, g, b, a = rmviz.posterior_cell_rgba(mean, variance, 100.0)
            assert (r, g, b) == rmviz.certainty_to_rgb(mean, variance, 100.0)
            assert a == pytest.approx(
                rmviz.variance_to_alpha(variance, 100.0))


def test_certainty_zero_means_exactly_one_thing_on_the_drawn_set():
    """The property that makes "gray == corrupt" readable rather than
    ambiguous, asserted through the real ResourceMap rather than argued.

    A cell is emitted only once count >= 1; ResourceMap.update refuses any
    reading whose sigma is non-finite or <= 0; so obs_precision is strictly
    positive for every applied reading and the posterior variance is strictly
    below the prior. Certainty 0 is therefore unreachable for a real cell BY
    CONSTRUCTION, not merely by the shipped RCDL (which is what
    test_the_shipped_scout_cannot_reach_zero_certainty pins).
    """
    rm = ResourceMap()
    # The largest sigma that still gets through the boundary guard, applied at
    # the very edge of the footprint, is the weakest evidence a cell can hold.
    rm.update(x=0.5, y=0.5, reading=3.5, sensor_uncertainty=1e6)
    variances = rm.get_variance_grid()[rm.get_count_grid() > 0]
    assert variances.size > 0
    assert (variances < rm.prior_variance).all()
    weakest = rmviz.variance_to_certainty(float(variances.max()),
                                          rm.prior_variance)
    assert weakest > 0.0, 'a drawn cell reached the "no information" colour'
    # And the rejected reading really is rejected, so nothing sneaks in at 0.
    assert rm.update(x=0.5, y=0.5, reading=3.5,
                     sensor_uncertainty=float('inf')) is False
