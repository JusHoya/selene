"""A single robot dropout must not permanently orphan a task — defect D3.

THREE INDEPENDENT OMISSIONS COMPOSE INTO A PERMANENT ORPHAN, and this file
covers the two that live in ``orchestrator_node`` / ``task_feed``. (a), the
widening of ``recover_tasks_for_robot`` to AUCTIONING and INTERRUPTED, is in
``task_queue.py`` and is pinned by ``test_task_queue.py``.

(c) IS THE ENTRY POINT. A bid does NOT refresh a heartbeat -- only
``FleetMonitor.update_robot`` does -- so a robot whose ``/<rid>/state`` stream is
lost while its bid traffic survives is declared OFFLINE at
``heartbeat_timeout_sec`` and can still bid on the next announcement.
``_resolve_auction`` then handed that bid list to a pure function with no fleet
handle at all, and the winner was written straight into ASSIGNED +
``assigned_robot``.

(b) MAKES IT PERMANENT. ``check_heartbeats`` skips a robot it has already
declared OFFLINE, so ``mark_offline`` -> ``recover_tasks_for_robot`` runs exactly
ONCE per robot. An assignment created after that one sweep is never looked at by
anything, ever.

(b) IS NEEDED EVEN WITH (c) FIXED. The liveness test inside ``_resolve_auction``
is not atomic with the ``assign_to_robot`` that follows it: every timer shares a
``ReentrantCallbackGroup`` under a 4-thread ``MultiThreadedExecutor``, so
``_heartbeat_check`` (1 Hz) and ``_auction_tick`` (2 Hz) genuinely interleave.
That interleaving is READ FROM THE SOURCE, not measured.

WHY THESE TESTS BIND UNBOUND METHODS ONTO A FAKE ``self``.
``OrchestratorNode.__init__`` needs a live rclpy context and ``conftest.py``'s
fake node returns ``SimpleNamespace(value=None)`` from every ``get_parameter``,
so the node cannot be constructed in this lane. The collaborators that matter --
``FleetMonitor`` and ``TaskQueue`` -- are REAL here, so the liveness rule and the
recovery sweep are exercised against the production objects rather than against
fakes shaped to agree with them. Same pattern as
``test_emergency_preemption_timeline.py::_Sim``.

NOT DEMONSTRATED. Nothing below is a live run: no ROS 2 on this host, and no
exit-gate row drops a robot.
"""

from __future__ import annotations

import ast
import inspect
import time

import pytest

from selene_orchestrator.fleet_monitor import FleetMonitor
from selene_orchestrator.orchestrator_node import OrchestratorNode
from selene_orchestrator.task_auction import Bid, TaskAuction
from selene_orchestrator.task_queue import TaskQueue, TaskStatus


HEARTBEAT_TIMEOUT = 10.0


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


class _Node:
    """A fake ``self`` carrying a REAL FleetMonitor and a REAL TaskQueue."""

    def __init__(self):
        self._fleet = FleetMonitor(heartbeat_timeout=HEARTBEAT_TIMEOUT)
        self._task_queue = TaskQueue()
        self._auction = TaskAuction(timeout_sec=5.0)
        self._logger = _Logger()
        self._preferred_robot_max_rounds = 3
        self._auction_backoff_base = 5.0
        self._auction_backoff_max = 60.0
        self._auction_max_failed_rounds = 3
        self._auction_failure_logged: dict[str, str] = {}
        self.alerts: list[tuple[str, str, str]] = []
        self.assignments: list[tuple[str, str]] = []
        self.motion_checks = 0
        self.distance_reports = 0

    # -- collaborators ------------------------------------------------------

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def _publish_assignment(self, task_id, robot_id, task):
        self.assignments.append((task_id, robot_id))

    def _authorise_quantity(self, task):
        return (0.0, '')

    def _note_haul_block(self, task, reason):
        pass

    def _check_motion_stalls(self):
        # Counted rather than stubbed away: test_simulation_stall.py asserts by
        # AST that _heartbeat_check calls this, and a fake that silently
        # absorbed the call would let the two tests disagree about what runs.
        self.motion_checks += 1

    def _report_distance_rejections(self):
        self.distance_reports += 1

    # -- the production code under test ------------------------------------

    def heartbeat_check(self):
        OrchestratorNode._heartbeat_check(self)

    def _recover_offline_robot_tasks(self):
        OrchestratorNode._recover_offline_robot_tasks(self)

    def _robot_is_live(self, robot_id):
        return OrchestratorNode._robot_is_live(self, robot_id)

    def resolve_auction(self):
        OrchestratorNode._resolve_auction(self)

    def _back_off_auction(self, task_id):
        return OrchestratorNode._back_off_auction(self, task_id)

    def _log_auction_failure(self, task_id, reason, bid_count, status):
        OrchestratorNode._log_auction_failure(
            self, task_id, reason, bid_count, status)

    # -- helpers ------------------------------------------------------------

    def see(self, robot_id, fsm_state='IDLE', age=0.0):
        """One RobotState, *age* seconds old on the monitor's own clock."""
        self._fleet.update_robot(
            robot_id, 'scout', fsm_state, 0.0, 0.0, 0.0, 1.0, '',
            capabilities=['prospect'], timestamp=time.monotonic() - age)

    def open_auction_on(self, task_id):
        self._task_queue.begin_auction(task_id)
        self._auction.start(task_id, time.monotonic())


