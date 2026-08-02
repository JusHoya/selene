"""The gate probe's EMERGENCY injection and its preemption clause, without ROS.

WHY THIS FILE EXISTS
--------------------
On 2026-08-01 the Phase 5 exit gate went 9 passed / 1 failed / 1 skipped and the
one failure was check 6: an operator-injected priority-10.0 task was announced in
about 3 s and then lost the auction, because the orchestrator runs ONE auction at
a time and the gate's own ``cancel_task`` frees a robot into an auction that is
already in flight. The decision taken in response is a change to auction
SEMANTICS, not a defect fix: an injection tagged ``emergency`` may abort an
auction already in flight; a non-emergency priority-10 injection keeps exactly
the old wait-your-turn behaviour.

That decision reaches this gate as a change of STIMULUS, and a change of stimulus
is the most dangerous kind of change a measuring instrument can absorb quietly.
Two failures are being guarded against here, and they are the reason every one of
these tests exists:

1. **The gate reports a semantics change it did not make.** The injection goes
   out over one of two transports — the rosbridge ``call_service`` path when
   tornado is present, the rclpy service client when it is not — and if only one
   of them carried ``emergency=True`` then half the runs of this gate would
   measure emergency preemption, half would measure wait-your-turn, and both
   would print the same sentence. So the flag is decided ONCE, off the generated
   type, and the same answer builds both requests.

2. **The gate certifies a preemption it did not observe.** Spec item 15 makes the
   corroboration CONDITIONAL: only when another task was provably under auction
   at the injection does check 6 additionally require that task to be seen
   leaving AUCTIONING with ``status_reason 'auction_preempted'``. A conditional
   assertion has a silent-pass failure mode that an unconditional one does not —
   a precondition that never holds is an assertion that never runs — so the
   not-applicable branch must REPORT ITSELF, and these tests pin that it does.

The third property, and the one worth stating on its own: **the clause can FAIL
check 6 and can never PASS it.** Check 6 is PRD row 4, "Operator-injected task
enters auction and gets assigned"; the row is passed by correlating the injected
``task_id`` through announcement and assignment with its target matched to 1e-3,
or it is not passed at all. A corroboration that could pass the row on its own
would be a second, weaker definition of check 6 hiding inside the first.

WHAT IS ASSERTED HERE:

* the reason literal the probe compares against is the SAME STRING
  ``selene_orchestrator.task_feed`` writes (guarded with ``importorskip``, so the
  lanes that do not span both packages skip rather than fail — register D-36);
* the websocket-frame decoding, separately from the decisions taken on it;
* the precondition's proof obligation — that "it said AUCTIONING" is NOT enough,
  because a task seen auctioning 0.4 s before the injection may have resolved
  0.1 s before it;
* every not-applicable branch, each of which must name which observation was
  missing;
* the outcome branches, including the two that look like success and are not
  (the victim vanishing from the snapshot, and the victim leaving AUCTIONING
  under some other reason);
* the two report sentences themselves, built by the real ``run_injection`` and
  the real ``correlate_injection`` against stand-ins for ROS.

None of it needs a robot, a websocket, or ROS on the path.
"""

import importlib.util
import os
import sys
import threading

import pytest


