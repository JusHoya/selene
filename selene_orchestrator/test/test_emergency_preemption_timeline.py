"""Emergency preemption on TIMELINES, through the real orchestrator loop.

WHAT THIS FILE IS FOR, AND WHY IT IS SEPARATE FROM
``test_emergency_preemption.py``. That file proves the mechanism does what it
says in one tick: an emergency candidate aborts a strictly lower-priority
auction, the round is refunded, the victim's status is restored. This file
asserts the DIFFERENT claim -- the one the change was actually bought for --
about what happens over SECONDS: which task ends up announced, which robot ends
up assigned, and how many auctions one emergency is allowed to destroy.

IT BEGAN AS AN ADVERSARIAL FILE AND EVERY TIMELINE IN IT IS THE ONE IT WAS
WRITTEN TO DEMONSTRATE. When first written, against the change as landed, all
five of these timelines showed the emergency losing or the orchestrator
destroying work for nothing:

  * a preemption fired with no idle robot to give the slot to, emptying the
    auction slot and stranding the victim's bidder for 7.0 s;
  * an emergency inside its own D-20 backoff was invisible to the decision
    meant to act on it, and a priority-5.0 survey took the last capable robot;
  * a preemption-stranded bidder re-entered IDLE through the one transition
    ``FleetMonitor`` ignores, so the capacity a preemption created could never
    wake the task it was performed for;
  * nothing bounded how many auctions one emergency could abort;
  * the gate probe's own new clause failed a conforming orchestrator.

The timelines are unchanged. What changed is the production code, and the
assertions now state the fixed behaviour with the old behaviour named in the
message so a regression says which one came back.

WHAT IS FAKED, AND WHAT THAT COSTS. ``_publish_announcement`` and
``_publish_assignment`` are recorders; the agents are a 40-line model of
``agent_node``'s three relevant behaviours (bid only while IDLE and capable,
leave BIDDING after ``auction_timeout_sec`` = 7.0 s, go busy on assignment).
Nothing here has run against ROS. What it CAN show is control flow and
arithmetic in the orchestrator, which is where all of these findings live.
"""

import time

import pytest

from selene_orchestrator.fleet_monitor import FleetMonitor         # noqa: E402
from selene_orchestrator.orchestrator_node import OrchestratorNode  # noqa: E402
from selene_orchestrator.task_auction import Bid, TaskAuction      # noqa: E402
from selene_orchestrator.task_feed import should_preempt           # noqa: E402
from selene_orchestrator.task_queue import TaskQueue, TaskStatus   # noqa: E402

#: The shipped orchestrator defaults, read off orchestrator_params.yaml rather
#: than invented, because the arithmetic in these timelines is the finding.
AUCTION_TIMEOUT_SEC = 5.0
AUCTION_TICK_SEC = 0.5
AUCTION_BACKOFF_BASE_SEC = 5.0
AUCTION_BACKOFF_MAX_SEC = 120.0
AUCTION_MAX_FAILED_ROUNDS = 5
#: agent_node.py:167 -- deliberately longer than the orchestrator's 5.0 s.
AGENT_AUCTION_TIMEOUT_SEC = 7.0


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, msg):
        self.lines.append(('info', str(msg)))

    def warn(self, msg):
        self.lines.append(('warn', str(msg)))

    def error(self, msg):
        self.lines.append(('error', str(msg)))

    def debug(self, msg):
        self.lines.append(('debug', str(msg)))

    def text(self):
        return '\n'.join(m for _lvl, m in self.lines)


