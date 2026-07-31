// FSM state -> color
export const STATE_COLORS = {
  IDLE: '#556080',
  BIDDING: '#a855f7',
  // D-01: ASSIGNED used to share '#a855f7' with BIDDING, so two of the nine FSM
  // states were not separable by colour anywhere in the UI — not on the map, not
  // in RobotDetail, not in FleetCards. '#f472b6' is unclaimed: it appears in
  // neither STATE_COLORS nor TYPE_COLORS below.
  ASSIGNED: '#f472b6',
  NAVIGATING: '#00d4ff',
  WORKING: '#00b894',
  RETURNING: '#ffc107',
  RECHARGING: '#00e676',
  ERROR: '#ff4757',
  OFFLINE: '#2a3050',
};

// FSM state -> 3-character abbreviation.
//
// D-01: the fleet map has no room for STATE_LABELS at 9 CSS px beside a robot
// id, but it does have room for three characters. This is the COLOUR-BLIND-SAFE
// channel of the state encoding: the state dot on the map carries
// STATE_COLORS, this carries the same information as text. Fixed at three
// characters so the label width does not jump as a robot changes state, which
// would make the collision planner in FleetMap.planRobotMarks re-plan on every
// transition. (The function was renamed from planRobotLabels by D-16, which
// also made that fixed width load-bearing in a second way: when a robot's id
// will not fit, the planner falls back to a tier that draws this abbreviation
// ALONE, so these three characters are the last thing dropped rather than the
// first.)
export const STATE_ABBREV = {
  IDLE: 'IDL',
  BIDDING: 'BID',
  ASSIGNED: 'ASN',
  NAVIGATING: 'NAV',
  WORKING: 'WRK',
  RETURNING: 'RET',
  RECHARGING: 'CHG',
  ERROR: 'ERR',
  OFFLINE: 'OFF',
};

// FSM state -> human label
export const STATE_LABELS = {
  IDLE: 'Idle',
  BIDDING: 'Bidding',
  ASSIGNED: 'Assigned',
  NAVIGATING: 'Navigating',
  WORKING: 'Working',
  RETURNING: 'Returning',
  RECHARGING: 'Recharging',
  ERROR: 'Error',
  OFFLINE: 'Offline',
};

// Robot type -> accent color
export const TYPE_COLORS = {
  scout: '#00d4ff',
  excavator: '#ffc107',
  hauler: '#00e676',
};

// Robot type -> icon label
export const TYPE_LABELS = {
  scout: 'Scout',
  excavator: 'Excavator',
  hauler: 'Hauler',
};

// A10: Visible floor for zero-ice readings.
//
// The old ramp started at rgb(0,0,0), so a genuine 0 wt% reading rendered as
// black. The heatmap composites with 'screen', where black is a no-op, making
// a real "we sampled here and found nothing" reading indistinguishable from
// terrain that was never sampled. Starting the ramp at a dark-but-visible blue
// keeps zero readings on screen.
//
// Value chosen empirically against the running dashboard: a single 0 wt%
// reading at rgb(10,30,90) was still only a faint smudge once 'screen'
// compositing and the sensor-uncertainty alpha were applied.
//
// AMENDED 2026-07-30 (D-02), TENSE ONLY — the value is unchanged and the
// finding above is left as the historical record it is. Both of its premises
// have since gone: the fleet map's heatmap is now a raster of the fused
// posterior blended by per-cell alpha (FleetMap.drawPosteriorRaster), and the
// sensor-uncertainty alpha went with the per-reading blobs. VERIFIED by grep:
// after that change `globalCompositeOperation` appears exactly once in
// selene_dashboard/src, in a comment, so no consumer of this ramp composites
// with 'screen' any more.
//
// THE FLOOR STILL HAS TO STAY, for a reason that outlived 'screen'. This ramp
// is the low end of a scale whose bottom now means "no ice HERE", while
// "nowhere near a reading" is drawn as nothing at all — and those two must not
// look alike. rgb(0,0,0) against the #0a0e1a map background, or against RViz2's
// dark ground plane at alpha 0.05, is indistinguishable from unpainted terrain.
// resource_map_viz.py's module docstring cites this comment as the reason its
// port starts at the same colour. Do not lower it back toward black.
const ICE_FLOOR_RGB = [20, 55, 150];

