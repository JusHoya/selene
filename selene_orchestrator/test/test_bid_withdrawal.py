"""A withdrawn bid must not win its auction — VL-29.

THE SENTINEL IS THE WHOLE PROTOCOL. ``selene_msgs/msg/BidResponse.msg`` carries
no withdrawal flag and no constant; the only documented contract on the field is
``docs/PRD.md:645``, "higher = more suitable". An operator ``cancel_task``
against a robot in BIDDING is expressed by ``agent_node._publish_bid_withdrawal``
as ``bid_score = -1.0``, a magic number named in one comment.

NOTHING ON THE ORCHESTRATOR SIDE READ IT. ``resolve_auction_winner`` guarded on
``if not bid_list`` -- emptiness, not liveness -- so a withdrawal-only list was
non-empty and ``max()`` elected the robot that withdrew, at -1.0. The
preferred-robot branch was worse: it ignores score entirely, so it elected a
withdrawal without even comparing it.

THE PRODUCTION SHAPE IS NOT THE REPORTED SHAPE, and that is why the fix cannot
be "ignore -1.0". ``TaskAuction`` has no notion of a bid being superseded --
``add_bid`` filters on ``_active`` and ``task_id`` only -- so a withdrawal
arrives as a SECOND row beside the robot's earlier positive bid. Dropping only
the sentinel leaves that 0.9 in the list, and it still wins. A withdrawal
therefore cancels every bid its robot made in the window.

This is CLAUDE.md's "wired but never called" one frame smaller: the writer is
the agent, and the missing reader is the orchestrator.

NOT DEMONSTRATED. There is no ROS 2 on this host; the claim these tests support
is "implemented and unit-tested". The live shape would be an operator
``cancel_task`` issued against a robot in BIDDING during an auction, checked for
the task NOT ending up ASSIGNED to that robot.
"""

from __future__ import annotations

import ast
import pathlib

from selene_orchestrator.task_auction import (
    Bid,
    TaskAuction,
    WITHDRAWN_BID_SCORE,
    is_withdrawal,
    live_bids,
)
from selene_orchestrator.task_feed import (
    OUTCOME_ASSIGN,
    OUTCOME_REQUEUE,
    resolve_auction_winner,
)
from selene_orchestrator.task_queue import TaskQueue


REPO = pathlib.Path(__file__).resolve().parents[2]


def _task(preferred_robot='', rounds=0):
    q = TaskQueue()
    q.add_task('t1', 'prospect', 0.0, 0.0, preferred_robot=preferred_robot)
    for _ in range(rounds):
        q.begin_auction('t1')
    return q.get_task('t1')


def _bid(robot_id, score):
    return Bid('t1', robot_id, score, 30.0, 80.0)


# ------------------------------------------------- the election, VL-29 proper

def test_a_lone_withdrawal_does_not_win_its_auction():
    """The reported shape. At HEAD this returned ``Bid('scout_09', -1.0)``."""
    winner, outcome, reason = resolve_auction_winner(
        _task(), [_bid('scout_09', WITHDRAWN_BID_SCORE)], 3)
    assert winner is None
    assert outcome == OUTCOME_REQUEUE
    assert reason == 'auction_no_bids'


def test_a_withdrawal_cancels_the_bid_that_robot_already_made():
    """THE PRODUCTION SHAPE, and the one that proves the fix is not cosmetic.

    A naive "drop the -1.0 row" filter passes the test above and FAILS this one:
    the robot's earlier 0.9 is still in the list and still wins.
    """
    bids = [_bid('scout_09', 0.9), _bid('scout_09', WITHDRAWN_BID_SCORE)]
    winner, outcome, reason = resolve_auction_winner(_task(), bids, 3)
    assert winner is None
    assert outcome == OUTCOME_REQUEUE
    assert reason == 'auction_no_bids'


def test_a_withdrawal_does_not_outrank_a_live_rival():
    bids = [_bid('scout_09', 0.9), _bid('scout_09', WITHDRAWN_BID_SCORE),
            _bid('scout_01', 0.4)]
    winner, outcome, _ = resolve_auction_winner(_task(), bids, 3)
    assert winner.robot_id == 'scout_01'
    assert outcome == OUTCOME_ASSIGN


def test_a_withdrawn_preferred_robot_does_not_win():
    """The unreported second path, and the worse one.

    The preferred-robot scan ignores score entirely, so it elected a -1.0
    without comparing anything. The filter therefore runs BEFORE it.
    """
    task = _task(preferred_robot='hauler_02', rounds=1)
    bids = [_bid('hauler_02', 0.8), _bid('hauler_02', WITHDRAWN_BID_SCORE)]
    winner, outcome, reason = resolve_auction_winner(task, bids, 3)
    assert winner is None
    assert outcome == OUTCOME_REQUEUE
    assert reason == 'preferred_robot_absent'


def test_a_zero_score_bid_is_still_a_bid():
    """THE NON-REGRESSION THAT KEEPS THE FILTER FROM BEING TOO BROAD.

    "score < 0 is not a bid" is the tempting wider rule and it is wrong: it
    invents a contract the PRD never stated and turns a negative
    ``bid_weight_*`` misconfiguration into a silent fleet-wide no-bid stall.
    """
    winner, outcome, _ = resolve_auction_winner(_task(), [_bid('a', 0.0)], 3)
    assert winner.robot_id == 'a'
    assert outcome == OUTCOME_ASSIGN