class _Robot:
    """agent_node's auction behaviour, and only that.

    Three behaviours are modelled because three are load-bearing here:

    * ``_on_task_announced`` returns immediately unless the FSM is IDLE, so an
      announcement published before this robot became idle is NEVER seen by it.
      That single line is why "free a robot and it will bid on whatever is in
      flight" is not how this system works.
    * ``_handle_bidding`` leaves BIDDING only on its OWN 7.0 s timeout. Nothing
      tells a bidder its auction went away, which is what makes a preempted
      auction's bidder unavailable for longer than the orchestrator's own 5.0 s
      window would have made it.
    * an assignment takes the robot out of the fleet for the rest of the
      timeline, which is what losing the freed robot to a survey task costs.
    """

    def __init__(self, robot_id, capabilities, state='WORKING'):
        self.robot_id = robot_id
        self.capabilities = list(capabilities)
        self.state = state
        self.bidding_since = 0.0
        self.pending_task_id = ''

    def hear_announcement(self, task_id, required, now):
        if self.state != 'IDLE':
            return None
        if not set(required).issubset(set(self.capabilities)):
            return None
        self.state = 'BIDDING'
        self.bidding_since = now
        self.pending_task_id = task_id
        return Bid(task_id=task_id, robot_id=self.robot_id, bid_score=1.0,
                   estimated_arrival_time=1.0, energy_after_task=1.0)

    def step(self, now):
        if (self.state == 'BIDDING'
                and now - self.bidding_since > AGENT_AUCTION_TIMEOUT_SEC):
            self.state = 'IDLE'
            self.pending_task_id = ''


class _Sim:
    """A driver for the REAL _auction_tick against a fake clock and fake robots."""

    def __init__(self, robots, backoff_base=AUCTION_BACKOFF_BASE_SEC):
        self.now = 1000.0
        self.robots = {r.robot_id: r for r in robots}
        self._task_queue = TaskQueue()
        self._auction = TaskAuction(timeout_sec=AUCTION_TIMEOUT_SEC)
        self._fleet = FleetMonitor()
        self._logger = _Logger()
        self._last_idle_arrivals = 0
        self._preferred_robot_max_rounds = 3
        self._auction_backoff_base = backoff_base
        self._auction_backoff_max = AUCTION_BACKOFF_MAX_SEC
        self._auction_max_failed_rounds = AUCTION_MAX_FAILED_ROUNDS
        self._auction_failure_logged = {}
        #: D2: the retry sweep's once-per-task latch. Nothing in this file
        #: fails a task, so it must stay empty in every timeline here.
        self._attempts_exhausted_alerted = set()
        self.announced = []      # (t, task_id)
        self.assigned = []       # (t, task_id, robot_id)
        self.alerts = []
        self.preempts = []       # (t, victim)
        self._publish_state()
        # The fleet as it stands at t=0 is SET-UP, not a fleet change. Without
        # this the very first tick sees idle_arrivals move from 0 and fires
        # wake_deferred_auctions, which would clear any backoff a test had
        # deliberately arranged -- i.e. every D-20 timeline would silently
        # measure a woken queue instead of a backed-off one. A real orchestrator
        # that has been up for minutes is in exactly this state.
        self._last_idle_arrivals = self._fleet.idle_arrivals

    # -- node surface ---------------------------------------------------- #

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def _authorise_quantity(self, task):
        return (0.0, '')

    def _note_haul_block(self, task, reason):
        pass

    def _publish_assignment(self, task_id, robot_id, task):
        self.assigned.append((round(self.now - 1000.0, 3), task_id, robot_id))
        self.robots[robot_id].state = 'ASSIGNED'
        # agent_node._on_task_assigned: a bidder that sees an assignment for the
        # task it bid on, to somebody else, fires AUCTION_LOST and returns to
        # IDLE. That is the ORDINARY BIDDING -> IDLE the fleet monitor ignores,
        # and modelling it is what keeps this harness honest about which idle
        # robots woke the queue and which did not.
        for other in self.robots.values():
            if (other.robot_id != robot_id and other.state == 'BIDDING'
                    and other.pending_task_id == task_id):
                other.state = 'IDLE'
                other.pending_task_id = ''

    def _publish_announcement(self, task):
        self.announced.append((round(self.now - 1000.0, 3), task.task_id))
        for robot in self.robots.values():
            bid = robot.hear_announcement(
                task.task_id, task.required_capabilities, self.now)
            if bid is not None:
                self._auction.add_bid(bid)
        self._publish_state()

    # -- bound production code ------------------------------------------- #

    def _wake_on_fleet_change(self):
        OrchestratorNode._wake_on_fleet_change(self)

    def _retry_failed_tasks(self):
        # D2. Bound rather than stubbed, for the same reason _robot_is_live
        # below is: every collaborator is real here, so every timeline in this
        # file runs the retry sweep as well. No task in this file ever goes
        # FAILED, so it is a no-op in all of them and every event trace must
        # stay identical -- if one moves, the sweep reaches too far.
        OrchestratorNode._retry_failed_tasks(self)

    def _report_attempts_exhausted(self):
        OrchestratorNode._report_attempts_exhausted(self)

    def _servable_by_idle_fleet(self, task):
        return OrchestratorNode._servable_by_idle_fleet(self, task)

    def _robot_is_live(self, robot_id):
        # D3(c). Bound rather than stubbed: ``self._fleet`` is a REAL
        # FleetMonitor, so binding it means every timeline in this file
        # exercises the liveness rule for free. None of these robots is ever
        # OFFLINE, so every timeline must stay event-for-event identical -- if
        # one moves, the liveness filter is wrong.
        return OrchestratorNode._robot_is_live(self, robot_id)

    def _preempt_for_emergency(self, now):
        victim = self._auction.get_task_id()
        aborted = OrchestratorNode._preempt_for_emergency(self, now)
        if aborted:
            self.preempts.append((round(self.now - 1000.0, 3), victim))
        return aborted

    def _resolve_auction(self):
        OrchestratorNode._resolve_auction(self)

    def _back_off_auction(self, task_id):
        return OrchestratorNode._back_off_auction(self, task_id)

    def _log_auction_failure(self, task_id, reason, bid_count, status):
        OrchestratorNode._log_auction_failure(
            self, task_id, reason, bid_count, status)

    # -- the clock ------------------------------------------------------- #

    def _publish_state(self):
        """Push every robot's FSM state through the REAL FleetMonitor.

        Not a shortcut past ``update_robot``: ``_note_idle_arrival``'s
        BIDDING -> IDLE handling is one of the findings, and a fake that set
        ``get_idle_robots`` directly would step straight over it.
        """
        for robot in self.robots.values():
            self._fleet.update_robot(
                robot.robot_id, 'scout', robot.state, 0.0, 0.0, 0.0, 1.0, '',
                capabilities=robot.capabilities, timestamp=self.now)

    def advance(self, seconds):
        """Run ticks at 0.5 s for *seconds*, stepping the robot models between."""
        end = self.now + seconds
        while self.now < end - 1e-9:
            self.now = round(self.now + AUCTION_TICK_SEC, 6)
            for robot in self.robots.values():
                robot.step(self.now)
            self._publish_state()
            OrchestratorNode._auction_tick(self)

    def tick(self):
        self.advance(AUCTION_TICK_SEC)

    def t(self):
        return round(self.now - 1000.0, 3)