// Concentration in wt% at which the ramp saturates red. MUST equal
// resource_map_viz.MAX_CONCENTRATION_WT, and test_dashboard_colour_parity.py
// parses it out of this file and asserts exactly that.
//
// D-17: this was the literal `/ 10` inside iceConcentrationRGB, and
// ResourceLegend separately hardcoded `t * 10` for its sweep and the string
// "10 wt%" for its axis label. Three copies of one number, in two files, none
// of which would have failed a build if the ramp were rescaled. The legend now
// derives its axis from this constant, so the bar cannot end up labelled for a
// range the ramp does not cover.
export const MAX_CONCENTRATION_WT = 10;

// Ice concentration -> [r, g, b] integers 0-255 (0..MAX_CONCENTRATION_WT wt%).
//
// D-02: the ramp arithmetic moved out of iceConcentrationColor() into this
// function, unchanged line for line, because posteriorCellRGBA() below needs
// the integer channels and cannot get them out of an 'rgba(...)' string.
// iceConcentrationColor() is now a one-line wrapper and its return value is
// byte-identical to what it produced before.
//
// CROSS-LANGUAGE: selene_orchestrator/selene_orchestrator/resource_map_viz.py's
// concentration_to_rgb() is a verbatim port of THIS function (that module's
// docstring cites colors.js:52-77, the range these lines used to occupy). The
// two are machine-compared by
// selene_orchestrator/test/test_dashboard_colour_parity.py, which parses the
// numeric literals below straight out of this file. Changing ICE_FLOOR_RGB,
// MAX_CONCENTRATION_WT or the three segment thresholds changes the RViz2
// overlay too, and the PRD exit-gate row "resource heatmap matches RViz2
// visualization" (docs/PRD.md:1504) is exactly the claim that they agree.
//
// D-18 — NON-FINITE INPUT IS CLAMPED TO 0 EXPLICITLY, and the Python half now
// does the same. This line used to read `Math.max(value || 0, 0)`, which
// mapped NaN to 0 only BY ACCIDENT (NaN is falsy) and mapped +Infinity to the
// top of the ramp, while resource_map_viz.concentration_to_rgb() RAISED on NaN
// out of math.floor(). That call sits inside the orchestrator's publish timer
// (orchestrator_node._publish_resource_map), so one poisoned cell stopped the
// whole RViz2 overlay while this file drew a plausible dark-blue patch — a
// divergence in exactly the side-by-side comparison docs/PRD.md:1504 asks for.
// `Number.isFinite` states the intent instead of relying on falsiness, and it
// is a DELIBERATE BEHAVIOUR CHANGE for +/-Infinity too: an infinite posterior
// mean is not a 10 wt% measurement. The ramp floor is only half the answer —
// certaintyRGB below forces such a cell to certainty 0, i.e. pure
// LOW_CONFIDENCE_GRAY at ALPHA_MIN, which reads "we do not know" rather than
// "we looked and there is no ice".
export function iceConcentrationRGB(value) {
  const finite = Number.isFinite(value) ? value : 0;
  const t = Math.min(Math.max(finite, 0) / MAX_CONCENTRATION_WT, 1);
  // Dark blue floor -> Blue -> Cyan -> Yellow -> Red
  let r, g, b;
  if (t < 0.25) {
    const s = t / 0.25;
    // Ramp from the visible floor up to pure blue, so the segment boundary at
    // t=0.25 still lands exactly on rgb(0,0,255).
    r = Math.round(ICE_FLOOR_RGB[0] * (1 - s));
    g = Math.round(ICE_FLOOR_RGB[1] * (1 - s));
    b = Math.round(ICE_FLOOR_RGB[2] + (255 - ICE_FLOOR_RGB[2]) * s);
  } else if (t < 0.5) {
    const s = (t - 0.25) / 0.25;
    r = 0; g = Math.round(255 * s); b = 255;
  } else if (t < 0.75) {
    const s = (t - 0.5) / 0.25;
    r = Math.round(255 * s); g = 255; b = Math.round(255 * (1 - s));
  } else {
    const s = (t - 0.75) / 0.25;
    r = 255; g = Math.round(255 * (1 - s)); b = 0;
  }
  return [r, g, b];
}

// Ice concentration -> color (0-10 wt%)
export function iceConcentrationColor(value, alpha = 0.7) {
  const [r, g, b] = iceConcentrationRGB(value);
  return `rgba(${r},${g},${b},${alpha})`;
}

// Battery level -> color
export function batteryColor(level) {
  if (level > 0.5) return '#00e676';
  if (level > 0.2) return '#ffc107';
  return '#ff4757';
}