def _load_probe():
    """Import scripts/phase5_probe.py by path; it is a script, not a package.

    Its module-level imports are stdlib only by design — that is what lets this
    lane exercise its pure halves on a box with no ROS — so this is a plain
    ``exec_module`` with no guard beyond the file existing.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    path = os.path.join(root, 'scripts', 'phase5_probe.py')
    if not os.path.exists(path):
        pytest.skip('scripts/phase5_probe.py is not in this checkout',
                    allow_module_level=True)
    spec = importlib.util.spec_from_file_location('phase5_probe_emergency',
                                                  path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

#: The injection instant every fixture below is written around. An absolute
#: epoch rather than 0.0, so that a sign error in one of the ``arrived -
#: inject_time`` differences cannot pass by arithmetic accident.
T0 = 1_800_000_000.0

#: The shipped ``auction_timeout_sec`` (orchestrator_params.yaml:44). Passed
#: explicitly everywhere below: the probe reads it off the live node and must
#: never assume it, and neither may these tests.
AUCTION_TIMEOUT = 5.0


def frame(arrived, tasks, topic=None):
    """One recorded websocket frame in ``RosbridgeClient.frames`` shape.

    *tasks* is ``{task_id: (status, status_reason)}``; the JSON shape rosbridge
    really delivers is built here so ``queue_snapshots`` is tested against the
    wire form rather than against its own output.
    """
    payload = {'tasks': [{'task_id': task_id,
                          'status': status,
                          'status_reason': reason}
                         for task_id, (status, reason) in tasks.items()]}
    return (arrived, topic or probe.TASK_QUEUE_TOPIC, payload, 512)


def snapshots(*pairs):
    """``queue_snapshots`` output built directly: ``(arrived, {id: (st, rsn)})``."""
    return [(float(arrived), dict(tasks)) for arrived, tasks in pairs]


AUCTIONING = probe.QUEUE_STATUS_AUCTIONING


# ---------------------------------------------------------------------------
# 0 — the literal that crosses the package boundary
# ---------------------------------------------------------------------------

def test_the_preempt_reason_matches_task_feeds_own_spelling():
    """A drift here is a permanent FAIL of check 6 naming the wrong system.

    The probe cannot import ``task_feed``: its module-level imports are stdlib
    only so that it loads on a box with no ROS, which is the property this whole
    lane depends on. So the literal is duplicated, and duplication across a
    package boundary needs a guard or it is just a bug waiting for a rename.

    ``importorskip`` rather than a bare import: the gate lane
    (``PYTHONPATH=selene_orchestrator;selene_isru``) has this package, but a lane
    that does not span it must SKIP rather than fail — register D-36, learned
    from ``test_terrain_guard.py`` taking the whole gate lane down with a bare
    cross-package import.
    """
    task_feed = pytest.importorskip('selene_orchestrator.task_feed')
    assert probe.AUCTION_PREEMPTED == task_feed.AUCTION_PREEMPTED


# ---------------------------------------------------------------------------
# 1 — decoding the recorded frames
# ---------------------------------------------------------------------------

def test_frames_decode_to_status_and_reason_per_task():
    out = probe.queue_snapshots([
        frame(T0, {'survey_03': (AUCTIONING, ''),
                   'manual_0000': ('PENDING', 'queued')}),
    ])
    assert out == [(T0, {'survey_03': (AUCTIONING, ''),
                         'manual_0000': ('PENDING', 'queued')})]


def test_frames_are_sorted_by_arrival_not_by_recording_order():
    """The clause slices on ``arrived <= inject_time``; order must be real."""
    out = probe.queue_snapshots([
        frame(T0 + 1.0, {'a': (AUCTIONING, '')}),
        frame(T0 - 1.0, {'a': ('PENDING', '')}),
    ])
    assert [arrived for arrived, _ in out] == [T0 - 1.0, T0 + 1.0]


def test_a_frame_whose_payload_is_not_a_dict_is_dropped_not_guessed_at():
    """rosbridge delivers JSON this probe did not build."""
    out = probe.queue_snapshots([
        (T0, probe.TASK_QUEUE_TOPIC, None, 0),
        (T0 + 0.5, probe.TASK_QUEUE_TOPIC, 'not a message', 0),
        frame(T0 + 1.0, {'a': (AUCTIONING, '')}),
    ])
    assert len(out) == 1


def test_a_task_entry_without_an_id_is_dropped():
    payload = {'tasks': [{'status': AUCTIONING}, {'task_id': '', 'status': 'X'},
                         {'task_id': 'a', 'status': AUCTIONING}]}
    out = probe.queue_snapshots([(T0, probe.TASK_QUEUE_TOPIC, payload, 1)])
    assert out == [(T0, {'a': (AUCTIONING, '')})]


def test_a_missing_status_reason_decodes_to_empty_rather_than_raising():
    """A TaskStatus older than ``status_reason`` must not crash the gate.

    It cannot corroborate anything either, and it does not: an empty reason is
    never equal to 'auction_preempted', so such a build fails the clause only if
    its precondition held — and a build that old has no emergency field on
    InjectTask.srv, so ``evaluate_preemption`` refuses the run before it gets
    here. Both halves are asserted separately below.
    """
    payload = {'tasks': [{'task_id': 'a', 'status': 'PENDING'}]}
    out = probe.queue_snapshots([(T0, probe.TASK_QUEUE_TOPIC, payload, 1)])
    assert out == [(T0, {'a': ('PENDING', '')})]


def test_tasks_is_absent_entirely():
    out = probe.queue_snapshots([(T0, probe.TASK_QUEUE_TOPIC, {}, 1)])
    assert out == [(T0, {})]


# ---------------------------------------------------------------------------
# 2 — the precondition: was an auction PROVABLY in flight?
# ---------------------------------------------------------------------------

def test_an_auction_opened_recently_enough_is_proved_in_flight():
    """The straightforward case, and the one the clause exists for.

    ``survey_03`` was not auctioning at T0-1.0 and was at T0-0.3, so its auction
    opened no earlier than T0-1.0; with a 5 s window it cannot resolve before
    about T0+3.75 even after the transport-latency allowance. It was in flight.
    """
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 1.0, {'survey_03': ('PENDING', '')}),
                  (T0 - 0.3, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim == 'survey_03'
    assert 'in flight' in note
    assert probe.TASK_QUEUE_TOPIC in note


def test_it_said_auctioning_is_not_enough_when_the_window_could_have_expired():
    """THE PROOF OBLIGATION. This is the false-FAIL this clause must not create.

    ``survey_03`` was already auctioning 8 s before the injection and its window
    is 5 s, so by T0 it may well have resolved on its own — in which case there
    was nothing left to preempt and demanding a preemption would fail a
    conforming orchestrator. NOT APPLICABLE, with the arithmetic named.
    """
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 9.0, {'survey_03': ('PENDING', '')}),
                  (T0 - 8.0, {'survey_03': (AUCTIONING, '')}),
                  (T0 - 0.3, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'could have expired' in note


def test_the_bound_is_taken_from_the_LATEST_not_auctioning_snapshot():
    """A task re-auctioned after a D-20 backoff has TWO auctioning runs.

    Bounding from the first one would date the current auction to the earlier
    run and declare a live auction expired. The task below auctioned at T0-20,
    fell back to PENDING under a D-20 backoff, and auctioned again at T0-0.4;
    only the second run is the one in flight, and taking the earliest
    not-auctioning frame instead of the latest returns None here.
    """
    victim, _note = probe.preemption_precondition(
        snapshots((T0 - 21.0, {'survey_03': ('PENDING', '')}),
                  (T0 - 20.0, {'survey_03': (AUCTIONING, '')}),
                  (T0 - 14.0, {'survey_03': ('PENDING', 'auction_no_bids')}),
                  (T0 - 0.9, {'survey_03': ('PENDING', 'auction_backoff')}),
                  (T0 - 0.4, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim == 'survey_03'


def test_an_auction_already_open_in_the_oldest_snapshot_cannot_be_bounded():
    """No observation of it opening means no bound on when it must resolve."""
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 2.0, {'survey_03': (AUCTIONING, '')}),
                  (T0 - 0.3, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'never observed' in note


def test_the_transport_latency_allowance_is_subtracted_and_it_matters():
    """The bound is taken off a websocket ARRIVAL, which lags the publish.

    Using arrival as-is would push the earliest possible resolution LATER and so
    bias the clause toward claiming "in flight" — the direction that
    manufactures failures. The case below sits inside that allowance: without
    subtracting MAX_TRANSPORT_LATENCY_SEC the auction looks live by 0.1 s past
    the orchestrator's next tick, and with it subtracted it does not.

    The window is written in terms of BOTH constants, so a change to either one
    is caught here rather than silently making the case stop isolating the
    allowance it is named for.
    """
    slack = probe.MAX_TRANSPORT_LATENCY_SEC
    assert slack > 0.1, 'this test is written around a non-trivial allowance'
    opened_after = (T0 + probe.ORCHESTRATOR_AUCTION_TICK_SEC
                    - AUCTION_TIMEOUT + 0.1)
    victim, note = probe.preemption_precondition(
        snapshots((opened_after, {'survey_03': ('PENDING', '')}),
                  (T0 - 0.2, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'could have expired' in note


def test_the_precondition_requires_the_auction_to_outlive_one_auction_tick():
    """A preemption can only happen on a tick, so "live at T0" is not enough.

    ``_auction_tick`` runs on a 0.5 s timer. An auction with 0.05 s of window
    left at the injection is correctly RESOLVED by the next tick and preempted
    by nothing — spec item 8 is "while an auction is active and NOT timed out".
    Before the tick margin existed this clause named that task as a victim and
    then reported PREEMPT_NOT_CORROBORATED, failing the one row the gate is
    trying to turn green for behaviour that is exactly as specified.

    The margin only ever moves a run from "victim named" to NOT APPLICABLE,
    which asserts LESS. It cannot turn a failure into a pass.
    """
    opened_after = T0 - AUCTION_TIMEOUT + probe.MAX_TRANSPORT_LATENCY_SEC + 0.05
    snaps = snapshots((opened_after, {'survey_03': ('PENDING', '')}),
                      (T0 - 0.2, {'survey_03': (AUCTIONING, '')}))
    victim, note = probe.preemption_precondition(
        snaps, T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None, note
    assert 'auction tick' in note

    # And the same recording with a full tick of extra window IS proven, so the
    # margin is a margin and not a blanket refusal.
    opened_later = opened_after + probe.ORCHESTRATOR_AUCTION_TICK_SEC + 0.01
    victim2, note2 = probe.preemption_precondition(
        snapshots((opened_later, {'survey_03': ('PENDING', '')}),
                  (T0 - 0.2, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim2 == 'survey_03', note2


def test_a_preemption_visible_before_the_injection_voids_the_clause():
    """MISATTRIBUTION, not missed detection, is the hazard this closes.

    ``_preempt_for_emergency`` added a SECOND exit from ``TaskAuction`` — its
    own ``reset()`` — so "the auction could not have resolved" no longer follows
    from the timeout arithmetic alone. If something OTHER than this injection is
    issuing emergencies at this orchestrator (a second operator, the dashboard,
    or the D-42 hazard of a whole second SELENE stack sharing the domain), a
    victim can already be carrying ``auction_preempted`` when this gate looks,
    and the clause would credit that preemption to its own request.
    """
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 3.0, {'survey_01': ('PENDING', probe.AUCTION_PREEMPTED),
                              'survey_03': ('PENDING', '')}),
                  (T0 - 0.3, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'ALREADY visible before this injection' in note
    assert 'D-42' in note


def test_the_prior_preemption_scan_looks_only_before_the_injection():
    """The consequence of THIS injection must not void THIS injection."""
    victim, _note = probe.preemption_precondition(
        snapshots((T0 - 1.0, {'survey_03': ('PENDING', '')}),
                  (T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
                  (T0 + 0.7, {'survey_03': ('PENDING',
                                            probe.AUCTION_PREEMPTED)})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim == 'survey_03'


def test_no_other_task_auctioning_is_not_applicable_and_says_so_plainly():
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 0.3, {'survey_03': ('ASSIGNED', ''),
                              'survey_04': ('PENDING', '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'no auction was in flight at injection' in note


def test_the_injected_task_auctioning_is_never_its_own_victim():
    """Preempting itself is not a thing, and would be a spectacular false pass."""
    victim, note = probe.preemption_precondition(
        snapshots((T0 - 1.0, {'manual_0000': ('PENDING', '')}),
                  (T0 - 0.3, {'manual_0000': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'no auction was in flight at injection' in note


def test_a_stale_snapshot_does_not_stand_in_for_the_injection_instant():
    stale = probe.PREEMPT_SNAPSHOT_STALENESS_SEC + 1.0
    victim, note = probe.preemption_precondition(
        snapshots((T0 - stale - 1.0, {'survey_03': ('PENDING', '')}),
                  (T0 - stale, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'past the' in note


def test_snapshots_arriving_only_after_the_injection_prove_nothing():
    victim, note = probe.preemption_precondition(
        snapshots((T0 + 0.3, {'survey_03': (AUCTIONING, '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT)
    assert victim is None
    assert 'at or before the injection' in note


def test_a_longer_live_auction_timeout_widens_what_counts_as_in_flight():
    """The window is the ORCHESTRATOR'S, read live, never a literal in the gate.

    Identical observations; only ``auction_timeout_sec`` differs. That is the
    D-12 rule — a gate that assumes a value the running system owns is measuring
    its own assumptions.
    """
    observed = snapshots((T0 - 9.0, {'survey_03': ('PENDING', '')}),
                         (T0 - 8.0, {'survey_03': (AUCTIONING, '')}),
                         (T0 - 0.3, {'survey_03': (AUCTIONING, '')}))
    assert probe.preemption_precondition(observed, T0, 'm', 5.0)[0] is None
    assert probe.preemption_precondition(observed, T0, 'm', 30.0)[0] == \
        'survey_03'


# ---------------------------------------------------------------------------
# 3 — the outcome: did the victim leave AUCTIONING, and carrying what?
# ---------------------------------------------------------------------------

def test_leaving_auctioning_with_the_preempt_reason_corroborates():
    status, note = probe.preemption_outcome(
        snapshots((T0 + 0.2, {'survey_03': (AUCTIONING, '')}),
                  (T0 + 0.7, {'survey_03': ('PENDING',
                                            probe.AUCTION_PREEMPTED)})),
        'survey_03', T0)
    assert status == probe.PREEMPT_CORROBORATED
    assert '0.70s after the injection' in note
    assert probe.AUCTION_PREEMPTED in note


def test_leaving_auctioning_under_any_other_reason_does_not_corroborate():
    """The auction resolved normally; the emergency did not abort it."""
    status, note = probe.preemption_outcome(
        snapshots((T0 + 0.2, {'survey_03': (AUCTIONING, '')}),
                  (T0 + 0.7, {'survey_03': ('ASSIGNED', 'auction_won')})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED
    assert 'auction_won' in note
    assert probe.AUCTION_PREEMPTED in note


def test_the_status_reason_is_read_off_the_FIRST_departure_not_a_later_one():
    """A task re-auctioned later carries a fresh reason; only the first counts.

    Reading the last snapshot instead would let an unrelated later preemption of
    the same task corroborate an abort that never happened.
    """
    status, _note = probe.preemption_outcome(
        snapshots((T0 + 0.5, {'survey_03': ('ASSIGNED', 'auction_won')}),
                  (T0 + 9.0, {'survey_03': ('PENDING',
                                            probe.AUCTION_PREEMPTED)})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED


def test_a_victim_that_vanishes_from_the_snapshot_is_not_corroboration():
    """It LOOKS like the auction ended. Nothing says why, so nothing is claimed."""
    status, note = probe.preemption_outcome(
        snapshots((T0 + 0.2, {'survey_03': (AUCTIONING, '')}),
                  (T0 + 0.7, {'survey_04': ('PENDING', '')})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED
    assert 'vanished' in note


def test_a_victim_still_auctioning_throughout_is_not_corroborated():
    status, note = probe.preemption_outcome(
        snapshots((T0 + 0.2, {'survey_03': (AUCTIONING, '')}),
                  (T0 + 4.0, {'survey_03': (AUCTIONING, '')})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED
    assert 'still %s' % (AUCTIONING,) in note


def test_no_snapshot_after_the_injection_is_not_corroborated_either():
    """Not applicable is decided by the PRECONDITION, never by the outcome.

    By the time this function is reached an auction was provably in flight, so
    "we saw nothing afterwards" is a gate that lost its instrument mid-
    measurement, not a fleet that had no auction to abort.
    """
    status, note = probe.preemption_outcome(
        snapshots((T0 - 0.3, {'survey_03': (AUCTIONING, '')})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED
    assert 'no %s snapshot arrived after it' % (probe.TASK_QUEUE_TOPIC,) in note


def test_a_pre_injection_departure_cannot_corroborate_a_later_preemption():
    """Only frames strictly after the injection are read for the consequence."""
    status, _note = probe.preemption_outcome(
        snapshots((T0 - 2.0, {'survey_03': ('PENDING',
                                            probe.AUCTION_PREEMPTED)}),
                  (T0 + 0.5, {'survey_03': (AUCTIONING, '')})),
        'survey_03', T0)
    assert status == probe.PREEMPT_NOT_CORROBORATED


# ---------------------------------------------------------------------------
# 4 — the combiner, and every branch that must report itself
# ---------------------------------------------------------------------------

def _in_flight_then(after):
    return snapshots((T0 - 1.0, {'survey_03': ('PENDING', '')}),
                     (T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
                     (T0 + 0.7, {'survey_03': after}))


def test_the_happy_path_end_to_end():
    status, note = probe.evaluate_preemption(
        _in_flight_then(('PENDING', probe.AUCTION_PREEMPTED)),
        T0, 'manual_0000', AUCTION_TIMEOUT, True, '')
    assert status == probe.PREEMPT_CORROBORATED
    # BOTH halves are reported: what was proved in flight, and what happened to
    # it. A corroboration that states only its conclusion is not evidence.
    assert 'in flight' in note
    assert probe.AUCTION_PREEMPTED in note


def test_the_failing_path_end_to_end():
    status, note = probe.evaluate_preemption(
        _in_flight_then(('ASSIGNED', 'auction_won')),
        T0, 'manual_0000', AUCTION_TIMEOUT, True, '')
    assert status == probe.PREEMPT_NOT_CORROBORATED
    assert 'auction_won' in note


def test_an_injection_that_did_not_carry_the_flag_asserts_nothing():
    """The pre-change orchestrator. It was never asked to preempt anything.

    This is the branch that lets this probe run against a workspace older than
    the emergency field without turning every such run into a red check 6.
    """
    status, note = probe.evaluate_preemption(
        _in_flight_then(('ASSIGNED', 'auction_won')),
        T0, 'manual_0000', AUCTION_TIMEOUT, False, '')
    assert status == probe.PREEMPT_NOT_APPLICABLE
    assert 'no preemption was requested' in note


def test_the_instrument_being_absent_is_reported_verbatim_and_asserts_nothing():
    """The caller owns the sentence; only it knows which half was missing."""
    reason = 'no rosbridge websocket was available on this run'
    status, note = probe.evaluate_preemption(
        _in_flight_then(('ASSIGNED', 'auction_won')),
        T0, 'manual_0000', AUCTION_TIMEOUT, True, reason)
    assert status == probe.PREEMPT_NOT_APPLICABLE
    assert note == reason


def test_an_empty_recording_asserts_nothing_and_names_the_topic():
    status, note = probe.evaluate_preemption(
        [], T0, 'manual_0000', AUCTION_TIMEOUT, True, '')
    assert status == probe.PREEMPT_NOT_APPLICABLE
    assert probe.TASK_QUEUE_TOPIC in note


def test_a_failed_precondition_carries_its_own_reason_out():
    status, note = probe.evaluate_preemption(
        snapshots((T0 - 0.3, {'survey_03': ('ASSIGNED', '')})),
        T0, 'manual_0000', AUCTION_TIMEOUT, True, '')
    assert status == probe.PREEMPT_NOT_APPLICABLE
    assert 'no auction was in flight at injection' in note


def test_the_clause_has_exactly_one_failing_value():
    """THE PROPERTY THE WHOLE DESIGN RESTS ON.

    Three outcomes, three distinct values, and ``correlate_injection`` turns
    exactly one of them into a problem. If NOT_APPLICABLE ever collided with
    CORROBORATED the not-applicable branch would start reading as evidence in
    ``--json-out``; if it ever collided with NOT_CORROBORATED a fleet with no
    auction in flight would fail the row.
    """
    values = {probe.PREEMPT_CORROBORATED, probe.PREEMPT_NOT_APPLICABLE,
              probe.PREEMPT_NOT_CORROBORATED}
    assert len(values) == 3


def test_the_not_applicable_sentence_says_it_asserts_nothing():
    """A conditional assertion whose precondition never holds is not a check.

    That is D-38's shape — a job that has never fired is not a check — and the
    only defence available to a report is that the row says so out loud.
    """
    sentence = probe.preemption_sentence(probe.PREEMPT_NOT_APPLICABLE, 'why')
    assert 'NOT APPLICABLE' in sentence
    assert 'nothing about preemption is asserted' in sentence
    assert 'why' in sentence


def test_the_two_decided_sentences_are_distinguishable_at_a_glance():
    corroborated = probe.preemption_sentence(probe.PREEMPT_CORROBORATED, 'x')
    missing = probe.preemption_sentence(probe.PREEMPT_NOT_CORROBORATED, 'x')
    assert corroborated.startswith('PREEMPTION CORROBORATED')
    assert missing.startswith('PREEMPTION NOT CORROBORATED')


# ---------------------------------------------------------------------------
# 5 — the stimulus: one decision, both transports
# ---------------------------------------------------------------------------

class FakeWebsocket:
    """Enough of ``RosbridgeClient`` for ``run_injection`` and check 6."""

    def __init__(self, available=True, reply=None, frames=()):
        self.available = available
        self._reply = reply
        self._frames = list(frames)
        self.calls = []

    def call_service(self, service, srv_type, args, timeout_sec):
        self.calls.append((service, srv_type, dict(args)))
        return self._reply

    def frames(self, topic=None):
        if topic is None:
            return list(self._frames)
        return [f for f in self._frames if f[1] == topic]


class FakeProbe:
    """Enough of ``ProbeNode`` for ``run_injection`` and ``correlate_injection``."""

    def __init__(self, emergency_field=True, announcements=(), assignments=(),
                 states=None):
        self.lock = threading.Lock()
        self.announcements = list(announcements)
        self.assignments = list(assignments)
        self._states = states or {}
        self._emergency_field = emergency_field
        self.injected = []

    def injection_carries_emergency(self):
        return self._emergency_field

    def inject_task(self, task_type, x, y, quantity=0.0, robot_id='',
                    emergency=False):
        self.injected.append({'task_type': task_type, 'x': x, 'y': y,
                              'emergency': emergency})
        # The real service response object, near enough: three attributes.
        return type('Response', (), {'success': True, 'task_id': 'manual_0000',
                                     'message': 'queued'})()

    def latest_state(self, rid):
        return self._states.get(rid)


def ws_reply(success=True, task_id='manual_0000', message='queued'):
    return {'result': True,
            'values': {'success': success, 'task_id': task_id,
                       'message': message}}


def test_the_websocket_request_carries_the_emergency_flag():
    results = probe.Results()
    fake_ws = FakeWebsocket(reply=ws_reply())
    task_id, _t, emergency = probe.run_injection(
        results, FakeProbe(), fake_ws, (-50.0, -100.0))
    assert task_id == 'manual_0000'
    assert emergency is True
    _service, _srv_type, args = fake_ws.calls[0]
    assert args['emergency'] is True


def test_the_rclpy_fallback_carries_the_same_flag():
    """The transport must not decide the semantics. This is the whole point."""
    results = probe.Results()
    fake_probe = FakeProbe()
    _task_id, _t, emergency = probe.run_injection(
        results, fake_probe, FakeWebsocket(available=False), (-50.0, -100.0))
    assert emergency is True
    assert fake_probe.injected[0]['emergency'] is True


def test_both_transports_are_driven_from_one_decision():
    """Same fake build, both paths, one answer — asserted side by side.

    Two independent spellings of this flag is how one run would measure
    emergency preemption and the next wait-your-turn, under one report sentence
    that could not be true of both.
    """
    over_ws = FakeWebsocket(reply=ws_reply())
    ws_probe = FakeProbe()
    probe.run_injection(probe.Results(), ws_probe, over_ws, (1.0, 2.0))
    direct = FakeProbe()
    probe.run_injection(probe.Results(), direct,
                        FakeWebsocket(available=False), (1.0, 2.0))
    assert over_ws.calls[0][2]['emergency'] == direct.injected[0]['emergency']


def test_a_build_without_the_field_omits_it_rather_than_sending_false():
    """rosbridge raises NonexistentFieldException on a field the .srv lacks.

    Sending ``emergency: False`` to an older workspace would fail check 5 — and
    with it checks 6 and 9 — on a build whose only sin is being older than this
    probe.
    """
    fake_ws = FakeWebsocket(reply=ws_reply())
    _task_id, _t, emergency = probe.run_injection(
        probe.Results(), FakeProbe(emergency_field=False), fake_ws,
        (-50.0, -100.0))
    assert emergency is False
    assert 'emergency' not in fake_ws.calls[0][2]


def test_an_old_build_reaches_the_rclpy_client_with_emergency_false():
    fake_probe = FakeProbe(emergency_field=False)
    probe.run_injection(probe.Results(), fake_probe,
                        FakeWebsocket(available=False), (0.0, 0.0))
    assert fake_probe.injected[0]['emergency'] is False


# ---------------------------------------------------------------------------
# 6 — the two report sentences, built by the real functions
# ---------------------------------------------------------------------------

def check_detail(results, number):
    return results.as_dict()[str(number)]['details']


def check_result(results, number):
    return results.as_dict()[str(number)]['result']


def test_check_5_says_it_is_an_emergency_injection_and_what_that_means():
    results = probe.Results()
    probe.run_injection(results, FakeProbe(),
                        FakeWebsocket(reply=ws_reply()), (-50.0, -100.0))
    detail = check_detail(results, 5)
    assert check_result(results, 5) == probe.PASS
    assert 'EMERGENCY INJECTION' in detail
    assert 'BOTH transports' in detail
    assert probe.EMERGENCY_SEMANTICS in detail
    assert probe.EMERGENCY_NOT_TESTED in detail
    # The transport is still named, which is what the generated footer quotes.
    assert 'rosbridge websocket' in detail


def test_check_5_says_so_when_the_build_could_not_carry_the_flag():
    results = probe.Results()
    probe.run_injection(results, FakeProbe(emergency_field=False),
                        FakeWebsocket(reply=ws_reply()), (0.0, 0.0))
    detail = check_detail(results, 5)
    assert 'NOT AN EMERGENCY INJECTION' in detail
    assert 'wait-your-turn' in detail


def test_check_5_carries_the_emergency_flag_into_json_out():
    """``--json-out`` is what the shell's footer reads; prose is not enough."""
    results = probe.Results()
    probe.run_injection(results, FakeProbe(),
                        FakeWebsocket(reply=ws_reply()), (0.0, 0.0))
    assert results.as_dict()['5']['measured']['emergency'] is True


