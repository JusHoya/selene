"""Auction window management for task allocation."""

import math
from dataclasses import dataclass


@dataclass
class Bid:
    task_id: str
    robot_id: str
    bid_score: float
    estimated_arrival_time: float
    energy_after_task: float


#: The score an agent publishes to WITHDRAW a bid it has already made.
#:
#: THE SENTINEL IS THE WHOLE PROTOCOL. ``selene_msgs/msg/BidResponse.msg`` has
#: no withdrawal flag and no constant; the only contract the field carries is
#: ``docs/PRD.md:645``, "higher = more suitable". So an operator ``cancel_task``
#: against a robot in BIDDING is expressed by
#: ``agent_node._publish_bid_withdrawal`` as a magic number in one comment, and
#: until this constant existed nothing on the orchestrator side read it at all:
#: a lone withdrawal was a non-empty bid list and WON its own auction at -1.0.
#:
#: DUPLICATED HERE RATHER THAN IMPORTED, and that is deliberate.
#: ``selene_orchestrator`` does not depend on ``selene_agent``, and the one
#: function that must read the sentinel -- ``task_feed.resolve_auction_winner``
#: -- lives in a module that imports no ROS by design, so a constant in a
#: ``.msg`` file would be unreachable from it as well as needing a ``rosidl``
#: regeneration for no reader. The two sides are held equal by a source-parsing
#: test (``test_bid_withdrawal.py::test_agent_sentinel_matches_this_constant``),
#: which is this repository's established way of crossing this exact boundary --
#: ``test_params_files_are_applied.py`` does the same for the ``bid_weight_*``
#: names.
WITHDRAWN_BID_SCORE = -1.0


def is_withdrawal(bid) -> bool:
    """Is this BidResponse a withdrawal rather than an offer?

    KEYED ON THE SENTINEL, NOT ON THE SIGN. "score < 0 is not a bid" is the
    broader rule and it is the wrong one: it invents a contract the PRD never
    stated, and it would turn a negative ``bid_weight_*`` misconfiguration
    (agent_node.py, agent.launch.py) into a silent fleet-wide no-bid stall.
    ``-1.0`` is exact in float32, so the wire round-trip cannot blunt the
    comparison, and the gap ``(-1.0, 0.0)`` has no producer at all.

    NON-FINITE SCORES ARE INCLUDED, one clause wider than VL-29 strictly needs.
    NaN is reachable from a NaN odometry reading through the agent's bid
    scoring, and ``max()`` over a list containing NaN returns whichever element
    came first -- so a NaN bid does not merely lose, it can WIN. Treating it as
    "not an offer" is the only reading under which the auction stays total.
    """
    score = float(bid.bid_score)
    return score <= WITHDRAWN_BID_SCORE or not math.isfinite(score)


def live_bids(bids) -> list:
    """Drop every bid from a robot that withdrew during this auction window.

    A WITHDRAWAL CANCELS THE BID ITS ROBOT ALREADY MADE, not just the sentinel
    row that carries it. ``TaskAuction`` has no notion of a bid being
    superseded, so the withdrawal arrives as a SECOND row beside the robot's
    earlier positive one; dropping only the sentinel leaves that 0.9 in the list
    and it still wins, which is the production shape of VL-29 rather than the
    reported one.

    Discarding the robot entirely is correct because it cannot service the bid:
    an operator ``cancel_task`` has already returned it to IDLE with no pending
    task, and it cannot re-bid inside the same window either -- a
    re-announcement is a new round and ``TaskAuction.start`` clears ``_bids``.
    """
    bid_list = list(bids)
    withdrawn = {b.robot_id for b in bid_list if is_withdrawal(b)}
    return [b for b in bid_list if b.robot_id not in withdrawn]


class TaskAuction:
    def __init__(self, timeout_sec: float = 5.0):
        self._timeout = timeout_sec
        self._task_id: str = ""
        self._start_time: float = 0.0
        self._active: bool = False
        self._bids: list[Bid] = []

    def start(self, task_id: str, start_time: float) -> None:
        self._task_id = task_id
        self._start_time = start_time
        self._active = True
        self._bids = []

    def add_bid(self, bid: Bid) -> None:
        """Record one bid, or apply one WITHDRAWAL, in the open window.

        THE RETRACTION IS APPLIED AT INGEST, which is where it belongs: the
        decision function one module over (``task_feed.resolve_auction_winner``)
        also filters, but a withdrawal left in ``_bids`` would still be counted
        by ``get_bid_count`` -- so ``_resolve_auction`` logged "1 bid(s)" for an
        auction with nothing in it -- and would still be handed to
        ``FleetMonitor.note_stranded_bidders`` by ``_preempt_for_emergency``,
        marking a robot that had already left BIDDING and buying one spurious
        idle arrival on a LATER auction.
        """
        if not self._active:
            return
        if bid.task_id != self._task_id:
            return
        if is_withdrawal(bid):
            self._bids = [b for b in self._bids if b.robot_id != bid.robot_id]
            return
        self._bids.append(bid)

    def is_active(self) -> bool:
        return self._active

    def is_timed_out(self, current_time: float) -> bool:
        if not self._active:
            return False
        return (current_time - self._start_time) >= self._timeout

    def select_winner(self) -> Bid | None:
        """Highest live bid, or None.

        THIS METHOD HAS NO PRODUCTION CALLER, and saying so is the point of the
        sentence. ``_resolve_auction`` elects through
        ``task_feed.resolve_auction_winner``, which is the only implementation
        that can express a preferred robot, an outcome and a reason. This one is
        kept and fixed rather than deleted -- the same disclosure
        ``orchestrator_node._publish_assignment_msg`` carries -- because it was a
        DORMANT SECOND COPY of VL-29: it took ``max()`` over ``_bids`` and
        guarded only on emptiness, so a withdrawal-only list elected the robot
        that withdrew. A dormant copy of a defect is still a defect the next
        caller inherits.

        The ``live_bids`` call is belt and braces given ``add_bid`` now filters
        at ingest: it is what keeps the method correct for a ``_bids`` list
        populated any other way.
        """
        bids = live_bids(self._bids)
        if not bids:
            return None
        return max(bids, key=lambda b: b.bid_score)

    def get_task_id(self) -> str:
        return self._task_id

    def get_bids(self) -> list[Bid]:
        return list(self._bids)

    def get_bid_count(self) -> int:
        return len(self._bids)

    def reset(self) -> None:
        self._task_id = ""
        self._start_time = 0.0
        self._active = False
        self._bids = []
