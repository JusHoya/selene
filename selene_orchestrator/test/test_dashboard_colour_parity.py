"""The RViz2 overlay and the dashboard heatmap must be the same colour ramp.

PRD exit-gate row 2 is "Resource heatmap matches RViz2 visualization"
(docs/PRD.md:1504), and its stated method is a human looking at two windows.
Nobody can run that here, and nobody ran it. What CAN be checked by machine is
the only thing that makes the comparison meaningful in the first place: that
both renderers are the same function of the same posterior.

``resource_map_viz`` says in its own module docstring that its ramp is "a
verbatim port of iceConcentrationRGB() in
selene_dashboard/src/utils/colors.js:113-135". This test parses the constants
out of that JavaScript, rebuilds the ramp from THOSE numbers with JavaScript's
rounding, and sweeps the full range against the Python. Nothing here imports a
JS runtime; it reads the file as text, which is the only option available.

The three regexes below are deliberately NOT scoped to a function body: each
literal they look for occurs exactly once at module scope in colors.js
(verified -- ``ICE_FLOOR_RGB`` once, ``MAX_CONCENTRATION_WT`` declared once,
and exactly three ``t < X`` thresholds), so scoping would add a brittle
brace-matcher for no gain. If a second ramp is ever added to that file, these
must be scoped to ``iceConcentrationRGB`` -- the ramp body, not the
``iceConcentrationColor`` wrapper that now merely calls it. (The divisor was a
bare ``/ 10`` until D-17 named it; see ``_parse_divisor``.)

MEASURED ON THIS BOX before ``_js_round`` existed: 5 of 1201 samples over
0-12 wt% differed by 1 in exactly one channel, because Python's ``round()`` is
banker's rounding and JavaScript's ``Math.round`` rounds half up -- at
0.25 wt% JS gives (18, 50, 161) and Python gave (18, 50, 160). The existing
``test_resource_map_viz.py`` pins four boundary values, all of which happen to
be exact, and never reads colors.js at all.

EXTENDED 2026-07-31 to the certainty half. It used to cover the concentration
ramp only, and said so; two independent reviews then re-derived
``varianceToCertainty`` / ``certaintyRGB`` / ``posteriorCellRGBA`` by hand,
found them in agreement, and both noted that nothing in CI would catch a
future drift. The four constants those functions share
(``LOW_CONFIDENCE_GRAY``, ``VARIANCE_FLOOR``, ``ALPHA_MIN``, ``ALPHA_MAX``) are
now parsed out of colors.js and compared, the mapping is rebuilt from THOSE
numbers and swept against the Python, and the 14-row pinned table in the
JavaScript is recomputed rather than read.

EXTENDED AGAIN 2026-07-31 (D-18) to the NON-FINITE domain, which everything
above deliberately or accidentally excluded: the sweeps step over floats, and
NaN is not a float you arrive at by stepping. That is why the pair diverged
there unnoticed for a phase — ``posteriorCellRGBA(NaN, 1, 100)`` returned the
ramp floor at half confidence while ``certainty_to_rgb(nan, 1.0, 100.0)``
raised ``ValueError`` inside the orchestrator's publish timer. The rows are
enumerated rather than swept, and pinned in colors.js as a second table.

THE TEXT-PARSING GAP IS NOW HALF-CLOSED. Everything above reads colors.js as
TEXT, so a change to a JS function BODY that leaves the constants alone — a
sign flipped inside ``varianceToCertainty``, say — is invisible to it. As of
D-18 there is also a lane that EXECUTES the real JavaScript
(``test_node_executes_the_real_javascript_and_agrees``): it strips the
``export`` keywords, runs the module under ``node``, and compares
``posteriorCellRGBA`` itself against Python. That lane SKIPS when ``node`` is
absent, which is the whole reason it is allowed to exist — the register's
objection to a JS test runner was that it would put Node in front of the
orchestrator's Python tests, and a skip does not. So: on a box with Node the
port is checked as code; on a box without it, as text. Neither is a browser,
and nothing here renders a pixel.

A CORRECTION TO THE REGISTER, RECORDED HERE BECAUSE THIS FILE IS WHERE THE
CLAIM WAS REPEATED. Open item 5 and deviation D-01 both say there is no
JavaScript test runner in this repository and that none was added. That was
false even before D-18: ``"test": "react-scripts test"`` has been in
selene_dashboard/package.json all along, and jest 27 + jsdom ship INSIDE
react-scripts 5.0.1, which is already a production dependency — so a JS suite
costs zero new packages. As of 2026-07-31 there is one:
selene_dashboard/src/__tests__/ (39 tests, run with
``CI=true npx react-scripts test --watchAll=false``). It does NOT supersede
this file and this file does not depend on it: the two lanes exist for
different reasons. A jest test can execute colors.js natively but cannot
compare it against resource_map_viz.py, which is the divergence D-18 was
about; only a Python test can hold both halves at once. The jest suite runs in
its own CI job (.github/workflows/ci.yaml, ``dashboard-tests``) so it still
never puts Node in front of the orchestrator's Python lane.
"""

