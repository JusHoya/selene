"""The adaptive survey planner must actually be consulted. FR-MAP-3.

WHY THIS EXISTS. AdaptiveSurveyPlanner shipped in Phase 4 with 8 green unit
tests and ZERO production call sites. `self._adaptive_survey` appeared exactly
once in orchestrator_node.py -- the assignment that created it. What actually
ran was htn_planner._generate_survey_waypoints(): a fixed hexagonal lattice of
10 points computed ONCE at mission decomposition, before a single sensor reading
existed. Nothing in the system could move a survey waypoint in response to data,
so SC-3 ("scouts visibly converge on ice deposit areas rather than uniformly
sampling") was unreachable by construction.

Unit tests on the planner could not catch that, because the planner was fine in
isolation. What was missing was the wiring. These tests check the wiring.
"""

import ast
import pathlib

import numpy as np
import pytest

from selene_orchestrator.adaptive_survey import (
    AdaptiveSurveyPlanner,
    COMMITTED_STATUSES,
    replan_pending_survey_targets,
    should_replan,
    zone_peak_mean,
)
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.task_queue import TaskQueue, TaskStatus

SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')


def _tree():
    return ast.parse(SOURCE.read_text(encoding='utf-8'))


# ------------------------------------------------------- the wiring itself

def test_adaptive_survey_planner_is_reachable_from_a_timer():
    """The planner must be consulted by something that actually runs.

    THIS IS THE TEST THAT FAILS ON THE PRE-FIX TREE. It is not about the
    planner's maths; it is about `self._adaptive_survey` having exactly one
    mention in the whole file -- the line that built it.
    """
    src = SOURCE.read_text(encoding='utf-8')
    mentions = src.count('self._adaptive_survey')
    assert mentions >= 2, (
        f'self._adaptive_survey appears {mentions} time(s) in '
        f'orchestrator_node.py. One mention means it is constructed and never '
        f'consulted, which is the state FR-MAP-3 was in for two phases.')

    # And the consultation must be reachable: a timer callback, not dead code.
    tree = _tree()
    timer_targets = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'create_timer'):
            for a in node.args:
                if isinstance(a, ast.Attribute):
                    timer_targets.add(a.attr)
    assert '_adaptive_survey_tick' in timer_targets, (
        f'no timer calls _adaptive_survey_tick; timers found: '
        f'{sorted(timer_targets)}')


def test_adaptive_survey_parameters_are_read():
    """Every adaptive_survey_* parameter declared must also be read.

    test_no_orphan_parameters.py enforces this globally; this names the group,
    so a failure says which requirement broke rather than reporting a count.
    """
    tree = _tree()
    declared, read = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        if not isinstance(name, str) or not name.startswith('adaptive_survey_'):
            continue
        if node.func.attr == 'declare_parameter':
            declared.add(name)
        elif node.func.attr == 'get_parameter':
            read.add(name)
    assert declared, 'no adaptive_survey_* parameters are declared'
    assert declared == read, (
        f'declared but never read: {sorted(declared - read)}')


def test_survey_zone_is_shared_with_the_htn_decomposition():
    """One definition of the zone, or the planner re-targets outside it."""
    src = SOURCE.read_text(encoding='utf-8')
    assert 'SURVEY_ZONE_CENTER' in src and 'SURVEY_ZONE_RADIUS' in src
    # The literal pair must not reappear where the constants belong.
    assert src.count('zone_center=(-100.0, -150.0)') == 0, (
        'the HTN decomposition still hardcodes the zone centre; it and the '
        'adaptive planner must share SURVEY_ZONE_CENTER or they can drift')


# ------------------------------------------------------------ the gate

def test_replan_waits_for_the_lattice_to_seed():
    """Adapting after one reading measured WORSE than not adapting at all."""
    assert not should_replan(completed_surveys=1, total_readings=50,
                             last_replan_readings=0, peak_mean=5.0,
                             seed_waypoints=2, min_signal_wt=1.0)
    assert should_replan(completed_surveys=2, total_readings=50,
                         last_replan_readings=0, peak_mean=5.0,
                         seed_waypoints=2, min_signal_wt=1.0)


def test_replan_requires_new_evidence():
    """Otherwise the timer recomputes an identical answer forever."""
    assert not should_replan(completed_surveys=5, total_readings=100,
                             last_replan_readings=100, peak_mean=5.0,
                             seed_waypoints=2, min_signal_wt=1.0)


def test_replan_requires_something_to_converge_on():
    """With no ice found the score degenerates to nearest-neighbour, which
    clusters the remaining budget beside the last scout -- worse than the
    lattice it would replace."""
    assert not should_replan(completed_surveys=5, total_readings=100,
                             last_replan_readings=0, peak_mean=0.4,
                             seed_waypoints=2, min_signal_wt=1.0)


