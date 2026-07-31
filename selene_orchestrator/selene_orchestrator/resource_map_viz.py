"""Serialisation and RViz2 colouring for the fused resource map.

FR-MAP-1(e)(f) — the posterior on the wire — and FR-MAP-4 — the colour-coded
RViz2 overlay.

WHY THIS MODULE IMPORTS NO ROS. Everything here is pure numpy in, plain Python
out: indices, floats, and (r, g, b, a) tuples. The orchestrator does the
trivial field-setting to turn that into ResourceMap / MarkerArray messages.

That split is not tidiness. selene_orchestrator/test/conftest.py stubs rclpy
when no ROS workspace is present, and its fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so an
OrchestratorNode cannot even be constructed under it. Keeping the arithmetic
ROS-free means the part that can actually be wrong — row order, the colour
ramp, the certainty mapping, the cell cap — is unit-tested in the fast CI lane
with nothing but numpy, on every push.
"""

import math

import numpy as np

# --------------------------------------------------------------------------
# Colour ramp. A verbatim port of iceConcentrationRGB() in
# selene_dashboard/src/utils/colors.js:113-135.
#
# CITATION UPDATED 2026-07-30. This block used to cite iceConcentrationColor()
# at colors.js:52-77. The ramp arithmetic moved -- unchanged line for line --
# into iceConcentrationRGB() when the dashboard's posteriorCellRGBA() needed
# integer channels rather than an 'rgba(...)' string; iceConcentrationColor()
# at :138-141 is now a wrapper around it. The VALUES did not change, so nothing
# below needed editing, only the pointer.
#
# Ported rather than reinvented so the RViz2 overlay and the dashboard heatmap
# render the same posterior the same colour. The PRD's FR-MAP-4(b) asks for
# "blue (low concentration / no ice) -> red (high concentration)", and this
# ramp is exactly that with cyan and yellow as intermediate stops; the PRD also
# asks (docs/PRD.md:1504) for the two views to be comparable side by side,
# which they cannot be if each invents its own palette.
#
# ICE_FLOOR_RGB is a dark-but-visible blue rather than black. The reason
# recorded in colors.js USED TO BE that the dashboard composited the heatmap
# with 'screen', where black is a no-op. That premise is gone: as of 2026-07-30
# FleetMap.jsx rasterises the fused posterior with the canvas default
# 'source-over' and `globalCompositeOperation` appears nowhere in the dashboard
# outside a comment. The floor stays anyway, for the reason that outlived it --
# rgb(0,0,0) at alpha 0.05 over RViz2's dark ground plane, or over the
# dashboard's #0a0e1a background, is indistinguishable from terrain nobody has
# ever visited, so a genuine "we sampled here and found nothing" reading would
# render as no reading at all.
# --------------------------------------------------------------------------
ICE_FLOOR_RGB = (20, 55, 150)

#: Concentration in wt% at which the ramp saturates red. The four deposits in
#: selene_sim/config/ice_deposits.yaml peak at 8.0 wt%, so 10.0 keeps the top
#: of the ramp in reserve and matches the dashboard's divisor exactly.
MAX_CONCENTRATION_WT = 10.0

#: Alpha for a cell whose posterior variance has collapsed to VARIANCE_FLOOR.
#: Below 1.0 on purpose: RViz2's PointsMarker only enables per-point alpha
#: blending when at least one colour has ``a != 1.0``. A fully opaque overlay
#: would silently fall back to flat marker colour.
ALPHA_MAX = 0.85

