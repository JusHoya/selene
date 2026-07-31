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


def resolve_auction_winner(task, bids: Iterable[Any],
                           max_rounds: int) -> tuple[Any, str, str]:
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
    """
    bid_list = list(bids)
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
