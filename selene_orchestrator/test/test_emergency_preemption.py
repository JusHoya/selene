"""Operator EMERGENCY preemption of an in-flight auction (2026-08-01).

A DELIBERATE CHANGE TO AUCTION SEMANTICS, not a defect fix, and these tests are
written to hold that line rather than merely to turn a gate row green.

Until this change the orchestrator ran exactly one auction at a time and
NOTHING interrupted it: ``_auction_tick`` returned early while
``TaskAuction.is_active()``, at any priority. The decision taken was NOT "make
priority preempt" -- it was "let the operator SAY it is an emergency, and
preempt only then". So the single most important test in this file is
``test_a_non_emergency_priority_10_injection_does_not_preempt``: it is what
proves the feature is not "always preempt", and it fails the moment somebody
decides priority alone should be enough.

WHY THE INTEGRATION TESTS BIND UNBOUND METHODS. ``OrchestratorNode.__init__``
needs a live rclpy context, and ``conftest.py``'s fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so the node cannot
be constructed in this lane at all. ``_auction_tick`` and
``_preempt_for_emergency`` are pure given the six collaborators ``_FakeNode``
supplies, so they are bound to it explicitly -- the same pattern, for the same
stated reason, as ``test_simulation_stall.py::_FakeNode``. That matters here
more than usual: ``test_e2e_integration.py::_Orchestrator.tick_auction`` is a
hand-written COPY of ``_auction_tick`` and nothing compares the two, so a test
written against that harness would measure the copy. These run the shipped
function.
"""

from __future__ import annotations

import ast
import pathlib
import time
import types

import pytest

from selene_orchestrator.orchestrator_node import (   # noqa: E402
    OrchestratorNode,
    _InjectTaskContext,
    inject_task_logic,
)
from selene_orchestrator.task_auction import Bid, TaskAuction   # noqa: E402
from selene_orchestrator.task_feed import (            # noqa: E402
    AUCTION_PREEMPTED,
    OUTCOME_PREFERENCE_DROPPED,
    OUTCOME_REQUEUE,
    REQUEUE_STATUS_BY_REASON,
    resolve_auction_winner,
    should_preempt,
    task_rows,
)
from selene_orchestrator.task_queue import (           # noqa: E402
    TaskQueue,
    TaskStatus,
)


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

    def debug(self, msg):
        self.lines.append(('debug', str(msg)))

    def text(self) -> str:
        return '\n'.join(m for _lvl, m in self.lines)


class _FakeNode:
    """The minimum surface ``_auction_tick`` and ``_preempt_for_emergency`` touch.

    Every collaborator is named explicitly rather than mocked wholesale, so a
    restructuring of the call graph breaks these tests loudly instead of
    quietly exercising less than they claim to.
    """

    def __init__(self, task_queue: TaskQueue, idle=('scout_01',),
                 auction_timeout: float = 30.0, idle_capabilities=None):
        self._task_queue = task_queue
        self._auction = TaskAuction(timeout_sec=auction_timeout)
        # `idle_capabilities` is what each idle robot can do; None means "every
        # idle robot can do everything", which is what every task in this file
        # needs (they carry no required_capabilities). A test that wants the
        # capability gate to bite passes a dict and gets the real predicate.
        caps = ({rid: set() for rid in idle} if idle_capabilities is None
                else {rid: set(c) for rid, c in idle_capabilities.items()})

        def _idle_with(required):
            need = set(required or ())
            if idle_capabilities is None:
                return list(idle)
            return [rid for rid in idle if need.issubset(caps.get(rid, set()))]

        self.stranded: list[str] = []
        self._fleet = types.SimpleNamespace(
            get_idle_robots=lambda: list(idle),
            get_idle_robots_with_capabilities=_idle_with,
            note_stranded_bidders=lambda ids: self.stranded.extend(ids))
        self._announce_pub = types.SimpleNamespace(
            publish=lambda msg: self.published.append(msg))
        self.alerts: list[tuple[str, str, str]] = []
        self.announced: list[str] = []
        self.published: list = []
        self.resolved: list[str] = []
        self.woke = 0
        self._logger = _Logger()

    # -- collaborators ------------------------------------------------------

    def get_logger(self):
        return self._logger

    def get_clock(self):
        return types.SimpleNamespace(
            now=lambda: types.SimpleNamespace(to_msg=lambda: object()))

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def _publish_announcement(self, task):
        self.announced.append(task.task_id)

    def _authorise_quantity(self, task):
        # (kg, block_reason). Nothing in this file exercises the D-06 ledger
        # gate; a haul that the ledger cannot cover is test_material_ledger's.
        return (0.0, '')

    def _note_haul_block(self, task, reason):
        pass

    def _wake_on_fleet_change(self):
        # Counted, not stubbed away: test_auction_backoff.py asserts by AST
        # that _auction_tick calls this, and a fake that silently absorbed the
        # call would let the two tests disagree about what runs.
        self.woke += 1

    def _resolve_auction(self):
        self.resolved.append(self._auction.get_task_id())
        self._auction.reset()

    # -- the production code under test ------------------------------------

    def _preempt_for_emergency(self, now):
        return OrchestratorNode._preempt_for_emergency(self, now)

    def _servable_by_idle_fleet(self, task):
        return OrchestratorNode._servable_by_idle_fleet(self, task)

    def tick(self):
        OrchestratorNode._auction_tick(self)

    def open_auction_on(self, task_id: str) -> None:
        """Put *task_id* into a live auction, the way _auction_tick would."""
        self._task_queue.begin_auction(task_id)
        self._auction.start(task_id, time.monotonic())