#: Alpha never goes to zero for an OBSERVED cell. A cell with exactly one
#: distant, uncertain reading is still evidence and should be faintly visible;
#: and RViz2 raises a marker status warning if every alpha in a CUBE_LIST is
#: 0.0. Unobserved cells are not emitted at all, which is the real
#: "transparent = uncertain" end of FR-MAP-4(c).
#:
#: NOT REACHED BY ANY MEASURED CELL FROM THE SHIPPED FLEET. One reading from
#: the 0.5 wt% scout spectrometer already puts a cell at alpha >= 0.4506; see
#: the reachability note in variance_to_certainty(). This value is the floor of
#: the mapping, not a value any measured cube in a shipped run will have.
#:
#: D-18 gave it exactly one reachable meaning: a cell whose posterior mean or
#: variance is not a finite number is drawn here, at pure LOW_CONFIDENCE_GRAY.
#: ResourceMap.update() refuses any reading without a finite, strictly positive
#: sigma, so every emitted cell has had at least one strictly-positive-precision
#: update and certainty 0 is unreachable for a measured cell BY CONSTRUCTION.
#: Gray at this alpha therefore means "corrupt", never "faint".
ALPHA_MIN = 0.05

#: Variance at which certainty saturates. ResourceMap floors sensor variance at
#: 1e-6, but a posterior that small needs implausibly many readings; 0.01
#: wt%^2 (sigma 0.1 wt%, a fifth of the scout's 0.5 wt% noise) is the practical
#: ceiling on confidence.
VARIANCE_FLOOR = 0.01

#: Colour a cell degrades toward as certainty falls to zero — FR-DASH-2(b) /
#: docs/PRD.md:503 asks for a "gray (no data / low confidence)" tier that
#: neither renderer had.
#:
#: IT MUST SATISFY b > g > r, and the reason is a test rather than taste:
#: test_resource_map_viz.test_marker_colours_track_their_inputs asserts
#: ``cols[0][2] > cols[0][0]`` — blue-dominant — for a cell whose variance
#: equals the prior, i.e. certainty 0, which under certainty_to_rgb renders as
#: pure LOW_CONFIDENCE_GRAY. A neutral gray breaks that assertion; a COOL gray
#: keeps "low concentration is blue-dominant" true and still reads as gray
#: against the scene. Do not change this value without re-checking that test.
#:
#: REACHED AT FULL STRENGTH ONLY AT certainty 0, which no MEASURED cell can
#: produce — see variance_to_certainty(). On a shipped run this colour appears
#: on a measured cell only as the far end of a lerp that gets at most ~50% of
#: the way here. Its one exact appearance is the D-18 case: a cell whose mean
#: or variance is not a finite number, drawn at ALPHA_MIN.
LOW_CONFIDENCE_GRAY = (90, 96, 110)


def _js_round(x):
    """Round half UP, the way JavaScript's ``Math.round`` does.

    Python's ``round()`` is banker's rounding: ``round(160.5) == 160`` while
    ``Math.round(160.5) === 161``. MEASURED on this box over 0–12 wt% at 0.01
    steps: 5 of 1201 samples differed by 1 in exactly one channel — at
    0.25 wt% the dashboard produces (18, 50, 161) and this module produced
    (18, 50, 160). Small, but this module's docstring claims a VERBATIM port of
    colors.js, and "verbatim except at exact halves" is the kind of caveat that
    quietly becomes untrue everywhere. With this helper the claim is exact and
    test_dashboard_colour_parity.py can assert equality instead of a tolerance.

    ``math.floor(x + 0.5)`` also matches ``Math.round``'s half-toward-+inf
    behaviour on negatives; every input here is non-negative regardless.
    """
    return math.floor(x + 0.5)


