"""The exit gate must not SKIP a row on a system that satisfied it — D-34.

WHY THIS FILE EXISTS
--------------------
``/{robot_id}/state`` was a LEVEL signal on a 0.5 s timer, and the FSM crosses
IDLE between an operator cancel and the next bid in 0.247 s and 0.301 s —
measured, from the two 2026-07-31 gate runs' own launch logs. Half a sampling
period. ``pick_prospect_robot`` polled ``probe.latest_state`` for that level for
ten seconds, never saw it, and returned a failure string; checks 6 and 9 SKIPped
on BOTH runs, costing PRD exit-gate rows 3 and 4, on a system that had done
exactly what those rows assert.

That is D-10's failure mode inverted. Not a check claiming more than it
measured — a check reporting nothing about a system that satisfied it. The
gate's contract is right: a SKIP is correctly not a pass. The instrument was
wrong, in two separate ways, and this file pins both repairs:

1. THE HISTORY WAS ALREADY THERE. ``_make_state_cb`` appends every sample and
   ``latest_state`` returns ``samples[-1]``; nothing read the rest. A transient
   state is in the recording whenever any sample landed in it, and no amount of
   polling a level recovers it afterwards. ``states_since`` reads it.
2. THE CANCEL'S OWN RESPONSE IS A CAUSAL RECEIPT and needs no sampling at all.
   ``/orchestrator/override_robot`` returns ``bool(agent_resp.accepted)``, the
   agent returns accepted only after firing OPERATOR_CANCEL, and OPERATOR_CANCEL
   maps unconditionally to IDLE from every state except OFFLINE — which the
   agent rejects on its own live FSM. So an accepted cancel means the FSM WAS in
   IDLE whether or not any sample carried it.

THE GATE HALF IS SUFFICIENT ALONE.
``test_the_stream_that_skipped_two_prd_rows_carries_a_durable_signature`` and
``test_corroboration_is_never_required_for_the_row_to_be_measured`` are the two
assertions that say so: with a sample stream in which IDLE never appears at all
— the stream both live runs recorded — the row is still measured. The
agent-side fix (publishing on every FSM transition) raises the probability that
a sample lands in the window; it does not make the gate correct, and a state
shorter than any publish scheme is always possible.

D-34 HAS A THIRD CONSEQUENCE, INSIDE CHECK 4, and the last section of this file
pins it. Making the publish rate variable turns check 4's IDLE motion rule from
a measurement of the robot into a measurement of the sampler: it sums ``|dp|``
once per sample, so more samples means more accumulated path, and a sample
published at the instant of the transition INTO idle drags the stopping
transient inside the window a 2 Hz sampler used to exclude by accident. Left
alone, D-34's fix could flip a currently-PASSING check to FAIL on correct
behaviour. The repair is rate-invariance, not a bigger threshold: the same
5 cm, measured as an excursion over a settled window.

WHAT IS NOT ASSERTED. Nothing here proves the freed robot bid, that the auction
ran, or that anything reached a robot. ``correlate_injection`` is what asserts
the row, it still can and does FAIL, and it never compares the auction winner to
the robot this function returned — a claim an earlier draft of this fix made and
which is false.

ROS-FREE, and free of cross-package imports: the gate lane carries only
``selene_orchestrator`` and ``selene_isru``, and an unguarded import across that
boundary is D-36.
"""

import ast
import importlib.util
import math
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

PROBE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'phase5_probe.py')

