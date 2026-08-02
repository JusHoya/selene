"""D2: a terminally FAILED task deadlocked everything downstream of it.

THE DEFECT, as observed live: ``select_site_907c0627`` depends_on all ten
surveys, ``survey_aa78d4f9`` went FAILED, and the mission was permanently dead
with the dashboard still reading "awaiting first extraction".
``_ready_tasks``'s ``deps_met`` satisfies a dependency only with COMPLETED, and
nothing in ``TaskQueue`` ever moved a task out of FAILED -- there was no
``retry_task``, no ``reset_failed``, no ``requeue_failed`` API at all.

THE SHAPE OF THE FIX, and what these tests are therefore pinning: a FAILED task
RESTS in FAILED, visibly, and is returned to PENDING by a separate, bounded,
explicitly-invoked sweep -- exactly as an ABANDONED task rests
PENDING-with-backoff-inf and is released only by ``wake_deferred_auctions``.
FAILED never enters REQUEUEABLE_STATUSES, so ``get_next_ready`` still never
returns a FAILED task and the three existing tests that assert precisely that
(``test_get_next_ready_still_ignores_terminal_statuses``,
``test_a_failed_task_is_never_re_auctioned``,
``test_e2e_task_result_failure_is_not_a_completion``) stay green verbatim.

WHAT IS NOT TESTED HERE, said rather than implied: nothing in this file runs
ROS, and these tests cover the ``TaskQueue`` half only.

THE SENTENCE THAT STOOD HERE -- "the sweep has no production caller yet --
``_auction_tick`` must call it" -- IS SUPERSEDED as of 2026-08-02. It does:
``orchestrator_node._auction_tick`` calls ``_retry_failed_tasks``, which calls
this sweep with ``task_feed.TASK_MAX_ATTEMPTS`` and ``TASK_RETRY_REQUEUED``,
and then ``_report_attempts_exhausted`` announces the tasks that have spent
their last attempt using ``get_transitive_dependents``. Until that landed, every
test in this file was green over an API with ZERO production callers -- the
"wired but never called" pattern, three instances of it, in the commit meant to
fix a mission-fatal deadlock. ``test_task_retry_wiring.py`` is what asserts the
caller exists; a green file here has never been evidence that any of this runs.
"""

from selene_orchestrator.task_queue import (
    REQUEUEABLE_STATUSES,
    TaskQueue,
    TaskStatus,
)


def _queue_with_blocked_chain() -> TaskQueue:
    """The live deadlock in miniature: one survey, one select_site behind it."""
    q = TaskQueue()
    q.add_task('survey', 'prospect', -80.0, -140.0, priority=1.0)
    q.add_task('select', 'select_site', 0.0, 0.0, priority=5.0,
               depends_on=['survey'])
    return q


class TestTheDeadlockItself:

    def test_a_failed_dependency_blocks_its_child_and_the_retry_unblocks_it(self):
        q = _queue_with_blocked_chain()
        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Path blocked, no alternate route')

        # THE INVARIANT, which holds BEFORE and AFTER the fix and must: a FAILED
        # task is not re-auctionable and its child is not unblocked. This is the
        # deadlock exactly as observed.
        assert q.get_task('survey').status is TaskStatus.FAILED
        assert q.get_next_ready() is None
        assert TaskStatus.FAILED not in REQUEUEABLE_STATUSES

        # THE REGRESSION: the sweep is what makes it work again.
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == ['survey']
        survey = q.get_task('survey')
        assert survey.status is TaskStatus.PENDING
        assert survey.status_reason == 'skill_failed_requeued'
        ready = q.get_next_ready()
        assert ready is not None and ready.task_id == 'survey'

        # And the child unblocks once the retried attempt succeeds.
        q.mark_complete('survey')
        ready = q.get_next_ready()
        assert ready is not None and ready.task_id == 'select'

    def test_the_sweep_is_silent_when_there_is_nothing_to_retry(self):
        """No FAILED task means no work, no event and an empty return.

        The caller logs only on a non-empty result, so this is what keeps a
        sweep on the 2 Hz auction tick from becoming D-20's 261-line flood.
        """
        q = _queue_with_blocked_chain()
        seen = []
        q.set_status_listener(lambda task, prev: seen.append(task.task_id))
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == []
        assert seen == []


class TestTheBound:

    def test_a_task_is_retried_until_the_attempt_budget_is_spent(self):
        q = _queue_with_blocked_chain()

        # Attempt 1 fails, retried.
        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Path blocked, no alternate route')
        assert q.get_task('survey').failed_attempts == 1
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == ['survey']

        # Attempt 2 fails, retried.
        q.assign_to_robot('survey', 'scout_02')
        q.mark_failed('survey', 'Path blocked, no alternate route')
        assert q.get_task('survey').failed_attempts == 2
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == ['survey']

        # Attempt 3 fails. THE BUDGET IS SPENT.
        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Path blocked, no alternate route')
        assert q.get_task('survey').failed_attempts == 3
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == []
        assert q.get_task('survey').status is TaskStatus.FAILED
        # And it stays spent: the sweep runs on every tick forever.
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == []
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == []

    def test_a_non_positive_bound_means_never_give_up(self):
        """A supported configuration, not a mistake.

        The same edge case ``task_feed.auction_failure_reason`` documents for
        ``max_rounds``: <= 0 disables the give-up branch rather than disabling
        the mechanism.
        """
        q = _queue_with_blocked_chain()
        for _ in range(20):
            q.assign_to_robot('survey', 'scout_01')
            q.mark_failed('survey', 'Drill actuator unavailable')
            assert q.retry_failed_tasks(0, 'skill_failed_requeued') == ['survey']
        assert q.get_task('survey').failed_attempts == 20