import json
import math
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from selene_orchestrator import resource_map_viz as rmviz

_COLORS_JS = (pathlib.Path(__file__).resolve().parents[2]
              / 'selene_dashboard' / 'src' / 'utils' / 'colors.js')

_LEGEND_JSX = (pathlib.Path(__file__).resolve().parents[2]
               / 'selene_dashboard' / 'src' / 'components' / 'ResourceLegend.jsx')


def _source() -> str:
    if not _COLORS_JS.is_file():
        pytest.skip(f'{_COLORS_JS} not present in this checkout')
    return _COLORS_JS.read_text(encoding='utf-8')


def _parse_ice_floor(source: str) -> tuple[int, int, int]:
    match = re.search(
        r'ICE_FLOOR_RGB\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', source)
    assert match, 'ICE_FLOOR_RGB not found in colors.js'
    return tuple(int(g) for g in match.groups())


def _parse_divisor(source: str) -> float:
    """The concentration divisor, now the named MAX_CONCENTRATION_WT.

    It used to be a bare ``/ 10`` inside ``iceConcentrationRGB`` and this
    function matched the literal. D-17 gave it a name because ResourceLegend
    was separately hardcoding the same 10 for its sweep AND the string
    "10 wt%" for its axis label — three copies, none of which would have failed
    a build if the ramp were rescaled. The assertion below is what keeps the
    name load-bearing: a future edit that puts a literal back in the ramp is a
    silent un-fix, so it fails here.
    """
    value = _parse_number(source, 'MAX_CONCENTRATION_WT')
    assert re.search(
        r'Math\.min\(Math\.max\(finite,\s*0\)\s*/\s*MAX_CONCENTRATION_WT\s*'
        r',\s*1\)', source), (
        'iceConcentrationRGB no longer divides by MAX_CONCENTRATION_WT; the '
        'ramp and the legend axis can now disagree')
    return value


def _parse_segment_thresholds(source: str) -> list[float]:
    """The three `t < X` segment boundaries, in source order."""
    return [float(m) for m in re.findall(r'\bt\s*<\s*([\d.]+)', source)]


def _js_round(x: float) -> int:
    """JavaScript Math.round: half away from zero toward +inf."""
    return math.floor(x + 0.5)


def _js_ramp(value: float, floor_rgb, divisor: float, thresholds):
    """iceConcentrationRGB(), rebuilt from the parsed JS constants.

    ``Number.isFinite(value) ? value : 0`` is modelled here as the explicit
    finiteness check the JavaScript now performs. It used to be ``value || 0``,
    which reached 0 for NaN only because NaN is falsy — and reached
    ``Infinity`` for +inf, i.e. the top of the ramp. Both languages now clamp
    every non-finite input to 0 (D-18).
    """
    finite = value if math.isfinite(value) else 0.0
    t = min(max(finite, 0.0) / divisor, 1.0)
    lo, mid, hi = thresholds
    if t < lo:
        s = t / lo
        return (_js_round(floor_rgb[0] * (1 - s)),
                _js_round(floor_rgb[1] * (1 - s)),
                _js_round(floor_rgb[2] + (255 - floor_rgb[2]) * s))
    if t < mid:
        s = (t - lo) / lo
        return (0, _js_round(255 * s), 255)
    if t < hi:
        s = (t - mid) / lo
        return (_js_round(255 * s), 255, _js_round(255 * (1 - s)))
    s = (t - hi) / lo
    return (255, _js_round(255 * (1 - s)), 0)


