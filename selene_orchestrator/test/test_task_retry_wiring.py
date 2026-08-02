"""D2 IN PRODUCTION: the retry sweep's call site, its bound and its escalation.

WHY THIS FILE EXISTS SEPARATELY FROM ``test_task_retry.py``. That one covers the
``TaskQueue`` half and says so in its own docstring -- "the sweep has no
production caller yet -- ``_auction_tick`` must call it". Forty-odd green tests
over ``retry_failed_tasks``, ``get_transitive_dependents`` and
``TaskEntry.failed_attempts`` proved the API worked in isolation while NOTHING
IN PRODUCTION CALLED ANY OF IT: instances 8, 9 and 10 of the "wired but never
called" pattern CLAUDE.md names as the first thing to check in any new code, in
the same commit that was supposed to fix a mission-fatal deadlock. Neither
existing guard can see that shape -- ``test_no_orphan_parameters.py`` sees
declared ROS parameters, ``test_nav_params_are_read.py`` sees nav_params.yaml
keys, and nothing in the suite catches a dead METHOD. This file is the reader.

WHAT IS ACTUALLY BEING PINNED, in one sentence each:

* ``_auction_tick`` calls the sweep, on every tick, BEFORE its early returns.
* The bound is ``task_feed.TASK_MAX_ATTEMPTS`` and a task really does stop.
* Exhaustion is ANNOUNCED -- which is what turns the residual failure from a
  silent deadlock into a stated one -- and the announcement names the blast
  radius that ``get_transitive_dependents`` computes.
* ``TaskEntry.failed_attempts`` has a live production reader through that path.

WHY THE INTEGRATION TESTS BIND UNBOUND METHODS. ``OrchestratorNode.__init__``
needs a live rclpy context and ``conftest.py``'s fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so the node cannot
be constructed in this lane. ``_auction_tick``, ``_retry_failed_tasks`` and
``_report_attempts_exhausted`` are pure given the collaborators ``_FakeNode``
supplies, so they are bound to it explicitly -- the same pattern, for the same
stated reason, as ``test_emergency_preemption.py::_FakeNode`` and
``test_simulation_stall.py::_FakeNode``. That matters more than usual here:
``test_e2e_integration.py::_Orchestrator.tick_auction`` is a hand-written COPY
of ``_auction_tick`` (and, like the copy, does not model the fleet-change wake
either), so a test written against that harness would measure the copy. These
run the shipped function.
"""

from __future__ import annotations

import ast
import pathlib
import time
import types

from selene_orchestrator.orchestrator_node import OrchestratorNode
from selene_orchestrator.task_auction import TaskAuction
from selene_orchestrator.task_feed import (
    TASK_ATTEMPTS_EXHAUSTED,
    TASK_MAX_ATTEMPTS,
    TASK_RETRY_REQUEUED,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus


SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')
MSG = (pathlib.Path(__file__).resolve().parents[2]
       / 'selene_msgs' / 'msg' / 'TaskStatus.msg')


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding='utf-8'))


def _func(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_tree())
                if isinstance(n, ast.FunctionDef) and n.name == name)


# --------------------------------------------------------------------------- #
#  Fakes                                                                       #
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

    def of(self, level: str) -> list[str]:
        return [m for lvl, m in self.lines if lvl == level]

    def text(self) -> str:
        return '\n'.join(m for _lvl, m in self.lines)