def _queue_with_running_survey(priority: float = 5.0) -> TaskQueue:
    q = TaskQueue()
    q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=priority)
    return q


def _inject_emergency(q: TaskQueue, task_id: str = 'manual_0000',
                      priority: float = 10.0, emergency: bool = True,
                      task_type: str = 'prospect') -> None:
    q.add_task(task_id, task_type, -100.0, -150.0, priority=priority,
               emergency=emergency)


# --------------------------------------------------------------------------- #
#  should_preempt -- the whole decision, in isolation                          #
# --------------------------------------------------------------------------- #

class _T:
    """A duck-typed task. Deliberately not a TaskEntry: should_preempt is
    documented as reading four attributes, and this is what proves it."""

    def __init__(self, task_id='t', priority=5.0, emergency=False,
                 task_type='prospect'):
        self.task_id = task_id
        self.priority = priority
        self.emergency = emergency
        self.task_type = task_type


class TestShouldPreempt:

    def test_an_emergency_at_higher_priority_preempts(self):
        assert should_preempt(
            _T('survey_a', 5.0),
            _T('manual_0000', 10.0, emergency=True)) is True

    def test_a_non_emergency_at_higher_priority_does_not(self):
        """THE USER'S DECISION, stated as a test.

        Priority 10.0 is what EVERY operator injection carries, emergency or
        not. If this ever passes with emergency=False the feature has silently
        become "always preempt", which is the thing the design refuses.
        """
        assert should_preempt(
            _T('survey_a', 5.0),
            _T('manual_0000', 10.0, emergency=False)) is False

    def test_two_emergencies_at_equal_priority_never_preempt_each_other(self):
        """THE TERMINATION ARGUMENT.

        Every operator injection is priority 10.0, so two emergencies are
        ALWAYS at equal priority. Were this to preempt, the second injection
        would abort the first's auction, the first would abort the second's on
        the next tick, and the auction slot would be traded forever without a
        round ever resolving.
        """
        a = _T('manual_0000', 10.0, emergency=True)
        b = _T('manual_0001', 10.0, emergency=True)
        assert should_preempt(a, b) is False
        assert should_preempt(b, a) is False

    def test_an_emergency_does_not_preempt_a_higher_priority_task(self):
        assert should_preempt(
            _T('critical', 12.0),
            _T('manual_0000', 10.0, emergency=True)) is False

    def test_a_task_cannot_preempt_its_own_auction(self):
        """Otherwise an emergency holding the slot would abort its own round
        and immediately re-open it, forever."""
        running = _T('manual_0000', 10.0, emergency=True)
        same = _T('manual_0000', 10.0, emergency=True)
        assert should_preempt(running, same) is False

    def test_a_select_site_candidate_never_preempts(self):
        """select_site is virtual: _auction_tick skips it, so aborting a real
        auction for one would strand the slot."""
        assert should_preempt(
            _T('survey_a', 5.0),
            _T('sel', 10.0, emergency=True, task_type='select_site')) is False

    def test_no_candidate_preempts_nothing(self):
        assert should_preempt(_T('survey_a', 5.0), None) is False

    def test_a_vanished_running_task_may_be_preempted_by_an_emergency(self):
        """The auctioned task left the queue between two ticks. There is no
        priority left to compare and nothing that can be starved."""
        assert should_preempt(
            None, _T('manual_0000', 10.0, emergency=True)) is True

    def test_a_vanished_running_task_is_still_not_preempted_by_an_ordinary_one(self):
        assert should_preempt(None, _T('survey_b', 99.0)) is False


# --------------------------------------------------------------------------- #
#  The auction tick -- the semantics change itself                             #
# --------------------------------------------------------------------------- #