def test_a_nan_score_cannot_win():
    """``max()`` over NaN returns whichever element came FIRST.

    So a NaN bid -- reachable from a NaN odometry reading through the agent's
    bid scoring -- does not merely lose, it can WIN. One clause wider than VL-29
    strictly needs, and stated as a deliberate inclusion rather than left
    ambiguous.
    """
    bids = [_bid('a', float('nan')), _bid('b', 0.5)]
    winner, outcome, _ = resolve_auction_winner(_task(), bids, 3)
    assert winner.robot_id == 'b'
    assert outcome == OUTCOME_ASSIGN


# ------------------------------------------------------------------- ingest

def test_a_withdrawal_retracts_at_ingest_so_the_bid_count_is_honest():
    """Filtering only at election would still log "1 bid(s)" for an empty one.

    It would also hand the withdrawn robot to
    ``FleetMonitor.note_stranded_bidders`` on a preemption, marking a robot that
    had already left BIDDING and buying one spurious idle arrival on a LATER
    auction.
    """
    a = TaskAuction()
    a.start('t1', 100.0)
    a.add_bid(_bid('scout_09', 0.9))
    a.add_bid(_bid('scout_09', WITHDRAWN_BID_SCORE))
    assert a.get_bid_count() == 0
    assert a.get_bids() == []


def test_ingest_retracts_only_the_withdrawing_robot():
    a = TaskAuction()
    a.start('t1', 100.0)
    a.add_bid(_bid('scout_09', 0.9))
    a.add_bid(_bid('scout_01', 0.4))
    a.add_bid(_bid('scout_09', WITHDRAWN_BID_SCORE))
    assert [b.robot_id for b in a.get_bids()] == ['scout_01']


def test_select_winner_the_dormant_second_copy():
    """``select_winner`` has NO production caller and carried the same bug.

    Fixed rather than deleted: deleting it would force deleting its three
    existing tests, which is editing tests to make a change land. The
    "no production caller" disclosure lives in its docstring, the way
    ``orchestrator_node._publish_assignment_msg`` carries its own.
    """
    a = TaskAuction()
    a.start('t1', 100.0)
    a._bids = [_bid('scout_09', 0.9), _bid('scout_09', WITHDRAWN_BID_SCORE)]
    assert a.select_winner() is None

    a._bids = [_bid('scout_09', 0.9), _bid('scout_09', WITHDRAWN_BID_SCORE),
               _bid('scout_01', 0.4)]
    assert a.select_winner().robot_id == 'scout_01'


# ---------------------------------------------------------- the predicate

def test_is_withdrawal_reads_the_constant_and_not_the_sign():
    assert is_withdrawal(_bid('a', WITHDRAWN_BID_SCORE)) is True
    assert is_withdrawal(_bid('a', -2.0)) is True
    assert is_withdrawal(_bid('a', float('nan'))) is True
    assert is_withdrawal(_bid('a', float('inf'))) is True
    assert is_withdrawal(_bid('a', 0.0)) is False
    assert is_withdrawal(_bid('a', -0.5)) is False


def test_live_bids_is_order_preserving_and_total():
    bids = [_bid('a', 0.1), _bid('b', 0.2), _bid('a', WITHDRAWN_BID_SCORE),
            _bid('c', 0.3)]
    assert [b.robot_id for b in live_bids(bids)] == ['b', 'c']
    assert live_bids([]) == []


# ------------------------------------------------- the cross-package boundary

def test_agent_sentinel_matches_this_constant():
    """The two sides of a protocol with no shared symbol, held equal by parsing.

    ``selene_orchestrator`` does not depend on ``selene_agent`` and the reader --
    ``task_feed.resolve_auction_winner`` -- imports no ROS by design, so neither
    a shared Python import nor a ``.msg`` constant can carry this value. Reading
    the producer's source is this repository's established way of crossing this
    exact boundary: ``test_params_files_are_applied.py`` parses the same file
    for the ``bid_weight_*`` names, and the agent side does the same to itself in
    ``test_battery_validity_is_wired.py``. No import crosses the boundary, so
    D-36's ``importorskip`` rule does not apply -- that rule is about imports.

    THIS TEST FAILS IF EITHER SIDE MOVES, which is the whole point: today the
    producer's value is a bare literal in ``agent_node._publish_bid_withdrawal``
    (that file is owned elsewhere and was deliberately not edited here), so the
    literal is what is compared. Replacing it with a named import of an agent-side
    constant is an improvement this test keeps honest either way, because it
    resolves a ``Name`` against that module's own assignments.
    """
    source = (REPO / 'selene_agent' / 'selene_agent' / 'agent_node.py'
              ).read_text(encoding='utf-8')
    tree = ast.parse(source)

    module_consts = {
        t.id: n.value.value
        for n in tree.body if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)
    }

    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == '_publish_bid_withdrawal')
    assigned = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == 'bid_score'
                        for t in n.targets)]
    assert len(assigned) == 1, 'the withdrawal sentinel is written exactly once'

    node = assigned[0]
    if isinstance(node, ast.Constant):
        value = node.value
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = -node.operand.value
    elif isinstance(node, ast.Name):
        value = module_consts[node.id]
    else:                                            # pragma: no cover
        raise AssertionError(f'unrecognised sentinel expression: {node!r}')

    assert float(value) == WITHDRAWN_BID_SCORE
