"""Check 11's arithmetic, without ROS — deviation D-35.

WHY THIS FILE EXISTS
--------------------
Check 11 of ``scripts/validate_phase5.sh`` claims PRD row 5, "Robot override
(send-to-location) works". It FAILed on one gate run and PASSed on the next,
on identical invocations, and the register measured what separated them: 33 cm
of x-displacement on a 3.6 m arc.

The check was not measuring ``send_to_location``. It commanded a target 6 m due
EAST of the robot from a fixed world-axis bearing list, while the fleet spawns
at x = -45 and drives south-west — a ~165 deg about-turn every run — and then
gave that about-turn a flat 12.0 s to make the displacement's dot product with
the bearing positive. The register measured the sign crossing at t ~= 10.2 s.
Two runs landed either side of it.

None of the three defects needs a robot to demonstrate, and none of the three
fixes needs one to pin:

* the bearing is now relative to the robot's own heading, which is already on
  the wire as ``RobotState.pose.theta`` and which the probe used to discard;
* the 12.0 s literal is deleted, not widened. Widening a threshold chosen from
  n = 1 to make a check pass is the failure this register exists to name. The
  replacement is derived per attempt from the bearing offset and the robot's
  own RCDL ``max_speed``;
* the pass predicate is a metre of RANGE CLOSURE rather than the SIGN of a dot
  product, because a sign test is a knife edge by construction and no bearing
  choice fixes that.

WHAT IS ASSERTED, and what each test would catch:

1. the derived window covers the very manoeuvre that produced the coin flip —
   historically grounded and non-circular, since the number it must exceed was
   measured on the running system before this code existed;
2. the window is a FUNCTION of bearing and speed, not a constant. A regression
   to any literal fails this;
3. bearings are heading-relative and never demand an about-turn;
4. the verdict rules: closes a cell -> PASS, closes a centimetre less -> not a
   PASS, drives away -> FAIL, never moves -> FAIL EARLY, state topic dies ->
   SKIP rather than blaming the robot;
5. every FAIL carries the planned-path evidence, which the old FAIL withheld;
6. the RCDL is the source of truth for max_speed and the fallback is loud;
7. neither script still claims the measured pose is dead-reckoned;
8. only a post-override sample can become the motion baseline, and a foreign
   task id a full grace period after acceptance is a FAIL rather than a retry.
   Sections 8 and 9 were added on 2026-07-31 after an adversarial review
   MEASURED that neither property could fail: the predicate that decides both
   lived inside a polling loop no test could drive without a robot, and
   mutating it to ``if True:`` left the whole probe suite green (45 tests, the
   reviewer's count, in an isolated copy of the tree). The
   predicate was extracted verbatim into ``evaluate_goto_acceptance`` — a pure
   refactor, no behaviour change — so that these tests can call it;
9. the named safety factor over the n = 1 yaw rate is actually applied to the
   computed window, and the window keeps that factor of margin over an
   independently modelled manoeuvre. The same review measured that halving
   ``GOTO_KINEMATIC_DERATE`` left every test green.

DELIBERATE NON-ASSERTIONS. Nothing here proves the override reaches a robot,
that the robot moves, or that the derived window is long enough for the REAL
vehicle — the yaw rate it rests on is n = 1, back-derived from one manoeuvre in
one run, and only a live gate run can close that. This file pins the arithmetic
so that a defect in it fails here rather than on WSL2 twenty minutes later.

ROS-FREE BY CONSTRUCTION, and cross-package-free too. ``scripts/phase5_probe.py``
imports ``rclpy`` inside ``main`` and nothing but the standard library at module
scope, so it is safe to import here; ``test_the_probe_imports_no_ros_at_module_
scope`` is what keeps that true. This file must never import ``selene_agent`` or
``selene_hal``: the gate lane puts only ``selene_orchestrator`` and
``selene_isru`` on the path, and an unguarded cross-package import is D-36.
"""

import ast
import importlib.util
import math
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

PROBE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'phase5_probe.py')
GATE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'validate_phase5.sh')