class TestAuctionTickPreemption:

    def test_an_emergency_preempts_an_in_flight_lower_priority_auction(self):
        """(a) The headline behaviour, end to end through the shipped tick."""
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        assert node._auction.is_active()

        _inject_emergency(q)
        node.tick()

        # The victim is out of the auction and back in the queue...
        assert q.get_task('survey_a').status is TaskStatus.PENDING
        assert q.get_task('survey_a').status_reason == AUCTION_PREEMPTED
        # ...and the emergency took the slot IN THE SAME TICK, not the next.
        assert node._auction.get_task_id() == 'manual_0000'
        assert node._auction.is_active()
        assert node.announced == ['manual_0000']
        assert node.resolved == [], 'the victim auction must not RESOLVE'

    def test_a_non_emergency_priority_10_injection_does_not_preempt(self):
        """(b) THE TEST THAT PROVES THIS IS NOT "ALWAYS PREEMPT".

        Same fixture as the test above, same priority 10.0, same idle robot.
        The only difference is the flag the operator did not set, and the
        outcome is the pre-existing behaviour: the injection waits.
        """
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')

        _inject_emergency(q, emergency=False)
        node.tick()

        assert q.get_task('survey_a').status is TaskStatus.AUCTIONING
        assert node._auction.get_task_id() == 'survey_a'
        assert node.announced == []
        assert node.alerts == []
        assert q.get_task('manual_0000').status is TaskStatus.PENDING

    def test_preemption_refunds_the_preferred_robot_round(self):
        """(c) A preemption must not expire ANOTHER operator's preference.

        ``resolve_auction_winner`` drops a preferred_robot once
        ``auction_rounds`` reaches inject_preferred_robot_max_rounds. That
        count is supposed to mean "the robot you asked for did not bid this
        many times". A round that was aborted rather than resolved taught
        nobody anything, so charging it would drop the preference for a reason
        that has nothing to do with the preferred robot.
        """
        max_rounds = 2
        q = TaskQueue()
        q.add_task('haul_a', 'haul', 0.0, 0.0, priority=5.0,
                   preferred_robot='hauler_02')
        node = _FakeNode(q)

        node.open_auction_on('haul_a')            # round 1
        assert q.get_task('haul_a').auction_rounds == 1
        _inject_emergency(q)
        node.tick()                               # preempted: round refunded
        assert q.get_task('haul_a').auction_rounds == 0

        # The next real round is round 1 again, so the preference SURVIVES.
        # Without the refund this would be round 2 of 2 and be dropped.
        q.begin_auction('haul_a')
        winner, outcome, reason = resolve_auction_winner(
            q.get_task('haul_a'), [Bid('haul_a', 'hauler_01', 0.99, 1.0, 1.0)],
            max_rounds)
        assert winner is None
        assert outcome == OUTCOME_REQUEUE
        assert reason == 'preferred_robot_absent'
        assert q.get_task('haul_a').preferred_robot == 'hauler_02'

    def test_without_the_refund_the_preference_would_have_been_dropped(self):
        """The counterfactual for the test above, so 'refunded' is falsifiable.

        Same two rounds, no preemption in between: the preference IS dropped.
        If the refund ever stops working, the test above turns into this one.
        """
        q = TaskQueue()
        q.add_task('haul_a', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        q.begin_auction('haul_a')
        q.set_status('haul_a', TaskStatus.PENDING, 'auction_no_bids')
        q.begin_auction('haul_a')
        _winner, outcome, reason = resolve_auction_winner(
            q.get_task('haul_a'), [Bid('haul_a', 'hauler_01', 0.99, 1.0, 1.0)],
            2)
        assert outcome == OUTCOME_PREFERENCE_DROPPED
        assert reason == 'preference_dropped'

    def test_preemption_does_not_feed_the_d20_backoff(self):
        """(d) A preemption is the ORCHESTRATOR'S choice, not the fleet's.

        ``failed_auctions`` and ``auction_backoff_until`` mean "the fleet did
        not bid on this". Nobody was given the chance to bid, so neither may
        move -- in either direction. The assertion is on both, because
        CLEARING the backoff would be as wrong as charging it: it would reward
        a task for being interrupted and hand it back the auction slot D-20
        took away.
        """
        q = _queue_with_running_survey()
        # Arrive with real backoff history, so "untouched" is observable.
        q.defer_auction('survey_a', 5.0, now=time.monotonic())
        before_failures = q.get_task('survey_a').failed_auctions
        before_deadline = q.get_task('survey_a').auction_backoff_until
        assert before_failures == 1 and before_deadline > 0.0

        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()

        task = q.get_task('survey_a')
        assert task.failed_auctions == before_failures
        assert task.auction_backoff_until == before_deadline

    def test_an_interrupted_victim_returns_to_interrupted(self):
        """(e) D-03's distinction survives a preemption.

        An operator-cancelled task rests in INTERRUPTED -- "was started, was
        stopped, awaiting re-auction". Forcing it to PENDING on the way out of
        an aborted auction would erase exactly what tells a cancelled task
        apart from one that never ran, which is the defect D-03 exists to fix,
        reintroduced through a side door.
        """
        q = TaskQueue()
        q.add_task('survey_a', 'prospect', 0.0, 0.0, priority=5.0)
        q.assign_to_robot('survey_a', 'scout_01')
        q.interrupt_task('survey_a', {'reason': 'operator_cancel_task'},
                         reason='operator_cancel_task')
        assert q.get_task('survey_a').status is TaskStatus.INTERRUPTED

        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()

        assert q.get_task('survey_a').status is TaskStatus.INTERRUPTED
        assert q.get_task('survey_a').status_reason == AUCTION_PREEMPTED

    def test_a_pending_victim_returns_to_pending(self):
        """The other half of (e): restoring is not "always INTERRUPTED" either."""
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()
        assert q.get_task('survey_a').status is TaskStatus.PENDING

    def test_the_preemption_produces_exactly_one_task_event(self):
        """The event comes free from abort_auction's status change.

        A second, hand-appended event would double-count the transition in the
        32-entry ring the dashboard replays.
        """
        q = _queue_with_running_survey()
        seen: list[tuple[str, str, str]] = []
        q.set_status_listener(
            lambda t, prev: seen.append(
                (t.task_id, prev.name, t.status.name)))
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        seen.clear()
        node.tick()

        assert seen == [
            ('survey_a', 'AUCTIONING', 'PENDING'),
            ('manual_0000', 'PENDING', 'AUCTIONING'),
        ]

    def test_the_preemption_is_alerted_and_logged_naming_both_tasks(self):
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()

        (severity, source, message) = node.alerts[0]
        assert severity == 'WARNING'
        assert source == '', 'no robot did this; the orchestrator did'
        assert 'manual_0000' in message and 'survey_a' in message
        assert 'NOT cancelled' in message
        log = node._logger.text()
        assert 'PREEMPTED' in log
        assert 'manual_0000' in log and 'survey_a' in log

    def test_the_victims_bids_are_discarded(self):
        """They were made for a round that will not resolve.

        Nothing in this system tells a stranded bidder its auction went away;
        the agent returns to IDLE on its own auction_timeout_sec. What must
        not happen is the bid surviving into the emergency's round and winning
        it for a task the robot never heard announced.
        """
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        node._auction.add_bid(Bid('survey_a', 'scout_01', 0.9, 30.0, 80.0))
        assert node._auction.get_bid_count() == 1

        _inject_emergency(q)
        node.tick()

        assert node._auction.get_task_id() == 'manual_0000'
        assert node._auction.get_bids() == []

    def test_two_emergencies_terminate_instead_of_trading_the_slot(self):
        """(f) again, but through the tick, which is where a loop would live.

        Twenty ticks with two emergencies queued: the auction opened on the
        first tick must still be the live one, and nothing may have been
        preempted, because the two are at equal priority.
        """
        q = TaskQueue()
        _inject_emergency(q, 'manual_0000')
        _inject_emergency(q, 'manual_0001')
        node = _FakeNode(q)

        node.tick()
        first = node._auction.get_task_id()
        assert first in ('manual_0000', 'manual_0001')
        for _ in range(20):
            node.tick()

        assert node._auction.get_task_id() == first
        assert node.announced == [first], node.announced
        assert node.alerts == []
        assert q.get_task(first).auction_rounds == 1

    def test_an_emergency_does_not_preempt_when_no_auction_is_running(self):
        """There is nothing to preempt; it simply wins the slot normally."""
        q = _queue_with_running_survey()
        _inject_emergency(q)
        node = _FakeNode(q)
        node.tick()
        assert node._auction.get_task_id() == 'manual_0000'
        assert node.alerts == [], 'no preemption happened, so no alert'
        assert q.get_task('survey_a').status is TaskStatus.PENDING

    def test_a_timed_out_auction_still_resolves_rather_than_being_preempted(self):
        """Resolution wins over preemption when both are available.

        A timed-out auction has bids to count. Aborting it instead would throw
        away a completed round and cost the fleet an assignment it had already
        earned -- strictly worse than the ~500 ms the emergency waits.
        """
        q = _queue_with_running_survey()
        node = _FakeNode(q, auction_timeout=0.0)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()

        assert node.resolved == ['survey_a']
        assert node.alerts == []
        assert node.announced == []

    def test_the_preemption_is_not_spent_when_no_robot_is_idle_to_take_it(self):
        """THE PREEMPTION IS ONLY SPENT WHEN IT BUYS SOMETHING.

        A robot that bid on the running auction is in BIDDING, not IDLE, and
        nothing in this system tells a bidder its auction went away. Aborting
        anyway would empty the auction slot, throw away a live bid and strand
        that bidder for its own 7.0 s agent timeout -- LONGER than the 5.0 s the
        orchestrator's own window had left -- and announce nothing, because the
        fall-through hits the same empty idle set.

        So nothing happens: the running auction is left to resolve, the victim
        keeps its round, and the emergency's one preemption stays UNSPENT for a
        tick on which it can be used.
        """
        q = _queue_with_running_survey()
        node = _FakeNode(q, idle=())
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()

        assert node._auction.is_active()
        assert node._auction.get_task_id() == 'survey_a'
        victim = q.get_task('survey_a')
        assert victim.status is TaskStatus.AUCTIONING
        assert victim.auction_rounds == 1, 'the round was not refunded'
        assert node.announced == []
        assert node.alerts == [], 'nothing was preempted, so nothing is alerted'
        emergency = q.get_task('manual_0000')
        assert emergency.preemption_spent is False
        assert emergency.auction_rounds == 0
        assert emergency.failed_auctions == 0
        assert emergency.auction_backoff_until == 0.0

    def test_no_idle_robot_has_the_capability_is_the_same_refusal(self):
        """The idle set is not empty -- it just cannot bid on this task.

        ``_auction_tick``'s idle gate is a bare ``if not idle``, so before this
        a single idle EXCAVATOR was enough to spend a prospect-only emergency's
        preemption and then burn its auction round. The predicate asks the
        question the agent asks: can some idle robot do this job at all?
        """
        q = TaskQueue()
        q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=5.0)
        q.add_task('manual_0000', 'prospect', -100.0, -150.0, priority=10.0,
                   emergency=True, required_capabilities=['prospect'])
        node = _FakeNode(q, idle=('excavator_01',),
                         idle_capabilities={'excavator_01': ['excavate']})
        node.open_auction_on('survey_a')
        node.tick()

        assert node._auction.get_task_id() == 'survey_a'
        assert q.get_task('manual_0000').preemption_spent is False
        assert node.announced == []

    def test_a_ledger_blocked_emergency_never_takes_the_slot(self):
        """The D-06 gate is asked BEFORE anything is destroyed.

        ``should_preempt`` is pure and filters only ``select_site``; it cannot
        know that ``inject_task_logic`` accepts a haul the ledger has no
        material for, which ``_auction_tick`` then refuses to announce. Choosing
        the candidate before that refusal is how a live auction gets taken away
        and given to nobody -- and, because the blocked emergency stays the
        queue's highest-priority answer, never given back.
        """
        q = _queue_with_running_survey()
        _inject_emergency(q, task_type='haul')
        node = _FakeNode(q)
        node._authorise_quantity = lambda task: (
            (0.0, 'no material at site') if task.task_id == 'manual_0000'
            else (0.0, ''))
        node.open_auction_on('survey_a')
        node.tick()

        assert node._auction.get_task_id() == 'survey_a'
        assert q.get_task('survey_a').status is TaskStatus.AUCTIONING
        assert q.get_task('manual_0000').preemption_spent is False
        assert node.announced == []
        assert node.alerts == []

    def test_one_injection_buys_exactly_one_abort(self):
        """THE BOUND. Nothing ever clears ``emergency``, so ``preemption_spent``
        is what stops an emergency nobody bids on aborting a fresh auction on
        every fleet change for the rest of the mission.
        """
        q = _queue_with_running_survey()
        _inject_emergency(q)
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        node.tick()
        assert node.announced == ['manual_0000']
        assert q.get_task('manual_0000').preemption_spent is True

        # The emergency's own auction now runs; put the survey back in the slot
        # the way a later tick would, and confirm the emergency cannot take it
        # a second time.
        node._auction.reset()
        q.set_status('manual_0000', TaskStatus.PENDING, 'auction_no_bids')
        node.open_auction_on('survey_a')
        node.announced.clear()
        node.alerts.clear()
        node.tick()

        assert node._auction.get_task_id() == 'survey_a'
        assert q.get_task('survey_a').status is TaskStatus.AUCTIONING
        assert node.announced == []
        assert node.alerts == []

    def test_the_stranded_bidders_are_named_before_the_bids_are_discarded(self):
        """``TaskAuction.reset()`` throws the bids away and nothing tells the
        bidders, so the fleet monitor is told instead -- see
        ``FleetMonitor.note_stranded_bidders``. Named BEFORE the reset, or the
        list is empty."""
        q = _queue_with_running_survey()
        _inject_emergency(q)
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        node._auction.add_bid(Bid(task_id='survey_a', robot_id='scout_02',
                                  bid_score=1.0, estimated_arrival_time=1.0,
                                  energy_after_task=0.5))
        node.tick()

        assert node.stranded == ['scout_02']

    def test_wake_on_fleet_change_still_runs_first_on_the_preempt_path(self):
        """D-20's deadlock guard is not skipped by the new branch."""
        q = _queue_with_running_survey()
        node = _FakeNode(q)
        node.open_auction_on('survey_a')
        _inject_emergency(q)
        node.tick()
        assert node.woke == 1