# ------------------------------------------------------------- constants

def test_ice_floor_is_identical_in_both_languages():
    assert _parse_ice_floor(_source()) == rmviz.ICE_FLOOR_RGB


def test_the_concentration_divisor_matches_max_concentration_wt():
    assert _parse_divisor(_source()) == rmviz.MAX_CONCENTRATION_WT


def test_the_segment_thresholds_are_the_expected_quarters():
    assert _parse_segment_thresholds(_source()) == [0.25, 0.5, 0.75]


# ------------------------------------------------------------- the ramp

def test_the_ramp_is_exactly_equal_across_the_whole_range():
    """Per-channel EXACT equality, not a tolerance.

    A tolerance would have hidden the banker's-rounding divergence, which is
    the one defect this test was written to find.
    """
    source = _source()
    floor_rgb = _parse_ice_floor(source)
    divisor = _parse_divisor(source)
    thresholds = _parse_segment_thresholds(source)

    mismatches = []
    for i in range(1201):                      # 0.00 .. 12.00 wt% at 0.01
        value = i / 100.0
        js = _js_ramp(value, floor_rgb, divisor, thresholds)
        py = rmviz.concentration_to_rgb(value)
        if js != py:
            mismatches.append((value, js, py))
    assert not mismatches, (
        f'{len(mismatches)} of 1201 samples differ; first few: '
        f'{mismatches[:5]}')


def test_js_round_rounds_half_up_where_python_would_not():
    """The specific behaviour the parity above depends on."""
    assert round(160.5) == 160                  # Python: banker's rounding
    assert rmviz._js_round(160.5) == 161        # JavaScript: half up
    assert rmviz._js_round(0.5) == 1
    assert rmviz._js_round(1.5) == 2
    assert rmviz._js_round(2.5) == 3


def test_the_sample_that_used_to_diverge():
    """0.25 wt%: JS (18, 50, 161), Python gave (18, 50, 160). MEASURED."""
    assert rmviz.concentration_to_rgb(0.25) == (18, 50, 161)


# ------------------------------------------------- the certainty half (D-02)

def _parse_number(source: str, name: str) -> float:
    match = re.search(rf'\b{name}\s*=\s*(-?[\d.eE+-]+)\s*;', source)
    assert match, f'{name} not found in colors.js'
    return float(match.group(1))


def _parse_gray(source: str) -> tuple[int, int, int]:
    match = re.search(
        r'LOW_CONFIDENCE_GRAY\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]',
        source)
    assert match, 'LOW_CONFIDENCE_GRAY not found in colors.js'
    return tuple(int(g) for g in match.groups())


def _js_certainty(variance, prior_variance, variance_floor):
    """varianceToCertainty(), rebuilt from the parsed JS constants."""
    # D-18: `if (!Number.isFinite(variance) || !Number.isFinite(priorVariance))
    # return 0;` — the "we do not know" end, rather than NaN into Math.round.
    if not (math.isfinite(variance) and math.isfinite(prior_variance)):
        return 0.0
    prior = max(prior_variance, variance_floor * 10)
    v = min(max(variance, variance_floor), prior)
    span = math.log10(prior / variance_floor)
    if span <= 0:
        return 1.0
    return min(max(math.log10(prior / v) / span, 0.0), 1.0)


def _js_posterior_cell(mean, variance, prior_variance, constants):
    """posteriorCellRGBA(), rebuilt from the parsed JS constants.

    The whole colour law on the JS side, in one place, so the non-finite rows
    below exercise the same composition the raster does rather than the two
    halves separately. Mirrors:

        certainty = Number.isFinite(meanWt)
          ? varianceToCertainty(variance, priorVariance) : 0
        c   = (isFinite(meanWt) && isFinite(certainty)) ? clamp(certainty) : 0
        rgb = lerp(LOW_CONFIDENCE_GRAY, iceConcentrationRGB(meanWt), c)
        a   = ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * c
    """
    gray = constants['gray']
    certainty = (_js_certainty(variance, prior_variance,
                               constants['variance_floor'])
                 if math.isfinite(mean) else 0.0)
    c = min(max(certainty, 0.0), 1.0) if math.isfinite(mean) else 0.0
    base = _js_ramp(mean, constants['floor_rgb'], constants['divisor'],
                    constants['thresholds'])
    rgb = tuple(_js_round(g + (ch - g) * c) for g, ch in zip(gray, base))
    alpha = (constants['alpha_min']
             + (constants['alpha_max'] - constants['alpha_min']) * c)
    return rgb, alpha