if not os.path.isfile(PROBE_SCRIPT):                 # pragma: no cover
    pytest.skip('scripts/phase5_probe.py is not in this checkout',
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location('phase5_probe_under_test',
                                               PROBE_SCRIPT)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


# ---- the manoeuvre the register measured, from its own table --------------
#: Sweep of the about-turn the old world-axis bearing forced, degrees.
D35_SWEEP_DEG = 164.8
#: When the old sign predicate first went true on that manoeuvre, seconds.
D35_CROSSING_SEC = 10.2
#: The window it had to beat. Deleted by this fix; kept here as the number the
#: derived window must not silently reproduce.
D35_OLD_WINDOW_SEC = 12.0
#: Scout max_speed, selene_hal/config/scout.yaml:3.
SCOUT_MAX_SPEED = 0.5

#: The safety factor the probe NAMES over its own kinematic model, and the
#: requirement section 9 holds the window to. ``GOTO_KINEMATIC_DERATE``'s own
#: docstring: "One named safety factor on the whole kinematic model above,
#: because every number in it is n = 1."
#:
#: DELIBERATELY NOT ``probe.GOTO_KINEMATIC_DERATE``. A test that reads the
#: constant it is checking cannot fail when that constant moves, which is
#: exactly the state section 9 exists to leave. This is the requirement stated
#: independently; the derate is one implementation of it, and a future fix that
#: bought the same margin another way (a more conservative declared yaw rate,
#: say) would keep these tests green, which is correct — the property is the
#: margin, not the number.
REQUIRED_KINEMATIC_SAFETY_FACTOR = 2.0

#: The task-id prefix ``operator_command.py:143`` builds for send_to_location.
#: SPELLED OUT rather than imported from either side: the contract spans two
#: packages, this lane cannot import ``selene_agent`` (D-36), and a shared
#: constant would let a rename stay green on both sides of it at once.
OVERRIDE_TASK_PREFIX = 'override_goto_'

#: Stand-in for the wall clock at which the override service answered.
ANSWERED = 100.0


def _sample(recv, x, y, **extra):
    sample = {'recv': recv, 'x': float(x), 'y': float(y), 'pose_valid': True,
              'fsm_state': 'NAVIGATING', 'current_task_id': 'override_goto_1',
              'theta': 0.0, 'speed': 0.0}
    sample.update(extra)
    return sample


def _closure_time(bearing_deg, max_speed, closure_m=None, dt=0.01, tmax=90.0):
    """Seconds this repository's steering law needs to close *closure_m*.

    A MODEL, NOT A MEASUREMENT, and it is here so the window test is not
    circular. It integrates the law in ``selene_agent/selene_agent/navigator.py``
    without importing it (that would be a cross-package import on the two-package
    gate lane — D-36): heading-error P control at ang_kp = 1.5, yaw capped at
    the ACHIEVED rate the probe declares, and linear speed at max_speed because
    ``navigator.py:542-549`` clamps the P term there for a 6 m goal whatever the
    heading error — which is why the vehicle sweeps an arc instead of turning on
    the spot, and why D-35's robot ended up 3.745 m from where it started.

    It reproduces the closure table quoted in ``goto_target``'s docstring to
    within a hundredth of a second, which is the only claim made for it.
    """
    if closure_m is None:
        closure_m = probe.GOTO_CLOSURE_M
    rng = probe.GOTO_RANGE_M
    tx = rng * math.cos(math.radians(bearing_deg))
    ty = rng * math.sin(math.radians(bearing_deg))
    x = y = theta = 0.0
    best = rng
    elapsed = 0.0
    cap = probe.GOTO_MEASURED_YAW_RATE_RAD_S
    while elapsed < tmax:
        desired = math.atan2(ty - y, tx - x)
        error = math.atan2(math.sin(desired - theta), math.cos(desired - theta))
        theta += max(-cap, min(cap, 1.5 * error)) * dt
        x += max_speed * math.cos(theta) * dt
        y += max_speed * math.sin(theta) * dt
        elapsed += dt
        best = min(best, math.hypot(tx - x, ty - y))
        if rng - best >= closure_m:
            return elapsed
    return float('inf')


# --------------------------------------------------------------------------
# 1-2. The window is derived, and it covers the manoeuvre that flipped.
# --------------------------------------------------------------------------

def test_the_derived_window_covers_the_manoeuvre_that_produced_the_coin_flip():
    """The formula must cover the very case the register recorded.

    Non-circular: 10.2 s was measured on the running system by a read-only pose
    subscriber during gate run 2, before any of this code existed. The old
    12.0 s literal cleared it by 1.8 s, which is what made the check a coin
    flip; the derived window clears it by a factor.
    """
    window = probe.goto_window_seconds(D35_SWEEP_DEG, SCOUT_MAX_SPEED)
    assert window > D35_CROSSING_SEC
    assert window > D35_OLD_WINDOW_SEC, (
        'the derived window for the 164.8 deg about-turn is %.1fs, no better '
        'than the 12.0 s literal it replaced' % (window,))


def test_the_window_is_a_function_of_bearing_and_of_speed():
    """A regression to any constant fails here, whatever its value."""
    assert (probe.goto_window_seconds(90.0, SCOUT_MAX_SPEED)
            > probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED))
    assert (probe.goto_window_seconds(45.0, 0.3)
            > probe.goto_window_seconds(45.0, 0.5))
    assert (probe.goto_window_seconds(-45.0, SCOUT_MAX_SPEED)
            == probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED))


def test_the_window_covers_the_modelled_closure_at_every_shipped_speed():
    """Every bearing offered must be reachable inside its own window.

    The three speeds are the shipped RCDLs (scout 0.5, hauler 0.4, excavator
    0.3 m/s). The margin is the GOTO_KINEMATIC_DERATE, which exists because the
    yaw rate underneath both sides is n = 1.
    """
    for bearing in probe.GOTO_BEARINGS_DEG:
        for speed in (0.5, 0.4, 0.3):
            window = probe.goto_window_seconds(bearing, speed)
            needed = _closure_time(abs(bearing), speed)
            assert window > needed, (
                'bearing %+.0f deg at %.1f m/s needs %.2fs to close %.1f m but '
                'the window is %.2fs' % (bearing, speed, needed,
                                         probe.GOTO_CLOSURE_M, window))


