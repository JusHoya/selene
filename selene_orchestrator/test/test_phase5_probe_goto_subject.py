"""Check 11's SUBJECT selection, without ROS — deviation D-42.

WHY THIS FILE EXISTS
--------------------
On 2026-08-01 the Phase 5 exit gate ran 10 passed / 1 failed / 0 skipped, and the
one failure was check 11. It had commanded ``scout_02`` — a robot that was
reporting **0.0% battery** and was **already in RETURNING** under the
energy-critical rule. The FSM accepted ``OPERATOR_GOTO``, the energy rule fired
**six milliseconds later**, the planned path ended 0.71 m from the recharge pad
and 4.54 m from the commanded target, and the check reported that as a
``send_to_location`` failure.

Neither the override path nor the FSM did anything wrong. Both transitions are
correct, in the right order, on the inputs they were given. What was wrong was
the gate's choice of subject, and the evidence it needed was **in its own
recording at the moment it chose**: ``_make_state_cb`` captures ``battery_level``
for every sample, and it had exactly ONE reader in the whole probe — a
``0.0 <= x <= 1.0`` range assertion in check 4, which ``0.0`` satisfies. So
check 4 PASSED on a robot reporting zero charge and said nothing.

That is this repository's "wired but never called" pattern — the seventh
instance, and the first one inside the measuring apparatus rather than the
system under test.

WHAT IS ASSERTED HERE, and what each test would catch:

1. the fitness predicate refuses a flat battery, and refuses it against the
   AGENT'S OWN threshold rather than a literal in the gate;
2. it refuses a robot already under a rule that outranks an operator goto —
   the RETURNING case, which is the one that actually happened;
3. selection is FIRST FIT in fleet order, so two runs of one commit choose the
   same robot whenever the fleet is in the same state;
4. an unfit fleet FAILS rather than SKIPs, because "no robot could accept an
   override" is a statement about the system;
5. …with exactly one exception: a probe that can see NO state at all is a blind
   instrument and says so, which is the D-34 rule;
6. the 2026-08-01 fleet, replayed from the register's own numbers, now picks a
   different robot than the one that failed.

None of it needs a robot, and none of it needs ROS.
"""

import importlib.util
import os
import sys

import pytest