def _correlated(ws, probe_stub=None, emergency=True, queue_available=True):
    """Run the real ``correlate_injection`` over a completed correlation.

    The announcement and the assignment are already in the recording, so the
    poll loop exits on its first pass and this costs one 0.2 s sleep.
    """
    results = probe.Results()
    stub = probe_stub or FakeProbe(
        announcements=[(T0 + 0.5, 'manual_0000', 'prospect', -50.0, -100.0, True)],
        assignments=[(T0 + 3.0, 'manual_0000', 'scout_01', -50.0, -100.0)],
        states={'scout_01': {'capabilities': ['prospect']}})
    probe.correlate_injection(results, stub, 'manual_0000', T0,
                              AUCTION_TIMEOUT, (-50.0, -100.0),
                              'the robot was already idle', chosen='scout_01',
                              ws=ws, emergency=emergency,
                              queue_topic_available=queue_available)
    return results


def test_check_6_states_the_emergency_semantics_and_what_it_does_not_test():
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 1.0, {'survey_03': ('PENDING', '')}),
        frame(T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
        frame(T0 + 0.7, {'survey_03': ('PENDING', probe.AUCTION_PREEMPTED)}),
    ]))
    detail = check_detail(results, 6)
    assert check_result(results, 6) == probe.PASS
    assert 'EMERGENCY INJECTION' in detail
    assert probe.EMERGENCY_SEMANTICS in detail
    assert probe.EMERGENCY_NOT_TESTED in detail
    assert 'PREEMPTION CORROBORATED' in detail


