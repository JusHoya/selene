"""The auction must stop re-announcing a task nobody bids on — deviation D-20.

MEASURED, live on ROS 2 Jazzy, 2026-07-31. Verbatim from the orchestrator log
of a run in which every scout was busy or faulted::

    Auction started for survey_8513ab73 (prospect) at (-95, -170) round=254
    Auction survey_8513ab73: auction_no_bids (0 bid(s)), re-queued as PENDING
    Auction started for survey_8513ab73 (prospect) at (-95, -170) round=255
    ...
    round=261

One task, **261 rounds**, one re-auction every ~5.5 s, forever, all at INFO.
Three costs, and the third is the one that mattered: it floods the log; it
burns the single auction SLOT, because ``_auction_tick`` runs one auction at a
time and returns early while one is active; and through that slot it starves
every other PENDING task in the queue for as long as no robot can bid.

The tests are in four groups:

* ``TestBackoffArithmetic`` / ``TestFailureReason`` — the pure schedule.
* ``TestQueueBackoff`` — what the backoff does to ``get_next_ready``, which is
  where the starvation actually lives.
* ``TestWakingOnAFleetChange`` — the deadlock the give-up state would cause if
  nothing re-opened it, and the two transitions that must NOT count as a fleet
  change.
* ``TestWiring`` — that the orchestrator calls all of it. Unit tests on a
  mechanism nothing invokes is the exact failure mode FR-MAP-3 shipped with for
  two phases (``test_adaptive_survey_wiring.py``), so the wiring is checked by
  AST here for the same reason.

Nothing here was run against ROS.
"""

import ast
import pathlib

import pytest