def _constants(source: str) -> dict:
    """Every numeric literal the JS colour law is built from, parsed once."""
    return {
        'floor_rgb': _parse_ice_floor(source),
        'divisor': _parse_divisor(source),
        'thresholds': _parse_segment_thresholds(source),
        'gray': _parse_gray(source),
        'variance_floor': _parse_number(source, 'VARIANCE_FLOOR'),
        'alpha_min': _parse_number(source, 'ALPHA_MIN'),
        'alpha_max': _parse_number(source, 'ALPHA_MAX'),
    }


def test_the_certainty_constants_are_identical_in_both_languages():
    """These four are the ones colors.js says "MUST equal resource_map_viz.py".

    Until this test existed that was an instruction to a human reading two
    files, and the register recorded it as unchecked.
    """
    source = _source()
    assert _parse_gray(source) == rmviz.LOW_CONFIDENCE_GRAY
    assert _parse_number(source, 'VARIANCE_FLOOR') == rmviz.VARIANCE_FLOOR
    assert _parse_number(source, 'ALPHA_MIN') == rmviz.ALPHA_MIN
    assert _parse_number(source, 'ALPHA_MAX') == rmviz.ALPHA_MAX


def test_certainty_is_exactly_equal_across_the_whole_range():
    """Log sweep over the variances a real posterior passes through.

    100.0 down to 0.001 covers the prior, the single-reading band
    (0.25 .. 0.99 for the shipped scout) and everything below the floor.
    """
    floor = _parse_number(_source(), 'VARIANCE_FLOOR')
    for i in range(401):
        variance = 100.0 * (10 ** (-5.0 * i / 400.0))
        js = _js_certainty(variance, 100.0, floor)
        py = rmviz.variance_to_certainty(variance, 100.0)
        assert js == pytest.approx(py, abs=1e-12), variance
    # Degenerate inputs both ports clamp rather than raise.
    for variance, prior in ((0.0, 100.0), (-5.0, 100.0), (1e9, 100.0),
                            (1.0, 0.0), (1.0, 1e6)):
        assert _js_certainty(variance, prior, floor) == pytest.approx(
            rmviz.variance_to_certainty(variance, prior), abs=1e-12)


def test_the_gray_lerp_and_the_alpha_ramp_are_exactly_equal():
    """certaintyRGB + posteriorCellRGBA's alpha, per channel, no tolerance.

    The gray lerp rounds, so this is where a banker's-rounding divergence of
    the kind D-08 records would reappear if _js_round were ever dropped.
    """
    source = _source()
    gray = _parse_gray(source)
    floor_rgb = _parse_ice_floor(source)
    divisor = _parse_divisor(source)
    thresholds = _parse_segment_thresholds(source)
    variance_floor = _parse_number(source, 'VARIANCE_FLOOR')
    alpha_min = _parse_number(source, 'ALPHA_MIN')
    alpha_max = _parse_number(source, 'ALPHA_MAX')

    mismatches = []
    for mean_i in range(0, 1101, 25):              # 0.00 .. 11.00 wt%
        mean = mean_i / 100.0
        for variance in (1000.0, 100.0, 10.0, 1.0, 0.9926, 0.2494, 0.09,
                         0.01, 0.001, 0.0):
            certainty = _js_certainty(variance, 100.0, variance_floor)
            base = _js_ramp(mean, floor_rgb, divisor, thresholds)
            js_rgb = tuple(_js_round(g + (c - g) * certainty)
                           for g, c in zip(gray, base))
            js_alpha = alpha_min + (alpha_max - alpha_min) * certainty
            py_rgb = rmviz.certainty_to_rgb(mean, variance, 100.0)
            py_alpha = rmviz.variance_to_alpha(variance, 100.0)
            if js_rgb != py_rgb or abs(js_alpha - py_alpha) > 1e-12:
                mismatches.append((mean, variance, js_rgb, py_rgb,
                                   js_alpha, py_alpha))
    assert not mismatches, f'{len(mismatches)} mismatches: {mismatches[:5]}'


