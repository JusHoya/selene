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
# Colour ramp. A verbatim port of iceConcentrationColor() in
# selene_dashboard/src/utils/colors.js:52-77.
#
# Ported rather than reinvented so the RViz2 overlay and the dashboard heatmap
# render the same posterior the same colour. The PRD's FR-MAP-4(b) asks for
# "blue (low concentration / no ice) -> red (high concentration)", and this
# ramp is exactly that with cyan and yellow as intermediate stops; the PRD also
# asks (docs/PRD.md:1504) for the two views to be comparable side by side,
# which they cannot be if each invents its own palette.
#
# ICE_FLOOR_RGB is a dark-but-visible blue rather than black, and the reason is
# recorded in colors.js: the dashboard composites the heatmap with 'screen',
# where black is a no-op, so a genuine "we sampled here and found nothing"
# reading would be indistinguishable from terrain nobody has ever visited.
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
ALPHA_MIN = 0.05

#: Variance at which certainty saturates. ResourceMap floors sensor variance at
#: 1e-6, but a posterior that small needs implausibly many readings; 0.01
#: wt%^2 (sigma 0.1 wt%, a fifth of the scout's 0.5 wt% noise) is the practical
#: ceiling on confidence.
VARIANCE_FLOOR = 0.01


def concentration_to_rgb(mean_wt):
    """Map ice concentration in wt% to (r, g, b), each 0..255 integers.

    Piecewise-linear over four segments, identical to the dashboard's ramp.
    Values outside [0, MAX_CONCENTRATION_WT] clamp to the ends.
    """
    t = min(max(float(mean_wt), 0.0) / MAX_CONCENTRATION_WT, 1.0)
    if t < 0.25:
        s = t / 0.25
        return (round(ICE_FLOOR_RGB[0] * (1 - s)),
                round(ICE_FLOOR_RGB[1] * (1 - s)),
                round(ICE_FLOOR_RGB[2] + (255 - ICE_FLOOR_RGB[2]) * s))
    if t < 0.5:
        s = (t - 0.25) / 0.25
        return (0, round(255 * s), 255)
    if t < 0.75:
        s = (t - 0.5) / 0.25
        return (round(255 * s), 255, round(255 * (1 - s)))
    s = (t - 0.75) / 0.25
    return (255, round(255 * (1 - s)), 0)


def variance_to_alpha(variance, prior_variance):
    """Map posterior variance to opacity — FR-MAP-4(c).

    Certainty is measured as how far the posterior variance has fallen from the
    prior, on a LOG scale:

        certainty = log10(prior / v) / log10(prior / VARIANCE_FLOOR)

    Log rather than linear because the Bayesian update divides variance
    multiplicatively: the first reading at a cell takes variance from 100 to
    ~0.09, and a linear map would put that cell at alpha 0.999 and every
    subsequent reading in the last 0.1% of the range — the overlay would show
    "observed once" and "observed twenty times" as indistinguishable. On a log
    scale one reading reads ~0.76 and further readings keep moving.

    Returns ALPHA_MIN..ALPHA_MAX. A variance at or above the prior gives
    ALPHA_MIN, not 0.0: see the note on ALPHA_MIN.
    """
    prior = max(float(prior_variance), VARIANCE_FLOOR * 10.0)
    v = min(max(float(variance), VARIANCE_FLOOR), prior)
    span = math.log10(prior / VARIANCE_FLOOR)
    if span <= 0.0:
        return ALPHA_MAX
    certainty = math.log10(prior / v) / span
    certainty = min(max(certainty, 0.0), 1.0)
    return ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * certainty


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
    """
    out = []
    for mean, var in zip(means, variances):
        r, g, b = concentration_to_rgb(mean)
        a = variance_to_alpha(var, prior_variance)
        out.append((r / 255.0, g / 255.0, b / 255.0, a))
    return out
