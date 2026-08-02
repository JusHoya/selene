"""``_on_task_result`` must terminate a task ONCE — defect D4.

THE DEFECT WAS REPRODUCED ON A RUNNING ROS 2 JAZZY STACK, not merely reasoned
about: a second TaskResult flipped an already-COMPLETED task to FAILED, and
because ``_ready_tasks`` satisfies a dependency only with COMPLETED, the
mission's ``select_site`` task was permanently deadlocked behind it.

THE GUARD ALREADY EXISTED 45 LINES ABOVE. ``_on_robot_state``'s positional
completion fallback reads ``not task.terminal_reported`` before inferring a
completion, so the FALLBACK defended itself against a task the AUTHORITATIVE
path had terminated -- while the authoritative path never defended itself
against itself. ``terminal_reported`` is documented in ``TaskEntry`` as a
one-way latch and was consulted only by the other subsystem.

WHY THESE TESTS BIND THE UNBOUND METHOD. ``OrchestratorNode.__init__`` needs a
live rclpy context and ``conftest.py``'s fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so the node cannot
be constructed in this lane at all. ``_on_task_result`` is pure given the three
collaborators ``_FakeNode`` supplies (``_task_queue``, ``get_logger()``,
``_publish_alert``), so it is bound explicitly -- the same pattern, for the same
stated reason, as ``test_emergency_preemption.py::_FakeNode`` and
``test_simulation_stall.py::_FakeNode``.

DELIBERATELY NOT WRITTEN AGAINST ``test_e2e_integration.py::_Orchestrator``.
That harness's ``report_result`` is a HAND-WRITTEN COPY of this logic and
nothing compares the two, so a test there would measure the copy and not the
shipped function.

NOT DEMONSTRATED. Every assertion below is the ROS-free lane. The DEFECT was
observed live; the FIX has not been. Two live-only questions stay open: whether
Fast DDS actually replays TaskResult history to a re-matched TRANSIENT_LOCAL
subscription, and whether the live duplicate came from such a replay or from a
second SELENE stack sharing the domain. The guard is correct under either, but
which one occurred is unmeasured.
"""

from __future__ import annotations

import pytest

from selene_msgs.msg import TaskResult

from selene_orchestrator.orchestrator_node import OrchestratorNode
from selene_orchestrator.task_queue import TaskQueue, TaskStatus


class _Logger:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def info(self, msg):
        self.lines.append(('info', str(msg)))

    def warn(self, msg):
        self.lines.append(('warn', str(msg)))

    def debug(self, msg):
        self.lines.append(('debug', str(msg)))

    def at(self, level) -> list[str]:
        return [m for lvl, m in self.lines if lvl == level]


class _FakeNode:
    """The three collaborators ``_on_task_result`` touches, and nothing else."""

    def __init__(self, task_queue: TaskQueue):
        self._task_queue = task_queue
        self.alerts: list[tuple[str, str, str]] = []
        self._logger = _Logger()

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    # -- the production code under test ------------------------------------

    def deliver(self, task_id, robot_id='scout_01', success=True,
                failure_reason='', task_type='prospect'):
        """Hand the SHIPPED ``_on_task_result`` one real TaskResult.

        Built from the real message class rather than a stand-in: ``conftest``
        stubs ``selene_msgs.msg.TaskResult`` without ROS and the generated type
        is used under ``colcon test``, so one import is correct in every lane.
        That is the D-14 / ``ROS_PYTHON_CHECK_FIELDS`` lesson. ``stamp`` is never
        read by this handler, so there is no ``builtin_interfaces/Time`` hazard
        here.
        """
        msg = TaskResult()
        msg.task_id = task_id
        msg.robot_id = robot_id
        msg.task_type = task_type
        msg.success = success
        msg.failure_reason = failure_reason
        OrchestratorNode._on_task_result(self, msg)


@pytest.fixture
def node():
    q = TaskQueue()
    q.add_task('excavate_1', 'excavate', 10.0, 20.0)
    q.assign_to_robot('excavate_1', 'scout_01')
    return _FakeNode(q)


# --------------------------------------------------------- the live defect

def test_a_second_result_cannot_flip_a_completed_task_to_failed(node):
    """The exact live flip that deadlocked ``select_site``.

    WITHOUT THE FIX the task ends FAILED with status_reason 'drill stalled',
    which is a permanent block on every task that depends on it.
    """
    node.deliver('excavate_1', success=True)
    assert node._task_queue.get_task('excavate_1').status is TaskStatus.COMPLETED

    node.deliver('excavate_1', success=False, failure_reason='drill stalled')

    task = node._task_queue.get_task('excavate_1')
    assert task.status is TaskStatus.COMPLETED
    assert task.status_reason == 'skill_complete'