if not os.path.isfile(PROBE_SCRIPT):                 # pragma: no cover
    pytest.skip('scripts/phase5_probe.py is not in this checkout',
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location('phase5_probe_for_freeing',
                                               PROBE_SCRIPT)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


# ---- The timeline the register measured, run 1 (register D-34's table). ----
CANCEL_ACCEPTED_AT = 131.417886
IDLE_ENTERED_AT = 131.418348
BIDDING_ENTERED_AT = 131.665462
IDLE_LASTED = BIDDING_ENTERED_AT - IDLE_ENTERED_AT          # 0.247114 s
STATE_PERIOD = 0.5


def _sample(recv, state, task_id='task_7'):
    return {'recv': recv, 'fsm_state': state, 'current_task_id': task_id,
            'robot_id': 'scout_01', 'robot_type': 'scout',
            'capabilities': ['prospect'], 'x': 0.0, 'y': 0.0, 'theta': 0.0,
            'speed': 0.0, 'battery_level': 0.9, 'pose_valid': True,
            'stamp': recv}


def _two_hertz_stream_that_misses_idle():
    """The sample stream both live gate runs actually recorded.

    A 0.5 s sampler phased so that no tick falls inside the 0.247 s IDLE window.
    This is the counterfactual the whole deviation rests on, so it is asserted
    rather than assumed.
    """
    stream = [_sample(CANCEL_ACCEPTED_AT - 0.2, 'NAVIGATING'),
              _sample(CANCEL_ACCEPTED_AT - 0.2 + STATE_PERIOD, 'BIDDING', ''),
              _sample(CANCEL_ACCEPTED_AT - 0.2 + 2 * STATE_PERIOD, 'BIDDING',
                      '')]
    return stream


def test_the_measured_idle_window_is_shorter_than_the_sampling_period():
    """Pins the arithmetic the rest of this file argues from."""
    assert IDLE_LASTED == pytest.approx(0.247114, abs=1e-6)
    assert IDLE_LASTED < STATE_PERIOD


def test_the_two_hertz_stream_really_does_miss_it():
    stream = _two_hertz_stream_that_misses_idle()
    inside = [s for s in stream
              if IDLE_ENTERED_AT <= s['recv'] < BIDDING_ENTERED_AT]
    assert not inside, 'the fixture is meant to straddle the IDLE window'
    assert not [s for s in stream if s['fsm_state'] == 'IDLE']


# --------------------------------------------------------------------------
# samples_since — the read that stopped throwing the recording away.
# --------------------------------------------------------------------------

def test_samples_since_returns_every_sample_at_or_after_the_cut():
    """THE MUTATION: make this return ``[samples[-1]]`` and this test goes red.

    That mutation is not hypothetical — it is precisely what ``latest_state``
    does, and doing it here would restore D-34's aliasing while every other
    test in the repository stayed green.
    """
    samples = [_sample(1.0, 'NAVIGATING'), _sample(1.5, 'IDLE', ''),
               _sample(2.0, 'BIDDING', ''), _sample(2.5, 'ASSIGNED')]
    got = probe.samples_since(samples, 1.5)
    assert [s['recv'] for s in got] == [1.5, 2.0, 2.5]
    assert [s['fsm_state'] for s in got] == ['IDLE', 'BIDDING', 'ASSIGNED']
    assert probe.samples_since(samples, 0.0) == samples
    assert probe.samples_since(samples, 99.0) == []


def test_samples_since_hands_back_copies():
    """The caller must not be able to corrupt the probe's own recording."""
    samples = [_sample(1.0, 'IDLE', '')]
    got = probe.samples_since(samples, 0.0)
    got[0]['fsm_state'] = 'MANGLED'
    assert samples[0]['fsm_state'] == 'IDLE'


def test_the_transient_idle_is_visible_in_history_and_invisible_to_a_level():
    """The whole deviation in one test, with the register's own numbers."""
    with_edge = _two_hertz_stream_that_misses_idle() + [
        _sample(IDLE_ENTERED_AT, 'IDLE', '')]
    with_edge.sort(key=lambda s: s['recv'])

    level_read = with_edge[-1]
    assert level_read['fsm_state'] != 'IDLE', (
        'the newest sample is never the transient one; that is why polling a '
        'level for ten seconds found nothing')

    history = probe.samples_since(with_edge, CANCEL_ACCEPTED_AT)
    assert any(s['fsm_state'] == 'IDLE' for s in history)


# --------------------------------------------------------------------------
# freeing_receipt — the causal receipt and its one hole.
# --------------------------------------------------------------------------

def test_an_accepted_cancel_is_a_receipt_on_its_own():
    ok, kind, note = probe.freeing_receipt(
        True, 'override cancel_task accepted', [], [], 'scout_01', 'inject_1')
    assert ok is True
    assert kind == ''
    assert 'OPERATOR_CANCEL' in note


def test_the_stream_that_skipped_two_prd_rows_carries_a_durable_signature():
    """SUFFICIENCY: the gate half needs no help from the agent half.

    Fed the sample stream both live runs recorded — one in which IDLE never
    appears at all — the robot is returned and checks 6 and 9 render a verdict
    instead of SKIPping. The agent-side publish-on-transition raises the
    probability that a sample lands in the window; it is not what makes this
    correct, and a state shorter than any publish scheme is always possible.

    AND THE EVIDENCE WAS ALREADY ON THE WIRE. Those post-cancel BIDDING samples
    carry an EMPTY ``current_task_id`` — the operator handler clears it and only
    a new assignment re-sets it — so the durable signature of the cancel was in
    the recording on both runs while the gate was polling for a 0.247 s level it
    could not see.
    """
    stream = probe.samples_since(_two_hertz_stream_that_misses_idle(),
                                 CANCEL_ACCEPTED_AT)
    assert stream and not [s for s in stream if s['fsm_state'] == 'IDLE']
    ok, kind, note = probe.freeing_receipt(
        True, '', stream, [], 'scout_01', 'inject_1')
    assert ok is True
    assert kind == 'cleared_task_id'
    assert 'current_task_id' in note


def test_duplicate_sequence_is_accepted_without_firing_and_is_not_a_receipt():
    """The one hole in the receipt argument, rejected explicitly.

    ``operator_command_logic`` returns accepted=True for a repeated sequence
    WITHOUT firing OPERATOR_CANCEL, and the orchestrator forwards that reason
    verbatim into ``response.message``.
    """
    ok, kind, note = probe.freeing_receipt(
        True, 'duplicate_sequence', [_sample(1.0, 'IDLE', '')], [],
        'scout_01', 'inject_1')
    assert ok is False
    assert kind == ''
    assert 'duplicate_sequence' in note


def test_a_rejected_cancel_is_not_a_receipt():
    ok, kind, note = probe.freeing_receipt(
        False, 'robot in OFFLINE, override rejected', [], [], 'scout_01', '')
    assert ok is False
    assert 'not accepted' in note


def test_a_service_call_that_never_answered_is_not_a_receipt():
    ok, _kind, note = probe.freeing_receipt(False, '', [], [], 'scout_01', '')
    assert ok is False
    assert 'no answer' in note


def test_corroboration_from_an_idle_sample_names_itself():
    stream = [_sample(1.0, 'IDLE', '')]
    ok, kind, note = probe.freeing_receipt(True, '', stream, [], 'scout_01',
                                           'inject_1')
    assert (ok, kind) == (True, 'idle_sample')
    assert 'IDLE state sample' in note


def test_corroboration_from_a_cleared_task_id():
    """The DURABLE post-cancel signature, which outlives the IDLE window.

    ``current_task_id`` is cleared by the operator handler and re-set only on a
    new assignment, so it persists through the whole BIDDING window — unlike
    IDLE, which lasted 0.247 s.
    """
    stream = [_sample(1.0, 'BIDDING', '')]
    ok, kind, note = probe.freeing_receipt(True, '', stream, [], 'scout_01',
                                           'inject_1')
    assert (ok, kind) == (True, 'cleared_task_id')
    assert 'current_task_id' in note


def test_corroboration_from_the_assignment_record():
    stream = [_sample(1.0, 'ASSIGNED', 'inject_1')]
    assignments = [(2.0, 'inject_1', 'scout_01', -50.0, -100.0)]
    ok, kind, note = probe.freeing_receipt(True, '', stream, assignments,
                                           'scout_01', 'inject_1')
    assert (ok, kind) == (True, 'assignment')
    assert 'assigned' in note


def test_an_assignment_to_another_robot_is_not_corroboration():
    stream = [_sample(1.0, 'ASSIGNED', 'inject_1')]
    assignments = [(2.0, 'inject_1', 'scout_02', -50.0, -100.0)]
    ok, kind, _note = probe.freeing_receipt(True, '', stream, assignments,
                                            'scout_01', 'inject_1')
    assert ok is True
    assert kind == '', 'that assignment says nothing about scout_01'


def test_corroboration_is_never_required_for_the_row_to_be_measured():
    """The expiry of the corroboration window must cost the row nothing.

    This is the difference from the settle loop it replaces, whose 10 s expiry
    WAS the verdict: two runs, two SKIPs, two unmeasured PRD rows. Here the
    worst case is a stream with no IDLE sample, no cleared task id and no
    assignment — nothing corroborating at all — and the row is still measured,
    on the receipt alone, with the report saying exactly that.
    """
    for stream in ([], [_sample(1.0, 'BIDDING', 'other_task')]):
        ok, kind, note = probe.freeing_receipt(True, '', stream, [],
                                               'scout_01', 'inject_1')
        assert ok is True
        assert kind == ''
        assert 'rests on the service response alone' in note


# --------------------------------------------------------------------------
# Wiring: the helpers must be on the live path.
# --------------------------------------------------------------------------

def _node_named(kind, name, parent=None):
    tree = parent or ast.parse(open(PROBE_SCRIPT, 'r', encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, kind) and node.name == name:
            return node
    pytest.fail('scripts/phase5_probe.py defines no %s %r'
                % (kind.__name__, name))


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


def test_probe_node_states_since_is_the_pure_helper():
    """The method the live probe calls must be the function this file pins."""
    node_class = _node_named(ast.ClassDef, 'ProbeNode')
    method = _node_named(ast.FunctionDef, 'states_since', node_class)
    assert 'samples_since' in _calls_within(method), (
        'ProbeNode.states_since does not use samples_since(), so the live gate '
        'and this test are measuring two different functions')


def test_pick_prospect_robot_reads_history_and_takes_the_receipt():
    """The anti-"wired but never called" test for this repair.

    BOTH loops are checked, not just the function. Phase 1 (the wait) and phase
    2 (the corroboration) each need the history read: an earlier version of this
    test looked only for the NAME anywhere in the function, and a mutation that
    gutted the phase-1 read left it green because phase 2 still used it.
    """
    source = _node_named(ast.FunctionDef, 'pick_prospect_robot')
    calls = _calls_within(source)
    assert 'freeing_receipt' in calls

    loops = [node for node in ast.walk(source) if isinstance(node, ast.While)]
    assert len(loops) >= 2, (
        'pick_prospect_robot should have a wait loop and a corroboration loop; '
        'found %d' % (len(loops),))
    for index, loop in enumerate(loops):
        assert 'states_since' in _calls_within(loop), (
            'loop %d of pick_prospect_robot does not read the recorded '
            'history, so it is polling a level again — which is D-34'
            % (index + 1,))


def _idle_run(positions, first_recv=0.0):
    """One bounded IDLE run: NAVIGATING, then *positions*, then BIDDING.

    *positions* is a list of ``(offset_seconds, x)`` pairs relative to the first
    IDLE sample. The bracketing samples are what make the run maximal.
    """
    samples = [_sample(first_recv - 0.5, 'NAVIGATING')]
    for offset, x in positions:
        sample = _sample(first_recv + offset, 'IDLE', '')
        sample['x'] = float(x)
        samples.append(sample)
    samples.append(_sample(first_recv + positions[-1][0] + 0.1, 'BIDDING', ''))
    return samples


def test_a_robot_that_wanders_while_idle_still_fails():
    """THE NON-WEAKENING GUARD. Run this first when reading the rest.

    Everything below relaxes something about HOW the IDLE rule is computed. This
    is the assertion that the rule still bites: a robot that reports IDLE for
    three seconds and drifts half a metre is a FAIL, at the same 5 cm threshold
    the rule has always used.
    """
    samples = _idle_run([(i * 0.5, i * 0.1) for i in range(7)])
    problems, reports = probe.evaluate_idle_motion(samples)
    assert problems, reports
    assert 'moved' in problems[0] or 'span' in problems[0]
    assert reports[0]['verdict'] == 'FAIL'
    assert reports[0]['excursion_settled_m'] >= probe.MOTION_EPS_M


def test_the_stopping_transient_does_not_fail_the_gate():
    """The hazard D-34's fix introduces, and the reason for the settle window.

    A robot entering IDLE from a moving state is decelerating: the operator
    handler zeroes the drive command and the wheels obey it some unmeasured time
    later. Modelled here as the adversarial review modelled it — 0.10 m of coast
    over 0.4 s — with a sample published at the instant of the transition. Under
    a whole-run path sum that run measures 0.100 m against a 0.05 m threshold
    and FAILS a robot that is behaving correctly. THE COAST PROFILE IS A MODEL,
    NOT A MEASUREMENT: nobody in this repository has measured the stopping
    distance, which is itself the reason a rule must not be silently tightened
    onto it.
    """
    samples = _idle_run([(0.0, 0.00), (0.3, 0.09), (0.8, 0.10), (1.3, 0.10),
                         (1.8, 0.10)])
    problems, reports = probe.evaluate_idle_motion(samples)
    assert reports[0]['path_length_m'] >= probe.MOTION_EPS_M, (
        'the fixture is meant to be one the OLD whole-run path sum failed'
    )
    assert not problems, reports
    assert reports[0]['verdict'] == 'PASS'
    assert reports[0]['excursion_settled_m'] == pytest.approx(0.0, abs=1e-9)


def test_a_short_window_is_not_promoted_by_a_transition_sample():
    """A sample count stopped being a duration when the rate became variable.

    Two 2 Hz samples is not a run. Adding the transition-instant sample makes it
    three — enough to trip a count-only threshold — without the robot having
    been IDLE for one moment longer. The span rule is what keeps the threshold
    meaning what it meant.

    THE SPAN RULE IS A SCOPE CONDITION, NOT AN ESCAPE HATCH, and the second half
    of this test is what proves it: the same motion, continued until the robot
    really has been IDLE for a second, is a FAIL.
    """
    brief = [(0.0, 0.00), (0.5, 0.06), (0.85, 0.12)]
    problems, reports = probe.evaluate_idle_motion(_idle_run(brief))
    assert len(reports) == 1
    assert reports[0]['samples'] == 3
    assert reports[0]['span_sec'] < probe.MOTION_MIN_SPAN_SEC
    assert not problems, (
        'a sub-second window is not the sustained IDLE this rule is about; '
        'judging it is what a bare sample count would have done')
    assert 'not judged' in reports[0]['verdict']

    sustained = brief + [(1.35, 0.18), (1.85, 0.24)]
    problems, reports = probe.evaluate_idle_motion(_idle_run(sustained))
    assert reports[0]['span_sec'] >= probe.MOTION_MIN_SPAN_SEC
    assert problems, reports


def test_the_idle_verdict_does_not_depend_on_the_sample_rate():
    """The property the whole repair exists for.

    ONE physical trajectory — a robot parked with a centimetre of position
    jitter — sampled at 2 Hz and at 10 Hz. The excursion is a property of the
    trajectory and barely moves; the summed path length is a property of the
    SAMPLER and grows fivefold. Only one of those two can decide a verdict
    honestly.

    The jitter is a deterministic function of the sample index, not an RNG: a
    fixture that flakes is worse than no fixture.
    """
    def trajectory(rate_hz, seconds=20.0):
        step = 1.0 / rate_hz
        count = int(seconds / step)
        return [(i * step, 0.01 * math.sin(i * 1.7)) for i in range(count)]

    slow_problems, slow = probe.evaluate_idle_motion(
        _idle_run(trajectory(2.0)))
    fast_problems, fast = probe.evaluate_idle_motion(
        _idle_run(trajectory(10.0)))

    assert not slow_problems and not fast_problems
    assert slow[0]['verdict'] == fast[0]['verdict'] == 'PASS'
    assert fast[0]['excursion_settled_m'] == pytest.approx(
        slow[0]['excursion_settled_m'], abs=0.005), (
        'the excursion must be a property of the trajectory, not of the rate')

    # CHARACTERIZATION PIN, not a regression test: ``_run_path_length`` is
    # unchanged by this repair and this assertion passes against the old code
    # too. It is here to record WHY the accumulator was removed from the verdict
    # path, so that a future reader who wants to put it back sees the number.
    assert fast[0]['path_length_m'] > 3 * slow[0]['path_length_m']


def test_an_unmeasurably_sparse_run_is_reported_and_not_judged():
    """D-34's own rule, applied to check 4: no verdict without a measurement."""
    # Long enough to qualify as a run, but only one sample lands after the
    # settle allowance, so there is no pair to measure an excursion between.
    samples = _idle_run([(0.0, 0.0), (0.4, 0.0), (1.0, 0.4)])
    problems, reports = probe.evaluate_idle_motion(samples)
    assert reports[0]['span_sec'] >= probe.MOTION_MIN_SPAN_SEC
    assert not problems, (
        'with only one sample after the settle allowance there is nothing to '
        'measure, and an instrument that cannot see must say so')
    assert 'not judged' in reports[0]['verdict']


def test_check_four_uses_the_rate_invariant_rule():
    """Anti-"wired but never called": the live check must call it."""
    calls = _calls_within(_node_named(ast.FunctionDef, 'evaluate_state_checks'))
    assert 'evaluate_idle_motion' in calls
    rule = _node_named(ast.FunctionDef, 'evaluate_idle_motion')
    rule_calls = _calls_within(rule)
    assert '_run_excursion' in rule_calls
    assert '_settled_tail' in rule_calls


def test_the_freeing_path_can_still_return_no_robot():
    """A gate that cannot decline is not a gate.

    ``pick_prospect_robot`` must still be able to answer "nothing to measure":
    no reachable candidate, or a cancel that was not accepted.
    """
    source = _node_named(ast.FunctionDef, 'pick_prospect_robot')
    returns_none = 0
    for child in ast.walk(source):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        if isinstance(child.value, ast.Tuple) and child.value.elts:
            first = child.value.elts[0]
            if isinstance(first, ast.Constant) and first.value is None:
                returns_none += 1
    assert returns_none >= 2, (
        'pick_prospect_robot has %d paths that decline to nominate a robot; it '
        'needs at least the unreachable-candidate and unaccepted-cancel ones'
        % (returns_none,))