def test_a_zero_or_negative_max_speed_cannot_produce_a_zero_window():
    """A missing RCDL must not divide by zero inside the gate."""
    assert probe.goto_window_seconds(45.0, 0.0) > probe.GOTO_SETTLE_S
    assert probe.goto_window_seconds(45.0, -1.0) > probe.GOTO_SETTLE_S


# --------------------------------------------------------------------------
# 9. The named safety factor over the n = 1 yaw rate is really applied.
#
#    WHY THIS SECTION EXISTS. An adversarial review on 2026-07-31 mutated
#    GOTO_KINEMATIC_DERATE from 2.0 to 1.0 and MEASURED that all 45 tests
#    stayed green: the windows halve (45 deg / 0.3 m/s: 13.71 s -> 7.35 s;
#    90 deg / 0.5: 17.08 -> 9.04; 164.8 deg / 0.5: 27.13 -> 14.06) yet still
#    exceed the 2.36-5.98 s manoeuvre times in the table in ``goto_target``,
#    which is exactly why nothing failed. The derate is NOT an orphan — it is
#    read at ``goto_window_seconds`` — but a regression removing the only
#    margin protecting an n = 1 constant would have been silent, and a silent
#    loss of margin on the instrument that produced a coin flip is the thing
#    this deviation is about.
#
#    Two different claims, pinned separately, because they fail differently:
#    the STRUCTURAL one (the derate multiplies the manoeuvre term and nothing
#    else) and the VALUE one (the margin that survives is the factor the file
#    names). Only the second dies when the constant is halved.
# --------------------------------------------------------------------------

def test_the_derate_scales_only_the_kinematic_term_of_the_window(monkeypatch):
    """Structural: window == settle + derate x (align + close), for any derate.

    This one deliberately does NOT die when the derate is halved — it reads
    whatever value is declared and checks the formula around it. What it kills
    is the derate being dropped from the expression, applied to the settle
    allowance as well (which would derate a dead-time budget that has nothing
    to do with the yaw rate), or applied to only one of the two terms. Both
    halves are recomputed here from the published primitives rather than by
    calling the function under test.

    ``monkeypatch`` restores the declared derate at teardown; the value-side
    tests below depend on it.
    """
    declared = probe.GOTO_KINEMATIC_DERATE
    for derate in (1.0, 2.0, 3.5, declared):
        monkeypatch.setattr(probe, 'GOTO_KINEMATIC_DERATE', derate)
        for bearing, speed in ((45.0, 0.5), (90.0, 0.3), (164.8, 0.4)):
            align = (abs(math.radians(bearing))
                     / probe.GOTO_MEASURED_YAW_RATE_RAD_S)
            close = probe.GOTO_CLOSURE_M / speed
            expected = probe.GOTO_SETTLE_S + derate * (align + close)
            window = probe.goto_window_seconds(bearing, speed)
            assert window == pytest.approx(expected, abs=1e-9), (
                'at derate %.2f the window for %+.1f deg / %.1f m/s is %.4fs, '
                'not the %.4fs the settle-plus-derated-manoeuvre form gives'
                % (derate, bearing, speed, window, expected))


def test_the_window_keeps_the_named_safety_factor_over_the_modelled_manoeuvre():
    """Value: every shipped bearing and speed keeps the factor of margin.

    The left side comes out of ``goto_window_seconds``; the right side is an
    INDEPENDENT integration of the steering law (``_closure_time``) that knows
    nothing about the probe's align-then-close decomposition. The settle
    allowance is subtracted because it is dead time before the manoeuvre
    starts, not margin on the manoeuvre.

    MEASURED, by running this comparison across the twelve shipped
    bearing-and-speed pairs: at the declared derate the worst margin is 3.14x
    (90 deg at the excavator's 0.3 m/s) and the best 4.26x. With the derate
    removed they fall to 1.57-2.13x and TEN of the twelve pairs drop below the
    factor this file requires — which is what makes this a regression test and
    not a restatement of the constant. It also fails if the declared yaw rate
    is raised far enough to eat the margin, since both sides move but not
    together.

    This strengthens ``test_the_window_covers_the_modelled_closure_at_every_
    shipped_speed`` above without replacing it: that test pins the plain
    covering property, which must hold whatever safety-factor policy the file
    adopts, and it is the one that would survive a deliberate, argued change to
    this requirement.
    """
    worst = None
    for bearing in probe.GOTO_BEARINGS_DEG:
        for speed in (0.5, 0.4, 0.3):
            window = probe.goto_window_seconds(bearing, speed)
            needed = _closure_time(abs(bearing), speed)
            margin = (window - probe.GOTO_SETTLE_S) / needed
            if worst is None or margin < worst[0]:
                worst = (margin, bearing, speed)
            assert margin >= REQUIRED_KINEMATIC_SAFETY_FACTOR, (
                'bearing %+.0f deg at %.1f m/s: the window allows %.2fs of '
                'manoeuvre against a modelled %.2fs, a margin of %.2fx, below '
                'the %.1fx safety factor the probe names over a yaw rate '
                'measured once' % (bearing, speed,
                                   window - probe.GOTO_SETTLE_S, needed,
                                   margin, REQUIRED_KINEMATIC_SAFETY_FACTOR))
    assert worst[0] < 10.0, (
        'the worst margin is %.2fx at %+.0f deg / %.1f m/s — if the whole '
        'envelope has become that forgiving the window has stopped being a '
        'threshold' % worst)