def test_a_second_result_cannot_flip_a_failed_task_to_completed(node):
    """The mirror: a failed task silently reported as done is just as wrong."""
    node.deliver('excavate_1', success=False, failure_reason='drill stalled')
    assert node._task_queue.get_task('excavate_1').status is TaskStatus.FAILED

    node.deliver('excavate_1', success=True)

    task = node._task_queue.get_task('excavate_1')
    assert task.status is TaskStatus.FAILED
    assert task.status_reason == 'drill stalled'


def test_the_failure_alert_is_not_doubled(node):
    """One failure, one operator alert.

    This matters more than it looks: while a FAILED task deadlocks everything
    downstream, that single WARNING is the operator's only signal, so a
    duplicate makes the alert log misreport how many tasks failed.
    """
    node.deliver('excavate_1', success=False, failure_reason='drill stalled')
    node.deliver('excavate_1', success=False, failure_reason='drill stalled')

    assert len(node.alerts) == 1
    assert node.alerts[0][0] == 'WARNING'


# ------------------------------------ the guard must not block the fallback

def test_an_inferred_completion_can_still_be_corrected_to_failed(node):
    """THE ANTI-REGRESSION FOR THE TEMPTING WRONG FIX.

    ``if task.status in (COMPLETED, FAILED): return`` is the obvious one-liner
    and it is wrong. ``_on_robot_state``'s positional fallback calls
    ``mark_complete`` WITHOUT setting ``terminal_reported``, deliberately: the
    two messages race on different topics with no ordering guarantee, and the
    authoritative TaskResult is meant to be able to correct an INFERRED
    completion to FAILED. Status-keying blocks that correction and records a
    failed excavate as COMPLETED -- D-03's headline defect, through a side door.

    This test passes before AND after the correct fix, and FAILS against the
    status-keyed variant. It was mutation-checked against that variant
    specifically.
    """
    # Exactly what orchestrator_node's fallback does, flag included: it does not
    # set one.
    node._task_queue.mark_complete('excavate_1', 'inferred_from_robot_state')
    assert node._task_queue.get_task('excavate_1').terminal_reported is False

    node.deliver('excavate_1', success=False, failure_reason='drill stalled')

    task = node._task_queue.get_task('excavate_1')
    assert task.status is TaskStatus.FAILED
    assert task.status_reason == 'drill stalled'
    assert len(node.alerts) == 1
    assert node.alerts[0][0] == 'WARNING'


# ------------------------------------------------------------- what is said

def test_a_contradicting_duplicate_is_logged_at_warn(node):
    """Two publishers disagreeing about one task is the second-stack shape."""
    node.deliver('excavate_1', success=True)
    node.deliver('excavate_1', success=False, failure_reason='drill stalled')

    warns = [m for m in node._logger.at('warn') if 'CONTRADICTS' in m]
    assert len(warns) == 1
    assert 'excavate_1' in warns[0]
    assert 'COMPLETED' in warns[0]


def test_an_agreeing_duplicate_is_quiet(node):
    """The TRANSIENT_LOCAL replay case, and it must not look like a fault.

    Both ledger topics are RELIABLE + TRANSIENT_LOCAL on both ends, so a
    re-matched subscription can be handed an agent's history again. Ignoring the
    repeat is what ``material_event_logic``'s ``event_id`` dedupe does for the
    sibling ledger topic; a warning per replayed result would flood the bounded
    operator ring instead.
    """
    node.deliver('excavate_1', success=True)
    node.deliver('excavate_1', success=True)

    assert node._logger.at('warn') == []
    assert node.alerts == []
    assert node._task_queue.get_task('excavate_1').status is TaskStatus.COMPLETED
    assert len(node._logger.at('debug')) == 1


# ------------------------------------------- controls: the first report works

def test_a_single_success_still_completes(node):
    """A fix that no-ops everything is caught here."""
    node.deliver('excavate_1', success=True)

    task = node._task_queue.get_task('excavate_1')
    assert task.status is TaskStatus.COMPLETED
    assert task.terminal_reported is True
    assert task.status_reason == 'skill_complete'
    assert node.alerts == []


def test_a_single_failure_still_fails_and_alerts_once(node):
    node.deliver('excavate_1', success=False, failure_reason='drill stalled')

    task = node._task_queue.get_task('excavate_1')
    assert task.status is TaskStatus.FAILED
    assert task.terminal_reported is True
    assert task.status_reason == 'drill stalled'
    assert [a[0] for a in node.alerts] == ['WARNING']


def test_an_unknown_task_is_still_warned_about_and_not_alerted(node):
    """Guards against the new block being inserted above the None check."""
    node.deliver('never_added', success=True)

    warns = [m for m in node._logger.at('warn') if 'unknown task' in m]
    assert len(warns) == 1
    assert 'never_added' in warns[0]
    assert node.alerts == []
