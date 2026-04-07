"""Tests for TaskQueue."""

from selene_orchestrator.task_queue import TaskQueue, TaskStatus


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
