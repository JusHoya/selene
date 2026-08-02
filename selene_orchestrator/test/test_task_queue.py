"""Tests for TaskQueue."""

from selene_orchestrator.task_queue import (
    REQUEUEABLE_STATUSES,
    TaskQueue,
    TaskStatus,
)


class TestTaskQueue:

    def test_add_and_retrieve(self):
        q = TaskQueue()
        q.add_task(
            't1', 'prospect', -80.0, -140.0,
            priority=1.0, required_capabilities=['prospect'],
        )
        task = q.get_next_pending()
        assert task is not None
        assert task.task_id == 't1'
        assert task.status == TaskStatus.PENDING

    def test_priority_ordering(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0, priority=0.5)
        q.add_task('t2', 'prospect', 0, 0, priority=1.0)
        q.add_task('t3', 'prospect', 0, 0, priority=0.8)
        task = q.get_next_pending()
        assert task.task_id == 't2'

    def test_status_transitions(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.set_status('t1', TaskStatus.AUCTIONING)
        assert q.get_task('t1').status == TaskStatus.AUCTIONING
        q.set_status('t1', TaskStatus.ASSIGNED)
        assert q.get_task('t1').status == TaskStatus.ASSIGNED

    def test_assign_to_robot(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.assign_to_robot('t1', 'scout_01')
        t = q.get_task('t1')
        assert t.status == TaskStatus.ASSIGNED
        assert t.assigned_robot == 'scout_01'

    def test_get_task_for_robot(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.assign_to_robot('t1', 'scout_01')
        assert q.get_task_for_robot('scout_01') == 't1'
        assert q.get_task_for_robot('scout_02') is None

    def test_recover_tasks_for_robot(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.add_task('t2', 'prospect', 10, 10)
        q.assign_to_robot('t1', 'scout_01')
        q.assign_to_robot('t2', 'scout_01')
        recovered = q.recover_tasks_for_robot('scout_01')
        assert set(recovered) == {'t1', 't2'}
        assert q.get_task('t1').status == TaskStatus.PENDING
        assert q.get_task('t1').assigned_robot == ''

    def test_recover_ignores_completed(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.assign_to_robot('t1', 'scout_01')
        q.mark_complete('t1')
        recovered = q.recover_tasks_for_robot('scout_01')
        assert recovered == []
        assert q.get_task('t1').status == TaskStatus.COMPLETED

    def test_completed_count(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.add_task('t2', 'prospect', 0, 0)
        q.mark_complete('t1')
        assert q.get_completed_count() == 1

    def test_empty_queue(self):
        q = TaskQueue()
        assert q.get_next_pending() is None
        assert q.get_pending_count() == 0

    def test_pending_skips_non_pending(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.set_status('t1', TaskStatus.ASSIGNED)
        assert q.get_next_pending() is None

    def test_get_next_ready_respects_dependencies(self):
        q = TaskQueue()
        q.add_task('dep1', 'prospect', 0, 0, priority=1.0)
        q.add_task('dep2', 'prospect', 10, 10, priority=1.0)
        q.add_task('child', 'excavate', 5, 5, priority=2.0, depends_on=['dep1', 'dep2'])

        # Initially: dep1, dep2, child all PENDING; child has unmet deps
        # dep1 and dep2 have no deps so they are ready (priority 1.0 each)
        ready = q.get_next_ready()
        assert ready is not None
        assert ready.task_id in ('dep1', 'dep2')

        # Complete one dep -- child still not ready (dep2 incomplete)
        q.mark_complete('dep1')
        ready = q.get_next_ready()
        assert ready.task_id == 'dep2'

        # Complete both deps -- child is now the only PENDING task and deps are met
        q.mark_complete('dep2')
        ready = q.get_next_ready()
        assert ready.task_id == 'child'

    def test_interrupt_preserves_metadata(self):
        q = TaskQueue()
        q.add_task('t1', 'excavate', 0, 0)
        q.assign_to_robot('t1', 'hauler_01')
        meta = {'kg_extracted': 12.5, 'progress_pct': 62}
        q.interrupt_task('t1', meta)

        t = q.get_task('t1')
        assert t.status == TaskStatus.INTERRUPTED
        assert t.assigned_robot == ''
        assert t.progress_metadata == meta

    def test_get_dependent_tasks(self):
        q = TaskQueue()
        q.add_task('parent', 'select_site', 0, 0)
        q.add_task('child1', 'excavate', 1, 1, depends_on=['parent'])
        q.add_task('child2', 'excavate', 2, 2, depends_on=['parent'])
        q.add_task('unrelated', 'prospect', 3, 3)

        deps = q.get_dependent_tasks('parent')
        dep_ids = {t.task_id for t in deps}
        assert dep_ids == {'child1', 'child2'}


class TestRequeueableStatuses:
    """D-03: INTERRUPTED becomes a resting, re-auctionable status."""

    def test_get_next_ready_returns_an_interrupted_task(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.assign_to_robot('t1', 'scout_01')
        q.interrupt_task('t1', {'reason': 'operator_cancel_task'},
                         reason='operator_cancel_task')

        ready = q.get_next_ready()
        assert ready is not None and ready.task_id == 't1'
        assert set(REQUEUEABLE_STATUSES) == {
            TaskStatus.PENDING, TaskStatus.INTERRUPTED}

    def test_get_next_ready_still_ignores_terminal_statuses(self):
        q = TaskQueue()
        q.add_task('done', 'prospect', 0, 0)
        q.add_task('failed', 'excavate', 0, 0)
        q.add_task('running', 'haul', 0, 0)
        q.mark_complete('done')
        q.mark_failed('failed', 'drill stalled')
        q.assign_to_robot('running', 'hauler_01')
        assert q.get_next_ready() is None

    def test_an_interrupted_dependency_does_not_unblock_a_child(self):
        """Only COMPLETED satisfies depends_on; INTERRUPTED must not."""
        q = TaskQueue()
        q.add_task('dep', 'excavate', 0, 0)
        q.add_task('child', 'haul', 0, 0, priority=9.0, depends_on=['dep'])
        q.assign_to_robot('dep', 'excavator_01')
        q.interrupt_task('dep', {}, reason='operator_cancel_task')

        ready = q.get_next_ready()
        assert ready.task_id == 'dep'          # the dependency, not the child

    def test_get_next_pending_still_means_literally_pending(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        q.assign_to_robot('t1', 'scout_01')
        q.interrupt_task('t1', {})
        assert q.get_next_pending() is None
        assert q.get_pending_count() == 0


class TestStatusBookkeeping:
    """D-03: every transition records why it happened and when."""

    def test_set_status_stamps_reason_and_time(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)
        before = q.get_task('t1').status_changed
        q.set_status('t1', TaskStatus.AUCTIONING, 'auction_started')
        task = q.get_task('t1')
        assert task.status_reason == 'auction_started'
        assert task.status_changed >= before
        # Wall-clock epoch seconds, not monotonic: this is published as a
        # builtin_interfaces/Time and a monotonic epoch renders as 1970.
        assert task.status_changed > 1_600_000_000

    def test_mark_failed_is_reachable_and_carries_the_reason(self):
        q = TaskQueue()
        q.add_task('t1', 'excavate', 0, 0)
        q.mark_failed('t1', 'drill stalled')
        assert q.get_task('t1').status == TaskStatus.FAILED
        assert q.get_task('t1').status_reason == 'drill stalled'

    def test_the_status_listener_fires_once_per_real_change(self):
        seen = []
        q = TaskQueue()
        q.set_status_listener(lambda task, prev: seen.append(
            (task.task_id, prev.name, task.status.name)))
        q.add_task('t1', 'prospect', 0, 0)          # no transition
        q.set_status('t1', TaskStatus.AUCTIONING)
        q.set_status('t1', TaskStatus.AUCTIONING)   # no-op, same status
        q.assign_to_robot('t1', 'scout_01')
        q.mark_complete('t1')

        assert seen == [
            ('t1', 'PENDING', 'AUCTIONING'),
            ('t1', 'AUCTIONING', 'ASSIGNED'),
            ('t1', 'ASSIGNED', 'COMPLETED'),
        ]

    def test_begin_auction_counts_the_rounds(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0, 0)
        assert q.begin_auction('t1') == 1
        q.set_status('t1', TaskStatus.PENDING, 'auction_no_bids')
        assert q.begin_auction('t1') == 2
        assert q.get_task('t1').auction_rounds == 2

    def test_set_progress_clamps_to_the_unit_interval(self):
        q = TaskQueue()
        q.add_task('t1', 'excavate', 0, 0)
        q.set_progress('t1', 0.42)
        assert q.get_task('t1').progress == 0.42
        q.set_progress('t1', 5.0)
        assert q.get_task('t1').progress == 1.0
        q.set_progress('t1', -1.0)
        assert q.get_task('t1').progress == 0.0


class TestNewTaskEntryFields:

    def test_every_new_field_defaults_so_old_call_sites_are_unaffected(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0, 0)     # the pre-2026-07-30 signature
        t = q.get_task('t1')
        assert t.site_id == ''
        assert t.quantity_kg == 0.0
        assert t.preferred_robot == ''
        assert t.progress == 0.0
        assert t.status_reason == ''
        assert t.auction_rounds == 0
        assert t.terminal_reported is False
        # Added 2026-08-01 with operator emergency preemption. False is what
        # every HTN-generated task must be: only inject_task_logic passes True.
        assert t.emergency is False
        # PENDING, not None: a task that has never been auctioned rests in
        # PENDING anyway, so abort_auction can never restore a status the task
        # could not legitimately be in.
        assert t.status_before_auction is TaskStatus.PENDING

    def test_site_id_survives_interrupt_task(self):
        """THE reason site_id is a dataclass field and not a progress_metadata
        key: interrupt_task assigns progress_metadata WHOLESALE, so an operator
        cancel would erase the site identity of exactly the tasks about to be
        re-queued and re-run -- and a MaterialEvent whose task has no site_id
        is dropped, so mass would stop reaching the ledger after one cancel.
        """
        q = TaskQueue()
        q.add_task('t1', 'excavate', 0, 0, site_id='site_abc')
        q.assign_to_robot('t1', 'excavator_01')
        q.interrupt_task('t1', {'reason': 'operator_cancel_task'})

        assert q.get_task('t1').site_id == 'site_abc'
        assert q.get_task('t1').progress_metadata == {
            'reason': 'operator_cancel_task'}

    def test_quantity_and_preference_round_trip_through_add_task(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 1.0, 2.0, quantity_kg=12.5,
                   preferred_robot='hauler_02', site_id='site_abc')
        t = q.get_task('t1')
        assert (t.quantity_kg, t.preferred_robot, t.site_id) == \
            (12.5, 'hauler_02', 'site_abc')