def test_check_6_fails_when_a_provable_in_flight_auction_was_not_aborted():
    """The clause CAN fail the row. Everything else about the row passed."""
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 1.0, {'survey_03': ('PENDING', '')}),
        frame(T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
        frame(T0 + 0.7, {'survey_03': ('ASSIGNED', 'auction_won')}),
    ]))
    assert check_result(results, 6) == probe.FAIL
    detail = check_detail(results, 6)
    assert 'PREEMPTION NOT CORROBORATED' in detail
    # Stated once, not twice: it is in the problem list, so the tail must not
    # repeat it.
    assert detail.count('PREEMPTION NOT CORROBORATED') == 1


def test_check_6_still_passes_with_no_auction_in_flight_and_reports_that():
    """The not-applicable branch must never pass SILENTLY."""
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 0.3, {'survey_03': ('ASSIGNED', '')}),
    ]))
    assert check_result(results, 6) == probe.PASS
    detail = check_detail(results, 6)
    assert 'NOT APPLICABLE' in detail
    assert 'no auction was in flight at injection' in detail


def test_check_6_asserts_the_announcement_carried_the_emergency_flag():
    """THE ANNOUNCEMENT HOP HAS A READER, AND THIS IS IT.

    ``TaskAnnouncement.emergency`` was the one field on this chain that was
    written by ``_publish_announcement`` and read by nothing — the repository's
    signature defect for the eighth time, and disclosed by a comment that named
    the exit-gate probe as a reader it did not have. It has one now: an
    injection made with emergency=True must produce an announcement carrying it,
    and a build that dropped ``msg.emergency`` fails check 6 rather than only a
    unit test.
    """
    stub = FakeProbe(
        announcements=[(T0 + 0.5, 'manual_0000', 'prospect', -50.0, -100.0,
                        False)],
        assignments=[(T0 + 3.0, 'manual_0000', 'scout_01', -50.0, -100.0)],
        states={'scout_01': {'capabilities': ['prospect']}})
    results = _correlated(FakeWebsocket(frames=[]), probe_stub=stub)
    assert check_result(results, 6) == probe.FAIL
    detail = check_detail(results, 6)
    assert 'did not survive' in detail
    assert results.as_dict()['6']['measured']['announced_emergency'] is False