def test_the_pinned_table_in_colors_js_recomputes_in_python():
    """The 14-row table at the bottom of colors.js was a reviewer's aid.

    It is parsed and recomputed here, so a table that drifts away from the
    functions it documents fails the build instead of misleading the next
    reader. Each row is `mean variance certainty -> (r, g, b, alpha)`.
    """
    rows = re.findall(
        r'^//\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+'
        r'\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)\s*$',
        _source(), re.MULTILINE)
    assert len(rows) >= 10, f'only {len(rows)} pinned rows found in colors.js'
    for mean, variance, certainty, r, g, b, alpha in rows:
        mean = float(mean)
        variance = float(variance)
        assert rmviz.variance_to_certainty(variance, 100.0) == pytest.approx(
            float(certainty), abs=5e-6), (mean, variance)
        assert rmviz.certainty_to_rgb(mean, variance, 100.0) == (
            int(r), int(g), int(b)), (mean, variance)
        assert rmviz.variance_to_alpha(variance, 100.0) == pytest.approx(
            float(alpha), abs=5e-5), (mean, variance)


# ------------------------------------- the non-finite domain (D-18)

#: Every way a cell's posterior can fail to be a number, as (mean, variance).
#: Enumerated rather than swept because that is exactly why this domain went
#: unchecked: the sweeps above step over floats, and NaN is not a float you
#: arrive at by stepping.
NON_FINITE_CASES = [
    (float('nan'), 1.0),
    (float('inf'), 1.0),
    (float('-inf'), 1.0),
    (float('nan'), 0.01),
    (2.5, float('nan')),
    (2.5, float('inf')),
    (2.5, float('-inf')),
    (float('nan'), float('nan')),
]


@pytest.mark.parametrize('mean,variance', NON_FINITE_CASES)
def test_the_two_ports_agree_on_a_non_finite_cell(mean, variance):
    """The divergence D-18 was opened for, both halves, no tolerance.

    MEASURED before the fix, on this box: the JS returned
    ``[55, 76, 130, 0.45]`` for (NaN, 1, 100) — the ramp floor at half
    confidence — while ``rmviz.certainty_to_rgb(nan, 1.0, 100.0)`` raised
    ``ValueError: cannot convert float NaN to integer``. The Python side is
    called from ``_publish_resource_map`` inside the map publish timer, so the
    RViz2 overlay stopped while the dashboard drew a plausible dark-blue patch.
    """
    consts = _constants(_source())
    js_rgb, js_alpha = _js_posterior_cell(mean, variance, 100.0, consts)
    py = rmviz.posterior_cell_rgba(mean, variance, 100.0)
    assert js_rgb == py[:3]
    assert js_alpha == pytest.approx(py[3], abs=1e-12)


@pytest.mark.parametrize('mean,variance', NON_FINITE_CASES)
def test_a_non_finite_cell_is_the_no_information_colour_in_both(mean, variance):
    """Not merely equal — equal to the value that MEANS "unusable".

    Two ports agreeing on the ramp floor would satisfy the test above and still
    tell an operator "we looked here and found no ice" about a corrupt cell.
    """
    consts = _constants(_source())
    js_rgb, js_alpha = _js_posterior_cell(mean, variance, 100.0, consts)
    assert js_rgb == tuple(consts['gray'])
    assert js_alpha == pytest.approx(consts['alpha_min'])


def test_the_second_pinned_table_in_colors_js_recomputes_in_python():
    """colors.js's non-finite table, parsed and recomputed rather than read.

    Same reasoning as the numeric table above: a comment that documents a
    function is a liability once it drifts, so it is executed instead.
    """
    rows = re.findall(
        r'^//\s+(NaN|-?Infinity|[\d.]+)\s+(NaN|-?Infinity|[\d.]+)\s+'
        r'\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)\s*$',
        _source(), re.MULTILINE)
    assert len(rows) >= 8, f'only {len(rows)} non-finite rows found in colors.js'
    for mean, variance, r, g, b, alpha in rows:
        m = float(mean)
        v = float(variance)
        assert not (math.isfinite(m) and math.isfinite(v)), (
            f'row ({mean}, {variance}) is finite and belongs in the other '
            f'table')
        got_r, got_g, got_b, got_a = rmviz.posterior_cell_rgba(m, v, 100.0)
        assert (got_r, got_g, got_b) == (int(r), int(g), int(b)), (mean,
                                                                   variance)
        assert got_a == pytest.approx(float(alpha), abs=5e-5), (mean, variance)