// ==========================================================================
// D-02 — the confidence axis of the resource heatmap.
//
// WHAT WAS WRONG. FleetMap drew one radial blob per raw ResourceMapUpdate and
// took its opacity from `sensor_uncertainty`, which traces back through
// selene_agent/selene_agent/skills/prospect.py:137-157 to the CONSTANT
// noise_stddev: 0.5 in selene_hal/config/scout.yaml:16. Every reading produced
// the identical alpha 0.35, so FR-DASH-2's "opacity proportional to confidence"
// axis carried no information at all. Confidence is a property of the FUSED
// POSTERIOR — how many readings have landed in a cell and how much they
// agreed — and that quantity only exists in the orchestrator's ResourceMap,
// which has been on the wire as /orchestrator/resource_map since D-09.
//
// EVERYTHING BELOW IS A PORT, NOT A DESIGN. Its counterpart is
// selene_orchestrator/selene_orchestrator/resource_map_viz.py —
// variance_to_certainty(), variance_to_alpha() and certainty_to_rgb() — which
// colours the RViz2 CUBE_LIST overlay from the same posterior. The direction of
// the port is the opposite of iceConcentrationRGB() above (Python copied JS
// there; here JS copies Python), for the same reason in both cases: the PRD's
// exit-gate row "resource heatmap matches RViz2 visualization"
// (docs/PRD.md:1504) is a claim about two renderers agreeing, and it cannot be
// true if each invents its own mapping.
//
// The four constants below MUST equal resource_map_viz.py's ALPHA_MIN,
// ALPHA_MAX, VARIANCE_FLOOR and LOW_CONFIDENCE_GRAY. As of 2026-07-31 that IS
// checked: test_dashboard_colour_parity.py parses all four out of this file,
// rebuilds varianceToCertainty and the gray lerp from them, sweeps both
// against the Python, and recomputes the pinned table at the bottom of this
// block row by row. (It used to compare the concentration ramp only, and this
// comment used to say so.)
//
// AND AS OF D-18 THE FUNCTION BODIES ARE CHECKED TOO, where Node is present.
// This comment used to end "what it still cannot see is a change to a function
// BODY here that leaves the constants alone". That gap is now covered by
// test_node_executes_the_real_javascript_and_agrees, which strips the `export`
// keywords, runs THIS FILE under node, and compares posteriorCellRGBA against
// resource_map_viz.posterior_cell_rgba over 146 cases including the
// non-finite ones. It SKIPS when node is absent — which is what keeps the
// orchestrator's Python CI lane free of a Node dependency — so on a bare CI
// box the port is still only checked as text. Mutation-checked on 2026-07-31:
// perturbing ALPHA_MAX by 0.01 fails 121 of the 146, and one channel of
// LOW_CONFIDENCE_GRAY fails 59.
// ==========================================================================

// Colour of a cell we have observed but are not yet confident about.
//
// COOL, not neutral, and the reason is a test on the Python side:
// test_resource_map_viz.test_marker_colours_track_their_inputs asserts
// blue > red for a cell whose variance still equals the prior. Under the
// certainty lerp such a cell renders as pure LOW_CONFIDENCE_GRAY, so a neutral
// gray would break that assertion. b > g > r keeps "low information reads
// blue-ish", consistent with the low end of the concentration ramp, while still
// reading as gray on screen. Do not change it without re-checking that test.
//
// D-18: this colour at ALPHA_MIN is also the exact rendering of a cell whose
// posterior mean or variance is not a finite number. See ALPHA_MIN above for
// why that reading is unambiguous rather than a collision.
export const LOW_CONFIDENCE_GRAY = [90, 96, 110];

// Variance (wt%^2) at which certainty saturates. ResourceMap floors sensor
// variance at 1e-6, but a posterior that small needs implausibly many readings;
// 0.01 wt%^2 (sigma 0.1 wt%, a fifth of the scout's 0.5 wt% noise) is the
// practical ceiling on confidence.
export const VARIANCE_FLOOR = 0.01;

// Alpha for an observed cell at zero certainty. Never 0: a cell with a single
// distant, uncertain reading is still evidence and must be distinguishable from
// terrain nobody has ever visited. Cells absent from cell_index are not drawn at
// all, and THAT is the "transparent = no data" end of the PRD's ramp.
//
// NO REAL CELL FROM THE SHIPPED FLEET REACHES IT — see varianceToCertainty
// below. The lowest alpha a MEASURED pixel can have is 0.4506, so this constant
// is the floor of the mapping rather than a value on screen, and the "we do not
// know" reading is carried entirely by the not-drawn case above.
//
// D-18 GAVE IT ONE REACHABLE MEANING, and only one: a cell whose posterior mean
// or variance is not a finite number renders here, at pure LOW_CONFIDENCE_GRAY.
// That is unambiguous precisely BECAUSE no measured cell can reach certainty 0
// — ResourceMap.update refuses any reading without a finite, strictly positive
// sigma, so every emitted cell has had at least one strictly-positive-precision
// update. Gray at this alpha therefore means "corrupt", never "faint".
export const ALPHA_MIN = 0.05;