def test_check_6_does_not_assert_the_flag_on_a_build_that_cannot_carry_it():
    """One-directional by construction.

    On a workspace whose ``InjectTask.srv`` predates the field the request is
    non-emergency, the announcement is non-emergency, and there is nothing to
    check — False == False would hold just as well on a build where
    ``_publish_announcement`` never sets the field at all, so asserting it there
    would be asserting nothing while looking like a check.
    """
    stub = FakeProbe(
        announcements=[(T0 + 0.5, 'manual_0000', 'prospect', -50.0, -100.0,
                        False)],
        assignments=[(T0 + 3.0, 'manual_0000', 'scout_01', -50.0, -100.0)],
        states={'scout_01': {'capabilities': ['prospect']}})
    results = _correlated(FakeWebsocket(frames=[]), probe_stub=stub,
                          emergency=False)
    assert check_result(results, 6) == probe.PASS


def test_check_6_tolerates_an_announcement_recorded_without_the_field():
    """A pre-D-44 recording is a 5-tuple. It must degrade, not IndexError."""
    stub = FakeProbe(
        announcements=[(T0 + 0.5, 'manual_0000', 'prospect', -50.0, -100.0)],
        assignments=[(T0 + 3.0, 'manual_0000', 'scout_01', -50.0, -100.0)],
        states={'scout_01': {'capabilities': ['prospect']}})
    results = _correlated(FakeWebsocket(frames=[]), probe_stub=stub,
                          emergency=False)
    assert check_result(results, 6) == probe.PASS