from selene_orchestrator.fleet_monitor import FleetMonitor
from selene_orchestrator.task_feed import (
    AUCTION_ABANDONED,
    AUCTION_BACKOFF,
    AUCTION_FLEET_CHANGED,
    AUCTION_NO_BIDS,
    REQUEUE_STATUS_BY_REASON,
    auction_backoff_sec,
    auction_failure_reason,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus

SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')

#: The shipped defaults, from orchestrator_params.yaml.
BASE = 5.0
CAP = 120.0
MAX_ROUNDS = 5


def _tree():
    return ast.parse(SOURCE.read_text(encoding='utf-8'))


# --------------------------------------------------------------------------- #
#  The schedule                                                                #
# --------------------------------------------------------------------------- #

class TestBackoffArithmetic:

    def test_the_shipped_schedule(self):
        """5, 10, 20, 40, 80, then the cap forever."""
        got = [auction_backoff_sec(n, BASE, CAP) for n in range(1, 9)]
        assert got == [5.0, 10.0, 20.0, 40.0, 80.0, 120.0, 120.0, 120.0]

    def test_the_flood_becomes_bounded(self):
        """THE REGRESSION, as a number.

        261 rounds at the measured ~5.5 s cadence is ~24 minutes of
        announcements. Under the shipped schedule the task is abandoned after
        5 failures, and those 5 span 5+10+20+40 = 75 seconds of waiting -- so
        the whole episode is 5 announcements instead of 261, and then silence.
        """
        delays = [auction_backoff_sec(n, BASE, CAP)
                  for n in range(1, MAX_ROUNDS)]
        assert sum(delays) == pytest.approx(75.0)
        assert auction_failure_reason(MAX_ROUNDS, MAX_ROUNDS) \
            == AUCTION_ABANDONED

    def test_the_cap_is_honoured_at_absurd_counts(self):
        """261 must not build 2**260 to take a min() of it."""
        assert auction_backoff_sec(261, BASE, CAP) == CAP
        assert auction_backoff_sec(10 ** 6, BASE, CAP) == CAP

    @pytest.mark.parametrize('rounds', [0, -1, -100])
    def test_no_delay_before_the_first_failure(self, rounds):
        assert auction_backoff_sec(rounds, BASE, CAP) == 0.0

    @pytest.mark.parametrize('base,cap', [(0.0, CAP), (-1.0, CAP),
                                          (BASE, 0.0), (BASE, -1.0)])
    def test_a_disabled_delay_is_zero_not_negative(self, base, cap):
        """Both come from ROS parameters an operator can set.

        A negative deadline would be in the past, which reads as "auctionable
        now" -- correct by accident. Returning 0.0 makes it correct on purpose.
        """
        assert auction_backoff_sec(3, base, cap) == 0.0


class TestFailureReason:

    def test_one_reason_per_state_not_per_round(self):
        """This is what lets the caller log on a CHANGE.

        261 identical INFO lines happened because every round carried the same
        reason and nothing compared it to the last one.
        """
        reasons = [auction_failure_reason(n, MAX_ROUNDS) for n in range(1, 8)]
        assert reasons == [
            AUCTION_NO_BIDS,
            AUCTION_BACKOFF, AUCTION_BACKOFF, AUCTION_BACKOFF,
            AUCTION_ABANDONED, AUCTION_ABANDONED, AUCTION_ABANDONED,
        ]

    def test_giving_up_can_be_disabled(self):
        """max_rounds <= 0 is a supported configuration, not a mistake."""
        for limit in (0, -1):
            assert auction_failure_reason(1, limit) == AUCTION_NO_BIDS
            assert auction_failure_reason(999, limit) == AUCTION_BACKOFF

    def test_every_reason_maps_to_a_requeue_status(self):
        """A reason with no entry would silently take the default.

        All three land in PENDING, and the point of asserting it is that PENDING
        is a decision: a task nobody bid on was never STARTED, so INTERRUPTED
        would be a lie about it (the same argument D-03 makes for
        'auction_no_bids').
        """
        for reason in (AUCTION_NO_BIDS, AUCTION_BACKOFF, AUCTION_ABANDONED):
            assert REQUEUE_STATUS_BY_REASON[reason] is TaskStatus.PENDING


# --------------------------------------------------------------------------- #
#  What it does to the queue                                                   #
# --------------------------------------------------------------------------- #

def _queue_with(*task_ids, priority=5.0):
    q = TaskQueue()
    for i, tid in enumerate(task_ids):
        q.add_task(tid, 'prospect', float(i), 0.0, priority=priority)
    return q


class TestQueueBackoff:

    def test_a_deferred_task_is_skipped_until_its_deadline(self):
        q = _queue_with('survey_a')
        q.defer_auction('survey_a', 5.0, now=1000.0)
        assert q.get_next_ready(now=1004.9) is None
        assert q.get_next_ready(now=1005.1).task_id == 'survey_a'

    def test_a_deferred_task_no_longer_starves_the_rest_of_the_queue(self):
        """THE REGRESSION. This is the cost that was not merely cosmetic.

        ``survey_a`` is the higher priority, so ``get_next_ready`` returned it
        every time and it held the single auction slot for 261 rounds. With the
        backoff it steps aside and the lower-priority work proceeds.
        """
        q = TaskQueue()
        q.add_task('survey_a', 'prospect', 0.0, 0.0, priority=5.0)
        q.add_task('excavate_b', 'excavate', 0.0, 0.0, priority=3.0)

        assert q.get_next_ready(now=1000.0).task_id == 'survey_a'
        q.defer_auction('survey_a', 5.0, now=1000.0)
        assert q.get_next_ready(now=1000.5).task_id == 'excavate_b'

    def test_an_abandoned_task_is_never_released_by_time_alone(self):
        """A "big enough" deadline is one that eventually passes."""
        q = _queue_with('survey_a')
        q.abandon_auction('survey_a')
        assert q.get_next_ready(now=1e12) is None
        assert q.get_next_ready(now=float('inf')) is None

    def test_an_abandoned_task_stays_pending_and_visible(self):
        """No new TaskStatus enum value; the reason field carries it.

        A new status would have to be rendered by the dashboard, documented in
        TaskStatus.msg and handled by every switch on that field. D-03 built
        `status_reason` for exactly this, and TaskQueue.jsx already draws it.
        """
        q = _queue_with('survey_a')
        q.abandon_auction('survey_a')
        q.set_status('survey_a', TaskStatus.PENDING, AUCTION_ABANDONED)
        task = q.get_task('survey_a')
        assert task.status is TaskStatus.PENDING
        assert task.status_reason == AUCTION_ABANDONED

    def test_the_failure_count_is_separate_from_auction_rounds(self):
        """auction_rounds is the lifetime count the dashboard shows.

        A task assigned on its fifth attempt must read auction_rounds 5 (it
        really did go through five auctions) and failed_auctions 0 (it is not
        one failure away from being abandoned).
        """
        q = _queue_with('survey_a')
        for _ in range(4):
            q.begin_auction('survey_a')
            q.defer_auction('survey_a', 1.0, now=1000.0)
        q.begin_auction('survey_a')
        q.assign_to_robot('survey_a', 'scout_01')

        task = q.get_task('survey_a')
        assert task.auction_rounds == 5
        assert task.failed_auctions == 0
        assert task.auction_backoff_until == 0.0

    def test_a_task_recovered_from_a_dead_robot_starts_clean(self):
        """A heartbeat timeout is a fleet change, not a refusal to bid."""
        q = _queue_with('survey_a')
        q.defer_auction('survey_a', 60.0, now=1000.0)
        q.assign_to_robot('survey_a', 'scout_01')
        q.set_status('survey_a', TaskStatus.IN_PROGRESS)
        q.recover_tasks_for_robot('scout_01')
        assert q.get_next_ready(now=1000.1).task_id == 'survey_a'

    def test_an_operator_cancel_starts_clean_too(self):
        q = _queue_with('survey_a')
        q.defer_auction('survey_a', 60.0, now=1000.0)
        q.interrupt_task('survey_a', {}, reason='operator_cancel_task')
        assert q.get_next_ready(now=1000.1).task_id == 'survey_a'

    def test_a_zero_delay_still_counts_the_failure(self):
        """auction_backoff_base_sec 0.0 must not disable the give-up bound."""
        q = _queue_with('survey_a')
        for n in range(1, 6):
            assert q.defer_auction('survey_a', 0.0, now=1000.0) == n
        assert q.get_task('survey_a').auction_backoff_until == 0.0
        assert auction_failure_reason(5, MAX_ROUNDS) == AUCTION_ABANDONED

    def test_deferring_an_unknown_task_is_a_no_op(self):
        q = TaskQueue()
        assert q.defer_auction('nope', 5.0) == 0
        q.abandon_auction('nope')
        q.clear_auction_backoff('nope')


# --------------------------------------------------------------------------- #
#  Coming back from the give-up state                                          #
# --------------------------------------------------------------------------- #

class _Fleet:
    """Drives a real FleetMonitor through fsm_state transitions."""

    def __init__(self, monitor, robot_id='scout_01'):
        self._m = monitor
        self._rid = robot_id
        self._t = 1000.0

    def state(self, fsm_state, robot_id=None, x=0.0, y=0.0):
        self._t += 0.5
        self._m.update_robot(
            robot_id=robot_id or self._rid, robot_type='scout',
            fsm_state=fsm_state, pose_x=x, pose_y=y, pose_theta=0.0,
            battery_level=0.9, current_task_id='', capabilities=['prospect'],
            timestamp=self._t)


class TestWakingOnAFleetChange:

    def test_an_abandoned_task_returns_when_a_robot_finishes_work(self):
        """WITHOUT THIS THE MISSION DEADLOCKS.

        A task abandoned because every capable robot was busy would stay
        abandoned after they all finished, and nothing would ever announce it
        again. That is a worse failure than the flood D-20 is about.
        """
        q = _queue_with('survey_a')
        q.abandon_auction('survey_a')
        assert q.get_next_ready(now=1e9) is None

        woken = q.wake_deferred_auctions(AUCTION_FLEET_CHANGED)
        assert woken == ['survey_a']
        assert q.get_next_ready(now=1000.0).task_id == 'survey_a'
        assert q.get_task('survey_a').status_reason == AUCTION_FLEET_CHANGED

    def test_a_woken_abandoned_task_gets_one_auction_not_another_five(self):
        """The escalation, and why the wake is not a plain reset.

        A robot arrives in IDLE after every completed task, so in a busy fleet
        the wake runs often. Resetting an abandoned task's failure count would
        buy it a fresh run of ``auction_max_failed_rounds`` announcements every
        time anything anywhere finished, and a task no robot can EVER service
        would be back to announcing on a loop -- D-20 with a longer period.
        """
        q = _queue_with('survey_a')
        for _ in range(MAX_ROUNDS):
            q.defer_auction('survey_a', 1.0, now=1000.0)
        q.abandon_auction('survey_a')

        q.wake_deferred_auctions(AUCTION_FLEET_CHANGED)
        task = q.get_task('survey_a')
        assert task.failed_auctions == MAX_ROUNDS       # count survives
        assert q.get_next_ready(now=1000.0) is not None  # but it may try again

        # One more failure and it is blocked again immediately.
        failures = q.defer_auction('survey_a', 1.0, now=1000.0)
        assert auction_failure_reason(failures, MAX_ROUNDS) == AUCTION_ABANDONED

    def test_a_merely_backed_off_task_does_start_clean(self):
        """It has not exhausted anything, so the asymmetry does not apply."""
        q = _queue_with('survey_a')
        q.defer_auction('survey_a', 20.0, now=1000.0)
        q.defer_auction('survey_a', 40.0, now=1000.0)
        q.wake_deferred_auctions(AUCTION_FLEET_CHANGED)
        assert q.get_task('survey_a').failed_auctions == 0

    def test_an_assignment_clears_the_escalation_outright(self):
        """The escalation must only ever affect tasks that keep failing."""
        q = _queue_with('survey_a')
        for _ in range(MAX_ROUNDS):
            q.defer_auction('survey_a', 1.0, now=1000.0)
        q.abandon_auction('survey_a')
        q.wake_deferred_auctions(AUCTION_FLEET_CHANGED)
        q.assign_to_robot('survey_a', 'scout_01')
        assert q.get_task('survey_a').failed_auctions == 0
        assert q.get_task('survey_a').auction_backoff_until == 0.0

    def test_waking_does_not_touch_tasks_that_were_never_deferred(self):
        q = _queue_with('survey_a', 'survey_b')
        q.defer_auction('survey_a', 5.0, now=1000.0)
        assert q.wake_deferred_auctions('x') == ['survey_a']

    def test_waking_does_not_resurrect_a_completed_task(self):
        q = _queue_with('survey_a')
        q.defer_auction('survey_a', 5.0, now=1000.0)
        q.mark_complete('survey_a')
        assert q.wake_deferred_auctions('x') == []

    def test_a_robot_finishing_work_counts_as_a_fleet_change(self):
        m = FleetMonitor()
        f = _Fleet(m)
        f.state('NAVIGATING')
        before = m.idle_arrivals
        f.state('IDLE')
        assert m.idle_arrivals == before + 1

    def test_an_idle_robot_that_simply_does_not_bid_is_not_a_fleet_change(self):
        """THE CASE THE 261-ROUND FLOOD WAS MEASURED IN, and the reason the
        trigger is a transition rather than set membership.

        ``_auction_tick`` only starts an auction when at least one robot is
        IDLE, so in the observed failure a robot WAS idle and just did not bid
        -- wrong capability, or ``can_afford_task`` said no. A robot that
        declines never leaves IDLE. If "a robot is idle" reset the backoff, it
        would reset on every single tick and the mechanism would do nothing.
        """
        m = FleetMonitor()
        f = _Fleet(m)
        f.state('IDLE')
        after_first = m.idle_arrivals
        for _ in range(20):
            f.state('IDLE')
        assert m.idle_arrivals == after_first

    def test_losing_an_auction_is_not_a_fleet_change_either(self):
        """BIDDING -> IDLE is ordinary churn, not news.

        A robot that bids on some OTHER task and loses returns to IDLE. If that
        counted, any second task being auctioned would keep resetting the first
        task's backoff.
        """
        m = FleetMonitor()
        f = _Fleet(m)
        f.state('IDLE')
        after_first = m.idle_arrivals
        for _ in range(5):
            f.state('BIDDING')
            f.state('IDLE')
        assert m.idle_arrivals == after_first

    @pytest.mark.parametrize('from_state', [
        'NAVIGATING', 'WORKING', 'RETURNING', 'RECHARGING', 'ERROR', 'ASSIGNED',
    ])
    def test_every_other_arrival_in_idle_counts(self, from_state):
        m = FleetMonitor()
        f = _Fleet(m)
        f.state(from_state)
        before = m.idle_arrivals
        f.state('IDLE')
        assert m.idle_arrivals == before + 1

    def test_a_robot_joining_the_fleet_counts(self):
        """First heartbeat, already IDLE: a robot that was not there is news."""
        m = FleetMonitor()
        _Fleet(m).state('IDLE')
        assert m.idle_arrivals == 1


# --------------------------------------------------------------------------- #
#  The wiring                                                                  #
# --------------------------------------------------------------------------- #

class TestWiring:
    """A mechanism nothing calls is FR-MAP-3's failure mode, not a fix."""

    def test_get_next_ready_is_called_with_a_clock(self):
        """``get_next_ready()`` with no argument ignores every backoff.

        The default is ``time.monotonic()``, so an argument-less call is not
        WRONG -- it just happens to work. This asserts the orchestrator passes
        the same ``now`` it uses for the auction timeout, so the two cannot
        drift apart across a slow tick.
        """
        calls = [n for n in ast.walk(_tree())
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'get_next_ready']
        assert calls, 'orchestrator_node.py no longer calls get_next_ready'
        assert all(c.args for c in calls), (
            'get_next_ready() is called with no clock argument, so it defaults '
            'to time.monotonic() rather than the auction tick\'s own `now`.')

    def test_the_backoff_is_applied_when_an_auction_fails(self):
        src = SOURCE.read_text(encoding='utf-8')
        assert '_back_off_auction' in src
        assert 'defer_auction' in src
        assert 'abandon_auction' in src

    def test_the_fleet_change_wake_is_reachable_from_the_auction_tick(self):
        """It has to run on the timer, not on a subscription callback.

        The task queue is walked by timers on the MultiThreadedExecutor;
        mutating it from a DDS callback thread would race them.
        """
        tree = _tree()
        auction_tick = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == '_auction_tick')
        called = {n.func.attr for n in ast.walk(auction_tick)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert '_wake_on_fleet_change' in called, (
            'nothing in _auction_tick wakes backed-off tasks, so an abandoned '
            'task is abandoned for the rest of the mission and the mission '
            'deadlocks. Calls found: %s' % (sorted(called),))

    def test_the_backoff_parameters_are_declared_and_read(self):
        """test_no_orphan_parameters.py enforces this globally.

        Named here so a failure says which requirement broke rather than
        reporting a count.
        """
        tree = _tree()
        declared, read = set(), set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            name = node.args[0].value
            if not isinstance(name, str):
                continue
            if node.func.attr == 'declare_parameter':
                declared.add(name)
            elif node.func.attr == 'get_parameter':
                read.add(name)
        for name in ('auction_backoff_base_sec', 'auction_backoff_max_sec',
                     'auction_max_failed_rounds'):
            assert name in declared, name
            assert name in read, name