# --------------------------------------------------------------------------- #
#  TaskQueue.abort_auction on its own                                          #
# --------------------------------------------------------------------------- #

class TestAbortAuction:

    def test_it_declines_when_the_task_is_not_auctioning(self):
        """Restoring a COMPLETED task to PENDING would resurrect finished work."""
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0.0, 0.0)
        q.mark_complete('t1')
        assert q.abort_auction('t1', AUCTION_PREEMPTED) is False
        assert q.get_task('t1').status is TaskStatus.COMPLETED

    def test_it_declines_for_an_unknown_task(self):
        assert TaskQueue().abort_auction('nope', AUCTION_PREEMPTED) is False

    def test_the_round_counter_floors_at_zero(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0.0, 0.0)
        q.set_status('t1', TaskStatus.AUCTIONING, 'auction_started')
        assert q.get_task('t1').auction_rounds == 0
        assert q.abort_auction('t1', AUCTION_PREEMPTED) is True
        assert q.get_task('t1').auction_rounds == 0

    def test_repeated_begin_auction_does_not_record_auctioning_as_the_prior(self):
        """begin_auction is not idempotent, and the tests in test_task_feed.py
        call it repeatedly to age a preferred_robot's round count. Without the
        guard, an abort after two calls would "restore" the task to AUCTIONING
        -- the state it was trying to leave."""
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0.0, 0.0)
        q.assign_to_robot('t1', 'scout_01')
        q.interrupt_task('t1', {}, reason='operator_cancel_task')
        q.begin_auction('t1')
        q.begin_auction('t1')
        assert q.get_task('t1').status_before_auction is TaskStatus.INTERRUPTED
        q.abort_auction('t1', AUCTION_PREEMPTED)
        assert q.get_task('t1').status is TaskStatus.INTERRUPTED

    def test_auction_preempted_is_deliberately_absent_from_the_requeue_map(self):
        """Every reason in that map answers "an auction RESOLVED; where does
        this land?" with a CONSTANT. A preempted auction did not resolve, and
        its landing place is not constant -- it is whatever the task was doing
        before. Listing it there with PENDING would be the D-03 erasure
        reached through a lookup table."""
        assert AUCTION_PREEMPTED not in REQUEUE_STATUS_BY_REASON