def test_check_6_never_passes_on_the_clause_alone():
    """Corroboration with a broken correlation is still a FAIL.

    The winner publishes no state, which is one of check 6's own problems. A
    corroborated preemption must not rescue it — the clause adds evidence, never
    a verdict.
    """
    stub = FakeProbe(
        announcements=[(T0 + 0.5, 'manual_0000', 'prospect', -50.0, -100.0, True)],
        assignments=[(T0 + 3.0, 'manual_0000', 'ghost_01', -50.0, -100.0)],
        states={})
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 1.0, {'survey_03': ('PENDING', '')}),
        frame(T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
        frame(T0 + 0.7, {'survey_03': ('PENDING', probe.AUCTION_PREEMPTED)}),
    ]), probe_stub=stub)
    assert check_result(results, 6) == probe.FAIL
    detail = check_detail(results, 6)
    assert 'publishes no state' in detail
    assert 'PREEMPTION CORROBORATED' in detail


def test_check_6_names_the_missing_websocket_rather_than_blaming_the_fleet():
    results = _correlated(FakeWebsocket(available=False))
    assert check_result(results, 6) == probe.PASS
    detail = check_detail(results, 6)
    assert 'NOT APPLICABLE' in detail
    assert 'ONLY over the rosbridge websocket' in detail


