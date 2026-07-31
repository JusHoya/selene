"""``apply_robot_progress``: RobotState -> queue progress and IN_PROGRESS.

D-03. ``TaskStatus.IN_PROGRESS`` had **no production writer**. Every
status-changing call site in the repository wrote AUCTIONING, ASSIGNED,
COMPLETED, FAILED, INTERRUPTED or PENDING; the only occurrence of IN_PROGRESS
being *set* anywhere was inside ``test_e2e_integration``'s own harness, so the
test fixture was what made the transition exist at all. Meanwhile the dashboard
draws the progress bar only for ``task.status === 'IN_PROGRESS'``
(``selene_dashboard/src/components/TaskQueue.jsx:120,173-182``) and otherwise
renders an em-dash -- so ``TaskStatus.progress``, added for FR-DASH-3, reached
the browser and was discarded, and the 'RUN' badge (``:73``) and the
``--in-progress`` style (``:60``) were dead code.

These tests drive the transition from a RobotState-shaped input, which is the
only way to catch its absence: asserting on ``set_status`` directly is exactly
what let the gap survive.
"""
from __future__ import annotations

import types

import pytest

from selene_orchestrator.orchestrator_node import (  # noqa: E402
    WORKING_FSM_STATES,
    apply_robot_progress,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus  # noqa: E402


def _state(robot_id='excavator_01', fsm_state='WORKING', current_task_id='t1',
           task_progress=0.0):
    """A field bag shaped like selene_msgs/msg/RobotState."""
    return types.SimpleNamespace(
        robot_id=robot_id, fsm_state=fsm_state,
        current_task_id=current_task_id, task_progress=task_progress)


@pytest.fixture
def assigned_queue():
    """A queue holding one task assigned to ``excavator_01``."""
    queue = TaskQueue()
    queue.add_task('t1', 'excavate', 0.0, 0.0,
                   required_capabilities=['excavate'])
    queue.begin_auction('t1')
    queue.assign_to_robot('t1', 'excavator_01')
    return queue


class TestPromotion:

    @pytest.mark.parametrize('fsm_state', sorted(WORKING_FSM_STATES))
    def test_a_working_robot_promotes_its_task(self, assigned_queue,
                                               fsm_state):
        apply_robot_progress(assigned_queue, _state(fsm_state=fsm_state))

        task = assigned_queue.get_task('t1')
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.status_reason == 'robot_started'

    def test_the_transition_reaches_the_event_log(self, assigned_queue):
        """Routed through set_status so the status listener sees it.

        D-05 replays that log in every TaskQueueState; a direct
        ``task.status = ...`` assignment would move the row and leave no trace
        of when it started.
        """
        seen = []
        assigned_queue.set_status_listener(
            lambda task, previous: seen.append(
                (task.task_id, previous.name, task.status.name)))

        apply_robot_progress(assigned_queue, _state())

        assert seen == [('t1', 'ASSIGNED', 'IN_PROGRESS')]

    def test_it_fires_exactly_once_however_often_the_robot_reports(
            self, assigned_queue):
        seen = []
        assigned_queue.set_status_listener(
            lambda task, previous: seen.append(task.status.name))

        for _ in range(5):
            apply_robot_progress(assigned_queue, _state())

        assert seen == ['IN_PROGRESS']

    def test_assigned_is_not_a_working_state(self, assigned_queue):
        """ASSIGNED means the skill has not started; TaskStatus already says so.

        The agent sits in ASSIGNED until ``_handle_assigned`` plans a path, and
        promoting there would make IN_PROGRESS mean the same thing as ASSIGNED.
        """
        apply_robot_progress(assigned_queue, _state(fsm_state='ASSIGNED'))
        assert assigned_queue.get_task('t1').status == TaskStatus.ASSIGNED

    def test_returning_is_not_a_working_state(self, assigned_queue):
        """The agent only reaches RETURNING after firing TASK_COMPLETE.

        ``_on_robot_state``'s completion fallback reads RETURNING as
        "finished", so promoting there would fight it.
        """
        apply_robot_progress(assigned_queue, _state(fsm_state='RETURNING'))
        assert assigned_queue.get_task('t1').status == TaskStatus.ASSIGNED

    def test_a_robot_running_something_else_promotes_nothing(
            self, assigned_queue):
        """A free-running survey sets current_task_id to ``prospect_<n>``.

        ``agent_node._handle_idle`` does this for its own waypoint lattice, and
        an operator goto sets ``override_goto_<n>``. Neither is an orchestrator
        task id, and neither should promote whatever the robot last won.
        """
        apply_robot_progress(
            assigned_queue, _state(current_task_id='prospect_3'))
        assert assigned_queue.get_task('t1').status == TaskStatus.ASSIGNED

    def test_an_unassigned_robot_touches_nothing(self, assigned_queue):
        assert apply_robot_progress(
            assigned_queue, _state(robot_id='hauler_01')) == ''
        assert assigned_queue.get_task('t1').status == TaskStatus.ASSIGNED

    def test_the_task_stays_findable_after_promotion(self, assigned_queue):
        """``get_task_for_robot`` must keep resolving it, or the completion
        fallback and the error re-queue in ``_on_robot_state`` both stop
        firing for a task that actually started."""
        apply_robot_progress(assigned_queue, _state())
        assert assigned_queue.get_task_for_robot('excavator_01') == 't1'
        assert assigned_queue.recover_tasks_for_robot('excavator_01') == ['t1']


class TestProgressMirror:

    def test_progress_is_mirrored_onto_the_entry(self, assigned_queue):
        assert apply_robot_progress(
            assigned_queue, _state(task_progress=0.42)) == 't1'
        assert assigned_queue.get_task('t1').progress == pytest.approx(0.42)

    def test_progress_is_clamped_by_the_queue(self, assigned_queue):
        apply_robot_progress(assigned_queue, _state(task_progress=1.9))
        assert assigned_queue.get_task('t1').progress == pytest.approx(1.0)
        apply_robot_progress(assigned_queue, _state(task_progress=-0.5))
        assert assigned_queue.get_task('t1').progress == pytest.approx(0.0)

    def test_progress_is_mirrored_even_when_the_robot_is_not_working(
            self, assigned_queue):
        """Reported while ASSIGNED, so the panel is not blank before the
        skill starts."""
        apply_robot_progress(
            assigned_queue, _state(fsm_state='ASSIGNED', task_progress=0.05))
        assert assigned_queue.get_task('t1').progress == pytest.approx(0.05)
        assert assigned_queue.get_task('t1').status == TaskStatus.ASSIGNED