# --------------------------------------------------------------------------- #
#  Structural: the two paths must ask the same questions                       #
# --------------------------------------------------------------------------- #

class TestTheGatesStayInSync:
    """AST, not behaviour, and deliberately so.

    ``_preempt_for_emergency`` destroys a live auction on the strength of a
    prediction: that the SAME tick will get as far as ``_publish_announcement``.
    Every gate ``_auction_tick`` applies between choosing the task and opening
    the auction is therefore a gate the preempt path has to apply FIRST, or the
    slot is emptied for a task that is then not announced -- and, because that
    task stays the queue's highest-priority answer, never announced at all.

    A behavioural test cannot see a gate that does not exist yet. This one at
    least fails loudly when a new one is added on one side only, which is the
    shape the review found: the D-06 ledger gate was on the announce path and
    not on the preempt path.
    """

    @staticmethod
    def _calls_in(name):
        """Every attribute NAMED in *name*'s body, called or merely referenced.

        Referenced as well as called, because ``_auction_tick`` hands the
        capability predicate to the queue as a value
        (``servable=self._servable_by_idle_fleet``) rather than invoking it, and
        a call-only walk would report the gate as absent from the very path that
        applies it.
        """
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / 'selene_orchestrator' / 'orchestrator_node.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        return {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}

    def test_both_paths_consult_the_capability_predicate(self):
        for fn in ('_auction_tick', '_preempt_for_emergency'):
            assert '_servable_by_idle_fleet' in self._calls_in(fn), fn

    def test_both_paths_consult_the_d06_ledger_gate(self):
        for fn in ('_auction_tick', '_preempt_for_emergency'):
            assert '_authorise_quantity' in self._calls_in(fn), fn

    def test_the_preempt_path_spends_the_shot_and_releases_the_backoff(self):
        calls = self._calls_in('_preempt_for_emergency')
        assert 'spend_preemption' in calls, (
            'nothing bounds how many auctions one emergency may abort')
        assert 'release_auction_backoff' in calls, (
            'the emergency may have been reached through its own D-20 backoff; '
            'without releasing it the fall-through skips the very task the '
            'abort was performed for')
        assert 'note_stranded_bidders' in calls, (
            'the bidders whose bids reset() discards arrive in IDLE through '
            'the one transition FleetMonitor ignores')

    def test_the_preempt_path_asks_for_the_preemption_candidate(self):
        """``get_next_ready`` hides a backed-off task, and the emergency is the
        likeliest task in the queue to be in a backoff."""
        calls = self._calls_in('_preempt_for_emergency')
        assert 'get_preemption_candidate' in calls
        assert 'get_next_ready' not in calls