@pytest.fixture
def clock(monkeypatch):
    """Bind ``time.monotonic`` to the simulation clock.

    ``_auction_tick`` reads ``time.monotonic()`` directly and ``defer_auction``
    defaults to it, so the backoff deadline and the auction window have to come
    off the same clock the ticks do or the arithmetic under test is not the
    arithmetic that runs.
    """
    holder = {'sim': None}

    def _monotonic():
        sim = holder['sim']
        return sim.now if sim is not None else 1000.0

    monkeypatch.setattr(time, 'monotonic', _monotonic)
    return holder


def _make_sim(clock, robots, **kwargs):
    sim = _Sim(robots, **kwargs)
    clock['sim'] = sim
    return sim


# --------------------------------------------------------------------------- #
#  1 -- no auction in flight: the flag changes nothing, by design.             #
# --------------------------------------------------------------------------- #

class TestNoAuctionInFlightIsUntouched:
    """NOT A DEFECT, AND RECORDED AS A TEST SO IT IS NOT MISTAKEN FOR ONE.

    The decision is that an emergency may abort an auction ALREADY IN FLIGHT.
    Where no auction is in flight there is nothing to abort, and priority 10.0
    already put the injection at the head of the queue before this change
    existed. So the emergency flag buying nothing on those timelines is the
    specification, not a gap in it -- and the gate probe's corroboration clause
    reports NOT APPLICABLE on exactly those runs rather than certifying
    something it did not measure.
    """

    def test_preempt_is_never_consulted_when_no_auction_is_active(self, clock):
        sim = _make_sim(clock, [_Robot('scout_01', ['prospect'], 'WORKING')])
        sim._task_queue.add_task('survey_a', 'prospect', -95.0, -170.0,
                                 priority=5.0)
        sim._task_queue.add_task('manual_0000', 'prospect', -100.0, -150.0,
                                 priority=10.0, emergency=True)
        sim.advance(20.0)
        assert sim.preempts == []
        # And nothing was announced either, because no robot was idle: the
        # emergency flag does not create capacity, and it is not supposed to.
        assert sim.announced == []
        # The shot is UNSPENT. It is spent only on a tick that goes on to
        # announce the emergency, so a fleet with nothing idle never burns it.
        assert sim._task_queue.get_task(
            'manual_0000').preemption_spent is False

    def test_the_flag_changes_nothing_once_a_robot_is_idle(self, clock):
        """A/B on the SAME timeline with the flag on and off.

        The two runs are identical event-for-event. With the auction slot free
        at the injection, priority 10.0 already wins it; the flag is for the
        case where the slot is NOT free.
        """
        traces = []
        for emergency in (True, False):
            sim = _make_sim(clock, [_Robot('scout_01', ['prospect'], 'IDLE')])
            sim._task_queue.add_task('survey_a', 'prospect', -95.0, -170.0,
                                     priority=5.0)
            sim._task_queue.add_task('manual_0000', 'prospect', -100.0, -150.0,
                                     priority=10.0, emergency=emergency)
            sim.advance(20.0)
            traces.append((sim.announced, sim.assigned, sim.preempts))
        assert traces[0] == traces[1]
        assert traces[0][2] == []


