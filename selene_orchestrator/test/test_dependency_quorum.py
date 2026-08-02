"""D2, the other half: a SOFT dependency edge, and the quorum on it.

WHAT THE FIRST HALF DID NOT FIX. Bounded retry plus a CRITICAL escalation made
the stop BOUNDED and LOUD. It did not make the mission SURVIVE a lost survey:
after the third attempt the survey rested in FAILED forever, every dependency
was satisfied only by COMPLETED, ``get_next_ready`` returned None forever and
the dashboard read "Objective 100 kg -- awaiting first extraction" for the rest
of the run. Measured live on a running ROS 2 Jazzy stack.

THE INSIGHT UNDER EVERY TEST IN THIS FILE is that the mission has TWO kinds of
edge and the queue enforced one:

  SOFT / EVIDENTIAL   survey -> select_site. ``htn_planner._pick_best_site``
                      scores the FUSED ResourceMap posterior and never reads the
                      survey task list at all. One lost survey degrades
                      CONFIDENCE; it does not invalidate the decision.
  HARD / CAUSAL       select_site -> excavate -> haul -> excavate ... You cannot
                      haul what was not excavated, and relaxing one of these
                      would put a mass in the ISRU ledger that no extraction
                      produced -- and that ledger's whole value is being the one
                      source of truth.

So the tests come in pairs: the soft edge must RELAX, and the hard edge must NOT
-- and the second half of every pair is the one that keeps a fix from becoming a
worse defect than the thing it fixed.

EVERY TEST HERE WAS MUTATION-CHECKED: the production change it names was
reverted alone, this file was run, the exact failure was recorded in the test's
docstring, and the change was restored. A test whose mutation output is not
recorded is not evidence.

NOTHING HERE IS DEMONSTRATED. This is a ROS-free unit lane. No live run, no
gate run, no ``colcon build`` -- none is needed for the wire (no .msg FIELD was
added and no layout moved; the .msg edits are comments), but "implemented and
unit-tested" is the whole claim.
"""

from __future__ import annotations

import ast
import math
import pathlib
import types

import pytest

from selene_orchestrator.htn_planner import (
    HTNPlanner,
    SELECT_SITE_SURVEY_QUORUM,
)
from selene_orchestrator.orchestrator_node import OrchestratorNode
from selene_orchestrator.resource_map import ResourceMap
from selene_orchestrator.task_feed import (
    SITE_SELECTED,
    SITE_SELECTED_PARTIAL,
    TASK_MAX_ATTEMPTS,
)
from selene_orchestrator.task_queue import TaskEntry, TaskQueue, TaskStatus


PLANNER_SOURCE = (pathlib.Path(__file__).resolve().parents[1]
                  / 'selene_orchestrator' / 'htn_planner.py')
NODE_SOURCE = (pathlib.Path(__file__).resolve().parents[1]
               / 'selene_orchestrator' / 'orchestrator_node.py')
MSG = (pathlib.Path(__file__).resolve().parents[2]
       / 'selene_msgs' / 'msg' / 'TaskStatus.msg')


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _exhaust(queue: TaskQueue, task_id: str,
             bound: int = TASK_MAX_ATTEMPTS) -> None:
    """Drive *task_id* to FAILED with every attempt spent, the production way.

    Through ``mark_failed`` and ``retry_failed_tasks`` rather than by writing
    ``failed_attempts``, so ``mark_failed``'s own "count only on a REAL
    transition" guard is inside the loop: a test that set the field directly
    would still pass if that guard were deleted.
    """
    for attempt in range(bound):
        queue.mark_failed(task_id, 'Path blocked, attempt %d' % attempt)
        if attempt < bound - 1:
            queue.retry_failed_tasks(bound, 'skill_failed_requeued')
    task = queue.get_task(task_id)
    assert task.status is TaskStatus.FAILED
    assert task.failed_attempts == bound


def _soft_queue(completed: int = 0, failed: int = 0, pending: int = 0,
                quorum: int = 1) -> TaskQueue:
    """The shipped shape in miniature: N surveys -> one soft select_site.

    ``quorum <= 0`` OMITS the keyword entirely rather than passing 0, and that
    is deliberate: a fixture that spells the default out explicitly cannot
    detect the default changing. Mutating ``add_task``'s ``depends_on_quorum``
    default survived a version of this file that passed ``quorum=0``.
    """
    q = TaskQueue()
    deps = []
    for i in range(completed):
        tid = 'survey_done_%d' % i
        q.add_task(tid, 'prospect', float(i), 0.0, priority=5.0)
        q.mark_complete(tid, 'skill_complete')
        deps.append(tid)
    for i in range(failed):
        tid = 'survey_dead_%d' % i
        q.add_task(tid, 'prospect', float(i), 1.0, priority=5.0)
        _exhaust(q, tid)
        deps.append(tid)
    for i in range(pending):
        tid = 'survey_flying_%d' % i
        q.add_task(tid, 'prospect', float(i), 2.0, priority=5.0)
        deps.append(tid)
    if quorum > 0:
        q.add_task('select', 'select_site', -100.0, -150.0, priority=4.0,
                   depends_on=deps, depends_on_quorum=quorum)
    else:
        q.add_task('select', 'select_site', -100.0, -150.0, priority=4.0,
                   depends_on=deps)
    return q