class _FakeNode:
    """The minimum surface ``_auction_tick`` and the D2 sweep touch.

    Every collaborator is named explicitly rather than mocked wholesale, so a
    restructuring of the call graph breaks these tests loudly instead of
    quietly exercising less than they claim to.
    """

    def __init__(self, task_queue: TaskQueue, idle=('scout_01',)):
        self._task_queue = task_queue
        self._auction = TaskAuction(timeout_sec=30.0)
        self._attempts_exhausted_alerted: set[str] = set()
        self._fleet = types.SimpleNamespace(
            get_idle_robots=lambda: list(idle),
            get_idle_robots_with_capabilities=lambda required: list(idle),
            note_stranded_bidders=lambda ids: None)
        self.alerts: list[tuple[str, str, str]] = []
        self.announced: list[str] = []
        self.resolved: list[str] = []
        self.woke = 0
        self._logger = _Logger()

    # -- collaborators ------------------------------------------------------

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def _publish_announcement(self, task):
        self.announced.append(task.task_id)

    def _authorise_quantity(self, task):
        return (0.0, '')

    def _note_haul_block(self, task, reason):
        pass

    def _wake_on_fleet_change(self):
        # Counted, not run: test_auction_backoff.py already asserts by AST that
        # _auction_tick calls it, and driving the real one would need a real
        # FleetMonitor for a mechanism this file is not about. Counted rather
        # than dropped so a fake cannot silently absorb the call.
        self.woke += 1

    def _resolve_auction(self):
        self.resolved.append(self._auction.get_task_id())
        self._auction.reset()

    # -- the production code under test ------------------------------------

    def _retry_failed_tasks(self):
        OrchestratorNode._retry_failed_tasks(self)

    def _report_attempts_exhausted(self):
        OrchestratorNode._report_attempts_exhausted(self)

    def _preempt_for_emergency(self, now):
        return OrchestratorNode._preempt_for_emergency(self, now)

    def _servable_by_idle_fleet(self, task):
        return OrchestratorNode._servable_by_idle_fleet(self, task)

    def tick(self):
        OrchestratorNode._auction_tick(self)

    # -- helpers ------------------------------------------------------------

    def alerts_of(self, severity: str) -> list[tuple[str, str, str]]:
        return [a for a in self.alerts if a[0] == severity]

    def fail(self, task_id: str, robot_id: str, reason: str) -> None:
        """What ``_on_task_result`` does to a task a skill reported failed.

        The auction slot is released first because that is the production
        ordering: a task a skill RAN won its auction, and ``_resolve_auction``
        reset the slot before the assignment was ever published. Leaving it
        held would mean every tick after the first returned at
        ``_auction.is_active()`` and these tests would measure that instead.
        """
        self._auction.reset()
        self._task_queue.assign_to_robot(task_id, robot_id)
        self._task_queue.mark_failed(task_id, reason)


def _deadlocked_queue() -> TaskQueue:
    """The live deadlock in miniature, and the shipped chain behind it.

    ``survey_aa78d4f9`` FAILED, ``select_site_907c0627`` depends_on it and every
    excavate and haul depends on that. Kept as a four-link chain because the
    blast radius report is only interesting when direct and TRANSITIVE
    dependents differ: 'select' alone is 1, the truth is 3.
    """
    q = TaskQueue()
    q.add_task('survey', 'prospect', -95.0, -170.0, priority=5.0)
    q.add_task('select', 'select_site', -100.0, -150.0, priority=4.0,
               depends_on=['survey'])
    q.add_task('excavate', 'excavate', -100.0, -150.0, priority=3.0,
               depends_on=['select'])
    q.add_task('haul', 'haul', -100.0, -150.0, priority=3.0,
               depends_on=['excavate'])
    return q


# --------------------------------------------------------------------------- #
#  The call site -- the whole point of this file                               #
# --------------------------------------------------------------------------- #