# --------------------------------------------------------------------------- #
#  2 -- the preemption is not spent on a tick that cannot use it.              #
# --------------------------------------------------------------------------- #

class TestPreemptionWithNoIdleRobot:
    """FIXED: ``_preempt_for_emergency`` now tests the idle set BEFORE aborting.

    It used to run before the idle gate and unconditionally, so on the gate's
    own stimulus ordering -- inject first, free a robot second -- the normal
    outcome was that the orchestrator destroyed a round, discarded a live bid
    and announced nothing. The victim's bidder is the robot that WOULD have been
    assigned; it is not told, so it sat in BIDDING for the remainder of its own
    7.0 s window (agent_node ``auction_timeout_sec``), which is LONGER than the
    5.0 s the orchestrator's own auction had left to run. The tick was net
    negative: an auction about to resolve became an empty slot plus an
    unavailable robot.
    """

    def test_nothing_is_destroyed_when_there_is_no_robot_to_give_it_to(
            self, clock):
        scout = _Robot('scout_01', ['prospect'], 'IDLE')
        sim = _make_sim(clock, [scout])
        sim._task_queue.add_task('survey_a', 'prospect', -95.0, -170.0,
                                 priority=5.0)
        # One tick opens survey_a's auction and the scout bids on it, which is
        # what takes the last idle robot out of the fleet.
        sim.tick()
        assert sim.announced == [(0.5, 'survey_a')]
        assert scout.state == 'BIDDING'
        assert sim._auction.get_bid_count() == 1
        assert sim._fleet.get_idle_robots() == []

        # The operator injects an emergency while that auction is in flight.
        sim._task_queue.add_task('manual_0000', 'prospect', -100.0, -150.0,
                                 priority=10.0, emergency=True)
        sim.tick()

        assert sim.preempts == [], (
            'the preemption fired on a tick that could announce nothing: the '
            'slot was emptied and the bid discarded for no gain')
        assert sim._auction.is_active()
        assert sim._auction.get_task_id() == 'survey_a'
        assert sim._task_queue.get_task('survey_a').auction_rounds == 1
        assert (sim._task_queue.get_task('survey_a').status
                is TaskStatus.AUCTIONING)
        assert sim._task_queue.get_task(
            'manual_0000').preemption_spent is False

    def test_the_auction_that_was_about_to_resolve_does_resolve(self, clock):
        """The cost of the old behaviour, measured from the other side.

        Left alone, survey_a's auction resolves 5.0 s after it opened and
        scout_01 is ASSIGNED. Preempting instead left scout_01 in BIDDING with
        no auction behind it, returning to IDLE only on its own 7.0 s timeout --
        2.5 s later than the orchestrator would have moved it, with the auction
        slot standing empty for all of it.
        """
        scout = _Robot('scout_01', ['prospect'], 'IDLE')
        sim = _make_sim(clock, [scout])
        sim._task_queue.add_task('survey_a', 'prospect', -95.0, -170.0,
                                 priority=5.0)
        sim.tick()                       # t=0.5 announce, bid at t=0.5
        sim._task_queue.add_task('manual_0000', 'prospect', -100.0, -150.0,
                                 priority=10.0, emergency=True)
        sim.advance(5.5)                 # past survey_a's 5.0 s window

        assert sim.preempts == []
        assert sim.assigned == [(5.5, 'survey_a', 'scout_01')], sim.assigned