# ------------------------------------- executing the real JavaScript (D-18)

#: (mean, variance, prior) triples driven through BOTH implementations. The
#: finite half exists so that a change to a JS function BODY — which the
#: text-parsing tests above are blind to by construction — is caught wherever
#: Node is installed.
_NODE_CASES = (
    [(m / 4.0, v, 100.0)
     for m in range(0, 45, 3)
     for v in (100.0, 10.0, 1.0, 0.9926, 0.2494, 0.09, 0.01, 0.001, 0.0)]
    + [(m, v, 100.0) for m, v in NON_FINITE_CASES]
    + [(2.5, 1.0, float('nan')), (2.5, 1.0, 0.0), (-3.0, 1.0, 100.0)]
)


def _js_number(x: float) -> str:
    """A Python float as a JavaScript literal, non-finite included."""
    if math.isnan(x):
        return 'NaN'
    if x == math.inf:
        return 'Infinity'
    if x == -math.inf:
        return '-Infinity'
    return repr(float(x))


def test_node_executes_the_real_javascript_and_agrees():
    """The only check here that RUNS colors.js instead of reading it.

    SKIPPED WHEN NODE IS ABSENT, and that is the point. The deviation register
    records the objection to a JavaScript test runner in this repository: it
    would put a Node dependency in front of the orchestrator's Python lane. A
    test that skips adds no dependency — CI keeps the text-parsing lane, and a
    developer box (or the WSL2 validation box) additionally gets the port
    checked as code rather than as text.

    It also checks the identity ResourceLegend now relies on:
    ``posteriorCellRGBAAtCertainty(m, varianceToCertainty(v, p))`` equals
    ``posteriorCellRGBA(m, v, p)``. That is what makes the legend the map's own
    colour law rather than a second implementation of it (D-17), and it is
    checkable from here precisely because the legend was rebuilt on top of the
    raster's function.
    """
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed; the text-parsing lane still ran')

    source = _source()
    # colors.js is an ES module, and `export` is the only ESM syntax in it, so
    # stripping the keyword yields a plain CommonJS script. Nothing else is
    # rewritten: the function bodies under test are byte-identical to what the
    # dashboard bundles.
    stripped = re.sub(r'^export\s+', '', source, flags=re.MULTILINE)
    assert 'export ' not in stripped, 'an export survived the strip'

    cases = ',\n'.join(
        '[%s, %s, %s]' % (_js_number(m), _js_number(v), _js_number(p))
        for m, v, p in _NODE_CASES)
    driver = (
        stripped
        + '\nconst CASES = [\n' + cases + '\n];\n'
        + 'const out = CASES.map(([m, v, p]) => posteriorCellRGBA(m, v, p));\n'
        + 'const via = CASES.map(([m, v, p]) =>\n'
        + '  posteriorCellRGBAAtCertainty(m, varianceToCertainty(v, p)));\n'
        + 'console.log(JSON.stringify({ out: out, via: via }));\n'
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / 'colors_probe.js'
        path.write_text(driver, encoding='utf-8')
        proc = subprocess.run([node, str(path)], capture_output=True,
                              text=True, timeout=120)
    assert proc.returncode == 0, f'node failed: {proc.stderr[-2000:]}'
    payload = json.loads(proc.stdout)

    mismatches = []
    for (mean, variance, prior), js in zip(_NODE_CASES, payload['out']):
        # JSON has no NaN: a null channel here means the JS produced NaN, which
        # is the failure that yields 'rgba(NaN,...)' — a string canvas rejects
        # silently, leaving the previous cell's colour on screen.
        assert all(c is not None for c in js), (mean, variance, prior, js)
        py = rmviz.posterior_cell_rgba(mean, variance, prior)
        if tuple(js[:3]) != tuple(py[:3]) or abs(js[3] - py[3]) > 1e-12:
            mismatches.append((mean, variance, prior, js, py))
    assert not mismatches, (
        f'{len(mismatches)} of {len(_NODE_CASES)} disagree between the real '
        f'JavaScript and resource_map_viz; first few: {mismatches[:5]}')

    assert payload['via'] == payload['out'], (
        'posteriorCellRGBAAtCertainty composed with varianceToCertainty is no '
        'longer posteriorCellRGBA, so ResourceLegend is drawing a colour law '
        'the raster does not apply — the D-17 defect, reintroduced')


# --------------------------------- the legend draws the map's law (D-17)

def _legend_source() -> str:
    if not _LEGEND_JSX.is_file():
        pytest.skip(f'{_LEGEND_JSX} not present in this checkout')
    return _LEGEND_JSX.read_text(encoding='utf-8')


def _legend_imports_from_colors() -> set:
    """The names ResourceLegend pulls out of utils/colors.

    Checked on the IMPORT LIST rather than by searching the file body, because
    the body legitimately names the old functions in the comment recording what
    D-17 was: a substring search would flag the explanation as the defect.
    """
    match = re.search(
        r'import\s*\{([^}]*)\}\s*from\s*[\'"]\.\./utils/colors[\'"]',
        _legend_source())
    assert match, 'ResourceLegend no longer imports from utils/colors'
    return {name.strip() for name in match.group(1).split(',') if name.strip()}


def test_the_legend_draws_through_the_rasters_own_colour_function():
    """D-17: the legend used to teach a colour no map cell can have.

    It built its bar from ``iceConcentrationColor(value, 1.0)`` — the PURE
    ramp — while the map draws ``posteriorCellRGBA``, which lerps toward
    LOW_CONFIDENCE_GRAY as certainty falls. MEASURED through the real
    ResourceMap: a cell observed once at 5.0 wt% renders rgb(31,199,204), which
    is on no point of that bar (r non-zero while b is not 255).

    This asserts the structural fix rather than the appearance, which is all
    that can be asserted from here: the legend colours its swatch with the
    raster's own function and imports nothing else colour-related. It would
    have failed against the shipped legend, which imported
    iceConcentrationColor, certaintyRGB, ALPHA_MIN and ALPHA_MAX.
    """
    imported = _legend_imports_from_colors()
    assert 'posteriorCellRGBAAtCertainty' in imported, (
        f'ResourceLegend imports {imported}; it must colour its swatch with '
        f'the same function the raster reduces to')
    forbidden = imported & {'iceConcentrationColor', 'iceConcentrationRGB',
                            'certaintyRGB'}
    assert not forbidden, (
        f'ResourceLegend imports {sorted(forbidden)} — a colour ramp that is '
        f'only PART of the law the map applies. That is exactly D-17.')


def test_the_legend_cannot_re_derive_the_alpha_ramp():
    """ALPHA_MIN/ALPHA_MAX in the legend meant a second copy of the alpha law.

    The old certainty bar computed ``ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) *
    certainty`` inline, so the constants agreed with resource_map_viz while the
    EXPRESSION was free to drift from posteriorCellRGBA's. Taking the alpha out
    of the same call as the colour is what removes the second copy.
    """
    imported = _legend_imports_from_colors()
    leaked = imported & {'ALPHA_MIN', 'ALPHA_MAX', 'VARIANCE_FLOOR',
                         'LOW_CONFIDENCE_GRAY'}
    assert not leaked, (
        f'ResourceLegend imports {sorted(leaked)}, which it only needs in '
        f'order to rebuild a mapping colors.js already exports whole')


def test_the_legend_axis_is_derived_from_the_ramps_own_constant():
    """The "10 wt%" label and the sweep must come from MAX_CONCENTRATION_WT.

    Otherwise rescaling the ramp leaves a legend labelled for a range the ramp
    no longer covers — the same class of defect as D-17 itself, one axis over.
    """
    assert 'MAX_CONCENTRATION_WT' in _legend_imports_from_colors()
    assert _parse_number(_source(), 'MAX_CONCENTRATION_WT') == \
        rmviz.MAX_CONCENTRATION_WT