# --------------------------------------------------------------------------- #
#  get_next_ready's tie-break                                                  #
# --------------------------------------------------------------------------- #

class TestGetNextReadyTieBreak:

    def test_an_emergency_wins_a_tie_at_equal_priority(self):
        """(g) Two operator injections are ALWAYS at equal priority (10.0), so
        without this the winner is dict insertion order."""
        q = TaskQueue()
        q.add_task('ordinary', 'prospect', 0.0, 0.0, priority=10.0)
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        assert q.get_next_ready(now=0.0).task_id == 'urgent'

    def test_the_tie_break_is_order_independent(self):
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.add_task('ordinary', 'prospect', 0.0, 0.0, priority=10.0)
        assert q.get_next_ready(now=0.0).task_id == 'urgent'

    def test_priority_still_decides_first(self):
        """An emergency does NOT outrank a higher-priority task. The tie-break
        settles ties; it is not a second priority scale."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.add_task('critical', 'prospect', 0.0, 0.0, priority=12.0)
        assert q.get_next_ready(now=0.0).task_id == 'critical'

    def test_a_deferred_emergency_is_still_skipped(self):
        """The tie-break is applied AFTER D-20's deferral filter, deliberately.
        An emergency inside its backoff window is not auctionable, and making
        it so here would hand one task the slot D-20 exists to protect."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.add_task('ordinary', 'prospect', 0.0, 0.0, priority=5.0)
        q.defer_auction('urgent', 10.0, now=1000.0)
        assert q.get_next_ready(now=1001.0).task_id == 'ordinary'

    def test_servable_skips_rather_than_returns(self):
        """A task no idle robot can bid on must not stop the queue behind it.

        Returning instead of skipping would let one top-priority emergency
        excavate, with the only excavator busy, stop ten surveys being auctioned
        to three idle scouts.
        """
        q = TaskQueue()
        q.add_task('urgent', 'excavate', 0.0, 0.0, priority=10.0,
                   emergency=True, required_capabilities=['excavate'])
        q.add_task('survey', 'prospect', 0.0, 0.0, priority=5.0,
                   required_capabilities=['prospect'])
        servable = lambda t: 'prospect' in t.required_capabilities  # noqa: E731
        assert q.get_next_ready(0.0, servable=servable).task_id == 'survey'
        # And with no predicate the answer is the pre-existing one.
        assert q.get_next_ready(0.0).task_id == 'urgent'