# --------------------------------------------------------------------------- #
#  3 -- THE BLOCKER: the D-20 backoff blind spot.                              #
# --------------------------------------------------------------------------- #

class TestEmergencyInBackoff:
    """FIXED on both sides: the round is not burned, and the backoff is not blind.

    The emergency used to acquire a D-20 backoff trivially -- ``_auction_tick``'s
    idle gate was a bare ``if not idle`` with no capability match, so a single
    idle excavator opened and wasted a whole round of a prospect-only auction --
    and a backed-off task is invisible to ``get_next_ready``, which was where
    ``_preempt_for_emergency`` got its candidate. For the whole backoff window
    the emergency could preempt nothing and a priority-5.0 survey was free to
    take the auction slot and any robot that bid on it.

    Two independent repairs, because either alone leaves a hole:
    ``get_next_ready(servable=...)`` stops the round being burned at all, and
    ``get_preemption_candidate`` sees an UNSPENT emergency through the backoff
    if one is accrued some other way.
    """

    def test_a_backed_off_emergency_IS_a_preemption_candidate(self, clock):
        sim = _make_sim(clock, [_Robot('scout_01', ['prospect'], 'WORKING')])
        q = sim._task_queue
        q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=5.0)
        q.add_task('manual_0000', 'prospect', -100.0, -150.0,
                   priority=10.0, emergency=True)
        q.defer_auction('manual_0000', AUCTION_BACKOFF_BASE_SEC, now=sim.now)

        # get_next_ready still hides it -- D-20's contract is unchanged.
        assert q.get_next_ready(sim.now).task_id == 'survey_a'
        # The preemption decision does not.
        candidate = q.get_preemption_candidate(sim.now)
        assert candidate.task_id == 'manual_0000'
        assert should_preempt(q.get_task('survey_a'), candidate) is True

    def test_an_idle_excavator_does_not_burn_a_prospect_rounds_worth(
            self, clock):
        """THE ACCRUAL MECHANISM, closed at the source.

        ``_auction_tick`` announces only what some IDLE robot could bid on. The
        excavator below cannot bid on a prospect task, so the round is never
        opened, no ``auction_no_bids`` is charged, and the emergency does not
        put itself to sleep.
        """
        sim = _make_sim(clock, [
            _Robot('excavator_01', ['excavate'], 'IDLE'),
        ])
        q = sim._task_queue
        q.add_task('manual_0000', 'prospect', -100.0, -150.0, priority=10.0,
                   emergency=True, required_capabilities=['prospect'])
        sim.advance(30.0)

        assert sim.announced == []
        entry = q.get_task('manual_0000')
        assert entry.auction_rounds == 0
        assert entry.failed_auctions == 0
        assert entry.auction_backoff_until == 0.0

    def test_a_lower_priority_task_is_not_starved_by_it(self, clock):
        """SKIP, not RETURN. The emergency the fleet cannot serve must not stop
        the surveys three idle scouts CAN serve."""
        sim = _make_sim(clock, [_Robot('scout_01', ['prospect'], 'IDLE')])
        q = sim._task_queue
        q.add_task('manual_0000', 'excavate', -100.0, -150.0, priority=10.0,
                   emergency=True, required_capabilities=['excavate'])
        q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=5.0,
                   required_capabilities=['prospect'])
        sim.advance(6.0)

        assert [a[1] for a in sim.announced] == ['survey_a']
        assert sim.assigned == [(5.5, 'survey_a', 'scout_01')], sim.assigned

    @staticmethod
    def _backed_off_excavate_emergency(clock):
        """The reachable shape of the blind spot, built once for three tests.

        A prospect survey's auction is in flight (so a scout is in BIDDING and
        the slot is taken), the emergency is an EXCAVATE inside a D-20 backoff,
        and two excavators are idle. The excavators' idleness woke nothing --
        they have simply been idle, and ``_note_idle_arrival`` counts
        transitions, not membership -- so ``wake_deferred_auctions`` has not run
        and the emergency really is asleep at the moment the decision is taken.
        That is what makes ``get_next_ready`` the wrong question and
        ``get_preemption_candidate`` the right one.
        """
        scout = _Robot('scout_01', ['prospect'], 'IDLE')
        exc_a = _Robot('excavator_01', ['excavate'], 'IDLE')
        exc_b = _Robot('excavator_02', ['excavate'], 'IDLE')
        sim = _make_sim(clock, [scout, exc_a, exc_b])
        q = sim._task_queue
        q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=5.0,
                   required_capabilities=['prospect'])
        q.add_task('manual_0000', 'excavate', -100.0, -150.0, priority=10.0,
                   emergency=True, required_capabilities=['excavate'])
        q.defer_auction('manual_0000', 20.0, now=sim.now)
        sim.tick()
        assert sim.announced == [(0.5, 'survey_a')], sim.announced
        assert scout.state == 'BIDDING'
        assert q.get_next_ready(sim.now) is None, (
            'the emergency must really be invisible to get_next_ready here, or '
            'this timeline is not testing what it says it is')
        return sim, q, scout

    def test_the_backed_off_emergency_takes_the_slot_and_the_robot(self, clock):
        """THE REGISTER'S OWN CHECK-6 FAILURE, END TO END, NOW WON.

        Before the fix ``_preempt_for_emergency`` asked ``get_next_ready``,
        which returns None on this queue state, so ``should_preempt`` was never
        even offered the emergency and the survey kept the slot.
        """
        sim, q, _scout = self._backed_off_excavate_emergency(clock)
        sim.tick()

        assert sim.preempts == [(1.0, 'survey_a')]
        assert (1.0, 'manual_0000') in sim.announced, sim.announced
        # The backoff was RELEASED, not merely reached through -- otherwise the
        # fall-through's get_next_ready would have skipped the very task the
        # abort was performed for and the slot would have gone to nobody.
        entry = q.get_task('manual_0000')
        assert entry.auction_backoff_until == 0.0
        assert entry.preemption_spent is True
        # The victim paid only its round, and got that back.
        victim = q.get_task('survey_a')
        assert victim.auction_rounds == 0
        assert victim.status is TaskStatus.PENDING
        assert victim.status_reason == 'auction_preempted'

        sim.advance(5.5)
        assert [a for a in sim.assigned if a[1] == 'manual_0000'], sim.assigned

    def test_one_emergency_cannot_abort_auction_after_auction(self, clock):
        """THE BOUND, over a timeline rather than a tick.

        ``emergency`` is never cleared, and ``wake_deferred_auctions`` releases
        a merely-backed-off task on EVERY fleet change (and zeroes its
        ``failed_auctions``, so it can never escalate to ABANDONED, the one
        state ``get_next_ready`` skips). Without ``preemption_spent`` the same
        emergency preempted a fresh auction on every one of those cycles --
        measured at 25 preemptions over 25 cycles, with the victim's
        ``auction_rounds`` pinned at 0 so it never completed a single round.
        """
        sim, q, _scout = self._backed_off_excavate_emergency(clock)
        sim.tick()
        assert sim.preempts == [(1.0, 'survey_a')]
        assert q.get_task('manual_0000').preemption_spent is True

        # Now drive the cycle the old code looped on: the emergency loses its
        # rounds, is backed off, and is released again by a fleet change. It
        # must never abort another auction.
        for _ in range(25):
            q.defer_auction('manual_0000', 20.0, now=sim.now)
            sim.advance(6.0)
            q.wake_deferred_auctions('fleet_changed')

        assert sim.preempts == [(1.0, 'survey_a')], (
            'one injection bought more than one abort: nothing bounds how many '
            'auctions an emergency nobody bids on may destroy')