class TestARejectedInjectionIsNeverResurrected:
    """THE MOST IMPORTANT TEST IN THIS FILE.

    ``inject_task_logic._reject`` writes FAILED through ``set_status``, not
    through ``mark_failed``, for injections the orchestrator refused: "unknown
    robot", "robot in ERROR", "robot lacks capabilities". A naive "retry every
    FAILED task" would auction those phantom rows to the fleet.

    The defence is STRUCTURAL -- ``failed_attempts`` is 0 because only
    ``mark_failed`` ever increments it -- rather than a match on
    ``status_reason``, which would silently start resurrecting them the day
    somebody spells that reason differently.
    """

    def test_an_inject_rejected_row_has_no_attempts_and_is_never_retried(self):
        q = TaskQueue()
        q.add_task('manual_0000', 'excavate', 5.0, 5.0, priority=10.0)
        # The exact call inject_task_logic._reject makes.
        q.set_status('manual_0000', TaskStatus.FAILED, 'inject_rejected')

        row = q.get_task('manual_0000')
        assert row.failed_attempts == 0
        assert q.retry_failed_tasks(3, 'skill_failed_requeued') == []
        assert row.status is TaskStatus.FAILED
        assert row.status_reason == 'inject_rejected'
        assert q.get_next_ready() is None


class TestTheDuplicateResultInteraction:
    """D2 meets D4 here: ``_on_task_result`` has no re-entry guard."""

    def test_a_duplicate_task_result_does_not_burn_a_retry(self):
        q = _queue_with_blocked_chain()
        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Loading timed out')
        q.mark_failed('survey', 'Loading timed out')
        q.mark_failed('survey', 'Loading timed out')
        # Counted on a REAL transition only, mirroring set_status's own rule.
        # This holds whether or not D4's re-entry guard lands.
        assert q.get_task('survey').failed_attempts == 1


class TestWhatARetryTouches:

    def _failed_task_with_history(self) -> TaskQueue:
        q = _queue_with_blocked_chain()
        q.begin_auction('survey')                 # auction_rounds -> 1
        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Unloading timed out')
        q.get_task('survey').terminal_reported = True
        q.defer_auction('survey', 5.0, now=100.0)  # failed_auctions -> 1
        return q

    def test_the_robot_is_released(self):
        q = self._failed_task_with_history()
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert q.get_task('survey').assigned_robot == ''

    def test_terminal_reported_is_cleared(self):
        """THE D4 COUPLING, and it is a hard ordering constraint.

        D4's fix adds ``if task.terminal_reported: return`` at the top of
        ``_on_task_result``. If a retry did not clear this, the retried
        attempt's own TaskResult would be silently dropped and the task could
        NEVER terminate again -- it would sit ASSIGNED forever, and
        ``_on_robot_state``'s completion-inference fallback skips a task with
        this set too, so nothing would rescue it.
        """
        q = self._failed_task_with_history()
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert q.get_task('survey').terminal_reported is False

    def test_the_auction_backoff_is_cleared(self):
        """D-20: a retried task is fresh work, not work the fleet declined.

        Same reasoning as ``recover_tasks_for_robot``.
        """
        q = self._failed_task_with_history()
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        task = q.get_task('survey')
        assert task.auction_backoff_until == 0.0
        assert task.failed_auctions == 0

    def test_the_attempt_count_is_kept(self):
        q = self._failed_task_with_history()
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert q.get_task('survey').failed_attempts == 1

    def test_the_auction_round_is_not_refunded(self):
        """Unlike ``abort_auction``, which does refund one.

        That round really did resolve, into an assignment that ran and failed.
        Refunding it would misreport how many auctions this task has cost the
        fleet, and ``resolve_auction_winner`` expires an operator's
        ``preferred_robot`` on exactly that count.
        """
        q = self._failed_task_with_history()
        assert q.get_task('survey').auction_rounds == 1
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert q.get_task('survey').auction_rounds == 1

    def test_a_retry_emits_exactly_one_task_event(self):
        """Bounded event-ring cost: FAILED -> PENDING is one real change.

        The ring is 32 entries, so a sweep that emitted two events per task
        would evict the dashboard's replay history twice as fast.
        """
        q = self._failed_task_with_history()
        seen = []
        q.set_status_listener(
            lambda task, prev: seen.append((task.task_id, prev.name,
                                            task.status.name)))
        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert seen == [('survey', 'FAILED', 'PENDING')]