def concentration_to_rgb(mean_wt):
    """Map ice concentration in wt% to (r, g, b), each 0..255 integers.

    Piecewise-linear over four segments, identical to the dashboard's ramp.
    Values outside [0, MAX_CONCENTRATION_WT] clamp to the ends.

    D-18 — A NON-FINITE MEAN IS CLAMPED TO 0.0 RATHER THAN RAISING. This used
    to go straight into _js_round -> math.floor, which raises
    ``ValueError: cannot convert float NaN to integer``; marker_colours() is
    called from orchestrator_node._publish_resource_map INSIDE the
    resource_map_publish_rate timer, so one poisoned cell stopped the RViz2
    overlay publishing at all, while colors.js quietly rendered the ramp floor
    (its ``Math.max(value || 0, 0)`` mapped NaN to 0 because NaN is falsy).
    Same map, two different pictures — a divergence in exactly the side-by-side
    comparison docs/PRD.md:1504 asks for.

    The ramp floor is only half the answer and this function is only half the
    law: certainty_to_rgb() below forces a non-finite mean to certainty 0, so
    such a cell renders as pure LOW_CONFIDENCE_GRAY at ALPHA_MIN — "we do not
    know" — rather than as the ramp's "we sampled here and found nothing".
    +/-Infinity is treated the same way in both languages as of this change;
    an infinite posterior mean is not a MAX_CONCENTRATION_WT measurement.
    """
    mean = float(mean_wt)
    if not math.isfinite(mean):
        mean = 0.0
    t = min(max(mean, 0.0) / MAX_CONCENTRATION_WT, 1.0)
    if t < 0.25:
        s = t / 0.25
        return (_js_round(ICE_FLOOR_RGB[0] * (1 - s)),
                _js_round(ICE_FLOOR_RGB[1] * (1 - s)),
                _js_round(ICE_FLOOR_RGB[2] + (255 - ICE_FLOOR_RGB[2]) * s))
    if t < 0.5:
        s = (t - 0.25) / 0.25
        return (0, _js_round(255 * s), 255)
    if t < 0.75:
        s = (t - 0.5) / 0.25
        return (_js_round(255 * s), 255, _js_round(255 * (1 - s)))
    s = (t - 0.75) / 0.25
    return (255, _js_round(255 * (1 - s)), 0)


def variance_to_certainty(variance, prior_variance):
    """How far a cell's posterior variance has fallen from the prior, 0..1.

        certainty = log10(prior / v) / log10(prior / VARIANCE_FLOOR)

    Log rather than linear because the Bayesian update divides variance
    multiplicatively. MEASURED 2026-07-31 by running the shipped
    ResourceMap.update() with the shipped scout RCDL (noise_stddev 0.5,
    selene_hal/config/scout.yaml:16) against the shipped defaults
    (prior_variance 100.0, footprint_radius 5.0, footprint_sigma 3.0): ONE
    reading takes a cell from variance 100.0 to 0.2494 at the footprint centre
    and 0.9926 at its edge. A linear map puts those at certainty 0.9975 and
    0.9901 — "observed once" and "observed twenty times" would be
    indistinguishable. On this log scale they read 0.6508 and 0.5008, and
    further readings keep moving (2 -> 0.7259, 3 -> 0.7699, 8 -> 0.8763).

    THE FIGURE THIS DOCSTRING USED TO GIVE — "the first reading takes variance
    from 100 to ~0.09" — WAS WRONG BY 2.8x for the shipped configuration, and
    it is the number a reviewer would use to sanity-check the alpha axis. 0.09
    is roughly where THREE readings land (0.0833). Corrected 2026-07-31 from
    the run above; test_the_shipped_scout_cannot_reach_zero_certainty in
    test_resource_map_viz.py re-derives it so it cannot go stale silently.

    Returns 0.0 at (or above) the prior and 1.0 at VARIANCE_FLOOR. This is the
    single certainty definition both renderers use: opacity here, and the
    gray-lerp in certainty_to_rgb, and the dashboard's varianceToCertainty.

    REACHABILITY, AND IT IS A REAL LIMITATION OF BOTH RENDERERS. A cell is only
    emitted when count >= 1, so at least one update has run, so with the only
    scalar-field sensor in the tree (0.5 wt%, the sole noise_stddev in
    selene_hal/config/*.yaml) NO EMITTED CELL CAN HAVE certainty below 0.5008
    or alpha below 0.4506 — the bottom ~55% of [ALPHA_MIN, ALPHA_MAX] and the
    fully-gray end of certainty_to_rgb are unreachable. They are reachable
    arithmetically (a noisier sensor: sigma 2.0 puts one edge reading at
    certainty 0.2148, alpha 0.2219), and the endpoints are kept as the
    mapping rather than recalibrated to one RCDL. What FR-DASH-2(b)'s "no
    data" tier is actually delivered by is the cell that is NOT EMITTED at all
    — transparent, drawn by neither renderer. Recorded in the deviation
    register under D-02; do not describe the gray end as something an operator
    will see on the shipped fleet.

    D-18: a non-finite variance or prior returns 0.0 — the "we do not know"
    end — instead of propagating NaN into _js_round. Note that ``-inf`` used to
    return 1.0 in BOTH languages, because ``max(-inf, VARIANCE_FLOOR)`` is
    VARIANCE_FLOOR; a negatively-infinite variance is not maximal confidence.
    """
    if not (math.isfinite(float(variance))
            and math.isfinite(float(prior_variance))):
        return 0.0
    prior = max(float(prior_variance), VARIANCE_FLOOR * 10.0)
    v = min(max(float(variance), VARIANCE_FLOOR), prior)
    span = math.log10(prior / VARIANCE_FLOOR)
    if span <= 0.0:
        return 1.0
    certainty = math.log10(prior / v) / span
    return min(max(certainty, 0.0), 1.0)