# --------------------------------------------------------------------------- #
#  4 -- the wake can now see a preempted bidder.                               #
# --------------------------------------------------------------------------- #

class TestPreemptedBidderWakesTheQueue:
    """FIXED: ``FleetMonitor`` is told which bidders a preemption stranded.

    ``_note_idle_arrival`` excludes ``BIDDING -> IDLE`` on the stated grounds
    that it "is an auction LOSS, the ordinary churn of a robot that bid and did
    not win". That is true of a round that RESOLVED and false of one that was
    ABORTED: nothing was won, nothing left the queue, and the robot is genuinely
    new capacity -- capacity the preemption itself created. Because
    ``_wake_on_fleet_change`` is driven only by ``idle_arrivals``, without this
    the capacity a preemption creates could never wake the backed-off or
    ABANDONED task the preemption was performed for, and ``inf`` has no other
    exit.
    """

    def test_an_ordinary_bidding_to_idle_is_still_not_a_fleet_change(self):
        """The exclusion is narrowed, not removed. An ordinary auction loss must
        still not reset the backoff every time some other task's auction runs."""
        fleet = FleetMonitor()
        fleet.update_robot('scout_01', 'scout', 'IDLE', 0.0, 0.0, 0.0, 1.0, '',
                           capabilities=['prospect'], timestamp=1000.0)
        baseline = fleet.idle_arrivals
        fleet.update_robot('scout_01', 'scout', 'BIDDING', 0.0, 0.0, 0.0, 1.0,
                           '', capabilities=['prospect'], timestamp=1001.0)
        fleet.update_robot('scout_01', 'scout', 'IDLE', 0.0, 0.0, 0.0, 1.0, '',
                           capabilities=['prospect'], timestamp=1008.0)
        assert fleet.idle_arrivals == baseline

    def test_a_stranded_bidder_returning_to_idle_IS_a_fleet_change(self):
        fleet = FleetMonitor()
        fleet.update_robot('scout_01', 'scout', 'IDLE', 0.0, 0.0, 0.0, 1.0, '',
                           capabilities=['prospect'], timestamp=1000.0)
        fleet.update_robot('scout_01', 'scout', 'BIDDING', 0.0, 0.0, 0.0, 1.0,
                           '', capabilities=['prospect'], timestamp=1001.0)
        baseline = fleet.idle_arrivals
        fleet.note_stranded_bidders(['scout_01'])
        fleet.update_robot('scout_01', 'scout', 'IDLE', 0.0, 0.0, 0.0, 1.0, '',
                           capabilities=['prospect'], timestamp=1008.0)
        assert fleet.idle_arrivals == baseline + 1

    def test_the_mark_is_consumed_and_does_not_outlive_its_auction(self):
        """A robot that goes on to WIN the next auction must not carry a stale
        mark into some later ordinary loss."""
        fleet = FleetMonitor()
        fleet.update_robot('scout_01', 'scout', 'BIDDING', 0.0, 0.0, 0.0, 1.0,
                           '', capabilities=['prospect'], timestamp=1000.0)
        fleet.note_stranded_bidders(['scout_01'])
        # Wins the next auction instead of timing out: the mark is spent here.
        fleet.update_robot('scout_01', 'scout', 'ASSIGNED', 0.0, 0.0, 0.0, 1.0,
                           '', capabilities=['prospect'], timestamp=1001.0)
        fleet.update_robot('scout_01', 'scout', 'BIDDING', 0.0, 0.0, 0.0, 1.0,
                           '', capabilities=['prospect'], timestamp=1010.0)
        baseline = fleet.idle_arrivals
        fleet.update_robot('scout_01', 'scout', 'IDLE', 0.0, 0.0, 0.0, 1.0, '',
                           capabilities=['prospect'], timestamp=1018.0)
        assert fleet.idle_arrivals == baseline

    def test_an_abandoned_task_is_woken_by_the_bidder_a_preemption_stranded(
            self, clock):
        """The end-to-end consequence, through the real orchestrator loop."""
        scout = _Robot('scout_01', ['prospect'], 'IDLE')
        exc_a = _Robot('excavator_01', ['excavate'], 'IDLE')
        sim = _make_sim(clock, [scout, exc_a])
        q = sim._task_queue
        q.add_task('survey_a', 'prospect', -95.0, -170.0, priority=5.0,
                   required_capabilities=['prospect'])
        q.add_task('manual_0000', 'excavate', -100.0, -150.0, priority=10.0,
                   emergency=True, required_capabilities=['excavate'])
        q.defer_auction('manual_0000', 20.0, now=sim.now)
        sim.tick()                      # survey_a announced, scout_01 bids
        sim.tick()                      # preempt; scout_01 is now stranded
        assert sim.preempts == [(1.0, 'survey_a')]
        assert scout.state == 'BIDDING'

        # A prospect task is ABANDONED -- auction_backoff_until == inf, which no
        # clock releases and only wake_deferred_auctions can.
        q.add_task('survey_b', 'prospect', -90.0, -160.0, priority=4.0,
                   required_capabilities=['prospect'])
        q.abandon_auction('survey_b')
        arrivals_before = sim._fleet.idle_arrivals

        sim.advance(8.0)                # the stranded bidder gives up at ~8.0

        assert sim._fleet.idle_arrivals > arrivals_before, (
            'the capacity the preemption created arrived through BIDDING -> '
            'IDLE, the transition _note_idle_arrival ignores, so nothing woke')
        assert q.get_task('survey_b').auction_backoff_until != float('inf')