def test_the_window_keeps_the_safety_factor_over_the_one_measured_manoeuvre():
    """The same requirement against the only manoeuvre anyone has MEASURED.

    10.2 s is when the old sign predicate first went true during gate run 2,
    recorded by a read-only pose subscriber on the running system before any of
    this code existed. It is the one non-modelled number in the whole
    kinematics argument, which is why the requirement is worth restating
    against it.

    IT IS ALSO LENIENT, and saying so is the honest part: the sign of a dot
    product goes positive EARLIER than a full metre of range closes, so 10.2 s
    is a lower bound on what that manoeuvre would cost under the predicate
    check 11 now uses. Twice a lower bound is less than twice the real thing.
    This is a floor; the modelled test above is what covers the bearings the
    probe actually commands. MEASURED: 27.13 s at the declared derate against
    the 20.4 s required here, and 14.06 s with the derate removed.
    """
    window = probe.goto_window_seconds(D35_SWEEP_DEG, SCOUT_MAX_SPEED)
    assert window >= REQUIRED_KINEMATIC_SAFETY_FACTOR * D35_CROSSING_SEC, (
        'the derived window for the 164.8 deg about-turn is %.2fs, less than '
        '%.1fx the %.1fs that manoeuvre was measured to take — the margin over '
        'the n = 1 yaw rate is gone' % (window,
                                        REQUIRED_KINEMATIC_SAFETY_FACTOR,
                                        D35_CROSSING_SEC))


# --------------------------------------------------------------------------
# 3. Bearings are heading-relative and never an about-turn.
# --------------------------------------------------------------------------

def test_the_bearing_list_never_demands_an_about_turn():
    assert probe.GOTO_BEARINGS_DEG, 'no bearings are offered at all'
    for bearing in probe.GOTO_BEARINGS_DEG:
        assert 0.0 < abs(bearing) <= 90.0, (
            'bearing %r is either straight ahead (where coast alone can supply '
            'the closure) or beyond a quarter turn (which is the manoeuvre '
            'D-35 exists to stop measuring)' % (bearing,))
    assert 0.0 not in probe.GOTO_BEARINGS_DEG
    assert 180.0 not in probe.GOTO_BEARINGS_DEG


def test_bearings_are_heading_relative():
    """The target must rotate with the robot. It used to be world-axis-aligned.

    The heading is the one the register measured at spawn, -2.33 rad.
    """
    origin = {'x': -45.0, 'y': -92.0, 'theta': -2.33}
    tx, ty = probe.goto_target(origin, 45.0)
    assert math.hypot(tx - origin['x'], ty - origin['y']) == pytest.approx(
        probe.GOTO_RANGE_M, abs=1e-9)
    bearing = math.atan2(ty - origin['y'], tx - origin['x'])
    assert bearing == pytest.approx(origin['theta'] + math.radians(45.0),
                                    abs=1e-9)

    turned = dict(origin, theta=origin['theta'] + math.pi)
    ux, uy = probe.goto_target(turned, 45.0)
    assert ux == pytest.approx(2 * origin['x'] - tx, abs=1e-9)
    assert uy == pytest.approx(2 * origin['y'] - ty, abs=1e-9)


# --------------------------------------------------------------------------
# 4. The verdict rules.
# --------------------------------------------------------------------------

def test_a_robot_that_closes_one_cell_passes_and_one_centimetre_less_does_not():
    """The mutation test of this gate: the threshold is pinned both ways."""
    baseline = _sample(0.0, 0.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)

    closed = probe.GOTO_CLOSURE_M
    samples = [baseline] + [_sample(i * 0.5, closed * i / 3.0, 0.0)
                            for i in range(1, 4)]
    verdict, detail, measured = probe.evaluate_goto_progress(
        samples, baseline, target, window, 2.0)
    assert verdict == probe.PASS, detail
    assert measured['closure_m'] == pytest.approx(closed, abs=1e-6)

    short = closed - 0.01
    samples = [baseline] + [_sample(i * 0.5, short * i / 3.0, 0.0)
                            for i in range(1, 4)]
    verdict, detail, measured = probe.evaluate_goto_progress(
        samples, baseline, target, window, 2.0)
    assert verdict is None, 'still inside the window, so undecided'
    verdict, detail, _ = probe.evaluate_goto_progress(
        samples, baseline, target, window, window + 0.1)
    assert verdict == probe.FAIL
    assert 'closed only' in detail