// Alpha at full certainty. Below 1.0 to match resource_map_viz.py, where the
// ceiling exists because RViz2's PointsMarker only enables per-point alpha
// blending once some colour has a != 1.0.
export const ALPHA_MAX = 0.85;

// Posterior variance -> certainty in 0..1.
//
// Verbatim port of resource_map_viz.variance_to_certainty(). Certainty is how
// far the posterior variance has fallen from the prior, on a LOG scale:
//
//     certainty = log10(prior / v) / log10(prior / VARIANCE_FLOOR)
//
// Log rather than linear because the Bayesian update divides variance
// multiplicatively. MEASURED 2026-07-31 by running the shipped
// ResourceMap.update() with the shipped scout RCDL (noise_stddev 0.5,
// selene_hal/config/scout.yaml:16): ONE reading takes a cell from variance
// 100.0 to 0.2494 at the footprint centre and 0.9926 at its edge, which on a
// linear map is certainty 0.9975 / 0.9901 — every subsequent reading would be
// squeezed into the last 0.1% of the range and "observed once" would look
// identical to "observed twenty times". On this log scale they read 0.6508 and
// 0.5008 and further readings keep moving (2 -> 0.7259, 3 -> 0.7699).
//
// THIS COMMENT USED TO SAY the first reading takes variance to ~0.09, and that
// was wrong by 2.8x for the shipped configuration: 0.09 is roughly where the
// THIRD reading lands. It is the number a reviewer would use to sanity-check
// the alpha axis, so it is corrected rather than left.
//
// THE BOTTOM OF THIS AXIS IS UNREACHABLE ON THE SHIPPED FLEET, and both
// renderers inherit that. A cell is only in cell_index once count >= 1, so at
// least one update has run; with the only scalar-field sensor in the tree
// (0.5 wt%) that puts every drawn cell at certainty >= 0.5008, alpha >= 0.4506
// and at most halfway to LOW_CONFIDENCE_GRAY. The ends of the mapping are kept
// as its definition — a noisier sensor reaches them (sigma 2.0 gives certainty
// 0.2148) — but the certainty legend's "unsure" end and the certainty-0 rows in
// the pinned table below describe cells this fleet cannot produce. Pinned by
// test_resource_map_viz.test_the_shipped_scout_cannot_reach_zero_certainty and
// recorded in docs/phase5_deviation_register.md D-02.
export function varianceToCertainty(variance, priorVariance) {
  // D-18: a non-finite variance or prior carries no information, so return the
  // "we do not know" end rather than letting NaN through. Untrapped, NaN
  // reaches Math.round() in certaintyRGB, produces NaN channels, and yields the
  // string 'rgba(NaN,NaN,NaN,NaN)' — which canvas rejects SILENTLY, leaving
  // whatever fillStyle was set last. A wrong colour with no error anywhere is
  // the worst of the three possible outcomes; ALPHA_MIN gray is the honest one.
  if (!Number.isFinite(variance) || !Number.isFinite(priorVariance)) return 0;
  const prior = Math.max(priorVariance, VARIANCE_FLOOR * 10);
  const v = Math.min(Math.max(variance, VARIANCE_FLOOR), prior);
  const span = Math.log10(prior / VARIANCE_FLOOR);
  if (span <= 0) return 1;
  const certainty = Math.log10(prior / v) / span;
  return Math.min(Math.max(certainty, 0), 1);
}