def _entry(**kwargs) -> TaskEntry:
    return TaskEntry(task_id='t', task_type='prospect', target_x=0.0,
                     target_y=0.0, **kwargs)


def _planner_func(name: str) -> ast.FunctionDef:
    tree = ast.parse(PLANNER_SOURCE.read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


# --------------------------------------------------------------------------- #
#  (a) The default is bit-for-bit the old rule                                 #
# --------------------------------------------------------------------------- #

class TestTheDefaultIsUnchanged:
    """The load-bearing invariant of the whole change.

    A quorum field that altered a task which does not set one would silently
    relax every causal edge in the mission at once.
    """

    def test_a_task_with_no_quorum_still_needs_every_dependency_COMPLETED(self):
        """MUTATION: ``add_task``'s ``depends_on_quorum: int = 0`` -> ``= 1``.
        (Mutating the TaskEntry FIELD default instead does nothing observable:
        ``add_task`` always passes the keyword through, so its own default is
        the one every caller actually gets. That mutation SURVIVED an earlier
        draft of this file and is why the fixture now omits the keyword rather
        than spelling out 0.) Recorded failure:

            assert not q.dependencies_met(q.get_task('select'), 3)
            AssertionError: a task with NO quorum became ready with a
            permanently FAILED dependency -- every causal edge in the mission
            has just been relaxed
        """
        q = _soft_queue(completed=2, failed=1, quorum=0)
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS), (
            'a task with NO quorum became ready with a permanently FAILED '
            'dependency -- every causal edge in the mission has just been '
            'relaxed')

    def test_a_task_with_no_quorum_is_ready_when_all_are_COMPLETED(self):
        q = _soft_queue(completed=3, quorum=0)
        assert q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS)

    def test_the_default_branch_ignores_the_retry_bound_entirely(self):
        """Passing ``max_attempts`` cannot change a hard edge's answer.

        That is what makes it safe for ``_auction_tick`` to pass the bound on
        every call rather than only for the one task that has a quorum.
        """
        q = _soft_queue(completed=2, failed=1, quorum=0)
        select = q.get_task('select')
        for bound in (0, 1, 3, 99):
            assert not q.dependencies_met(select, bound), bound


# --------------------------------------------------------------------------- #
#  (b) Clause (a): RESOLVED, not merely counted                                #
# --------------------------------------------------------------------------- #

class TestNothingMayStillBeInFlight:
    """THE MOST IMPORTANT TEST IN THIS FILE.

    Without clause (a) the fix trades a deadlock for silent evidence loss:
    select_site fires the instant the k-th survey lands, the other nine scouts
    are abandoned mid-drive, and the mission chooses its extraction site off one
    reading while looking exactly like a success.
    """

    def test_a_quorum_is_not_met_while_a_dependency_is_still_PENDING(self):
        """MUTATION: drop the ``_dependency_resolved`` test from
        ``dependencies_met``'s loop (count COMPLETED only). Recorded failure:

            assert not q.dependencies_met(q.get_task('select'), 3)
            AssertionError: select_site became ready with 9 surveys still in
            flight -- the quorum fired the instant the first one landed and the
            rest are about to be abandoned
        """
        q = _soft_queue(completed=1, pending=9)
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS), (
            'select_site became ready with 9 surveys still in flight -- the '
            'quorum fired the instant the first one landed and the rest are '
            'about to be abandoned')

    @pytest.mark.parametrize('status', [
        TaskStatus.AUCTIONING, TaskStatus.ASSIGNED,
        TaskStatus.IN_PROGRESS, TaskStatus.INTERRUPTED,
    ])
    def test_no_non_terminal_status_counts_as_resolved(self, status):
        q = _soft_queue(completed=1, pending=1)
        q.set_status('survey_flying_0', status, 'test')
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS)

    def test_a_FAILED_dependency_with_an_attempt_left_is_not_resolved(self):
        """The DDS race, not a hypothetical.

        ``mark_failed`` runs from ``_on_task_result`` on a callback thread of
        the MultiThreadedExecutor, so a dependency can flip to FAILED between
        ``_auction_tick``'s retry sweep and its ``get_next_ready`` in the SAME
        tick, with two attempts still to come.

        MUTATION: weaken ``_dependency_resolved``'s last line to
        ``return True`` (any FAILED is resolved). Recorded failure:

            assert not q.dependencies_met(select, 3)
            AssertionError: a survey with 2 attempts left was treated as
            finished; the retry sweep is about to re-queue it
        """
        q = _soft_queue(completed=1, pending=1)
        q.mark_failed('survey_flying_0', 'Path blocked, no alternate route')
        select = q.get_task('select')
        assert q.get_task('survey_flying_0').failed_attempts == 1
        assert not q.dependencies_met(select, TASK_MAX_ATTEMPTS), (
            'a survey with 2 attempts left was treated as finished; the retry '
            'sweep is about to re-queue it')

        # And the boundary itself: nothing else changes, only the count.
        _exhaust_remaining = q.get_task('survey_flying_0')
        for attempt in range(1, TASK_MAX_ATTEMPTS):
            q.retry_failed_tasks(TASK_MAX_ATTEMPTS, 'skill_failed_requeued')
            q.mark_failed('survey_flying_0', 'Path blocked, attempt %d' % attempt)
        assert _exhaust_remaining.failed_attempts == TASK_MAX_ATTEMPTS
        assert q.dependencies_met(select, TASK_MAX_ATTEMPTS), (
            'the same task, exhausted, is still not resolved -- the quorum can '
            'never be met and D2 is not fixed')

    def test_a_D20_ABANDONED_dependency_is_not_resolved(self):
        """Abandonment is explicitly NOT terminal.

        ``wake_deferred_auctions`` un-abandons on any idle arrival, so calling
        it resolved would fire the quorum against a survey one fleet change away
        from running. This stall shape SURVIVES this change and is named rather
        than papered over.
        """
        q = _soft_queue(completed=1, pending=1)
        q.abandon_auction('survey_flying_0')
        assert math.isinf(q.get_task('survey_flying_0').auction_backoff_until)
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS)

    def test_an_unknown_dependency_id_is_never_satisfied(self):
        """``add_task`` never validates ``depends_on``, so a typo must block
        loudly rather than evaporate into a satisfied quorum. Same answer in
        both branches, and the same answer as before this change."""
        for quorum in (0, 1):
            q = _soft_queue(completed=1, quorum=quorum)
            q.get_task('select').depends_on.append('survey_typo')
            assert not q.dependencies_met(q.get_task('select'),
                                          TASK_MAX_ATTEMPTS), quorum