def test_a_robot_that_drives_away_fails():
    baseline = _sample(0.0, 0.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)
    samples = [baseline] + [_sample(i * 0.5, -1.0 * i, 0.0)
                            for i in range(1, 6)]
    verdict, detail, measured = probe.evaluate_goto_progress(
        samples, baseline, target, window, window + 0.1)
    assert verdict == probe.FAIL, detail
    # Closure is floored at zero because the baseline is itself in the sample
    # set: it is "the best progress ever made", and this robot made none.
    assert measured['closure_m'] == pytest.approx(0.0, abs=1e-9)
    assert measured['min_range_m'] == pytest.approx(
        measured['baseline_range_m'], abs=1e-9)
    assert measured['moved_m'] > probe.GOTO_CLOSURE_M, (
        'the robot moved further than the closure threshold — a bare "did it '
        'move" test would have passed this trace, which is the whole point')


def test_a_stationary_robot_fails_early_and_says_so():
    baseline = _sample(0.0, 0.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)
    samples = [baseline] + [_sample(i * 0.5, 0.001 * i, 0.0)
                            for i in range(1, 12)]
    verdict, detail, _ = probe.evaluate_goto_progress(
        samples, baseline, target, window, probe.GOTO_STALL_S + 0.1)
    assert verdict == probe.FAIL
    assert 'did not move' in detail
    assert probe.GOTO_STALL_S + 0.1 < window, (
        'this test only proves an EARLY failure if the stall deadline is '
        'inside the window')


def test_a_dead_state_topic_skips_rather_than_fails():
    """D-34's rule: an instrument that cannot see must not blame the system.

    ``latest_state`` replays its cached sample forever, so the old loop reported
    "moved only 0.000 m in 12s" against a topic that had stopped publishing.
    """
    baseline = _sample(0.0, 0.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)
    samples = [baseline, _sample(0.5, 0.0, 0.0)]
    verdict, detail, _ = probe.evaluate_goto_progress(
        samples, baseline, target, window, window + 0.1)
    assert verdict == probe.SKIP
    assert 'state stopped arriving' in detail


def test_repeated_identical_samples_are_not_four_samples():
    """A cached sample replayed four times is one measurement, not four."""
    baseline = _sample(0.0, 0.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)
    samples = [baseline] * 8
    verdict, _detail, measured = probe.evaluate_goto_progress(
        samples, baseline, target, window, window + 0.1)
    assert measured['samples'] == 1
    assert verdict == probe.SKIP


def test_samples_with_an_invalid_pose_are_not_measured():
    """D-31: before its first /odom_world message a robot publishes (0, 0).

    Dropping those can only push this toward SKIP; it can never manufacture a
    PASS out of a fabricated origin.
    """
    baseline = _sample(0.0, 5.0, 0.0)
    target = (10.0, 0.0)
    window = probe.goto_window_seconds(45.0, SCOUT_MAX_SPEED)
    samples = [baseline] + [_sample(i * 0.5, 0.0, 0.0, pose_valid=False)
                            for i in range(1, 6)]
    verdict, detail, measured = probe.evaluate_goto_progress(
        samples, baseline, target, window, window + 0.1)
    assert measured['invalid_pose_samples'] == 5
    assert verdict == probe.SKIP, detail
    assert 'pose_valid=false' in detail


# --------------------------------------------------------------------------
# 5. Every FAIL carries the planned-path evidence.
# --------------------------------------------------------------------------

def test_every_failure_message_carries_the_planned_path_note():
    """Reporting defect D-35(1). The FAIL used to withhold the best evidence.

    Run 1 FAILed on the displacement while its planned path ended 0.50 m from
    the commanded target — the one number showing the override had worked — and
    the report never printed it, because path_note was interpolated only into
    the PASS branch.
    """
    note = 'planned_path ends (-65.50, -111.50), 0.50 m from the commanded target'
    failed = probe.goto_detail('scout_02', ['closed only 0.11 m'], note, True)
    assert note in failed
    assert 'scout_02' in failed
    passed = probe.goto_detail('scout_02', ['closed 1.40 m'], note, True)
    assert note in passed


def test_an_absent_path_note_is_not_printed_twice():
    """When no path was published the note is already one of the problems."""
    note = 'no planned_path was published after the override'
    text = probe.goto_detail('scout_02', [note], note, False)
    assert text.count(note) == 1


# --------------------------------------------------------------------------
# 6. The RCDL is the source of truth, and the fallback is loud.
# --------------------------------------------------------------------------

def test_read_rcdl_max_speed_prefers_the_rcdl(tmp_path):
    yaml_module = pytest.importorskip('yaml')
    (tmp_path / 'scout.yaml').write_text('robot_type: scout\nmax_speed: 0.75\n',
                                         encoding='utf-8')
    speed, source = probe.read_rcdl_max_speed(str(tmp_path), 'scout',
                                              yaml_module)
    assert speed == pytest.approx(0.75)
    assert 'scout.yaml' in source


def test_read_rcdl_max_speed_degrades_loudly(tmp_path):
    yaml_module = pytest.importorskip('yaml')
    missing = str(tmp_path / 'nowhere')
    speed, source = probe.read_rcdl_max_speed(missing, 'scout', yaml_module)
    assert speed == probe.GOTO_DEFAULT_MAX_SPEED_MPS
    assert 'nowhere' in source and 'default' in source

    speed, source = probe.read_rcdl_max_speed('', 'scout', yaml_module)
    assert speed == probe.GOTO_DEFAULT_MAX_SPEED_MPS
    assert '--rcdl-dir' in source