# --------------------------------------------------------------------------- #
#  5 -- the gate probe's clause no longer fails a conforming orchestrator.     #
# --------------------------------------------------------------------------- #

def _load_probe():
    import importlib.util
    import os
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    path = os.path.join(here, 'scripts', 'phase5_probe.py')
    spec = importlib.util.spec_from_file_location('_probe_timeline', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProbePreconditionHasATickMargin:
    """FIXED: the clause proves the auction was live at the orchestrator's next
    OPPORTUNITY TO ACT, not merely at the injection instant.

    ``_auction_tick`` runs on a 0.5 s timer, so a preemption can only happen up
    to a whole period after the injection. With less window than that left, the
    orchestrator correctly takes the ``is_timed_out`` branch, ``_resolve_auction``
    runs, and no preemption happens -- precisely as spec item 8 requires ("while
    an auction is active and NOT timed out"). Before the margin existed the
    clause named a victim on those runs and then reported NOT CORROBORATED,
    which ``correlate_injection`` appends to check 6's ``problems`` list: a new
    way to fail the one row the gate is trying to turn green, caused by the
    orchestrator behaving exactly as specified.
    """

    def test_the_precondition_declines_with_less_slack_than_one_tick(self):
        probe = _load_probe()
        inject = 1000.0
        # survey_a first seen NOT auctioning 4.70 s before the injection, and
        # AUCTIONING in every snapshot after that. The earliest it can time out
        # is 995.30 - 0.25 + 5.0 = 1000.05, i.e. 0.05 s of slack -- less than
        # the 0.5 s until the orchestrator's next tick.
        snaps = [(inject - 4.70, {'survey_a': ('PENDING', '')})]
        t = inject - 4.20
        while t <= inject:
            snaps.append((round(t, 3), {'survey_a': ('AUCTIONING',
                                                     'auction_started')}))
            t += 0.5
        victim, why = probe.preemption_precondition(
            snaps, inject, 'manual_0000', 5.0)
        assert victim is None, why
        assert 'auction tick' in why

        # And the whole clause is NOT APPLICABLE rather than NOT CORROBORATED,
        # so check 6 gains no problem from a conforming orchestrator resolving
        # the auction on the tick after the injection.
        snaps.append((inject + 0.60,
                      {'survey_a': ('PENDING', 'auction_no_bids')}))
        status, note = probe.evaluate_preemption(
            snaps, inject, 'manual_0000', 5.0, True, '')
        assert status == probe.PREEMPT_NOT_APPLICABLE, note

    def test_the_margin_is_the_orchestrators_own_tick_period(self):
        """Derived from the orchestrator, not borrowed from a different number.

        ``MAX_TRANSPORT_LATENCY_SEC`` is 0.25 and is there for websocket arrival
        lag; it is half the tick period it would have had to cover, and using it
        for this would be borrowing a constant for a purpose it was not measured
        for.
        """
        probe = _load_probe()
        assert probe.ORCHESTRATOR_AUCTION_TICK_SEC == AUCTION_TICK_SEC
        assert probe.MAX_TRANSPORT_LATENCY_SEC < AUCTION_TICK_SEC