# --------------------------------------------------------------------------- #
#  get_preemption_candidate, spend_preemption, release_auction_backoff         #
# --------------------------------------------------------------------------- #

class TestPreemptionCandidate:
    """The blind spot that made the whole mechanism unreachable in practice.

    ``_preempt_for_emergency`` used to ask ``get_next_ready``, which SKIPS a
    task inside its D-20 backoff -- and the emergency, injected into a fleet
    busy enough to be worth an emergency, is the likeliest task in the queue to
    be in one. So the decision that was supposed to act on it could not see it,
    and a priority-5.0 survey was free to take the auction slot and the one
    capable robot.
    """

    def test_a_backed_off_emergency_is_still_a_preemption_candidate(self):
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.add_task('ordinary', 'prospect', 0.0, 0.0, priority=5.0)
        q.defer_auction('urgent', 10.0, now=1000.0)

        assert q.get_next_ready(1001.0).task_id == 'ordinary'
        assert q.get_preemption_candidate(1001.0).task_id == 'urgent'

    def test_an_abandoned_emergency_is_still_a_preemption_candidate(self):
        """``abandon_auction`` writes math.inf, which no clock releases."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.abandon_auction('urgent')
        assert q.get_next_ready(1e9) is None
        assert q.get_preemption_candidate(1e9).task_id == 'urgent'

    def test_a_backed_off_ORDINARY_task_is_not_reached_through(self):
        """D-20 still binds on everything that is not an unspent emergency."""
        q = TaskQueue()
        q.add_task('ordinary', 'prospect', 0.0, 0.0, priority=10.0)
        q.defer_auction('ordinary', 10.0, now=1000.0)
        assert q.get_preemption_candidate(1001.0) is None

    def test_a_SPENT_emergency_is_not_reached_through_either(self):
        """THE BOUND, at the queue layer. Once the shot is spent the emergency
        is an ordinary priority-10.0 task and D-20 binds on it like anything
        else -- which is what stops it aborting a fresh auction every time
        ``wake_deferred_auctions`` releases it."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.defer_auction('urgent', 10.0, now=1000.0)
        assert q.spend_preemption('urgent') is True
        assert q.get_preemption_candidate(1001.0) is None

    def test_spend_preemption_is_idempotent_and_reports_it(self):
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, emergency=True)
        assert q.spend_preemption('urgent') is True
        assert q.spend_preemption('urgent') is False
        assert q.spend_preemption('nosuch') is False

    def test_release_auction_backoff_keeps_the_failure_count(self):
        """Deliberately NOT ``clear_auction_backoff``.

        The emergency has to be visible to ``get_next_ready`` in the same tick
        that aborted an auction for it, or the slot is taken from a live auction
        and given to nobody. What it must NOT do is re-arm D-20's escalation:
        an emergency that keeps failing still has to reach
        ``auction_max_failed_rounds`` and be abandoned.
        """
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, priority=10.0,
                   emergency=True)
        q.defer_auction('urgent', 10.0, now=1000.0)
        q.defer_auction('urgent', 10.0, now=1000.0)
        q.release_auction_backoff('urgent')

        entry = q.get_task('urgent')
        assert entry.auction_backoff_until == 0.0
        assert entry.failed_auctions == 2, (
            'clear_auction_backoff would have zeroed this and re-armed the '
            'escalation D-20 needs in order to terminate')
        assert q.get_next_ready(1001.0).task_id == 'urgent'

    def test_the_candidate_honours_servable_too(self):
        """Aborting a live auction to announce something nobody idle can bid on
        is the worst of both outcomes."""
        q = TaskQueue()
        q.add_task('urgent', 'excavate', 0.0, 0.0, priority=10.0,
                   emergency=True, required_capabilities=['excavate'])
        q.defer_auction('urgent', 10.0, now=1000.0)
        assert q.get_preemption_candidate(
            1001.0, servable=lambda t: False) is None