def test_the_default_max_speed_is_the_slowest_shipped_rcdl():
    """The fallback must lengthen the window, never shorten it."""
    for speed in (0.5, 0.4, 0.3):
        assert probe.GOTO_DEFAULT_MAX_SPEED_MPS <= speed


# --------------------------------------------------------------------------
# 7. Neither script still claims the measured pose is dead-reckoned.
# --------------------------------------------------------------------------

def test_the_probe_no_longer_claims_the_pose_is_dead_reckoned():
    """Reporting defect D-35(2), in the two files that carried it.

    ``pose_source`` defaults to ``localisation``, in which mode
    ``world_odometry_node`` publishes the simulator's true world pose. The
    caveat was wrong in the safe direction, which is exactly how a false
    statement survives review and gets copied forward.
    """
    for path in (PROBE_SCRIPT, GATE_SCRIPT):
        with open(path, 'r', encoding='utf-8') as handle:
            text = handle.read()
        assert 'still dead-reckoned' not in text.lower(), (
            '%s still asserts the measured pose is dead-reckoned'
            % (os.path.basename(path),))
        assert 'pose_source' in text, (
            '%s must name the parameter that decides which pose it is reading'
            % (os.path.basename(path),))


# --------------------------------------------------------------------------
# 8. Which sample may become the motion baseline — assertions (2) and (2b).
#
#    WHY THIS SECTION EXISTS. The predicate underneath both assertions —
#    ``if task.startswith('override_goto_'):`` — is the mechanism the D-35 fix
#    credits with killing the coin flip: it is what makes the motion baseline a
#    sample published AFTER the agent accepted the override rather than the
#    up-to-0.5 s and ~0.25 m stale pre-call sample the old code took off a 2 Hz
#    topic. An adversarial review MEASURED that it was unpinned — mutated to
#    ``if True:`` in an isolated copy, all 45 tests stayed green — because it
#    lived inside a polling loop that cannot run without a robot. The cause was
#    structural, not careless. The predicate is now in
#    ``evaluate_goto_acceptance``, extracted verbatim, and these tests drive it.
#
#    THE EXTRACTION IS A PURE REFACTOR, and that was checked rather than
#    claimed: the pre-extraction loop was reimplemented verbatim beside the new
#    one and the two were compared over 168 exhaustive single-sample histories
#    and 20,000 randomised growing multi-scan ones, including the case where a
#    foreign sample proven in one scan must survive the next. Zero mismatches.
#
#    Each test below names the mutation it was RUN against. All nine mutations
#    were executed on 2026-07-31 and every one of them turned this file red;
#    that is the only evidence any of these are regression tests rather than
#    decoration.
# --------------------------------------------------------------------------

def test_only_an_override_goto_task_id_can_become_the_motion_baseline():
    """MUTATION: ``if task.startswith(...)`` -> ``if True:`` fails here.

    Both samples are NAVIGATING, which is the whole point of assertion (2b):
    reaching NAVIGATING proves the agent is driving somewhere, not that it took
    this command. The queue task arrives first, so a predicate that accepts any
    NAVIGATING sample returns it.
    """
    queue_task = _sample(ANSWERED + 0.1, 1.0, 0.0,
                         current_task_id='task_prospect_007')
    mine = _sample(ANSWERED + 0.4, 2.0, 0.0,
                   current_task_id=OVERRIDE_TASK_PREFIX + '17')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [queue_task, mine], ANSWERED)
    assert baseline is mine, (
        'the baseline came from task %r, so check 11 would measure a robot '
        'driving something that is not this override'
        % (baseline and baseline['current_task_id'],))
    assert verdict is None, detail


def test_a_stale_pre_override_sample_is_never_the_motion_baseline():
    """MUTATION: the same one, in the units the register measured D-35 in.

    ``states_since`` is cut just BEFORE the service call, so the first samples
    it returns can predate the override entirely. RobotState publishes at 2 Hz,
    so a scout at its 0.5 m/s max_speed is up to 0.25 m down-track by the time
    the operator handler has stopped it (``operator_command.py:126-127``) —
    the same order as the 33 cm that separated this check's FAIL from its PASS.
    Nothing about the stale sample looks wrong: it is NAVIGATING, its pose is
    valid, and it arrives first. The task-id prefix is the only thing keeping
    it out of the measurement, and the closure this check asserts is 1.00 m.
    """
    stale = _sample(ANSWERED - 0.4, 0.0, 0.0,
                    current_task_id='task_prospect_007')
    fresh = _sample(ANSWERED + 0.2, 0.25, 0.0,
                    current_task_id=OVERRIDE_TASK_PREFIX + '17')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [stale, fresh], ANSWERED)
    assert baseline is not None, 'no baseline was chosen at all'
    assert baseline is fresh, (
        'the motion baseline is a sample from %.2fs before the override was '
        'answered, %.2f m up-track of where the robot actually started'
        % (ANSWERED - baseline['recv'], abs(fresh['x'] - baseline['x'])))
    assert verdict is None, detail
    assert abs(fresh['x'] - stale['x']) == pytest.approx(0.25, abs=1e-9), (
        'this fixture no longer separates the two candidate origins by the '
        'displacement it exists to reject')