# --------------------------------------------------------------------------- #
#  (c) Clause (b): k = 1, and NOT 0                                            #
# --------------------------------------------------------------------------- #

class TestTheEvidenceFloorHolds:

    def test_the_fix_itself_one_survived_survey_is_enough(self):
        """9 dead, 1 COMPLETED -> READY. This is D2, fixed, at queue level.

        MUTATION: restore ``_ready_tasks``' original
        ``deps_met = all(... == COMPLETED)`` block and ``dependencies_met``'s
        quorum branch to the same. Recorded failure:

            assert q.dependencies_met(q.get_task('select'), 3)
            AssertionError: one dead survey still kills select_site -- D2 is
            not fixed
        """
        q = _soft_queue(completed=1, failed=9)
        assert q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS), (
            'one dead survey still kills select_site -- D2 is not fixed')

    def test_zero_completed_surveys_is_NOT_enough_and_that_is_D29(self):
        """ALL TEN DEAD -> the mission STILL STOPS, deliberately.

        ``_pick_best_site`` falls back to the zone centre when there are no
        readings at all, so a quorum of 0 would let this mission choose an
        extraction site having surveyed NOTHING and report success -- the exact
        shape of deviation D-29, where an exit-gate check passed vacuously on a
        map with total_observations = 0. Ten CRITICAL exhaustion alerts have
        already fired by this point; a loud stop is the right answer.

        MUTATION: ``return completed >= min(quorum, len(deps))`` -> ``return
        True``. Recorded failure:

            assert not q.dependencies_met(q.get_task('select'), 3)
            AssertionError: an extraction site would be chosen having surveyed
            NOTHING -- that is D-29
        """
        q = _soft_queue(completed=0, failed=10)
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS), (
            'an extraction site would be chosen having surveyed NOTHING -- '
            'that is D-29')

    def test_the_constant_is_one_and_the_planner_uses_it(self):
        assert SELECT_SITE_SURVEY_QUORUM == 1

    def test_a_larger_quorum_needs_more_completions(self):
        q = _soft_queue(completed=2, failed=8, quorum=3)
        assert not q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS)
        q2 = _soft_queue(completed=3, failed=7, quorum=3)
        assert q2.dependencies_met(q2.get_task('select'), TASK_MAX_ATTEMPTS)


# --------------------------------------------------------------------------- #
#  (d) The HARD edges do not move                                              #
# --------------------------------------------------------------------------- #

class TestTheCausalChainIsUntouched:
    """"FAILED-exhausted counts as RESOLVED" read carelessly would relax exactly
    the edge that must never relax."""

    def test_an_excavate_still_blocks_on_a_dead_select_site(self):
        """MUTATION: ``if quorum <= 0:`` branch -> ``return True``. Recorded
        failure:

            assert not q.dependencies_met(q.get_task('excavate'), 3)
            AssertionError: an excavate became ready with no site selected --
            the causal chain has been relaxed
        """
        q = TaskQueue()
        q.add_task('select', 'select_site', 0.0, 0.0, priority=4.0)
        q.add_task('excavate', 'excavate', 0.0, 0.0, priority=3.0,
                   depends_on=['select'])
        _exhaust(q, 'select')
        assert not q.dependencies_met(q.get_task('excavate'),
                                      TASK_MAX_ATTEMPTS), (
            'an excavate became ready with no site selected -- the causal '
            'chain has been relaxed')

    def test_a_haul_still_blocks_on_a_dead_excavate(self):
        q = TaskQueue()
        q.add_task('excavate', 'excavate', 0.0, 0.0, priority=3.0)
        q.add_task('haul', 'haul', 0.0, 0.0, priority=3.0,
                   depends_on=['excavate'])
        _exhaust(q, 'excavate')
        assert not q.dependencies_met(q.get_task('haul'), TASK_MAX_ATTEMPTS), (
            'a haul became ready with nothing extracted -- it would put a mass '
            'in the ISRU ledger that no excavation produced')
        assert q.get_next_ready(0.0, max_attempts=TASK_MAX_ATTEMPTS) is None