# ------------------------------------------------- committed tasks are frozen

def _queue_with(states):
    q = TaskQueue()
    for i, st in enumerate(states):
        q.add_task(task_id=f't{i}', task_type='prospect',
                   target_x=float(i), target_y=0.0, priority=5.0,
                   required_capabilities=['prospect'])
        q.set_status(f't{i}', st)
    return q


def test_only_pending_targets_are_rewritten():
    """A target already announced or assigned must never move.

    The auction scores bids against the announced coordinates and the agent
    copies the assigned ones into its own state; nothing re-reads the queue. So
    rewriting a committed target desynchronises the orchestrator from where the
    robot is actually driving, silently.
    """
    rm = ResourceMap(width=140, height=140, resolution=1.0,
                     origin_x=-170.0, origin_y=-220.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    planner = AdaptiveSurveyPlanner(rm)
    q = _queue_with([TaskStatus.PENDING, TaskStatus.AUCTIONING,
                     TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS,
                     TaskStatus.COMPLETED])
    before = {t.task_id: (t.target_x, t.target_y) for t in q.get_all_tasks()}
    moves = replan_pending_survey_targets(planner, q, (-100.0, -150.0))
    after = {t.task_id: (t.target_x, t.target_y) for t in q.get_all_tasks()}
    moved = {tid for tid in before if before[tid] != after[tid]}
    assert moved <= {'t0'}, f'a committed task was rewritten: {moved}'
    assert all(m[0] == 't0' for m in moves)


def test_committed_statuses_covers_every_broadcast_state():
    for st in (TaskStatus.AUCTIONING, TaskStatus.ASSIGNED,
               TaskStatus.IN_PROGRESS):
        assert st in COMMITTED_STATUSES
    assert TaskStatus.PENDING not in COMMITTED_STATUSES
    assert TaskStatus.COMPLETED not in COMMITTED_STATUSES


def test_replan_never_changes_the_waypoint_budget():
    """Termination is structural: this cannot create or delete a task."""
    rm = ResourceMap(width=140, height=140, resolution=1.0,
                     origin_x=-170.0, origin_y=-220.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    planner = AdaptiveSurveyPlanner(rm)
    q = _queue_with([TaskStatus.PENDING] * 4)
    n_before = len(q.get_all_tasks())
    for _ in range(5):
        replan_pending_survey_targets(planner, q, (-100.0, -150.0))
    assert len(q.get_all_tasks()) == n_before


def test_pending_tasks_do_not_all_get_the_same_waypoint():
    """Each selection must reserve its waypoint, or the argmax repeats."""
    rm = ResourceMap(width=140, height=140, resolution=1.0,
                     origin_x=-170.0, origin_y=-220.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    planner = AdaptiveSurveyPlanner(rm)
    q = _queue_with([TaskStatus.PENDING] * 4)
    replan_pending_survey_targets(planner, q, (-100.0, -150.0))
    targets = [(t.target_x, t.target_y) for t in q.get_all_tasks()]
    assert len(set(targets)) == len(targets), f'duplicate targets: {targets}'


def test_non_survey_tasks_are_untouched():
    rm = ResourceMap(width=140, height=140, resolution=1.0,
                     origin_x=-170.0, origin_y=-220.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    q = TaskQueue()
    q.add_task(task_id='haul_1', task_type='haul', target_x=1.0, target_y=2.0,
               priority=5.0, required_capabilities=['haul'])
    replan_pending_survey_targets(AdaptiveSurveyPlanner(rm), q, (-100.0, -150.0))
    t = q.get_all_tasks()[0]
    assert (t.target_x, t.target_y) == (1.0, 2.0)


# ------------------------------------------------------- the planner can see

def test_signal_probe_reaches_observed_cells_at_production_spacing():
    """THE DEFECT THAT MADE WIRING ALONE INSUFFICIENT.

    min_spacing (8.0 m) exceeds ResourceMap's footprint_radius (5.0 m), so an
    admissible candidate is never within 8 m of a reading. Probing at the map
    resolution (1.0 m) sampled points 7-9 m away -- outside every footprint,
    always prior_mean. Both the signal AND variance terms were then constant and
    the score collapsed to pure nearest-neighbour.
    """
    rm = ResourceMap(width=140, height=140, resolution=1.0,
                     origin_x=-170.0, origin_y=-220.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    planner = AdaptiveSurveyPlanner(rm)          # production defaults
    # A candidate exactly min_spacing away, the closest one admissible.
    signal = planner._get_neighbor_signal(-72.0, -140.0)
    assert signal > 0.0, (
        'the signal term is zero at the closest admissible candidate; the '
        'planner cannot see ice and degenerates to nearest-neighbour')


def test_probe_radius_defaults_to_min_spacing():
    rm = ResourceMap(width=40, height=40, resolution=1.0,
                     origin_x=-20.0, origin_y=-20.0)
    assert AdaptiveSurveyPlanner(rm, min_spacing=8.0)._signal_probe_radius == 8.0
    assert AdaptiveSurveyPlanner(
        rm, min_spacing=8.0, signal_probe_radius=3.0)._signal_probe_radius == 3.0


def test_planner_prefers_the_deposit_over_a_nearer_empty_cell():
    """FR-MAP-3(c): cells adjacent to high readings are prioritised."""
    rm = ResourceMap(width=200, height=200, resolution=1.0,
                     origin_x=-200.0, origin_y=-250.0)
    rm.update(x=-80.0, y=-140.0, reading=8.0, sensor_uncertainty=0.5)
    planner = AdaptiveSurveyPlanner(rm, w_distance=0.05)
    # Reference sits far from the deposit, so nearest-neighbour would NOT pick it.
    chosen = planner.select_next_waypoint((-130.0, -170.0))
    assert chosen is not None
    d_deposit = np.hypot(chosen[0] + 80.0, chosen[1] + 140.0)
    d_ref = np.hypot(chosen[0] + 130.0, chosen[1] + 170.0)
    assert d_deposit < d_ref, (
        f'chose {chosen}: {d_deposit:.1f} m from the deposit but {d_ref:.1f} m '
        f'from the reference -- still behaving as nearest-neighbour')


# ---------------------------------------------------------------- zone peak

def test_zone_peak_mean_finds_the_deposit():
    rm = ResourceMap(width=200, height=200, resolution=1.0,
                     origin_x=-200.0, origin_y=-250.0)
    assert zone_peak_mean(rm, (-100.0, -150.0), 60.0) == pytest.approx(0.0)
    rm.update(x=-80.0, y=-140.0, reading=7.0, sensor_uncertainty=0.5)
    assert zone_peak_mean(rm, (-100.0, -150.0), 60.0) > 1.0


def test_zone_peak_mean_ignores_ice_outside_the_zone():
    rm = ResourceMap(width=400, height=400, resolution=1.0,
                     origin_x=-250.0, origin_y=-250.0)
    rm.update(x=100.0, y=100.0, reading=9.0, sensor_uncertainty=0.5)
    assert zone_peak_mean(rm, (-100.0, -150.0), 60.0) == pytest.approx(0.0)


# ------------------------------------------------------------------- SC-3

# The four deposits in selene_sim/config/ice_deposits.yaml, and the ground-truth
# formula neutron_spectrometer_node._compute_concentration uses. Duplicated here
# rather than imported because selene_sim is a different package and this test
# must run in the no-ROS lane; if the yaml changes, this constant is what tells
# you the SC-3 evidence needs re-measuring.
_DEPOSITS = [(-80.0, -140.0, 25.0, 8.0, 12.0), (-110.0, -170.0, 15.0, 4.0, 8.0),
             (-90.0, -130.0, 10.0, 2.5, 5.0), (-120.0, -155.0, 20.0, 6.0, 10.0)]
_ZONE_C, _ZONE_R = (-100.0, -150.0), 60.0


def _truth(x, y):
    total = 0.0
    for cx, cy, radius, peak, sigma in _DEPOSITS:
        d = np.hypot(x - cx, y - cy)
        if d <= radius:
            total += peak * np.exp(-(d * d) / (2 * sigma * sigma))
    return float(total)


def _survey(adaptive, seed_waypoints=2, min_signal=1.0):
    """Drive a full survey; return the ground truth at each visited waypoint."""
    from selene_orchestrator.htn_planner import _generate_survey_waypoints
    rm = ResourceMap()
    q = TaskQueue()
    for i, (x, y) in enumerate(_generate_survey_waypoints(_ZONE_C, _ZONE_R)):
        q.add_task(task_id='survey_%02d' % i, task_type='prospect',
                   target_x=float(x), target_y=float(y), priority=5.0,
                   required_capabilities=['prospect'])
    planner = AdaptiveSurveyPlanner(rm, psr_center=_ZONE_C, psr_radius=_ZONE_R)
    last, visited = 0, []
    for _ in range(len(q.get_all_tasks())):
        if adaptive:
            completed = sum(1 for t in q.get_all_tasks()
                            if t.status == TaskStatus.COMPLETED)
            peak = zone_peak_mean(rm, _ZONE_C, _ZONE_R)
            total = rm.get_total_readings()
            if should_replan(completed, total, last, peak,
                             seed_waypoints, min_signal):
                last = total
                replan_pending_survey_targets(
                    planner, q, visited[-1] if visited else _ZONE_C)
        nxt = next((t for t in q.get_all_tasks()
                    if t.status == TaskStatus.PENDING), None)
        if nxt is None:
            break
        x, y = nxt.target_x, nxt.target_y
        rm.update(x=x, y=y, reading=_truth(x, y), sensor_uncertainty=0.5)
        q.set_status(nxt.task_id, TaskStatus.COMPLETED)
        visited.append((x, y))
    return [_truth(x, y) for x, y in visited]


def test_sc3_adaptive_survey_converges_on_the_deposits():
    """SC-3: "scouts visibly converge on ice deposit areas rather than
    uniformly sampling the entire terrain".

    Deterministic: the lattice, the planner and the ground-truth field are all
    deterministic, so these numbers are reproducible rather than sampled.

    MEASURED at the shipped defaults, ten waypoints over the real deposit field:
        static    first half 2.21 -> second half 3.40 wt%,  60% of the second
                  half on >= 4 wt%
        adaptive  first half 3.86 -> second half 5.34 wt%,  80%
    i.e. 1.57x the second-half mean. The thresholds below sit well clear of
    those figures so ordinary drift does not fail the build, but a regression
    to nearest-neighbour behaviour (which is what the unwired planner did) puts
    adaptive back at parity with static and trips it.
    """
    static = _survey(adaptive=False)
    adaptive = _survey(adaptive=True)
    assert len(static) == len(adaptive) > 4

    half = len(static) // 2
    s_second = sum(static[half:]) / len(static[half:])
    a_second = sum(adaptive[half:]) / len(adaptive[half:])
    assert a_second > s_second * 1.2, (
        f'adaptive second-half mean {a_second:.2f} wt% vs static '
        f'{s_second:.2f} - the survey is not converging on the ice')

    # And it should improve as evidence accumulates, not merely start lucky.
    a_first = sum(adaptive[:half]) / len(adaptive[:half])
    assert a_second > a_first, (
        f'adaptive got worse over time ({a_first:.2f} -> {a_second:.2f} wt%)')


def test_sc3_needs_the_signal_probe_fix_not_just_the_wiring():
    """Wiring the planner up without fixing its blind probe is not enough.

    signal_probe_radius below (min_spacing - footprint_radius) puts every probe
    outside every observation footprint, the signal term is identically zero,
    and the planner degenerates to nearest-neighbour however well it is wired.
    This reproduces that by forcing the old 1.0 m probe radius.
    """
    from selene_orchestrator.htn_planner import _generate_survey_waypoints
    rm = ResourceMap()
    for x, y in list(_generate_survey_waypoints(_ZONE_C, _ZONE_R))[:3]:
        rm.update(x=float(x), y=float(y), reading=_truth(float(x), float(y)),
                  sensor_uncertainty=0.5)
    visited = [(float(x), float(y)) for x, y in
               list(_generate_survey_waypoints(_ZONE_C, _ZONE_R))[:3]]
    blind = AdaptiveSurveyPlanner(rm, psr_center=_ZONE_C, psr_radius=_ZONE_R,
                                  signal_probe_radius=1.0)
    seeing = AdaptiveSurveyPlanner(rm, psr_center=_ZONE_C, psr_radius=_ZONE_R)

    # ADMISSIBLE candidates only: at least min_spacing (8 m) from every visited
    # waypoint, which is exactly the set select_next_waypoint may choose from.
    # That constraint is the whole point — a candidate closer than min_spacing
    # is never a candidate, so the fact that a 1 m probe could see ice there is
    # irrelevant.
    spacing = 8.0
    admissible = []
    for gx in range(-140, -59, 5):
        for gy in range(-190, -109, 5):
            c = (float(gx), float(gy))
            if np.hypot(c[0] - _ZONE_C[0], c[1] - _ZONE_C[1]) > _ZONE_R:
                continue
            if all(np.hypot(c[0] - v[0], c[1] - v[1]) >= spacing for v in visited):
                admissible.append(c)
    assert len(admissible) > 50, 'not enough admissible candidates to conclude'

    assert max(blind._get_neighbor_signal(*c) for c in admissible) == \
        pytest.approx(0.0, abs=1e-9), (
        'the 1.0 m probe found signal at an admissible candidate; it should be '
        'blind, because no admissible candidate is within footprint_radius '
        '(5 m) of any reading')
    assert max(seeing._get_neighbor_signal(*c) for c in admissible) > 0.0, \
        'the fixed probe must reach observed cells from an admissible candidate'