def test_the_baseline_is_the_first_override_sample_and_only_a_navigating_one():
    """MUTATION: dropping the ``fsm_state != 'NAVIGATING'`` guard fails here.

    Two properties, both of which move the measurement. ``elapsed`` is taken
    from ``baseline['recv']``, so accepting a LATER override sample would
    shorten the window the robot is judged against and throw away the motion in
    between — hence first, not latest. And a sample carrying the override id
    while the FSM has not reached NAVIGATING is not evidence of assertion (2)
    at all; the agent sets the id before it plans.
    """
    accepted = _sample(ANSWERED + 0.05, 0.0, 0.0, fsm_state='IDLE',
                       current_task_id=OVERRIDE_TASK_PREFIX + '17')
    first = _sample(ANSWERED + 0.2, 0.1, 0.0,
                    current_task_id=OVERRIDE_TASK_PREFIX + '17')
    later = _sample(ANSWERED + 0.7, 0.4, 0.0,
                    current_task_id=OVERRIDE_TASK_PREFIX + '17')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [accepted, first, later], ANSWERED)
    assert baseline is first
    assert verdict is None, detail


def test_a_foreign_task_id_a_full_grace_period_after_acceptance_is_a_fail():
    """MUTATION: disabling the foreign branch, or ``if True:`` above it, fails.

    Assertion (2b)'s teeth, and the reason it is a FAIL rather than a retry on
    the next bearing: the service said success and the agent is demonstrably
    driving something else, which is a defect in the system rather than an
    unlucky pick by the probe. Re-rolling stimuli until one passes is what this
    register exists to name.
    """
    foreign = _sample(ANSWERED + probe.GOTO_TASK_ID_GRACE_S, 1.0, 0.0,
                      current_task_id='task_haul_003')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [foreign], ANSWERED)
    assert baseline is None
    assert verdict == probe.FAIL
    for fragment in ('scout_02', 'accepted send_to_location', 'task_haul_003',
                     'override_goto_'):
        assert fragment in detail, (
            'the FAIL message does not say %r, so the report would not name '
            'what the robot was doing instead: %r' % (fragment, detail))


def test_a_foreign_task_id_inside_the_grace_period_is_not_yet_a_fail():
    """MUTATION: ``GOTO_TASK_ID_GRACE_S`` -> 0.0 fails here.

    The grace exists because the id and the state are published together but
    the transition and the next timer tick are not simultaneous: the probe must
    let the on-transition publish (D-34) and one more timer publish go by
    before it calls a stale id a defect. Pinning the lower side of the boundary
    is what stops the grace being quietly shortened into a race.

    The second assertion holds the constant to the derivation its own docstring
    gives — two 0.5 s publish periods. It is a claim-versus-code check, not an
    independent measurement of the publish rate, and it would not notice if
    RobotState stopped being published at 2 Hz.
    """
    foreign = _sample(ANSWERED + probe.GOTO_TASK_ID_GRACE_S - 0.05, 1.0, 0.0,
                      current_task_id='task_haul_003')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [foreign], ANSWERED)
    assert baseline is None
    assert verdict is None, detail
    assert probe.GOTO_TASK_ID_GRACE_S >= 2 * 0.5


def test_a_navigating_sample_with_an_empty_task_id_is_not_a_foreign_task():
    """CHARACTERIZATION PIN, not a regression test on observed behaviour.

    Nothing has ever been observed publishing NAVIGATING with an empty
    ``current_task_id``, so this records the reading the code takes rather than
    a requirement anyone measured: an empty id is undecided, not foreign, which
    is the forgiving direction and cannot manufacture a FAIL out of a field the
    agent simply had not filled in yet. If a live run ever produces one, this
    is the test to argue with.

    MUTATION: dropping the ``task and`` guard fails here.
    """
    blank = _sample(ANSWERED + probe.GOTO_TASK_ID_GRACE_S + 5.0, 1.0, 0.0,
                    current_task_id='')
    baseline, verdict, detail = probe.evaluate_goto_acceptance(
        'scout_02', [blank], ANSWERED)
    assert baseline is None
    assert verdict is None, detail


def test_a_non_navigating_sample_is_neither_a_baseline_nor_a_foreign_task():
    """MUTATION: dropping the ``fsm_state != 'NAVIGATING'`` guard fails here.

    The other side of the guard from the test above: a robot sitting IDLE with
    a queue task id is not "navigating something that is not this override",
    and calling it one would fail check 11 for a robot that never started.
    """
    idle = _sample(ANSWERED + 5.0, 0.0, 0.0, fsm_state='IDLE',
                   current_task_id='task_haul_003')
    assert probe.evaluate_goto_acceptance(
        'scout_02', [idle], ANSWERED) == (None, None, '')
    assert probe.evaluate_goto_acceptance(
        'scout_02', [], ANSWERED) == (None, None, '')


# --------------------------------------------------------------------------
# Wiring. A helper nothing calls is this repository's oldest failure mode.
# --------------------------------------------------------------------------