# --------------------------------------------------------------------------- #
#  The wire and the injection handler                                          #
# --------------------------------------------------------------------------- #

class _Req:
    def __init__(self, emergency=False, task_type='prospect'):
        self.task_type = task_type
        self.target_location = types.SimpleNamespace(x=-100.0, y=-150.0, z=0.0)
        self.quantity = 0.0
        self.assigned_robot_id = ''
        self.emergency = emergency


class _Resp:
    def __init__(self):
        self.success = False
        self.task_id = ''
        self.message = ''


def _ctx(q: TaskQueue, alerts: list):
    return _InjectTaskContext(
        task_queue=q,
        fleet_monitor=types.SimpleNamespace(get_robot=lambda rid: None),
        next_task_id=lambda: q.make_unique_task_id('manual'),
        now_stamp=object(),
        publish_alert=lambda sev, msg: alerts.append((sev, msg)),
        site_id='site_0001',
    )


class TestInjectTaskStoresTheFlag:

    @pytest.mark.parametrize('emergency', [True, False])
    def test_the_flag_reaches_the_queue_entry(self, emergency):
        """(h) first half."""
        q, alerts = TaskQueue(), []
        out = inject_task_logic(_ctx(q, alerts), _Req(emergency=emergency),
                                _Resp())
        assert out.success is True
        assert q.get_task(out.task_id).emergency is emergency

    def test_the_response_states_the_consequence_for_an_emergency(self):
        """(h) second half. This string is the operator's toast AND the
        TaskEvent detail in the dashboard history, so it is the whole account
        of a semantics change the operator just triggered."""
        q, alerts = TaskQueue(), []
        out = inject_task_logic(_ctx(q, alerts), _Req(emergency=True), _Resp())
        assert 'EMERGENCY' in out.message
        assert 'preempts an auction already in flight' in out.message
        assert any('EMERGENCY' in m for _sev, m in alerts)

    def test_the_response_states_the_consequence_for_a_non_emergency(self):
        """Stated in BOTH directions: "waits for the auction in flight" is the
        behaviour a reader is most likely to assume priority 10.0 overrides."""
        q, alerts = TaskQueue(), []
        out = inject_task_logic(_ctx(q, alerts), _Req(emergency=False), _Resp())
        assert 'not an emergency' in out.message
        assert 'waits for any auction already in flight' in out.message
        assert 'EMERGENCY' not in out.message

    def test_a_request_without_the_field_degrades_to_non_emergency(self):
        """An older client, or a hand-built request in a ROS-free lane. The
        fail-safe default and the backward-compatible default are the same
        one: False is exactly today's behaviour."""
        q, alerts = TaskQueue(), []
        req = _Req()
        del req.emergency
        out = inject_task_logic(_ctx(q, alerts), req, _Resp())
        assert out.success is True
        assert q.get_task(out.task_id).emergency is False

    def test_the_priority_is_still_10_either_way(self):
        """Emergency is not a priority bump. If it ever becomes one, the
        equal-priority termination argument in should_preempt stops holding."""
        q, alerts = TaskQueue(), []
        a = inject_task_logic(_ctx(q, alerts), _Req(emergency=True), _Resp())
        b = inject_task_logic(_ctx(q, alerts), _Req(emergency=False), _Resp())
        assert q.get_task(a.task_id).priority == 10.0
        assert q.get_task(b.task_id).priority == 10.0


class TestProjectionAndAnnouncement:

    def test_task_rows_projects_emergency(self):
        """(i) The dict keys are TaskStatus.msg's field names by contract, so a
        missing one is a KeyError in the publisher rather than a dashboard
        default."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 0.0, 0.0, emergency=True)
        q.add_task('ordinary', 'prospect', 0.0, 0.0)
        rows = {r['task_id']: r for r in task_rows(q)}
        assert rows['urgent']['emergency'] is True
        assert rows['ordinary']['emergency'] is False

    def test_htn_style_tasks_are_never_emergency(self):
        """The default is what guarantees it, and the four htn_planner call
        sites pass nothing. Only inject_task_logic ever passes True."""
        q = TaskQueue()
        q.add_task('survey_1', 'prospect', 0.0, 0.0, priority=5.0)
        assert q.get_task('survey_1').emergency is False

    def test_the_announcement_carries_the_flag(self):
        """(j) Through the shipped _publish_announcement, not a re-implementation."""
        q = TaskQueue()
        q.add_task('urgent', 'prospect', 1.0, 2.0, priority=10.0,
                   emergency=True)
        q.add_task('ordinary', 'prospect', 1.0, 2.0, priority=5.0)
        node = _FakeNode(q)

        OrchestratorNode._publish_announcement(node, q.get_task('urgent'))
        OrchestratorNode._publish_announcement(node, q.get_task('ordinary'))

        assert [m.emergency for m in node.published] == [True, False]
        assert [m.task_id for m in node.published] == ['urgent', 'ordinary']