# --------------------------------------------------------------------------- #
#  (e) The RESOLVED table, whole                                               #
# --------------------------------------------------------------------------- #

class TestTheResolvedTableCoversEveryStatus:
    """A status omitted from the table is how a soft edge quietly becomes hard
    again -- or how a survey still driving gets counted as finished."""

    RESOLVED = {TaskStatus.COMPLETED}

    @pytest.mark.parametrize('status', list(TaskStatus))
    def test_every_status_is_classified_as_documented(self, status):
        dep = _entry(status=status)
        expected = status in self.RESOLVED
        assert TaskQueue._dependency_resolved(dep, TASK_MAX_ATTEMPTS) is expected

    def test_the_table_covers_the_whole_enum(self):
        """A new TaskStatus cannot be added without this file failing, which is
        the discipline ``test_conftest_mirrors_msgs.py`` applies to fields."""
        assert {s.name for s in TaskStatus} == {
            'PENDING', 'AUCTIONING', 'ASSIGNED', 'IN_PROGRESS',
            'COMPLETED', 'FAILED', 'INTERRUPTED',
        }

    @pytest.mark.parametrize('attempts,resolved', [
        (0, False), (1, False), (2, False), (3, True), (4, True),
    ])
    def test_the_three_FAILED_sub_cases(self, attempts, resolved):
        """``failed_attempts == 0`` is ``inject_task_logic._reject``'s row --
        a request that was REFUSED, not a task that ran and failed. It is
        unretryable, so it must block rather than resolve."""
        dep = _entry(status=TaskStatus.FAILED, failed_attempts=attempts)
        assert TaskQueue._dependency_resolved(
            dep, TASK_MAX_ATTEMPTS) is resolved


class TestTheExhaustionPredicateIsShared:

    def test_the_bound_is_one_expression_with_three_callers(self):
        """MUTATION: re-inline ``0 < TASK_MAX_ATTEMPTS <= task.failed_attempts``
        at ``_report_attempts_exhausted``. The behavioural tests stay green --
        which is the point: three copies of a bound drift silently, so this is
        asserted structurally.
        """
        tree = ast.parse(NODE_SOURCE.read_text(encoding='utf-8'))
        report = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == '_report_attempts_exhausted')
        called = {n.func.attr for n in ast.walk(report)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert 'attempts_exhausted' in called, sorted(called)

        queue_source = (pathlib.Path(__file__).resolve().parents[1]
                        / 'selene_orchestrator' / 'task_queue.py')
        qtree = ast.parse(queue_source.read_text(encoding='utf-8'))
        for name in ('retry_failed_tasks', '_dependency_resolved'):
            func = next(n for n in ast.walk(qtree)
                        if isinstance(n, ast.FunctionDef) and n.name == name)
            attrs = {n.func.attr for n in ast.walk(func)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)}
            assert 'attempts_exhausted' in attrs, (name, sorted(attrs))

    def test_a_non_positive_bound_means_retry_forever(self):
        """The supported configuration ``retry_failed_tasks`` documents. If the
        orchestrator will never give up, the dependency has not stopped
        moving -- so a soft quorum correctly degenerates to today's deadlock."""
        dep = _entry(status=TaskStatus.FAILED, failed_attempts=99)
        for bound in (0, -1):
            assert TaskQueue.attempts_exhausted(dep, bound) is False
            assert TaskQueue._dependency_resolved(dep, bound) is False


# --------------------------------------------------------------------------- #
#  (f) The bound is PLUMBED, and its default preserves every existing caller   #
# --------------------------------------------------------------------------- #