def _function_source(name):
    tree = ast.parse(open(PROBE_SCRIPT, 'r', encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    pytest.fail('scripts/phase5_probe.py defines no %s()' % (name,))


def _calls_within(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_run_send_to_location_actually_uses_the_new_helpers():
    """Every helper this file tests must be on check 11's live path.

    ``AdaptiveSurveyPlanner`` shipped with green unit tests and zero call
    sites; so did ``MaterialInventory``'s writers, ``resource_map_publish_rate``
    and ``recharge_threshold``. A tested pure function with no caller is the
    same defect wearing a test suite.
    """
    calls = _calls_within(_function_source('run_send_to_location'))
    for helper in ('goto_target', 'goto_window_seconds', 'read_rcdl_max_speed',
                   'evaluate_goto_acceptance', 'evaluate_goto_progress',
                   'goto_detail', 'states_since', 'get_remote_parameters'):
        assert helper in calls, (
            'run_send_to_location never calls %s(), so check 11 does not use '
            'what this file pins' % (helper,))


def test_check_eleven_measures_from_the_history_not_from_a_level():
    """The D-34 lesson, applied to check 11's own measurement.

    Precise on purpose: the argument handed to ``evaluate_goto_progress`` must
    itself be a ``states_since`` call. An earlier version of this test looked
    for the name anywhere in the function and stayed green when the measurement
    was switched back to ``[latest_state(...)]``, because the NAVIGATING scan
    above it still used the history.
    """
    source = _function_source('run_send_to_location')
    fed_from_history = False
    for node in ast.walk(source):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(
            func, 'attr', '')
        if name != 'evaluate_goto_progress' or not node.args:
            continue
        first = node.args[0]
        if (isinstance(first, ast.Call)
                and getattr(first.func, 'attr', '') == 'states_since'):
            fed_from_history = True
    assert fed_from_history, (
        'evaluate_goto_progress is not fed from states_since(), so check 11 is '
        'measuring a level again')
    text = ast.dump(source)
    assert 'GOTO_BEARINGS_DEG' in text, (
        'check 11 must iterate the declared bearing list rather than open-code '
        'its own tuple')


def test_the_motion_baseline_is_the_sample_the_acceptance_scan_chose():
    """Section 8 pins a function; this pins that check 11 uses its answer.

    The extraction moved the post-override predicate somewhere a test can reach
    it. That buys nothing if ``evaluate_goto_progress`` is later handed
    ``start`` or ``origin`` — both are pre-call samples, both are in scope, and
    both would restore exactly the stale origin D-35 removed, silently, with
    every test in section 8 still green.

    Structural rather than behavioural: it reads the AST for the name bound to
    the acceptance call's first output and requires that same name to be the
    baseline argument. It also requires the acceptance scan to be fed from
    ``states_since`` rather than a cached level, which is D-34's lesson.
    """
    source = _function_source('run_send_to_location')

    bound = set()
    for node in ast.walk(source):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, 'id', getattr(call.func, 'attr', ''))
        if name != 'evaluate_goto_acceptance':
            continue
        assert len(call.args) >= 2 and isinstance(call.args[1], ast.Call), (
            'evaluate_goto_acceptance is not being handed a call at all, so it '
            'cannot be reading the state history')
        assert getattr(call.args[1].func, 'attr', '') == 'states_since', (
            'the acceptance scan is fed from something other than '
            'states_since(), so check 11 is deciding (2) off a level again')
        for target in node.targets:
            if isinstance(target, ast.Tuple) and target.elts:
                first = target.elts[0]
                if isinstance(first, ast.Name):
                    bound.add(first.id)
    assert bound, (
        'nothing in run_send_to_location binds the baseline returned by '
        'evaluate_goto_acceptance')

    used = set()
    for node in ast.walk(source):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
        if name != 'evaluate_goto_progress' or len(node.args) < 2:
            continue
        second = node.args[1]
        used.add(second.id if isinstance(second, ast.Name) else ast.dump(
            second))
    assert used, 'evaluate_goto_progress is never called with a baseline'
    assert used <= bound, (
        'the motion measurement is baselined on %s, which is not what '
        'evaluate_goto_acceptance returned (%s) — that is the stale pre-call '
        'origin D-35 removed' % (sorted(used - bound), sorted(bound)))


def test_the_probe_imports_no_ros_at_module_scope():
    """This whole file rests on that property; nothing else enforced it.

    ``rclpy`` is imported inside ``main`` deliberately. A top-level ROS import
    would turn every test here into an ImportError on the two-package gate
    lane — which is D-36 from the other side.
    """
    tree = ast.parse(open(PROBE_SCRIPT, 'r', encoding='utf-8').read())
    forbidden = ('rclpy', 'selene_msgs', 'selene_agent', 'selene_hal',
                 'selene_orchestrator', 'nav_msgs', 'visualization_msgs',
                 'rcl_interfaces', 'numpy', 'yaml', 'tornado')
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or '').split('.')[0]]
        else:
            continue
        for name in names:
            assert name not in forbidden, (
                'scripts/phase5_probe.py imports %r at module scope; it must '
                'stay importable with nothing but the standard library'
                % (name,))