@pytest.fixture
def node():
    n = _Node()
    n._task_queue.add_task('t1', 'prospect', 10.0, 20.0,
                           required_capabilities=['prospect'])
    return n


# ------------------------------------------------- (b) the permanent orphan

def test_a_task_assigned_after_the_one_and_only_sweep_is_still_recovered(node):
    """THE HEADLINE. ``check_heartbeats`` reports a robot ONCE, ever.

    Sequence: the robot goes quiet and is swept (holding nothing); THEN the task
    lands on it; then a later tick. Without the sweep the second tick sees
    ``check_heartbeats() == []`` -- the robot is already OFFLINE -- and the task
    sits ASSIGNED to a corpse forever.
    """
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node.heartbeat_check()
    assert node._fleet.get_robot('scout_01')['fsm_state'] == 'OFFLINE'

    node._task_queue.assign_to_robot('t1', 'scout_01')
    assert node._task_queue.get_task('t1').status is TaskStatus.ASSIGNED

    # The robot is already OFFLINE, so this sweep is the only thing that can
    # see the task at all.
    assert node._fleet.check_heartbeats() == []
    node.heartbeat_check()

    task = node._task_queue.get_task('t1')
    assert task.status is TaskStatus.PENDING
    assert task.assigned_robot == ''
    assert task.status_reason == 'robot_offline'


def test_the_operator_is_told_once_that_the_task_was_stranded(node):
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node.heartbeat_check()
    node._task_queue.assign_to_robot('t1', 'scout_01')
    node.alerts.clear()

    node.heartbeat_check()
    assert [a[0] for a in node.alerts] == ['ERROR']
    assert 'scout_01' in node.alerts[0][2]
    assert 't1' in node.alerts[0][2]

    # And the second sweep over the same robot finds nothing left to say.
    node.alerts.clear()
    node.heartbeat_check()
    assert node.alerts == []


def test_the_sweep_is_silent_when_there_is_nothing_to_do(node):
    """THE FLOOD GUARD. A 1 Hz sweep that spoke every tick would be D-20 again.

    D-20 measured 261 identical INFO lines for one task and the third cost --
    starving the auction slot -- was the one that mattered. An unconditional
    alert here would put the same shape into the operator's bounded ring.
    """
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node.heartbeat_check()          # declares it OFFLINE, recovers nothing
    node.alerts.clear()
    node._logger.lines.clear()

    for _ in range(20):
        node.heartbeat_check()

    assert node.alerts == []
    assert node._logger.at('warn') == []


def test_the_sweep_leaves_a_live_robots_task_alone(node):
    """The rule is "the monitor has declared this robot dead", nothing wider."""
    node.see('scout_01', fsm_state='ASSIGNED')
    node._task_queue.assign_to_robot('t1', 'scout_01')

    node.heartbeat_check()

    task = node._task_queue.get_task('t1')
    assert task.status is TaskStatus.ASSIGNED
    assert task.assigned_robot == 'scout_01'
    assert node.alerts == []


def test_the_first_sweep_still_recovers_and_still_alerts(node):
    """CONTROL: the pre-existing timed_out path is untouched.

    A fix that moved recovery entirely into the new sweep would change the alert
    an operator sees at the moment of a dropout, which is the one they act on.
    """
    node.see('scout_01', fsm_state='ASSIGNED', age=HEARTBEAT_TIMEOUT + 1.0)
    node._task_queue.assign_to_robot('t1', 'scout_01')

    node.heartbeat_check()

    task = node._task_queue.get_task('t1')
    assert task.status is TaskStatus.PENDING
    assert task.status_reason == 'heartbeat_timeout'
    assert [a[0] for a in node.alerts] == ['ERROR']
    assert 'Heartbeat timeout' in node.alerts[0][2]


def test_heartbeat_check_still_runs_its_other_two_passengers(node):
    """D-22 and D-31 share this timer; inserting a call must not displace them."""
    node.heartbeat_check()
    assert node.motion_checks == 1
    assert node.distance_reports == 1


# --------------------------------------- (c) the liveness rule, actually wired