def variance_to_alpha(variance, prior_variance):
    """Map posterior variance to opacity — FR-MAP-4(c).

    ALPHA_MIN..ALPHA_MAX, linear in ``variance_to_certainty``. A variance at or
    above the prior gives ALPHA_MIN, not 0.0: see the note on ALPHA_MIN.

    THIS IS ALPHA FROM THE VARIANCE ALONE and does not see the mean, so it is
    NOT the alpha a cell is drawn with when the mean is non-finite. Use
    posterior_cell_rgba() for a cell; this stays public because the FR-MAP-4(c)
    mapping is a thing in its own right and several tests pin it directly.
    """
    return (ALPHA_MIN
            + (ALPHA_MAX - ALPHA_MIN) * variance_to_certainty(
                variance, prior_variance))


def _effective_certainty(mean_wt, variance, prior_variance):
    """The one certainty both channels of a drawn cell are derived from.

    Verbatim counterpart of the ``Number.isFinite(meanWt) ? ... : 0`` in
    colors.js's posteriorCellRGBA(). It exists as a named function because the
    alternative — hue from the mean in certainty_to_rgb(), alpha from the
    variance in variance_to_alpha() — lets the two channels of ONE cell
    disagree when the mean is non-finite: gray hue at a confident alpha.
    posterior_cell_rgba() below is what marker_colours() calls so that the two
    channels cannot come from two different certainties (D-18).
    """
    if not math.isfinite(float(mean_wt)):
        return 0.0
    return variance_to_certainty(variance, prior_variance)


def certainty_to_rgb(mean_wt, variance, prior_variance):
    """Concentration colour desaturated toward gray as certainty falls.

    ``lerp(LOW_CONFIDENCE_GRAY, concentration_to_rgb(mean_wt), certainty)``.

    FR-DASH-2(b) asks for a gray tier and neither renderer had one; alpha alone
    could not supply it, because over dark lunar terrain a low-alpha blue and a
    low-alpha red both fade toward the same dark, and the operator cannot tell
    "we are confident there is nothing here" from "we barely looked". Pulling
    hue toward gray as well makes uncertainty legible in a second channel.

    Applied to BOTH renderers (here, and colors.js's posteriorCellRGBA) so the
    RViz2 overlay and the dashboard heatmap stay a verbatim pair — which is the
    only way PRD exit-gate row 2, "resource heatmap matches RViz2
    visualization", is checkable at all.

    D-18: a non-finite MEAN forces certainty 0, i.e. pure LOW_CONFIDENCE_GRAY,
    rather than merely falling to the ramp floor. The ramp floor states "we
    sampled here and found nothing"; a mean that is not a number states
    "this cell's posterior is corrupt", and the two must not look alike — the
    same argument ICE_FLOOR_RGB is kept for. The reading is unambiguous on the
    drawn set: no cell the shipped fleet emits can reach certainty 0 (see
    variance_to_certainty), so pure gray at ALPHA_MIN means exactly this.
    """
    certainty = _effective_certainty(mean_wt, variance, prior_variance)
    hot = concentration_to_rgb(mean_wt)
    return tuple(
        _js_round(gray + (channel - gray) * certainty)
        for gray, channel in zip(LOW_CONFIDENCE_GRAY, hot)
    )