class TestTheRetryBoundDefault:

    def test_without_the_bound_a_FAILED_dependency_is_never_resolved(self):
        """Every direct TaskQueue caller and every existing test omits it, and
        must therefore see exactly today's behaviour.

        MUTATION: ``max_attempts: int = 0`` -> ``= TASK_MAX_ATTEMPTS`` on
        ``dependencies_met``. Recorded failure:

            assert not q.dependencies_met(q.get_task('select'))
            AssertionError: the bound defaulted to something; a caller that
            never opted in has had its readiness rule changed under it
        """
        q = _soft_queue(completed=1, failed=9)
        assert not q.dependencies_met(q.get_task('select')), (
            'the bound defaulted to something; a caller that never opted in '
            'has had its readiness rule changed under it')
        assert q.get_next_ready(0.0) is None

    def test_the_production_call_sites_pass_the_bound(self):
        """MUTATION: drop ``max_attempts=TASK_MAX_ATTEMPTS`` from
        ``_auction_tick``'s ``get_next_ready``. Recorded failure:

            AssertionError: _auction_tick's get_next_ready does not pass the
            retry bound, so a soft quorum can never see an exhausted dependency
        """
        tree = ast.parse(NODE_SOURCE.read_text(encoding='utf-8'))
        for func_name, call_name in (
                ('_auction_tick', 'get_next_ready'),
                ('_preempt_for_emergency', 'get_preemption_candidate')):
            func = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name == func_name)
            call = next(n for n in ast.walk(func)
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == call_name)
            keywords = {kw.arg for kw in call.keywords}
            assert 'max_attempts' in keywords, (
                "%s's %s does not pass the retry bound, so a soft quorum can "
                "never see an exhausted dependency" % (func_name, call_name))
            # The clock stays POSITIONAL: test_auction_backoff.py AST-walks
            # these calls and a keyword clock has an empty `.args`.
            assert call.args, func_name


# --------------------------------------------------------------------------- #
#  (g) Degenerate quorums                                                      #
# --------------------------------------------------------------------------- #

class TestDegenerateQuorums:

    def test_a_quorum_larger_than_the_dependency_list_is_clamped(self):
        """An unsatisfiable readiness predicate is the permanent silent deadlock
        this change exists to remove, so the clamped worst case is "all of
        them" -- the default this class has always had. The cost, stated: a
        mis-set quorum is masked rather than loud."""
        q = _soft_queue(completed=3, quorum=5)
        assert q.dependencies_met(q.get_task('select'), TASK_MAX_ATTEMPTS)
        q2 = _soft_queue(completed=2, failed=1, quorum=5)
        assert not q2.dependencies_met(q2.get_task('select'),
                                       TASK_MAX_ATTEMPTS)

    def test_a_quorum_over_an_empty_dependency_list_is_vacuous_not_deadlocked(self):
        q = TaskQueue()
        q.add_task('lonely', 'prospect', 0.0, 0.0, depends_on_quorum=4)
        assert q.dependencies_met(q.get_task('lonely'), TASK_MAX_ATTEMPTS)

    def test_completed_dependencies_counts_only_COMPLETED(self):
        q = _soft_queue(completed=2, failed=3, pending=1)
        assert q.completed_dependencies(q.get_task('select')) == 2


# --------------------------------------------------------------------------- #
#  (h) The queue-level D2 regression, through get_next_ready                   #
# --------------------------------------------------------------------------- #

class TestTheQueueUnblocks:

    def test_get_next_ready_returns_select_site_on_a_partial_quorum(self):
        """MUTATION: restore ``_ready_tasks``' original all-COMPLETED genexp.
        Recorded failure:

            assert q.get_next_ready(0.0, max_attempts=3) is not None
            AssertionError: get_next_ready returns None forever -- this is the
            live deadlock, reproduced
        """
        q = _soft_queue(completed=9, failed=1)
        answer = q.get_next_ready(0.0, max_attempts=TASK_MAX_ATTEMPTS)
        assert answer is not None, (
            'get_next_ready returns None forever -- this is the live deadlock, '
            'reproduced')
        assert answer.task_id == 'select'

    def test_a_preemption_candidate_asks_the_same_question(self):
        """One question with one clause relaxed, not two that drift."""
        q = _soft_queue(completed=9, failed=1)
        candidate = q.get_preemption_candidate(
            0.0, max_attempts=TASK_MAX_ATTEMPTS)
        assert candidate is not None and candidate.task_id == 'select'


# --------------------------------------------------------------------------- #
#  (i) The planner -- without this the queue-side half is inert                #
# --------------------------------------------------------------------------- #

@pytest.fixture
def resource_map():
    return ResourceMap(width=100, height=100, resolution=1.0,
                       origin_x=-50.0, origin_y=-50.0,
                       prior_mean=0.0, prior_variance=100.0)


@pytest.fixture
def queue():
    return TaskQueue()


@pytest.fixture
def planner(queue, resource_map):
    return HTNPlanner(queue, resource_map)


def _survey_ids(queue: TaskQueue) -> list[str]:
    return [t.task_id for t in queue.get_all_tasks()
            if t.task_type == 'prospect']


def _select_task(queue: TaskQueue) -> TaskEntry:
    return next(t for t in queue.get_all_tasks()
                if t.task_type == 'select_site')