def _load_probe():
    """Import scripts/phase5_probe.py by path; it is a script, not a package."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    path = os.path.join(root, 'scripts', 'phase5_probe.py')
    spec = importlib.util.spec_from_file_location('phase5_probe_goto', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

FLEET = ['scout_01', 'scout_02', 'excavator_01', 'hauler_01']


def sample(fsm_state='IDLE', battery=0.9, pose_valid=True):
    return {'fsm_state': fsm_state, 'battery_level': battery,
            'pose_valid': pose_valid, 'theta': 0.0}


def thresholds(value=0.15):
    return {rid: value for rid in FLEET}


# ---------------------------------------------------------------------------
# 1 & 2 — the fitness predicate
# ---------------------------------------------------------------------------

def test_a_healthy_idle_robot_is_fit():
    ok, reason = probe.goto_subject_fitness(sample(), 0.15)
    assert ok is True
    assert reason == ''


def test_a_flat_battery_is_refused_and_the_reason_names_the_numbers():
    """The 2026-08-01 subject: 0.0% charge."""
    ok, reason = probe.goto_subject_fitness(sample(battery=0.0), 0.15)
    assert ok is False
    assert 'battery_level 0.0%' in reason
    assert 'energy_critical_threshold' in reason
    # The floor is the agent's threshold PLUS the margin, and the message says
    # both so a reader can tell which number moved.
    assert '20.0%' in reason


def test_the_floor_is_the_agents_threshold_not_a_literal():
    """A fleet configured with a different critical threshold moves the floor.

    This is the D-12 rule: the gate must not assert its own assumptions about a
    value the running system owns. A robot at 30% is fit against a 15% threshold
    and unfit against a 40% one, and nothing in the probe decides which.
    """
    at_30 = sample(battery=0.30)
    assert probe.goto_subject_fitness(at_30, 0.15)[0] is True
    assert probe.goto_subject_fitness(at_30, 0.40)[0] is False


def test_the_margin_is_applied_above_the_threshold_not_at_it():
    """A robot exactly AT the critical threshold is refused, not accepted.

    The manoeuvre itself costs charge — up to ~1.6 percentage points at the
    longest window the probe generates — so a subject sitting on the threshold
    would cross it mid-check and produce the 2026-08-01 failure again with a
    smaller number in the log.
    """
    assert probe.goto_subject_fitness(sample(battery=0.15), 0.15)[0] is False
    assert probe.goto_subject_fitness(sample(battery=0.20), 0.15)[0] is False
    assert probe.goto_subject_fitness(sample(battery=0.2001), 0.15)[0] is True


@pytest.mark.parametrize('state', ['RETURNING', 'RECHARGING', 'OFFLINE', 'ERROR'])
def test_states_under_an_outranking_rule_are_refused(state):
    """RETURNING is the one that actually happened on 2026-08-01."""
    ok, reason = probe.goto_subject_fitness(sample(fsm_state=state), 0.15)
    assert ok is False
    assert state in reason


@pytest.mark.parametrize('state', ['IDLE', 'NAVIGATING', 'WORKING', 'ASSIGNED',
                                   'BIDDING'])
def test_ordinary_working_states_are_still_fit(state):
    """The fix must not narrow the check to idle robots only.

    PRD row 5 names no robot and no state. A gate that only ever commanded IDLE
    robots would be measuring less than the row asks for — an override that
    interrupts real work is the interesting case.
    """
    assert probe.goto_subject_fitness(sample(fsm_state=state), 0.15)[0] is True


def test_an_invalid_pose_is_refused_and_cites_d31():
    ok, reason = probe.goto_subject_fitness(sample(pose_valid=False), 0.15)
    assert ok is False
    assert 'D-31' in reason


def test_a_robot_with_no_state_at_all_is_refused_with_the_shared_constant():
    ok, reason = probe.goto_subject_fitness(None, 0.15)
    assert ok is False
    # The literal must match what goto_no_subject_verdict tests against, or a
    # system failure silently becomes a skipped measurement.
    assert reason == probe.GOTO_NO_STATE_REASON


# ---------------------------------------------------------------------------
# 3 — selection order
# ---------------------------------------------------------------------------

def test_first_fit_in_fleet_order_wins():
    states = {rid: sample() for rid in FLEET}
    chosen, rejections = probe.select_goto_robot(FLEET, states, thresholds())
    assert chosen == 'scout_01'
    assert rejections == []


def test_the_reserved_robot_is_skipped_and_recorded():
    states = {rid: sample() for rid in FLEET}
    chosen, rejections = probe.select_goto_robot(
        FLEET, states, thresholds(), exclude=('scout_01',))
    assert chosen == 'scout_02'
    assert rejections == [('scout_01', probe.GOTO_RESERVED_REASON)]


def test_selection_is_not_ranked_by_charge():
    """A fuller robot later in the fleet does NOT displace a fit earlier one.

    Ranking would make the subject depend on a quantity that moves between runs,
    and two runs of one commit would stop being comparable — the property D-10
    needs from this gate above every other.
    """
    states = {rid: sample(battery=0.5) for rid in FLEET}
    states['hauler_01'] = sample(battery=1.0)
    chosen, _ = probe.select_goto_robot(FLEET, states, thresholds())
    assert chosen == 'scout_01'


def test_robots_after_the_winner_are_not_examined():
    states = {rid: sample() for rid in FLEET}
    states['hauler_01'] = None
    _chosen, rejections = probe.select_goto_robot(FLEET, states, thresholds())
    assert [rid for rid, _ in rejections] == []


def test_every_robot_passed_over_is_reported_with_a_reason():
    states = {
        'scout_01': sample(battery=0.0),
        'scout_02': sample(fsm_state='RETURNING'),
        'excavator_01': None,
        'hauler_01': sample(),
    }
    chosen, rejections = probe.select_goto_robot(FLEET, states, thresholds())
    assert chosen == 'hauler_01'
    assert [rid for rid, _ in rejections] == ['scout_01', 'scout_02',
                                              'excavator_01']
    assert all(reason for _rid, reason in rejections)


# ---------------------------------------------------------------------------
# 4 & 5 — the verdict when nothing is fit
# ---------------------------------------------------------------------------

def test_an_unfit_fleet_fails_it_does_not_skip():
    """FAIL, exit 1, and the row points at the system rather than at the probe."""
    rejections = [('scout_01', 'battery_level 0.0% at or below the 20.0% floor'),
                  ('scout_02', 'fsm_state RETURNING -- already under a rule')]
    verdict, detail = probe.goto_no_subject_verdict(rejections)
    assert verdict == probe.FAIL
    assert 'NO ROBOT WAS IN A STATE TO ACCEPT THE OVERRIDE' in detail
    assert 'D-42' in detail
    assert 'scout_01' in detail and 'scout_02' in detail


def test_a_blind_probe_skips_because_that_is_an_instrument_failure():
    """Every candidate silent -> SKIP, and the row says check 4 owns that verdict.

    The D-34 rule: an instrument that cannot see must say so rather than render
    a verdict on the system.
    """
    rejections = [('scout_01', probe.GOTO_NO_STATE_REASON),
                  ('scout_02', probe.GOTO_NO_STATE_REASON)]
    verdict, detail = probe.goto_no_subject_verdict(rejections)
    assert verdict == probe.SKIP
    assert 'check 4' in detail


def test_one_silent_robot_among_unfit_ones_still_fails():
    """A mixed fleet is a fleet failure, not a blind instrument."""
    rejections = [('scout_01', probe.GOTO_NO_STATE_REASON),
                  ('scout_02', 'battery_level 0.0% at or below the 20.0% floor')]
    verdict, _ = probe.goto_no_subject_verdict(rejections)
    assert verdict == probe.FAIL


def test_only_the_reserved_robot_means_a_one_robot_fleet_and_skips():
    verdict, detail = probe.goto_no_subject_verdict(
        [('scout_01', probe.GOTO_RESERVED_REASON)])
    assert verdict == probe.SKIP
    assert 'check 7' in detail


# ---------------------------------------------------------------------------
# 6 — the 2026-08-01 fleet, replayed
# ---------------------------------------------------------------------------

def test_the_2026_08_01_fleet_would_now_choose_a_different_subject():
    """Replay of the run that failed, from the register's own numbers.

    Fleet 2/1/1. scout_01 was reserved by check 7. scout_02 was reporting 0.0%
    and was in RETURNING under the energy-critical rule. The remaining two were
    healthy. The old positional rule took eligible[1] = scout_02 and measured
    the energy rule; this one takes excavator_01 and measures the override.
    """
    states = {
        'scout_01': sample(fsm_state='RECHARGING', battery=0.62),
        'scout_02': sample(fsm_state='RETURNING', battery=0.0),
        'excavator_01': sample(fsm_state='IDLE', battery=0.97),
        'hauler_01': sample(fsm_state='IDLE', battery=0.99),
    }
    chosen, rejections = probe.select_goto_robot(
        FLEET, states, thresholds(), exclude=('scout_01',))

    assert chosen == 'excavator_01'
    assert chosen != 'scout_02', 'the robot whose 0.0% took the gate down'
    reasons = dict(rejections)
    assert 'RETURNING' in reasons['scout_02']
    # scout_02 is rejected on the FIRST failing criterion it meets, which is its
    # state; the battery is the deeper fault and D-42 owns it.
    assert reasons['scout_01'] == probe.GOTO_RESERVED_REASON


def test_a_fleet_that_is_entirely_flat_fails_with_every_battery_named():
    """The other half of the same run: if D-42 had hit all four robots.

    The gate must then say the fleet could not accept an override, rather than
    command one of them and report the consequence as an override defect.
    """
    states = {rid: sample(fsm_state='IDLE', battery=0.0) for rid in FLEET}
    chosen, rejections = probe.select_goto_robot(FLEET, states, thresholds())
    assert chosen is None
    verdict, detail = probe.goto_no_subject_verdict(rejections)
    assert verdict == probe.FAIL
    for rid in FLEET:
        assert rid in detail