def posterior_cell_rgba(mean_wt, variance, prior_variance):
    """One fused posterior cell -> (r, g, b, a); r/g/b 0..255 ints, a 0..1.

    The whole colour law in one call, and the exact counterpart of colors.js's
    posteriorCellRGBA(). Both channels come from ONE certainty
    (_effective_certainty), which is the property that makes the pair
    checkable: a renderer that derives hue and alpha from two different
    certainties can disagree with its twin on a cell neither of them thinks is
    unusual (D-18).
    """
    certainty = _effective_certainty(mean_wt, variance, prior_variance)
    r, g, b = certainty_to_rgb(mean_wt, variance, prior_variance)
    return (r, g, b, ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * certainty)


def select_observed(count_grid, max_cells=None):
    """Return the flat indices of observed cells, ascending, optionally capped.

    "Observed" is ``count > 0`` — the only predicate that is correct. Not
    ``mean != 0``: a scout that samples bare regolith legitimately reads 0.0
    wt%, and dropping those cells would erase exactly the negative evidence a
    survey exists to gather. Not ``variance < prior`` either, which is true of
    the same set but says it obliquely.

    When more than *max_cells* are observed the selection is DECIMATED WITH A
    DETERMINISTIC STRIDE rather than truncated. Truncation would show the
    lowest-index cells, i.e. a solid block of the southern edge of the surveyed
    area and nothing north of it — a picture that is wrong in a way that looks
    right. A stride thins the whole field evenly, and being deterministic it
    does not shimmer between frames.
    """
    flat = np.flatnonzero(count_grid.reshape(-1) > 0)
    if max_cells is not None and 0 < max_cells < flat.size:
        stride = int(math.ceil(flat.size / float(max_cells)))
        flat = flat[::stride]
    return flat


def cell_centres(flat_indices, width, resolution, origin_x, origin_y):
    """World (x, y) centres for flat row-major indices. Row 0 is minimum-y.

    Mirrors ResourceMap.grid_to_world(), which already adds the half-cell
    offset, so these are cell CENTRES while ResourceMap.msg's ``origin`` is the
    outer corner of cell (0, 0).
    """
    rows, cols = np.divmod(np.asarray(flat_indices, dtype=np.int64), int(width))
    xs = cols * resolution + origin_x + resolution / 2.0
    ys = rows * resolution + origin_y + resolution / 2.0
    return xs, ys


def marker_colours(means, variances, prior_variance):
    """Per-cell (r, g, b, a) floats in 0..1, ready for std_msgs/ColorRGBA.

    One tuple per input cell, in the same order. RViz2 silently discards
    per-point colours when ``len(colors) != len(points)`` — it falls back to
    the flat marker colour with no error surfaced — so the caller must keep
    these arrays in lockstep with the points.

    Certainty enters TWICE, on purpose: as alpha (FR-MAP-4(c)) and as a lerp
    toward LOW_CONFIDENCE_GRAY (FR-DASH-2(b)). See certainty_to_rgb.

    NOTE FOR ANYONE COMPARING AGAINST D-08's MEASURED FIGURES: the cube counts
    and per-point alphas recorded there ("3779 points, alpha 0.453–0.662, 233
    red-dominant and 3546 blue-dominant cubes") were measured on 2026-07-30
    BEFORE the gray-lerp existed. Alpha is unchanged by it; the hue figures
    describe the older colour law.

    TOTAL BY CONSTRUCTION (D-18). This used to raise ValueError out of
    _js_round -> math.floor on a non-finite mean, and its only caller is
    orchestrator_node._publish_resource_map, running on the
    resource_map_publish_rate timer — so ONE bad cell silenced the whole
    overlay while the dashboard drew a plausible patch. posterior_cell_rgba()
    is total for every float, and _publish_resource_map now also catches, so
    two independent things have to fail before an operator loses the overlay
    without being told.
    """
    out = []
    for mean, var in zip(means, variances):
        r, g, b, a = posterior_cell_rgba(mean, var, prior_variance)
        out.append((r / 255.0, g / 255.0, b / 255.0, a))
    return out