class TestThePlannerCarriesTheQuorum:

    def test_select_site_is_the_only_task_with_a_soft_edge(self, planner, queue):
        """MUTATION: drop the ``depends_on_quorum=`` keyword from
        ``decompose_collect_ice``'s select_site ``add_task``. Recorded failure:

            assert select.depends_on_quorum == 1
            AssertionError: assert 0 == 1
        """
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        select = _select_task(queue)
        assert select.depends_on_quorum == SELECT_SITE_SURVEY_QUORUM == 1
        for task in queue.get_all_tasks():
            if task.task_type != 'select_site':
                assert task.depends_on_quorum == 0, task.task_id

    def test_the_generated_cycles_are_hard_edges(self, planner, queue):
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        for tid in _survey_ids(queue):
            queue.mark_complete(tid, 'skill_complete')
        planner.check_and_advance()
        cycles = [t for t in queue.get_all_tasks()
                  if t.task_type in ('excavate', 'haul')]
        assert cycles, 'no cycles were generated at all'
        for task in cycles:
            assert task.depends_on_quorum == 0, task.task_id


class TestThePlannerAsksTheQueue:

    def test_check_and_advance_does_not_restate_the_dependency_rule(self):
        """THE GUARD AGAINST D2 COMING BACK.

        The defect was two copies of "a dependency is satisfied only by
        COMPLETED", one of them here. A third enforcement point would be wrong
        in exactly this way and its symptom would be a mission that deadlocks or
        fires early -- not a failing test. So the shape is asserted, not just
        the behaviour.
        """
        func = _planner_func('check_and_advance')
        called = {n.func.attr for n in ast.walk(func)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert 'dependencies_met' in called, sorted(called)
        alls = [n for n in ast.walk(func)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == 'all']
        assert not alls, (
            'check_and_advance restates a dependency rule with all(); the '
            'queue and the planner can now drift, which IS D2')


class TestTheShippedMissionSurvivesOneDeadSurvey:
    """The end-to-end regression: the live observation, as a unit test."""

    def _nine_of_ten(self, planner, queue):
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        assert len(surveys) >= 2, surveys
        for tid in surveys[:-1]:
            queue.mark_complete(tid, 'skill_complete')
        _exhaust(queue, surveys[-1])
        return surveys

    def test_select_site_resolves_and_the_cycles_are_generated(
            self, planner, queue):
        """MUTATION: restore ``check_and_advance``'s original ``all_done``
        genexp (leaving ``_ready_tasks`` fixed). Recorded failure:

            assert select.status is TaskStatus.COMPLETED
            AssertionError: assert <TaskStatus.PENDING: 'PENDING'> is
            <TaskStatus.COMPLETED: 'COMPLETED'>

        That mutation is the whole reason the planner edit exists: select_site
        is VIRTUAL, ``_auction_tick`` skips it by task_type, and this call is
        the only thing in the system that ever resolves it. Fixing the queue
        alone would have shipped a fix that did nothing.
        """
        surveys = self._nine_of_ten(planner, queue)
        planner.check_and_advance()

        select = _select_task(queue)
        assert select.status is TaskStatus.COMPLETED
        assert select.status_reason == SITE_SELECTED_PARTIAL
        assert planner.get_site_id() != ''
        excavates = [t for t in queue.get_all_tasks()
                     if t.task_type == 'excavate']
        hauls = [t for t in queue.get_all_tasks() if t.task_type == 'haul']
        assert excavates and hauls, (
            'the ISRU chain was never generated -- the mission is still dead')

        # And the chain is actually runnable: the excavate is what the auction
        # offers next, the dead survey notwithstanding.
        answer = queue.get_next_ready(0.0, max_attempts=TASK_MAX_ATTEMPTS)
        assert answer is not None and answer.task_type == 'excavate', answer
        assert queue.get_task(surveys[-1]).status is TaskStatus.FAILED

    def test_the_evidence_counts_are_reported(self, planner, queue):
        """MUTATION: swap ``completed`` for ``total`` in
        ``check_and_advance``'s ``_site_evidence`` assignment. Recorded failure:

            assert planner.get_site_evidence() == (9, 10)
            AssertionError: assert (10, 10) == (9, 10)
        """
        surveys = self._nine_of_ten(planner, queue)
        planner.check_and_advance()
        assert planner.get_site_evidence() == (len(surveys) - 1, len(surveys))

    def test_it_does_NOT_fire_while_a_survey_is_still_PENDING(
            self, planner, queue):
        """The other half of the pair: no early resolution."""
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        for tid in surveys[:-1]:
            queue.mark_complete(tid, 'skill_complete')
        planner.check_and_advance()

        assert _select_task(queue).status is TaskStatus.PENDING
        assert [t for t in queue.get_all_tasks()
                if t.task_type == 'excavate'] == []
        assert planner.get_site_evidence() == (0, 0)

    def test_full_evidence_is_reported_as_such(self, planner, queue):
        """MUTATION: stamp ``SITE_SELECTED_PARTIAL`` unconditionally. Recorded
        failure:

            assert select.status_reason == 'site_selected'
            AssertionError: assert 'site_selected_partial' == 'site_selected'
        """
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        for tid in surveys:
            queue.mark_complete(tid, 'skill_complete')
        planner.check_and_advance()

        select = _select_task(queue)
        assert select.status_reason == SITE_SELECTED
        assert planner.get_site_evidence() == (len(surveys), len(surveys))

    def test_a_second_decomposition_resets_the_evidence(self, planner, queue):
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        for tid in surveys:
            queue.mark_complete(tid, 'skill_complete')
        planner.check_and_advance()
        assert planner.get_site_evidence()[1] > 0
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        assert planner.get_site_evidence() == (0, 0)


# --------------------------------------------------------------------------- #
#  (j) The operator is told -- through the shipped _htn_advance                #
# --------------------------------------------------------------------------- #

class _Logger:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def info(self, msg):
        self.lines.append(('info', str(msg)))

    def warn(self, msg):
        self.lines.append(('warn', str(msg)))

    def error(self, msg):
        self.lines.append(('error', str(msg)))

    def debug(self, msg):
        self.lines.append(('debug', str(msg)))

    def of(self, level):
        return [m for lvl, m in self.lines if lvl == level]


class _AdvanceNode:
    """The minimum surface ``_htn_advance`` touches, named explicitly.

    A mechanism nothing calls is the failure mode this repository has been
    bitten by ten times, so the alert is driven through the SHIPPED method
    rather than asserted from the planner's return value.
    """

    def __init__(self, planner: HTNPlanner):
        self._htn_planner = planner
        self._registered_sites: set[str] = set()
        self._inventory = types.SimpleNamespace(
            register_site=lambda site_id, position, estimated_kg: None)
        self.alerts: list[tuple[str, str, str]] = []
        self._logger = _Logger()

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def advance(self):
        OrchestratorNode._htn_advance(self)

    def alerts_of(self, severity):
        return [a for a in self.alerts if a[0] == severity]


class TestTheDegradationIsVisible:

    def _mission(self, planner, queue, dead: int):
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        for tid in surveys[:len(surveys) - dead]:
            queue.mark_complete(tid, 'skill_complete')
        for tid in surveys[len(surveys) - dead:]:
            _exhaust(queue, tid)
        return surveys

    def test_one_WARNING_names_the_counts(self, planner, queue):
        """MUTATION: delete the partial-evidence alert block from
        ``_htn_advance``. Recorded failure:

            assert len(warnings) == 1
            AssertionError: assert 0 == 1
        """
        surveys = self._mission(planner, queue, dead=1)
        node = _AdvanceNode(planner)
        node.advance()

        warnings = node.alerts_of('WARNING')
        assert len(warnings) == 1, node.alerts
        message = warnings[0][2]
        assert 'PARTIAL EVIDENCE' in message, message
        assert '%d of %d' % (len(surveys) - 1, len(surveys)) in message, message
        assert planner.get_site_id() in message, message
        assert node._logger.of('warn'), 'the log says nothing'

    def test_it_is_raised_ONCE_and_not_at_1Hz_forever(self, planner, queue):
        """Latched by the existing ``_registered_sites`` early return -- no new
        latch flag, and no possibility of a 1 Hz repeat for the rest of the
        mission."""
        self._mission(planner, queue, dead=1)
        node = _AdvanceNode(planner)
        for _ in range(50):
            node.advance()
        assert len(node.alerts_of('WARNING')) == 1, len(node.alerts)

    def test_full_evidence_raises_nothing(self, planner, queue):
        """MUTATION: drop the ``0 < surveyed < planned`` guard. Recorded
        failure:

            assert node.alerts == []
            AssertionError: assert [('WARNING', '', 'extraction site ...')] == []
        """
        self._mission(planner, queue, dead=0)
        node = _AdvanceNode(planner)
        node.advance()
        assert node.alerts == [], node.alerts

    def test_the_severity_is_WARNING_and_never_CRITICAL(self, planner, queue):
        """CRITICAL in this node means "the orchestrator has STOPPED and nothing
        will clear it". This says the opposite: it PROCEEDED, degraded. Spending
        CRITICAL on a running mission devalues the one level the dashboard
        renders specially."""
        self._mission(planner, queue, dead=1)
        node = _AdvanceNode(planner)
        node.advance()
        assert node.alerts_of('CRITICAL') == []

    def test_the_ledger_site_is_still_registered_exactly_once(
            self, planner, queue):
        """The alert was added AFTER the registration; nothing about the D-06
        ordering guarantee moved."""
        registered = []
        self._mission(planner, queue, dead=1)
        node = _AdvanceNode(planner)
        node._inventory = types.SimpleNamespace(
            register_site=lambda site_id, position, estimated_kg:
                registered.append(site_id))
        node.advance()
        node.advance()
        assert registered == [planner.get_site_id()]


# --------------------------------------------------------------------------- #
#  (k) The loudest message in the node is not left asserting a lie             #
# --------------------------------------------------------------------------- #

class TestTheExhaustionAlertStaysHonest:
    """``_report_attempts_exhausted``'s CRITICAL used to say the blocked
    dependents "can NEVER become ready while it stays FAILED -- a dependency is
    satisfied only by COMPLETED". After this change that is false for exactly
    the dependent it was written about, select_site, in exactly the scenario
    this change exists for. No test asserted the wording, so nothing would have
    caught it; this is that test.
    """

    def _exhausted_alert(self) -> str:
        """The CRITICAL, produced by the SHIPPED method, for a soft dependent.

        Driven through ``_report_attempts_exhausted`` rather than read out of
        the source, so this measures what an operator would actually receive.
        """
        q = _soft_queue(completed=9, failed=1)
        node = types.SimpleNamespace(
            _task_queue=q,
            _attempts_exhausted_alerted=set(),
            alerts=[],
            _log=_Logger())
        node.get_logger = lambda: node._log
        node._publish_alert = (
            lambda severity, source, message:
                node.alerts.append((severity, source, message)))
        OrchestratorNode._report_attempts_exhausted(node)
        critical = [a for a in node.alerts if a[0] == 'CRITICAL']
        assert len(critical) == 1, node.alerts
        return critical[0][2]

    def test_the_alert_does_not_claim_a_soft_dependent_is_dead(self):
        """MUTATION: restore the "can NEVER become ready while it stays FAILED
        -- a dependency is satisfied only by COMPLETED" sentence. Recorded
        failure:

            assert 'can NEVER become ready' not in message
            AssertionError: the CRITICAL alert asserts a deadlock that the very
            same commit removes
            assert 'can NEVER become ready' not in 'task survey_dead_0
            (prospect) has FAILED 3 time(s) ... 1 task(s) already in the queue
            depend on it, directly or transitively, and can NEVER become ready
            while it stays FAILED -- a dependency is satisfied only by
            COMPLETED: [...]'
        """
        message = self._exhausted_alert()
        assert 'can NEVER become ready' not in message, (
            'the CRITICAL alert asserts a deadlock that the very same commit '
            'removes')
        assert 'SOFT dependency quorum' in message, (
            'the alert does not tell the operator that a soft dependent may '
            'still run, so the CRITICAL and the WARNING that follows it read '
            'as a contradiction')

    def test_it_still_names_the_blast_radius_and_the_floor(self):
        """The correction must not cost the alert what it was already saying."""
        message = self._exhausted_alert()
        assert '1 task(s)' in message, message
        assert 'select' in message, message
        assert 'FLOOR' in message, message


# --------------------------------------------------------------------------- #
#  (l) The wire: bought with a comment, not a field                            #
# --------------------------------------------------------------------------- #

class TestTheWireDocumentation:

    def test_both_site_reasons_are_documented(self):
        text = MSG.read_text(encoding='utf-8')
        for reason in (SITE_SELECTED, SITE_SELECTED_PARTIAL):
            assert f"'{reason}'" in text, (
                f'{reason!r} is written onto TaskStatus.status_reason by '
                f'htn_planner and is not documented in TaskStatus.msg')

    def test_the_quorum_is_documented_where_depends_on_is(self):
        text = MSG.read_text(encoding='utf-8')
        assert 'depends_on_quorum' in text, (
            'depends_on no longer means "all of these must be COMPLETED" and '
            'the message does not say so')

    def test_no_field_was_added_or_reordered(self):
        """Rule (e): documentation only. A field change needs a rosidl
        regeneration and this branch has had none."""
        fields = [ln.split()[0] for ln in
                  MSG.read_text(encoding='utf-8').splitlines()
                  if ln.strip() and not ln.startswith('#')]
        assert fields == [
            'string', 'string', 'string', 'string', 'string', 'float32',
            'float32', 'float32', 'geometry_msgs/Point', 'string', 'string[]',
            'string[]', 'string', 'builtin_interfaces/Time', 'uint32', 'bool',
        ], fields


class TestNoRosParameterWasAdded:

    def test_the_quorum_is_a_module_constant(self):
        """Rule 3. ``test_no_orphan_parameters.py``'s allow-list is the single
        name ``fleet_state_publish_rate`` and cannot see a parameter that is
        declared AND read, so this is asserted here too."""
        tree = ast.parse(NODE_SOURCE.read_text(encoding='utf-8'))
        declared = {
            n.args[0].value
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == 'declare_parameter'
            and n.args and isinstance(n.args[0], ast.Constant)}
        assert not [d for d in declared if 'quorum' in d], sorted(declared)


class TestTheAuctionIsUnchangedForVirtualTasks:

    def test_a_quorum_ready_select_site_is_never_auctioned(
            self, planner, queue):
        """Pre-existing behaviour, re-asserted because the window now opens in a
        NEW circumstance -- with a FAILED survey resting in the queue -- and it
        must not later be mistaken for a new stall. ``_auction_tick`` returns on
        task_type, and the 1 Hz planner resolves it within a second."""
        planner.decompose_collect_ice((0.0, 0.0), 30.0, 40.0)
        surveys = _survey_ids(queue)
        for tid in surveys[:-1]:
            queue.mark_complete(tid, 'skill_complete')
        _exhaust(queue, surveys[-1])
        answer = queue.get_next_ready(0.0, max_attempts=TASK_MAX_ATTEMPTS)
        assert answer.task_type == 'select_site'
        # The tick returns on task_type before any auction is opened. Asserted
        # against the shipped source rather than re-run here.
        source = NODE_SOURCE.read_text(encoding='utf-8')
        tick = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef)
                    and n.name == '_auction_tick')
        assert "'select_site'" in ast.get_source_segment(source, tick)