class TestTheMonotonicityInvariant:
    """The ungated sweep depends on ``failed_attempts`` never being reset.

    The caller runs this on every auction tick WITHOUT gating it on
    ``FleetMonitor.idle_arrivals`` the way ``_wake_on_fleet_change`` is gated.
    That is safe only because the count is monotone: a task can be retried at
    most ``max_attempts - 1`` times in its entire life whatever the fleet does.
    D-20 HAD to be gated because ``wake_deferred_auctions`` RESETS
    ``failed_auctions``, so an ungated sweep would re-arm the flood.

    This test is what stops a future change adding ``failed_attempts = 0`` to
    ``clear_auction_backoff`` and silently reinstating an unbounded retry loop.
    """

    def test_no_requeue_path_anywhere_resets_the_attempt_count(self):
        q = _queue_with_blocked_chain()

        q.assign_to_robot('survey', 'scout_01')
        q.mark_failed('survey', 'Path blocked on route to pickup')
        assert q.get_task('survey').failed_attempts == 1

        q.retry_failed_tasks(3, 'skill_failed_requeued')
        assert q.get_task('survey').failed_attempts == 1

        q.assign_to_robot('survey', 'scout_02')
        assert q.get_task('survey').failed_attempts == 1

        q.mark_failed('survey', 'Path blocked on route to depot')
        assert q.get_task('survey').failed_attempts == 2

        q.interrupt_task('survey', {}, reason='operator_cancel_task')
        assert q.get_task('survey').failed_attempts == 2

        q.wake_deferred_auctions('fleet_change')
        assert q.get_task('survey').failed_attempts == 2

        q.clear_auction_backoff('survey')
        assert q.get_task('survey').failed_attempts == 2

        q.abandon_auction('survey')
        q.wake_deferred_auctions('fleet_change')
        assert q.get_task('survey').failed_attempts == 2


class TestTheBlastRadiusReport:
    """``get_transitive_dependents`` is what an exhaustion alert must name.

    It also finally gives ``get_dependent_tasks`` a caller: that function had
    ZERO production callers and was sitting in the exact place this defect
    needed it -- an eighth instance of the "wired but never called" pattern
    CLAUDE.md enumerates.
    """

    def _chain(self) -> TaskQueue:
        q = TaskQueue()
        q.add_task('survey', 'prospect', 0, 0)
        q.add_task('select', 'select_site', 0, 0, depends_on=['survey'])
        q.add_task('excavate', 'excavate', 0, 0, depends_on=['select'])
        q.add_task('haul', 'haul', 0, 0, depends_on=['excavate'])
        q.add_task('unrelated', 'prospect', 9, 9)
        return q

    def test_the_whole_downstream_chain_is_reported_not_just_the_children(self):
        q = self._chain()
        # The direct dependents alone would say ONE task is blocked. The real
        # number is three, and understating a blast radius in an operator alert
        # is the failure that alert exists to prevent.
        assert {t.task_id for t in q.get_dependent_tasks('survey')} == {'select'}
        assert {t.task_id for t in q.get_transitive_dependents('survey')} == {
            'select', 'excavate', 'haul'}

    def test_an_unrelated_task_is_not_reported_as_blocked(self):
        q = self._chain()
        blocked = {t.task_id for t in q.get_transitive_dependents('survey')}
        assert 'unrelated' not in blocked
        assert 'survey' not in blocked

    def test_a_dependency_cycle_downstream_of_the_seed_terminates(self):
        """``add_task`` does not validate ``depends_on``, so a cycle is
        representable. The visited set is REQUIRED, not defensive.

        The cycle here deliberately does NOT contain the seed. A cycle that
        closes back on the seed terminates anyway, because the seed is excluded
        from the result -- so a two-task ``a <-> b`` case would not exercise the
        visited set at all and would pass with it removed.
        """
        q = TaskQueue()
        q.add_task('seed', 'prospect', 0, 0)
        q.add_task('x', 'excavate', 1, 1, depends_on=['seed', 'y'])
        q.add_task('y', 'haul', 2, 2, depends_on=['x'])
        assert {t.task_id for t in q.get_transitive_dependents('seed')} == {'x', 'y'}

    def test_a_cycle_containing_the_seed_terminates_and_excludes_it(self):
        q = TaskQueue()
        q.add_task('a', 'prospect', 0, 0, depends_on=['b'])
        q.add_task('b', 'prospect', 0, 0, depends_on=['a'])
        q.add_task('c', 'haul', 0, 0, depends_on=['b'])
        assert {t.task_id for t in q.get_transitive_dependents('a')} == {'b', 'c'}
        assert {t.task_id for t in q.get_transitive_dependents('b')} == {'a', 'c'}

    def test_a_task_with_no_dependents_reports_an_empty_blast_radius(self):
        q = self._chain()
        assert q.get_transitive_dependents('haul') == []
        assert q.get_transitive_dependents('no_such_task') == []