def test_check_6_names_a_build_without_taskqueuestate():
    results = _correlated(FakeWebsocket(frames=[]), queue_available=False)
    detail = check_detail(results, 6)
    assert 'NOT APPLICABLE' in detail
    assert 'no selene_msgs/msg/TaskQueueState' in detail


def test_check_6_reports_a_non_emergency_run_as_such():
    """A workspace older than the field. The row must not claim otherwise."""
    results = _correlated(FakeWebsocket(frames=[]), emergency=False)
    detail = check_detail(results, 6)
    assert 'WAS NOT AN EMERGENCY INJECTION' in detail
    assert probe.EMERGENCY_NOT_TESTED in detail


def test_check_6_records_the_clause_in_json_out_on_a_passing_run():
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 1.0, {'survey_03': ('PENDING', '')}),
        frame(T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
        frame(T0 + 0.7, {'survey_03': ('PENDING', probe.AUCTION_PREEMPTED)}),
    ]))
    measured = results.as_dict()['6']['measured']
    assert measured['emergency'] is True
    assert measured['preemption'] == probe.PREEMPT_CORROBORATED
    assert measured['task_queue_snapshots'] == 3
    assert 'preemption_note' in measured


def test_the_detail_lines_survive_the_pipe_delimited_stdout_protocol():
    """``Results.emit`` writes CHECK/<n>/<result>/<title>/<details>.

    A '|' anywhere in these long new sentences would split a report row in
    ``validate_phase5.sh``'s ``IFS='|' read``. ``_sanitise`` replaces them, and
    this asserts the sentences never need it — a mangled sentence is a mangled
    report either way.
    """
    for text in (probe.EMERGENCY_SEMANTICS, probe.EMERGENCY_NOT_TESTED):
        assert '|' not in text
        assert '\n' not in text
    results = _correlated(FakeWebsocket(frames=[
        frame(T0 - 1.0, {'survey_03': ('PENDING', '')}),
        frame(T0 - 0.3, {'survey_03': (AUCTIONING, '')}),
        frame(T0 + 0.7, {'survey_03': ('PENDING', probe.AUCTION_PREEMPTED)}),
    ]))
    assert '|' not in check_detail(results, 6)
    assert '\n' not in check_detail(results, 6)