class TestTheProductionCallSite:

    def test_the_retry_sweep_is_reachable_from_the_auction_tick(self):
        """The AST half. A method nothing calls is not a fix.

        Asserted structurally as well as behaviourally because the behavioural
        test below could be satisfied by a sweep called from anywhere, and
        WHICH callback runs it is load-bearing: the task queue is walked by
        timers on the MultiThreadedExecutor, so mutating it from a DDS
        subscription callback would race them. That is the same reason
        ``_wake_on_fleet_change`` is called here rather than in
        ``_on_robot_state``.
        """
        called = {n.func.attr for n in ast.walk(_func('_auction_tick'))
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert '_retry_failed_tasks' in called, (
            'nothing in _auction_tick retries a FAILED task, so one failed '
            'survey deadlocks select_site and the whole ISRU chain behind it, '
            'permanently. Calls found: %s' % (sorted(called),))

    def test_the_sweep_runs_before_every_early_return_in_the_tick(self):
        """Placement, not just presence.

        ``_auction_tick`` returns early four ways -- an auction is running, no
        robot is idle, no task is ready, the ledger blocks a haul. A fleet whose
        only remaining work is a failed task hits the "no task ready" return, so
        a sweep placed after it would never run in exactly the situation it
        exists for.
        """
        body = _func('_auction_tick').body
        first_return = next(
            i for i, stmt in enumerate(body)
            if any(isinstance(n, ast.Return) for n in ast.walk(stmt)))
        sweep = next(
            i for i, stmt in enumerate(body)
            if any(isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == '_retry_failed_tasks'
                   for n in ast.walk(stmt)))
        assert sweep < first_return, (
            'the retry sweep is placed after an early return in _auction_tick, '
            'so a queue whose only remaining work is a FAILED task never '
            'reaches it.')

    def test_the_sweep_still_runs_while_an_auction_holds_the_slot(self):
        """The behavioural half of the placement claim.

        ``_auction_tick`` returns as soon as it finds a live auction. Measured
        through the shipped function rather than inferred from the AST.
        """
        q = _deadlocked_queue()
        node = _FakeNode(q)
        node.fail('survey', 'scout_01', 'Path blocked, no alternate route')
        # Something else holds the single auction slot and is not timed out.
        q.add_task('other', 'prospect', 0.0, 0.0, priority=9.0)
        q.begin_auction('other')
        node._auction.start('other', time.monotonic())

        node.tick()

        assert node.announced == [], 'the tick did not return early after all'
        assert q.get_task('survey').status is TaskStatus.PENDING

    def test_the_sweep_uses_the_module_constants_and_not_literals(self):
        """The bound and the reason are ``task_feed``'s, not re-spelled here.

        A second spelling of 'skill_failed_requeued' is how the dashboard and
        TaskStatus.msg drift away from what is actually written.
        """
        call = next(
            n for n in ast.walk(_func('_retry_failed_tasks'))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == 'retry_failed_tasks')
        assert [a.id for a in call.args if isinstance(a, ast.Name)] == [
            'TASK_MAX_ATTEMPTS', 'TASK_RETRY_REQUEUED']

    def test_no_ros_parameter_was_added_for_the_retry_bound(self):
        """Rule 3, asserted here as well as globally.

        ``test_no_orphan_parameters.py`` fails the build on a DECLARED parameter
        nothing reads; it cannot see a parameter that is declared AND read, so
        it would not notice the bound becoming a knob. The value belongs to the
        layered design -- ``navigator.MAX_REPLAN_ATTEMPTS`` already bounds the
        replan one layer down -- not to a deployment.
        """
        declared = {
            n.args[0].value
            for n in ast.walk(_tree())
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == 'declare_parameter'
            and n.args and isinstance(n.args[0], ast.Constant)}
        assert not [d for d in declared
                    if 'retry' in d or 'attempt' in d], sorted(declared)


# --------------------------------------------------------------------------- #
#  The deadlock, broken, through the shipped _auction_tick                     #
# --------------------------------------------------------------------------- #

class TestTheDeadlockIsBrokenInProduction:

    def test_a_failed_survey_is_re_announced_on_the_next_tick(self):
        """One tick, both halves: back to PENDING and straight into an auction.

        The resting state is observed through the status listener rather than
        after the tick, because ``begin_auction`` moves the very same task to
        AUCTIONING in the same pass -- which IS the behaviour wanted (the retry
        costs no extra tick of latency), and would hide the PENDING it passed
        through if only the end state were asserted.
        """
        q = _deadlocked_queue()
        seen: list[tuple[str, str]] = []
        q.set_status_listener(
            lambda task, previous: seen.append(
                (task.status.name, task.status_reason)))
        node = _FakeNode(q)
        node.fail('survey', 'scout_01', 'Path blocked, no alternate route')

        # The deadlock exactly as observed: FAILED is not re-auctionable and
        # nothing downstream can become ready.
        assert q.get_task('survey').status is TaskStatus.FAILED
        assert q.get_next_ready() is None
        assert q.get_task('survey').assigned_robot == 'scout_01'

        node.tick()

        assert ('PENDING', TASK_RETRY_REQUEUED) in seen, seen
        assert node.announced == ['survey'], (
            'the retried task was not offered to the fleet in the same tick')
        assert q.get_task('survey').status is TaskStatus.AUCTIONING
        assert q.get_task('survey').assigned_robot == '', (
            'the retry kept the assignment of the robot that failed it')

    def test_the_retried_attempt_can_complete_and_unblocks_the_chain(self):
        """The retry is worth nothing if the second attempt cannot terminate.

        ``terminal_reported`` is cleared by ``retry_failed_tasks`` for exactly
        this reason: with it left set, ``_on_task_result``'s re-entry guard
        rejects the retried attempt's TaskResult and the task sits ASSIGNED
        forever -- a deadlock traded for a quieter one.
        """
        q = _deadlocked_queue()
        node = _FakeNode(q)
        node.fail('survey', 'scout_01', 'Drill actuator unavailable')
        node.tick()

        assert q.get_task('survey').terminal_reported is False
        q.assign_to_robot('survey', 'scout_02')
        q.mark_complete('survey', 'skill_complete')

        ready = q.get_next_ready()
        assert ready is not None and ready.task_id == 'select', (
            'select_site is still blocked after its dependency completed')

    def test_a_task_nothing_depends_on_is_retried_just_the_same(self):
        q = TaskQueue()
        q.add_task('lonely', 'prospect', 1.0, 2.0, priority=5.0)
        node = _FakeNode(q)
        node.fail('lonely', 'scout_01', 'Loading timed out')

        node.tick()

        assert node.announced == ['lonely']
        assert q.get_task('lonely').status is TaskStatus.AUCTIONING


# --------------------------------------------------------------------------- #
#  The bound                                                                   #
# --------------------------------------------------------------------------- #

class TestTheBoundHolds:

    def test_a_task_is_attempted_exactly_TASK_MAX_ATTEMPTS_times(self):
        """"Do not make a FAILED task retry forever", measured end to end.

        ``TASK_MAX_ATTEMPTS`` is 3 and it bounds ATTEMPTS, not retries: three
        failures, two re-queues.
        """
        q = _deadlocked_queue()
        node = _FakeNode(q)

        for attempt in range(1, TASK_MAX_ATTEMPTS + 1):
            node.fail('survey', 'scout_01', f'failure {attempt}')
            assert q.get_task('survey').failed_attempts == attempt
            node.tick()

        survey = q.get_task('survey')
        assert survey.status is TaskStatus.FAILED
        assert survey.failed_attempts == TASK_MAX_ATTEMPTS
        assert node.announced == ['survey'] * (TASK_MAX_ATTEMPTS - 1)

        # And it stays given up on, however long the mission runs.
        for _ in range(50):
            node.tick()
        assert q.get_task('survey').status is TaskStatus.FAILED
        assert node.announced == ['survey'] * (TASK_MAX_ATTEMPTS - 1)

    def test_an_operator_rejection_is_never_resurrected(self):
        """``inject_task_logic._reject`` writes FAILED through ``set_status``.

        It therefore never increments ``failed_attempts``, and the sweep refuses
        it structurally rather than by matching on ``status_reason``. Auctioning
        a rejected injection -- "unknown robot", "robot lacks capabilities" --
        to the fleet would be the sweep inventing work nobody asked for.
        """
        q = TaskQueue()
        q.add_task('manual_0000', 'excavate', 0.0, 0.0, priority=10.0)
        q.set_status('manual_0000', TaskStatus.FAILED, 'inject_rejected')
        node = _FakeNode(q)

        node.tick()

        rejected = q.get_task('manual_0000')
        assert rejected.status is TaskStatus.FAILED
        assert rejected.status_reason == 'inject_rejected'
        assert node.announced == []
        assert node.alerts == [], (
            'a rejected injection was reported as an exhausted task')


# --------------------------------------------------------------------------- #
#  The escalation -- an ANNOUNCED deadlock instead of a silent one             #
# --------------------------------------------------------------------------- #

class TestTheEscalationIsLoud:

    def _exhaust(self, node: _FakeNode, task_id: str = 'survey') -> None:
        for attempt in range(TASK_MAX_ATTEMPTS):
            node.fail(task_id, 'scout_01', f'Path blocked, attempt {attempt}')
            node.tick()

    def test_exhaustion_raises_one_CRITICAL_alert_naming_the_task(self):
        q = _deadlocked_queue()
        node = _FakeNode(q)
        self._exhaust(node)

        critical = node.alerts_of('CRITICAL')
        assert len(critical) == 1, node.alerts
        severity, source, message = critical[0]
        assert source == 'scout_01', 'the alert does not name the last robot'
        assert 'survey' in message
        assert str(TASK_MAX_ATTEMPTS) in message
        assert 'Path blocked, attempt 2' in message, (
            "the skill's own last failure reason is not in the alert")

    def test_the_alert_names_the_TRANSITIVE_blast_radius(self):
        """This is what ``get_transitive_dependents`` exists for.

        The chain is survey -> select -> excavate -> haul. Direct dependents
        are 1; the truth is 3. An alert reporting 1 would understate a
        mission-fatal event by the whole downstream chain, which is the failure
        mode the alert exists to prevent.
        """
        q = _deadlocked_queue()
        node = _FakeNode(q)
        self._exhaust(node)

        message = node.alerts_of('CRITICAL')[0][2]
        assert '3 task(s)' in message, message
        for blocked in ('select', 'excavate', 'haul'):
            assert blocked in message, message

    def test_the_alert_says_the_count_is_a_floor(self):
        """Radical honesty about the number, in the message itself.

        The excavate and haul cycles are generated only AFTER select_site
        COMPLETES, so at the moment a survey exhausts its attempts most of what
        it has killed does not exist in the queue and cannot be counted.
        """
        q = _deadlocked_queue()
        node = _FakeNode(q)
        self._exhaust(node)
        assert 'FLOOR' in node.alerts_of('CRITICAL')[0][2].upper()

    def test_a_task_blocking_nothing_is_a_WARNING_not_a_CRITICAL(self):
        """Severity carries the distinction the blast radius measures.

        The dashboard renders CRITICAL specially (AlertLog.jsx), so raising one
        for a task that blocks nothing would make the level meaningless by the
        end of a long mission.
        """
        q = TaskQueue()
        q.add_task('lonely', 'prospect', 1.0, 2.0, priority=5.0)
        node = _FakeNode(q)
        self._exhaust(node, 'lonely')

        assert node.alerts_of('CRITICAL') == []
        warnings = node.alerts_of('WARNING')
        assert len(warnings) == 1, node.alerts
        assert 'lonely' in warnings[0][2]

    def test_the_alert_is_raised_once_and_not_at_2Hz_forever(self):
        """An exhausted task NEVER leaves FAILED, so an unlatched sweep is the
        D-20 flood arriving from a third direction -- 261 identical lines, at
        twice the rate, for the rest of the mission."""
        q = _deadlocked_queue()
        node = _FakeNode(q)
        self._exhaust(node)
        assert len(node.alerts_of('CRITICAL')) == 1

        for _ in range(100):
            node.tick()

        assert len(node.alerts_of('CRITICAL')) == 1, (
            '%d alerts after 100 further ticks' % len(node.alerts_of('CRITICAL')))
        assert len(node._logger.of('error')) == 1

    def test_the_terminal_reason_is_written_without_a_second_TaskEvent(self):
        """``set_status`` finds the task already FAILED and returns at its
        ``previous == status`` guard, so the reason is updated and the listener
        does not fire. One transition, one event -- the same mechanism
        ``wake_deferred_auctions`` uses for its direct write.
        """
        q = _deadlocked_queue()
        events: list[tuple[str, str]] = []
        q.set_status_listener(
            lambda task, previous: events.append(
                (task.task_id, task.status.name)))
        node = _FakeNode(q)
        self._exhaust(node)

        assert q.get_task('survey').status_reason == TASK_ATTEMPTS_EXHAUSTED
        survey_events = [name for tid, name in events if tid == 'survey']
        # Three attempts and two re-queues, each re-queue re-entering the
        # ordinary auction in the same tick -- and NOTHING after the last
        # FAILED. An exhaustion that fired the listener would append a second
        # 'FAILED' here and evict a real transition from the 32-entry ring the
        # dashboard replays.
        assert survey_events == [
            'ASSIGNED', 'FAILED', 'PENDING', 'AUCTIONING',
            'ASSIGNED', 'FAILED', 'PENDING', 'AUCTIONING',
            'ASSIGNED', 'FAILED'], survey_events

    def test_the_last_skill_reason_survives_in_the_event_ring(self):
        """The terminal reason REPLACES the skill's on the task row, and that
        trade is only honest because the skill's string is still recoverable.
        """
        q = _deadlocked_queue()
        details: list[tuple[str, str]] = []
        q.set_status_listener(
            lambda task, previous: details.append(
                (task.status.name, task.status_reason)))
        node = _FakeNode(q)
        self._exhaust(node)

        assert ('FAILED', 'Path blocked, attempt 2') in details


# --------------------------------------------------------------------------- #
#  failed_attempts has a live production reader                                #
# --------------------------------------------------------------------------- #

class TestFailedAttemptsIsRead:
    """It was WRITTEN by ``mark_failed`` and read only by an unreachable
    method: transitively dead. These assert the two production readers it has
    now, both reached from ``_auction_tick``.
    """

    def test_the_bound_reads_it(self):
        """Read 1: ``retry_failed_tasks`` stops at the count."""
        q = _deadlocked_queue()
        node = _FakeNode(q)
        q.get_task('survey').failed_attempts = TASK_MAX_ATTEMPTS - 1
        node.fail('survey', 'scout_01', 'one more')

        node.tick()

        assert q.get_task('survey').status is TaskStatus.FAILED
        assert node.announced == []

    def test_the_escalation_reports_it(self):
        """Read 2: the alert and the log line quote the attempt count."""
        q = _deadlocked_queue()
        node = _FakeNode(q)
        for attempt in range(TASK_MAX_ATTEMPTS):
            node.fail('survey', 'scout_01', f'attempt {attempt}')
            node.tick()

        assert f'FAILED {TASK_MAX_ATTEMPTS} time(s)' in (
            node.alerts_of('CRITICAL')[0][2])
        assert f'FAILED {TASK_MAX_ATTEMPTS} time(s)' in (
            node._logger.of('error')[0])

    def test_the_retry_log_line_quotes_the_attempt_number(self):
        q = _deadlocked_queue()
        node = _FakeNode(q)
        node.fail('survey', 'scout_01', 'Path blocked, no alternate route')
        node.tick()

        (line,) = [w for w in node._logger.of('warn') if 'survey' in w]
        assert f'failed 1 of {TASK_MAX_ATTEMPTS} attempt(s)' in line, line


# --------------------------------------------------------------------------- #
#  TaskStatus.msg documents every reason this path can emit                    #
# --------------------------------------------------------------------------- #

class TestTheWireDocumentation:
    """A status_reason the message does not document is a string the dashboard
    renders as opaque text and no reader can trace. ``robot_offline`` was left
    undocumented by an earlier pass and is included here so it stays fixed.
    """

    def test_every_new_reason_is_documented_in_TaskStatus_msg(self):
        text = MSG.read_text(encoding='utf-8')
        for reason in (TASK_RETRY_REQUEUED, TASK_ATTEMPTS_EXHAUSTED,
                       'robot_offline'):
            assert f"'{reason}'" in text, (
                f'{reason!r} is written onto TaskStatus.status_reason by '
                f'production code and is not documented in TaskStatus.msg')

    def test_the_documentation_is_a_comment_and_no_field_was_added(self):
        """Rule (e): documentation only. A field change needs a rosidl
        regeneration, and this branch has had none.
        """
        fields = [ln.split()[0] for ln in
                  MSG.read_text(encoding='utf-8').splitlines()
                  if ln.strip() and not ln.startswith('#')]
        assert fields == [
            'string', 'string', 'string', 'string', 'string', 'float32',
            'float32', 'float32', 'geometry_msgs/Point', 'string', 'string[]',
            'string[]', 'string', 'builtin_interfaces/Time', 'uint32', 'bool',
        ], fields
