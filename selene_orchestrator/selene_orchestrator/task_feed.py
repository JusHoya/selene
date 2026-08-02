"""The task-queue snapshot feed and the constrained auction — D-03/D-04/D-05.

WHY THIS MODULE IMPORTS NO ROS, and why it exists at all.

``selene_orchestrator/test/conftest.py``'s fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so an
``OrchestratorNode`` cannot be constructed in the ROS-free lane at all. Anything
that can actually be wrong -- the ring buffer's eviction accounting, the
projection of a TaskEntry onto the wire's field names, the four-way auction
decision D-04 introduces -- therefore has to live outside the node or it is
untested. This is the same split, for the same stated reason, as
``resource_map_viz.py``.

UNITS AND TYPES ON THE BOUNDARY. Everything here is plain Python: a `stamp` is
epoch seconds as a float, a position is an ``(x, y)`` tuple. The node converts
those to ``builtin_interfaces/Time`` and ``geometry_msgs/Point`` when it fills
the message. Dict KEYS, however, are the exact field names of
``selene_msgs/msg/TaskStatus`` and ``selene_msgs/msg/TaskEvent``, so a rename on
either side shows up as a KeyError in the publisher rather than as a field the
dashboard silently reads as its default.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Iterable

from selene_orchestrator.task_auction import live_bids
from selene_orchestrator.task_queue import TaskStatus


#: Event kinds. 'status' is a task status transition; 'operator' is a
#: dashboard-initiated command, including a REJECTED one -- FR-DASH-6(d) asks
#: for override actions to be "logged and visible in the task history", and a
#: rejection ("robot in ERROR, override refused") is often the more interesting
#: record.
KIND_STATUS = 'status'
KIND_OPERATOR = 'operator'


class TaskEventLog:
    """Bounded, monotonically-sequenced event ring replayed in every snapshot.

    Two things a status table cannot express, which is why this exists beside
    ``task_rows`` rather than instead of it:

    1. A transition that does not rest. INTERRUPTED -> re-auction -> COMPLETED
       leaves no trace in the final row, so "this task was cancelled once" is
       unrecoverable from the table alone.
    2. An operator action that touches no task -- 'force_recharge' on an idle
       robot, 'send_to_location'. There is no task row to hang it on.

    ``seq`` is monotonic from construction and never reused, so a client that
    receives the whole ring in every snapshot can dedupe on it, and can detect
    that it missed events (lowest seq in this snapshot > highest seq it holds
    + 1). ``dropped`` counts evictions since construction: non-zero means the
    snapshot is not the complete history, which the dashboard has to say rather
    than imply the list is exhaustive.
    """

    def __init__(self, capacity: int = 32):
        # A capacity <= 0 would make deque(maxlen=0) silently discard every
        # event while still reporting a growing `dropped`, i.e. an event log
        # that logs nothing. Floor at 1 instead.
        self._capacity = max(1, int(capacity))
        self._events: deque = deque(maxlen=self._capacity)
        self._seq_next = 0
        self._dropped = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def seq_next(self) -> int:
        """The seq the NEXT event will be given."""
        return self._seq_next

    @property
    def dropped(self) -> int:
        """Events evicted from the ring since construction."""
        return self._dropped

    def append(self, kind: str, action: str, task_id: str = '',
               robot_id: str = '', actor: str = '', detail: str = '',
               accepted: bool = False,
               target: tuple[float, float] | None = None,
               stamp: float | None = None) -> dict:
        """Append one event and return it. Keys are TaskEvent.msg field names."""
        event = {
            'seq': self._seq_next,
            'stamp': time.time() if stamp is None else float(stamp),
            'kind': kind,
            'task_id': task_id,
            'robot_id': robot_id,
            'actor': actor,
            'action': action,
            'detail': detail,
            'accepted': bool(accepted),
            'target': ((0.0, 0.0) if target is None
                       else (float(target[0]), float(target[1]))),
        }
        self._seq_next += 1
        if len(self._events) == self._capacity:
            self._dropped += 1
        self._events.append(event)
        return event

    def snapshot(self) -> list[dict]:
        """The ring, oldest first."""
        return list(self._events)


def task_rows(task_queue) -> list[dict]:
    """Project every TaskEntry onto the field names of TaskStatus.msg.

    ``status`` is the enum NAME as a string ('PENDING', 'INTERRUPTED', ...),
    matching ``class TaskStatus(str, Enum)`` and the exact spellings the
    dashboard already switches on. ``target_location`` is an ``(x, y)`` tuple
    and ``status_changed`` is epoch seconds; the node converts both.

    Tasks are never removed from the queue, so a freshly-loaded browser sees
    the full history rather than only what happened since it connected.
    """
    rows = []
    for task in task_queue.get_all_tasks():
        rows.append({
            'task_id': task.task_id,
            'task_type': task.task_type,
            'status': _status_name(task.status),
            'assigned_robot': task.assigned_robot,
            'preferred_robot': task.preferred_robot,
            'priority': float(task.priority),
            'progress': float(task.progress),
            'quantity_kg': float(task.quantity_kg),
            'target_location': (float(task.target_x), float(task.target_y)),
            'parent_task_id': task.parent_task_id,
            'depends_on': list(task.depends_on),
            'required_capabilities': list(task.required_capabilities),
            'status_reason': task.status_reason,
            'status_changed': float(task.status_changed),
            'auction_rounds': int(task.auction_rounds),
            'emergency': bool(getattr(task, 'emergency', False)),
        })
    return rows


def _status_name(status) -> str:
    """TaskStatus enum -> its NAME, tolerating a plain string."""
    return getattr(status, 'name', None) or str(status)


# --------------------------------------------------------------------------- #
#  D-04: the constrained auction                                              #
# --------------------------------------------------------------------------- #

#: Outcomes ``resolve_auction_winner`` can return.
OUTCOME_ASSIGN = 'assign'
OUTCOME_REQUEUE = 'requeue'
OUTCOME_PREFERENCE_DROPPED = 'preference_dropped'


def resolve_auction_winner(task, bids: Iterable[Any], max_rounds: int,
                           is_live=None) -> tuple[Any, str, str]:
    """Pick the winner of one auction. Returns ``(winner|None, outcome, reason)``.

    FR-DASH-5(b) says an operator-injected task "enters the auction". What the
    orchestrator did instead was force-assign it, and that path was already
    broken for the only case it existed to serve: it pre-empted the target
    robot's running task and then published a TaskAssignment which
    ``agent_node._on_task_assigned`` discards for any robot not in BIDDING or
    ASSIGNED -- i.e. exactly the busy robot it was meant to serve. The operator
    lost the running task and gained nothing.

    So a targeted injection becomes a CONSTRAINED auction. The four cases:

    * No preference -> highest bid wins; no bids -> requeue
      (``reason='auction_no_bids'``).
    * Preference, and that robot bid -> it wins REGARDLESS of score. This is
      the whole point: the operator asked for that robot.
    * Preference, that robot did not bid, and the task has been through fewer
      than *max_rounds* auctions -> requeue and wait for it
      (``reason='preferred_robot_absent'``). Deliberately not "assign to
      somebody else this round": a robot that is busy now is usually free in
      one auction period, and silently substituting a different robot is the
      behaviour the operator used the field to prevent.
    * Preference, that robot did not bid, and *max_rounds* auctions have now
      happened -> the preference is dropped and the task re-queued with the
      field cleared, so the NEXT auction is fully open. It is not assigned to
      a runner-up in this round: 'assign' means "this bid won", and conflating
      the two would make the event log say a robot won an auction it was never
      preferred for. The cost is one extra auction period.

    ``task.auction_rounds`` is expected to have been incremented already by
    ``TaskQueue.begin_auction`` when this auction started, so a *max_rounds* of
    3 means the preference survives auctions 1 and 2 and is dropped at 3.

    A FIFTH CASE, and it is the one the four above silently assumed away: an
    element of *bids* that is not an offer. Two kinds exist and both used to
    win.

    * VL-29, a WITHDRAWAL. ``agent_node._publish_bid_withdrawal`` retracts a bid
      by publishing ``task_auction.WITHDRAWN_BID_SCORE`` (-1.0), and this
      function guarded only on ``if not bid_list`` -- emptiness, not liveness --
      so a withdrawal-only list was non-empty and elected the robot that
      withdrew, at -1.0. ``live_bids`` drops every bid from a robot that
      withdrew, before either election path sees it, so the preferred-robot scan
      below cannot elect one either.
    * D3(c), a bid from a robot the fleet monitor has DECLARED OFFLINE. A bid
      does not refresh a heartbeat -- only ``FleetMonitor.update_robot`` does --
      so a robot whose state stream is lost while its bid traffic survives is
      declared OFFLINE and can still bid on the next announcement. Electing it
      writes ASSIGNED plus ``assigned_robot`` onto a robot whose heartbeat can
      never fire again, and ``check_heartbeats`` skips an already-OFFLINE robot,
      so nothing in the system ever looks at that task again.

    *is_live* is an optional ``robot_id -> bool`` predicate; ``None`` means "ask
    nothing", which is exactly today's behaviour and is what keeps every
    existing three-argument call site meaningful. It is trailing and defaulted
    for the same reason and in the same shape as
    ``TaskQueue.get_next_ready(servable=...)``: the fleet question is answered on
    the node's side of the boundary, while the decision that can actually be
    wrong stays in this ROS-free module where the gate lane can drive it.

    An ALL-OFFLINE or all-withdrawn bid list therefore resolves as
    ``auction_no_bids``, which is the correct landing place and needs no new
    reason string: it feeds D-20's backoff in ``_resolve_auction``. The honest
    detail -- who was discarded and why -- is logged there rather than encoded
    in a status string the dashboard renders as free text.
    """
    bid_list = live_bids(bids)
    if is_live is not None:
        bid_list = [b for b in bid_list if is_live(b.robot_id)]
    preferred = (getattr(task, 'preferred_robot', '') or '') if task else ''

    if preferred:
        for bid in bid_list:
            if bid.robot_id == preferred:
                return bid, OUTCOME_ASSIGN, 'preferred_robot'
        rounds = int(getattr(task, 'auction_rounds', 0) or 0)
        if rounds >= max(1, int(max_rounds)):
            return None, OUTCOME_PREFERENCE_DROPPED, 'preference_dropped'
        return None, OUTCOME_REQUEUE, 'preferred_robot_absent'

    if not bid_list:
        return None, OUTCOME_REQUEUE, 'auction_no_bids'
    return max(bid_list, key=lambda b: b.bid_score), OUTCOME_ASSIGN, ''


#: Which status a requeue lands in, keyed by the reason that caused it.
#:
#: A task nobody bid on was never started, so INTERRUPTED ("was started, was
#: stopped") would be a lie about it; PENDING is the honest resting place and
#: is equally re-auctionable. A task held back waiting for its preferred robot
#: WAS acted on by the operator, and showing that in the dashboard is the point
#: of D-03.
#:
#: D-20's two new reasons are listed explicitly rather than left to the
#: ``.get(..., PENDING)`` default. They resolve to the same status, and saying
#: so here is the difference between a decision and an accident: a task that
#: nobody bid on -- once, five times, or abandoned -- was still never STARTED,
#: so PENDING remains the only honest status for it. What changed is the
#: reason, not the state.
#:
#: ``AUCTION_PREEMPTED`` IS DELIBERATELY ABSENT and its absence is a decision,
#: not the omission it looks like. Every reason in this map answers "an auction
#: RESOLVED against this task; where does it land?", and the answer is a
#: constant because the task was never started. A preempted auction did not
#: resolve at all, so the honest landing place is not a constant: it is
#: whatever the task was doing before the auction opened, which
#: ``TaskQueue.abort_auction`` restores from ``status_before_auction``.
#: Listing it here with a value of PENDING would be exactly the D-03 erasure --
#: an INTERRUPTED task quietly re-PENDed -- reached through a lookup table.
#: ``_resolve_auction`` is the only consumer of this map and the preempt path
#: does not go through it.
REQUEUE_STATUS_BY_REASON = {
    'auction_no_bids': TaskStatus.PENDING,
    'auction_backoff': TaskStatus.PENDING,
    'auction_abandoned': TaskStatus.PENDING,
    'preferred_robot_absent': TaskStatus.INTERRUPTED,
    'preference_dropped': TaskStatus.PENDING,
}


# --------------------------------------------------------------------------- #
#  D-20: backing off an auction nobody bids on                                 #
# --------------------------------------------------------------------------- #
#
# MEASURED, live on ROS 2 Jazzy, 2026-07-31. One task reached auction round
# **261** — a fresh announcement every ~5.5 s, forever, every one of them at
# INFO:
#
#     Auction started for survey_8513ab73 (prospect) at (-95, -170) round=254
#     Auction survey_8513ab73: auction_no_bids (0 bid(s)), re-queued as PENDING
#     Auction started for survey_8513ab73 (prospect) at (-95, -170) round=255
#     ...
#     round=261
#
# Three separate costs, and the third is the one that matters. It floods the
# log; it burns the auction SLOT, because ``_auction_tick`` runs exactly one
# auction at a time and returns early while one is active; and through that
# slot it starves every other PENDING task in the queue for as long as no robot
# can bid. A single unbiddable task stops the whole fleet's dispatch.
#
# WHY IT NEVER TERMINATED. ``resolve_auction_winner`` returns
# ``auction_no_bids`` and the caller re-queues to PENDING, which
# ``get_next_ready`` immediately returns again — the same task, at the same
# priority, with nothing anywhere recording that the last attempt failed.
# ``auction_rounds`` counted the attempts and no code read the count.

#: First failure. Kept as the pre-existing spelling so the value documented in
#: TaskStatus.msg and rendered by the dashboard does not change meaning.
AUCTION_NO_BIDS = 'auction_no_bids'

#: Failing repeatedly; the next announcement is delayed by the backoff.
AUCTION_BACKOFF = 'auction_backoff'

#: Given up. Not announced again until the FLEET changes — see
#: ``TaskQueue.wake_deferred_auctions`` and ``FleetMonitor.idle_arrivals``.
AUCTION_ABANDONED = 'auction_abandoned'

#: What a woken task's ``status_reason`` becomes.
AUCTION_FLEET_CHANGED = 'fleet_changed'


# --------------------------------------------------------------------------- #
#  D2: the bounded retry of a task a SKILL reported FAILED (2026-08-02)        #
# --------------------------------------------------------------------------- #
#
# OBSERVED LIVE on a running ROS 2 Jazzy stack. ``survey_aa78d4f9`` was flipped
# to FAILED; ``select_site_907c0627`` depends_on all ten surveys; every excavate
# and haul in the shipped mission is generated only AFTER select_site COMPLETES.
# ``TaskQueue._ready_tasks`` satisfies a dependency ONLY with COMPLETED, so
# ``select_site_907c0627`` could never become ready, the whole ISRU chain was
# permanently dead, and the dashboard read "Objective 100 kg -- awaiting first
# extraction" for the rest of the run. The only operator signal was a single
# WARNING FleetAlert buried among wheel-slip and drift notices.
#
# THE FIX IS AUCTION ABANDONMENT'S SHAPE, one layer away, because that is the
# same problem already solved well here: a task that attracts no bid for
# ``auction_max_failed_rounds`` gets ``auction_backoff_until = math.inf``, and
# that state is BOTH recoverable (``wake_deferred_auctions``, wired to
# ``FleetMonitor.idle_arrivals``) AND observable (a WARNING FleetAlert that says
# GIVING UP by name). Skill-reported FAILED had NEITHER half: nothing moved a
# task out of FAILED and nothing said the mission had stopped. It now has both
# -- ``TaskQueue.retry_failed_tasks`` called from ``_auction_tick``, and
# ``orchestrator_node._report_attempts_exhausted``.
#
# THESE ARE MODULE CONSTANTS AND NOT ROS PARAMETERS, and that is a decision.
# ``selene_orchestrator/test/test_no_orphan_parameters.py``'s allow-list is down
# to the single name ``fleet_state_publish_rate`` and stays there; more to the
# point, a retry bound is not a per-deployment tuning knob. It is a property of
# the layered design -- ``PathFollower`` already replans up to
# ``navigator.MAX_REPLAN_ATTEMPTS = 3`` before a skill fails at all, so the
# failure this bound counts is one that has ALREADY survived a bounded retry one
# layer down. An operator given a dial would be tuning the wrong layer.

#: How many times one task may be ATTEMPTED before the orchestrator gives up on
#: it. 3, which is the value ``TaskQueue.retry_failed_tasks`` was built and
#: unit-tested against, and the same bound ``navigator.MAX_REPLAN_ATTEMPTS``
#: applies to the replan one layer below.
#:
#: It bounds ATTEMPTS, not retries: 3 means the task runs, fails, runs, fails,
#: runs, fails -- and is then done. Two re-queues, not three.
TASK_MAX_ATTEMPTS = 3

#: ``status_reason`` on a FAILED task the retry sweep has returned to PENDING.
#:
#: The task really is PENDING again and enters the ordinary auction with no
#: special handling; the reason is the only thing that tells the dashboard this
#: row is a SECOND attempt rather than work that has never been tried.
TASK_RETRY_REQUEUED = 'skill_failed_requeued'

#: ``status_reason`` on a FAILED task that has spent every attempt.
#:
#: IT REPLACES THE SKILL'S OWN FAILURE REASON, once, and that trade is
#: deliberate. 'Path blocked, no alternate route' says why the last attempt
#: failed but not that the orchestrator has stopped -- and "stopped" is the one
#: thing an operator has to know, because nothing in this system will clear it.
#: The skill's reason is not lost: it was published in the WARNING FleetAlert
#: ``_on_task_result`` raises per failure, it is the ``detail`` of the FAILED
#: TaskEvent in the ring the dashboard replays, and the exhaustion alert quotes
#: it verbatim.
TASK_ATTEMPTS_EXHAUSTED = 'attempts_exhausted'


# --------------------------------------------------------------------------- #
#  D2, the other half: the SOFT dependency edge (2026-08-02)                   #
# --------------------------------------------------------------------------- #
#
# A BOUNDED RETRY MAKES THE STOP BOUNDED AND LOUD. IT DOES NOT MAKE THE MISSION
# SURVIVE A LOST SURVEY. After the third attempt the survey rests in FAILED
# forever, and until now every dependent needed it COMPLETED -- so the mission
# was still permanently dead, just noisily. What changed is that the queue now
# distinguishes the two kinds of edge the mission has always had:
#
#   HARD / CAUSAL      select_site -> excavate -> haul -> excavate ...
#                      Unchanged, and it must stay unchanged: a haul admitted
#                      without its excavate would put a mass in the ISRU ledger
#                      that no extraction produced.
#   SOFT / EVIDENTIAL  survey -> select_site. ``htn_planner._pick_best_site``
#                      scores the FUSED posterior and never reads the survey
#                      task list, so losing one of ten surveys degrades
#                      confidence, not correctness.
#
# See ``TaskQueue.dependencies_met`` for the rule and
# ``htn_planner.SELECT_SITE_SURVEY_QUORUM`` for why the quorum is 1 and not 0.

#: ``status_reason`` on a select_site task resolved with EVERY survey COMPLETED.
#:
#: It was a bare literal in ``htn_planner`` and is promoted to a constant only
#: so it cannot drift from its partial-evidence twin below: the two are read as
#: a pair by anyone asking "was this site chosen on the whole zone or not".
SITE_SELECTED = 'site_selected'

#: ``status_reason`` on a select_site task resolved on a PARTIAL quorum.
#:
#: Every survey was RESOLVED and at least ``SELECT_SITE_SURVEY_QUORUM`` of them
#: COMPLETED, but not all of them did -- the rest exhausted every attempt and
#: stay FAILED. The mission PROCEEDED rather than deadlocking, and the site is
#: the best cell of a smaller surveyed area than was planned.
#:
#: THIS IS THE DURABLE HALF OF THE OPERATOR DISCLOSURE. The WARNING FleetAlert
#: raised beside it lives in a 32-entry ring; this sits on the task row for the
#: rest of the mission, so an operator who joins an hour later still sees it.
#:
#: TWENTY-ONE CHARACTERS, DELIBERATELY: ``TaskQueue.jsx`` renders
#: ``truncate(task.status_reason, 26)``, so a longer spelling would reach the
#: operator's badge cut off mid-word. The full string survives in the row title
#: either way.
SITE_SELECTED_PARTIAL = 'site_selected_partial'


# --------------------------------------------------------------------------- #
#  Operator emergency preemption (2026-08-01)                                  #
# --------------------------------------------------------------------------- #
#
# A DELIBERATE CHANGE TO AUCTION SEMANTICS, NOT A DEFECT FIX, and it is written
# here in those terms because the alternative reading turns a decision into an
# accident.
#
# Until now the orchestrator ran exactly one auction at a time and NOTHING could
# interrupt it: ``_auction_tick`` returns early while ``TaskAuction.is_active()``
# and no priority, however high, changed that. An operator injection at priority
# 10.0 therefore waited for whatever was in flight, and the Phase 5 exit gate's
# check 6 sometimes lost that race.
#
# The decision taken was NOT "make priority preempt". It was "let the operator
# SAY it is an emergency, and preempt only then". A non-emergency priority-10
# injection keeps exactly the old behaviour. The reason to draw the line there
# rather than at priority is that priority is a scheduling number the planner
# also writes, and inferring intent from it would mean any future task type
# given a high number silently acquired the right to abort auctions.

#: What the PREEMPTED task's ``status_reason`` becomes. It is written on the
#: VICTIM, never on the emergency task: "my auction was taken away", not
#: "I took one".
AUCTION_PREEMPTED = 'auction_preempted'


def should_preempt(running_task, candidate) -> bool:
    """May *candidate* abort the in-flight auction for *running_task*?

    Pure, so the whole decision is testable without a ROS node, an auction
    object or a clock -- the same split, for the same reason, as
    ``resolve_auction_winner`` above.

    True iff ALL of:

    * *candidate* is not None -- there is something to preempt FOR.
    * ``candidate.emergency`` -- THE WHOLE CONTROL SURFACE. A priority-10
      injection with this false waits, exactly as it did before this function
      existed. There is no ROS parameter and no threshold: the operator's own
      flag is the only input, so there is nothing to misconfigure and nothing
      that can be tuned into "always preempt" by accident.
    * ``not candidate.preemption_spent`` -- THE BOUND, and it is a bound on the
      TOTAL number of auctions one injection may abort, not a rate. Nothing
      ever clears ``emergency``, so without this the flag would be a standing
      licence: an emergency nobody bids on is backed off, released again by
      ``wake_deferred_auctions`` on every fleet change, and would abort
      whatever fresh auction was in flight each time -- once per robot that
      finishes anything, for the rest of the mission, with the victim's round
      refunded every time so it could never complete one. One injection buys
      ONE abort. A second could not help anyway: an abort frees the auction
      SLOT and never a robot, so if the emergency did not attract a bid the
      first time, the slot is not what it was short of.
    * the two are not the same task -- a task cannot preempt its own auction,
      which would abort a round and immediately re-open it, forever.
    * ``candidate.priority > running_task.priority``, STRICTLY. THIS IS THE
      TERMINATION ARGUMENT. Two emergencies at equal priority -- and every
      operator injection is priority 10.0, so two emergencies are ALWAYS at
      equal priority -- do not preempt each other. Without the strictness a
      second emergency would abort the first one's auction, the first would
      abort the second's on the next tick, and the fleet would trade the
      auction slot back and forth without ever resolving a round. Equal
      priority is settled by ``TaskQueue.get_next_ready``'s emergency
      tie-break and then by waiting, which is finite.
    * ``candidate.task_type != 'select_site'`` -- select_site is a VIRTUAL task
      the HTN planner resolves and no robot ever bids on (``_auction_tick``
      skips it). Aborting a real auction to open one that will never be
      announced would strand the slot. It cannot arise today, because
      ``inject_task_logic`` rejects every task_type outside
      MANUAL_TASK_CAPABILITIES and only ``inject_task_logic`` sets
      ``emergency``, but the guard is cheap and the coupling between those two
      facts is not obvious from here.

    *running_task* MAY BE None, and then an emergency candidate may preempt.
    That is the case where the task whose auction is in flight has vanished
    from the queue between the tick that started it and this one -- there is no
    priority left to compare against and nothing that can be starved by taking
    the slot back.

    WHAT THIS FUNCTION DOES NOT DECIDE, and must not be read as having decided.
    It answers "MAY this candidate preempt", never "WILL the preemption buy
    anything". Whether an idle robot exists that can bid on the candidate, and
    whether the D-06 ledger will let it be announced at all, are questions about
    the fleet and the inventory that a pure function of two tasks cannot see;
    ``orchestrator_node._preempt_for_emergency`` asks both BEFORE it aborts
    anything. The split matters because an abort that is not followed by an
    announcement in the same tick empties the auction slot and gives it to
    nobody -- worse than not preempting, and the reason those gates are on the
    caller's side of this boundary rather than bolted on here with a fleet
    handle threaded through.
    """
    if candidate is None:
        return False
    if not getattr(candidate, 'emergency', False):
        return False
    if getattr(candidate, 'preemption_spent', False):
        return False
    if getattr(candidate, 'task_type', '') == 'select_site':
        return False
    if running_task is None:
        return True
    if getattr(candidate, 'task_id', '') == getattr(running_task, 'task_id', ''):
        return False
    return float(getattr(candidate, 'priority', 0.0)) > \
        float(getattr(running_task, 'priority', 0.0))


def auction_backoff_sec(failed_rounds: int, base_sec: float,
                        max_sec: float) -> float:
    """Seconds to wait before re-announcing, after *failed_rounds* failures.

    Binary exponential, ``base * 2**(n-1)``, clamped to *max_sec*. At the
    shipped 5 s base and 120 s cap that is 5, 10, 20, 40, 80, 120, 120, ...

    WHY EXPONENTIAL AND NOT A FIXED LONGER PERIOD. The two things that make a
    task unbiddable have opposite timescales. A robot busy on a 40 s excavate
    frees itself soon, and a fixed 60 s delay would idle the fleet waiting for
    a task that was biddable after 10; a task no robot in the fleet can EVER
    service (wrong capability, permanently out of energy range) must not be
    retried on any schedule at all. A doubling delay is cheap for the first
    case and converges to the cap for the second, and the give-up bound is what
    handles the second properly.

    *base_sec* is not defaulted to ``auction_timeout_sec``, though 5.0 is the
    same number today: they measure different things — how long an auction
    stays open, versus how long to wait before opening another — and coupling
    them would mean a slower auction silently became a slower retry.

    Defensive on the inputs because both come from ROS parameters an operator
    can set: a non-positive base or cap disables the delay rather than
    producing a negative deadline, and *failed_rounds* below 1 returns 0.0.
    """
    rounds = int(failed_rounds)
    if rounds < 1:
        return 0.0
    base = float(base_sec)
    cap = float(max_sec)
    if not (base > 0.0) or not (cap > 0.0):
        return 0.0
    # Exponent capped before the shift: 2**261 is a perfectly good Python int
    # and there is no reason to build it only to take a min() of it.
    exponent = min(rounds - 1, 32)
    return min(base * float(2 ** exponent), cap)


def auction_failure_reason(failed_rounds: int, max_rounds: int) -> str:
    """The ``status_reason`` for a no-bid auction, given the failure count.

    One reason per state rather than per round, which is what lets the caller
    log only on a CHANGE: 261 rounds produced 261 identical INFO lines because
    every round carried the same reason and there was nothing to compare.

    ``max_rounds <= 0`` disables giving up entirely — the task backs off to the
    cap and keeps retrying forever, which is the pre-D-20 behaviour slowed
    down. It is a supported configuration, not a mistake, so it must not
    silently abandon on round 1.
    """
    rounds = int(failed_rounds)
    limit = int(max_rounds)
    if limit > 0 and rounds >= limit:
        return AUCTION_ABANDONED
    if rounds <= 1:
        return AUCTION_NO_BIDS
    return AUCTION_BACKOFF