def test_an_offline_bidder_does_not_win_against_a_live_one(node):
    """Drives the REAL ``_resolve_auction`` against a REAL FleetMonitor."""
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node.see('scout_02', fsm_state='IDLE')
    node._fleet.mark_offline('scout_01')
    node.open_auction_on('t1')
    node._auction.add_bid(Bid('t1', 'scout_01', 0.9, 10.0, 0.8))
    node._auction.add_bid(Bid('t1', 'scout_02', 0.1, 30.0, 0.5))

    node.resolve_auction()

    task = node._task_queue.get_task('t1')
    assert task.status is TaskStatus.ASSIGNED
    assert task.assigned_robot == 'scout_02'
    assert node.assignments == [('t1', 'scout_02')]


def test_an_auction_with_only_a_dead_bidder_assigns_nobody(node):
    """The harder half: nothing is elected, and the task lands re-auctionable.

    STATED HONESTLY: this is strictly better than an ASSIGNED corpse, but it is
    not "and then it gets done". The task enters D-20's backoff and needs a live
    robot to bid on a later round.
    """
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node._fleet.mark_offline('scout_01')
    node.open_auction_on('t1')
    node._auction.add_bid(Bid('t1', 'scout_01', 0.9, 10.0, 0.8))

    node.resolve_auction()

    task = node._task_queue.get_task('t1')
    assert task.status is TaskStatus.PENDING
    assert task.assigned_robot == ''
    assert task.failed_auctions == 1
    assert node.assignments == []


def test_the_discarded_bid_is_named_in_the_log(node):
    """`auction_no_bids (1 bid(s))` would contradict itself; the count is live."""
    node.see('scout_01', age=HEARTBEAT_TIMEOUT + 1.0)
    node._fleet.mark_offline('scout_01')
    node.open_auction_on('t1')
    node._auction.add_bid(Bid('t1', 'scout_01', 0.9, 10.0, 0.8))

    node.resolve_auction()

    discarded = [m for m in node._logger.at('warn') if 'declared OFFLINE' in m]
    assert len(discarded) == 1
    assert 'scout_01' in discarded[0]
    assert '(0 bid(s))' in '\n'.join(node._logger.at('info'))


def test_an_unknown_robot_is_treated_as_live(node):
    """UNKNOWN IS NOT DEAD, and the asymmetry is deliberate.

    A robot the monitor has never heard of is one whose first RobotState has not
    arrived. Refusing its bid would burn an auction round on a fleet that is
    merely still starting up.
    """
    assert node._fleet.get_robot('scout_99') is None
    assert node._robot_is_live('scout_99') is True

    node.open_auction_on('t1')
    node._auction.add_bid(Bid('t1', 'scout_99', 0.4, 10.0, 0.8))
    node.resolve_auction()

    assert node._task_queue.get_task('t1').assigned_robot == 'scout_99'


def test_a_live_bidder_still_wins_normally(node):
    """CONTROL, so a filter that rejected everything would be caught."""
    node.see('scout_01', fsm_state='IDLE')
    node.open_auction_on('t1')
    node._auction.add_bid(Bid('t1', 'scout_01', 0.4, 10.0, 0.8))

    node.resolve_auction()

    assert node._task_queue.get_task('t1').assigned_robot == 'scout_01'
    assert [m for m in node._logger.at('warn') if 'declared OFFLINE' in m] == []


# ------------------------------------------------------------- AST wiring

def _calls_in(method) -> set[str]:
    """Every ``self.<name>(...)`` called anywhere in *method*'s body."""
    tree = ast.parse(inspect.getsource(method).lstrip())
    return {
        node.func.attr
        for node in ast.walk(tree)
        if (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'self')
    }


def test_heartbeat_check_calls_the_sweep():
    """A comment or a docstring mention cannot satisfy this.

    CLAUDE.md records SEVEN production instances of "wired but never called" in
    this repository, one of them inside the measuring apparatus. A new method is
    not a fix until something calls it.
    """
    assert '_recover_offline_robot_tasks' in _calls_in(
        OrchestratorNode._heartbeat_check)


def test_resolve_auction_calls_the_liveness_predicate():
    assert '_robot_is_live' in _calls_in(OrchestratorNode._resolve_auction)


def test_resolve_auction_passes_is_live_to_the_pure_decision():
    """The predicate must reach ``resolve_auction_winner``, not just be computed.

    Filtering only in the node would leave the pure function -- the one three
    harnesses call directly with hand-built lists -- still able to elect a
    corpse.
    """
    tree = ast.parse(inspect.getsource(OrchestratorNode._resolve_auction).lstrip())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == 'resolve_auction_winner']
    assert len(calls) == 1
    assert [kw.arg for kw in calls[0].keywords] == ['is_live']