// (concentration, certainty) -> [r, g, b] integers 0-255.
//
// The gray tier FR-DASH-2 asks for, applied as a LERP TOWARD
// LOW_CONFIDENCE_GRAY rather than as a fifth segment at the bottom of the
// concentration ramp. That distinction matters: a gray segment below dark blue
// would mean "gray == very little ice", but the PRD's gray means "we do not
// know", which is an axis orthogonal to concentration. Bolting it onto
// iceConcentrationRGB() would also have broken that function's verbatim-port
// relationship with resource_map_viz.concentration_to_rgb() and with
// ResourceGraph.jsx, neither of which has any notion of certainty.
//
// Exported as the named counterpart of resource_map_viz.certainty_to_rgb:
// Python's certainty_to_rgb(mean, variance, prior) is exactly
// certaintyRGB(mean, varianceToCertainty(variance, prior)). Callers that draw
// cells — the raster and the legend — go through posteriorCellRGBA /
// posteriorCellRGBAAtCertainty below, which add the alpha half of the law.
export function certaintyRGB(meanWt, certainty) {
  const base = iceConcentrationRGB(meanWt);
  // D-18: a non-finite MEAN forces certainty 0 — pure LOW_CONFIDENCE_GRAY —
  // rather than merely falling to the ramp floor. The ramp floor means "we
  // sampled here and found nothing"; a cell whose posterior mean is not a
  // number means "this cell's posterior is corrupt", and those two must not
  // look alike (the same argument ICE_FLOOR_RGB above is kept for). Because no
  // cell the shipped fleet produces can reach certainty 0 — every emitted cell
  // has had at least one strictly-positive-precision update, see
  // varianceToCertainty — pure gray at ALPHA_MIN is unambiguous: on the drawn
  // set it means exactly this.
  const c = Number.isFinite(meanWt) && Number.isFinite(certainty)
    ? Math.min(Math.max(certainty, 0), 1)
    : 0;
  // Math.round here is what resource_map_viz.py's _js_round() exists to
  // reproduce: Python's round() is banker's rounding and differs by 1 on
  // exactly-half values.
  return [
    Math.round(LOW_CONFIDENCE_GRAY[0] + (base[0] - LOW_CONFIDENCE_GRAY[0]) * c),
    Math.round(LOW_CONFIDENCE_GRAY[1] + (base[1] - LOW_CONFIDENCE_GRAY[1]) * c),
    Math.round(LOW_CONFIDENCE_GRAY[2] + (base[2] - LOW_CONFIDENCE_GRAY[2]) * c),
  ];
}

// (concentration, certainty) -> [r, g, b, a]. THE WHOLE COLOUR LAW, with the
// certainty already extracted from the posterior.
//
// Both channels are driven by the SAME certainty value, so a low-confidence
// cell is simultaneously desaturated toward gray and made transparent. Two
// reinforcing encodings of one quantity, which is what makes the axis legible
// against a dark, textured terrain where alpha alone is easy to misread.
//
// D-17 — THIS SPLIT EXISTS SO THE LEGEND CANNOT DRIFT FROM THE MAP. The legend
// has to sweep certainty directly (it has no variance in hand, and no cell to
// take one from), and it used to do that by re-deriving the alpha ramp inline
// and drawing its concentration bar through iceConcentrationColor() at alpha
// 1.0 — the PURE ramp, which the map never draws. Measured: a cell observed
// once at 5.0 wt% renders rgb(31,199,204), a colour on no point of that bar.
// ResourceLegend now calls THIS function, and posteriorCellRGBA below is this
// function composed with varianceToCertainty, so the legend is the map's own
// colour law by construction rather than by a comment asking someone to keep
// two copies in step.
export function posteriorCellRGBAAtCertainty(meanWt, certainty) {
  const c = Number.isFinite(meanWt) && Number.isFinite(certainty)
    ? Math.min(Math.max(certainty, 0), 1)
    : 0;
  const [r, g, b] = certaintyRGB(meanWt, c);
  return [r, g, b, ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * c];
}

// One fused posterior cell -> [r, g, b, a]. r/g/b are 0-255 INTEGERS, a is
// 0..1. This is the only function FleetMap's raster calls.
//
// The Python counterpart is resource_map_viz.posterior_cell_rgba(), which
// marker_colours() calls once per cell for the same reason this exists as one
// function: deriving the hue from the mean and the alpha from the variance in
// two separate calls lets them disagree about a cell whose mean is non-finite
// (D-18) — gray hue, confident alpha.
export function posteriorCellRGBA(meanWt, variance, priorVariance) {
  // D-18: a non-finite mean means the posterior is unusable whatever the
  // variance says, so it collapses BOTH channels, not just the hue.
  const certainty = Number.isFinite(meanWt)
    ? varianceToCertainty(variance, priorVariance)
    : 0;
  return posteriorCellRGBAAtCertainty(meanWt, certainty);
}

// --------------------------------------------------------------------------
// PINNED TABLE — now a real check. Every row below is parsed out of this file
// and recomputed against resource_map_viz.certainty_to_rgb +
// variance_to_alpha by
// selene_orchestrator/test/test_dashboard_colour_parity.py, so a row that
// drifts away from the functions it documents fails the build. Keep the
// `mean variance certainty -> ( r, g, b, alpha )` column shape: the parser
// matches on it.
//
// posteriorCellRGBA(mean, variance, priorVariance = 100.0). If the two ports
// disagree, the PRD's side-by-side comparison (docs/PRD.md:1504) is false.
//
//   mean   variance   certainty   -> (  r,   g,   b, alpha )
//   ----   --------   ---------      -----------------------
//   0.00     100.00     0.00000      ( 90,  96, 110, 0.0500 )
//   0.00       1.00     0.50000      ( 55,  76, 130, 0.4500 )
//   0.00       0.01     1.00000      ( 20,  55, 150, 0.8500 )
//   2.50     100.00     0.00000      ( 90,  96, 110, 0.0500 )
//   2.50       1.00     0.50000      ( 45,  48, 183, 0.4500 )
//   2.50       0.09     0.76144      ( 21,  23, 220, 0.6592 )
//   2.50       0.01     1.00000      (  0,   0, 255, 0.8500 )
//   5.00       1.00     0.50000      ( 45, 176, 183, 0.4500 )
//   5.00       0.01     1.00000      (  0, 255, 255, 0.8500 )
//   7.50       0.09     0.76144      (216, 217,  26, 0.6592 )
//   7.50       0.01     1.00000      (255, 255,   0, 0.8500 )
//  10.00     100.00     0.00000      ( 90,  96, 110, 0.0500 )
//  10.00       0.09     0.76144      (216,  23,  26, 0.6592 )
//  10.00       0.01     1.00000      (255,   0,   0, 0.8500 )
//
// Note the three certainty-0 rows: at zero certainty the cell is pure
// LOW_CONFIDENCE_GRAY whatever its mean, which is the intended reading —
// "we sampled here once, from far away, and cannot yet tell you how much ice".
//
// THOSE THREE ROWS ARE NOT REACHABLE with the sensor this fleet ships, and
// neither is the 1.00 variance row: see varianceToCertainty above. Under
// noise_stddev 0.5 a drawn cell sits between certainty 0.5008 (one reading at
// the edge of its footprint, alpha 0.4506) and ~0.88 (eight readings). At
// 3.5 wt% those two ends are rgb(45,99,183) and rgb(31,100,204). The rows
// remain as the definition of the mapping, not as a description of what an
// operator will see.
// --------------------------------------------------------------------------

// --------------------------------------------------------------------------
// PINNED TABLE 2 — THE NON-FINITE DOMAIN (D-18). Same parser, same file, same
// test; a separate table because the first one is swept numerically and these
// inputs are not numbers you can sweep to.
//
// Every row is "no usable posterior": pure LOW_CONFIDENCE_GRAY at ALPHA_MIN,
// whichever argument went bad. Before this change the two renderers disagreed
// here — posteriorCellRGBA(NaN, 1, 100) returned [55, 76, 130, 0.45] (the ramp
// floor, half-confident) while Python's certainty_to_rgb(nan, 1.0, 100.0)
// raised ValueError inside the orchestrator's publish timer and stopped the
// RViz2 overlay entirely. Both now render the same "we do not know" cell, and
// the reading is unambiguous because no cell the shipped fleet emits can reach
// certainty 0 (varianceToCertainty above).
//
// Two rows are behaviour changes on BOTH sides, not just repairs of a
// divergence: mean +Infinity used to render pure red (the top of the ramp) and
// variance -Infinity used to render at FULL certainty, because
// Math.max(-Infinity, VARIANCE_FLOOR) is VARIANCE_FLOOR. Neither was a
// measurement.
//
//   mean        variance    -> (  r,   g,   b, alpha )
//   ---------   ---------      -----------------------
//   NaN            1.0000      ( 90,  96, 110, 0.0500 )
//   Infinity       1.0000      ( 90,  96, 110, 0.0500 )
//   -Infinity      1.0000      ( 90,  96, 110, 0.0500 )
//   NaN            0.0100      ( 90,  96, 110, 0.0500 )
//   2.5000            NaN      ( 90,  96, 110, 0.0500 )
//   2.5000       Infinity      ( 90,  96, 110, 0.0500 )
//   2.5000      -Infinity      ( 90,  96, 110, 0.0500 )
//   NaN               NaN      ( 90,  96, 110, 0.0500 )
// --------------------------------------------------------------------------
