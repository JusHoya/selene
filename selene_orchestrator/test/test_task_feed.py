"""The task-queue snapshot feed and the constrained auction — D-03/D-04/D-05.

Everything here is pure Python and runs in the ROS-free gate lane. That is the
point of ``task_feed.py`` existing at all: ``conftest.py``'s fake node returns
``SimpleNamespace(value=None)`` from every ``get_parameter``, so an
``OrchestratorNode`` cannot be constructed here and any decision left inside it
is untested.
"""

from dataclasses import dataclass

from selene_orchestrator import task_feed
from selene_orchestrator.task_feed import (
    OUTCOME_ASSIGN,
    OUTCOME_PREFERENCE_DROPPED,
    OUTCOME_REQUEUE,
    REQUEUE_STATUS_BY_REASON,
    TaskEventLog,
    resolve_auction_winner,
    task_rows,
)
from selene_orchestrator.task_queue import (
    REQUEUEABLE_STATUSES,
    TaskQueue,
    TaskStatus,
)


@dataclass
class _Bid:
    task_id: str
    robot_id: str
    bid_score: float


# --------------------------------------------------------------- event ring

class TestTaskEventLog:

    def test_seq_is_monotonic_and_never_reused(self):
        log = TaskEventLog(capacity=4)
        seqs = [log.append(kind='status', action='PENDING')['seq']
                for _ in range(10)]
        assert seqs == list(range(10))
        assert log.seq_next == 10
        # Even after eviction, the surviving events keep their original seq.
        assert [e['seq'] for e in log.snapshot()] == [6, 7, 8, 9]

    def test_ring_evicts_oldest_first_and_counts_the_drops(self):
        log = TaskEventLog(capacity=3)
        for i in range(3):
            log.append(kind='status', action=f'A{i}')
        assert log.dropped == 0
        assert [e['action'] for e in log.snapshot()] == ['A0', 'A1', 'A2']

        log.append(kind='status', action='A3')
        assert log.dropped == 1
        assert [e['action'] for e in log.snapshot()] == ['A1', 'A2', 'A3']

    def test_snapshot_is_oldest_first(self):
        log = TaskEventLog(capacity=8)
        for i in range(5):
            log.append(kind='status', action=str(i))
        assert [e['action'] for e in log.snapshot()] == ['0', '1', '2', '3', '4']

    def test_a_client_can_detect_a_gap_from_seq_next_and_the_ring(self):
        """The reason both numbers are on the wire.

        A continuously-connected client knows it missed events when the lowest
        seq in a snapshot exceeds the highest it holds + 1.
        """
        log = TaskEventLog(capacity=2)
        for _ in range(6):
            log.append(kind='status', action='x')
        lowest = log.snapshot()[0]['seq']
        assert lowest == 4
        assert log.seq_next == 6
        assert log.dropped == 4

    def test_capacity_zero_is_floored_rather_than_silently_swallowing(self):
        """deque(maxlen=0) would discard every event while `dropped` climbed."""
        log = TaskEventLog(capacity=0)
        log.append(kind='status', action='kept')
        assert log.capacity == 1
        assert [e['action'] for e in log.snapshot()] == ['kept']

    def test_operator_events_carry_the_response_message_and_verdict(self):
        log = TaskEventLog()
        event = log.append(kind=task_feed.KIND_OPERATOR, action='cancel_task',
                           robot_id='scout_01', actor='operator',
                           detail='robot in ERROR, override rejected',
                           accepted=False, target=(3.0, 4.0))
        assert event['kind'] == 'operator'
        assert event['accepted'] is False
        assert event['detail'] == 'robot in ERROR, override rejected'
        assert event['target'] == (3.0, 4.0)

    def test_every_taskevent_msg_field_is_present(self):
        expected = {'seq', 'stamp', 'kind', 'task_id', 'robot_id', 'actor',
                    'action', 'detail', 'accepted', 'target'}
        log = TaskEventLog()
        assert set(log.append(kind='status', action='PENDING')) == expected


# ------------------------------------------------------------- task_rows

class TestTaskRows:

    def test_projects_every_taskstatus_msg_field_with_the_right_name(self):
        """Field names are the wire's, so a rename fails loudly in the
        publisher rather than reading as a default in the dashboard."""
        expected = {
            'task_id', 'task_type', 'status', 'assigned_robot',
            'preferred_robot', 'priority', 'progress', 'quantity_kg',
            'target_location', 'parent_task_id', 'depends_on',
            'required_capabilities', 'status_reason', 'status_changed',
            'auction_rounds', 'emergency',
        }
        q = TaskQueue()
        q.add_task('t1', 'excavate', 1.0, 2.0)
        (row,) = task_rows(q)
        assert set(row) == expected

    def test_status_is_the_enum_name_as_a_string(self):
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0.0, 0.0)
        q.set_status('t1', TaskStatus.INTERRUPTED, 'operator_cancel_task')
        (row,) = task_rows(q)
        assert row['status'] == 'INTERRUPTED'
        assert isinstance(row['status'], str)
        assert row['status_reason'] == 'operator_cancel_task'

    def test_carries_the_new_d03_d04_fields(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', -8.0, -14.0, priority=10.0,
                   quantity_kg=12.5, preferred_robot='hauler_02',
                   site_id='site_abc')
        q.begin_auction('t1')
        q.assign_to_robot('t1', 'hauler_02')
        q.set_progress('t1', 0.4)
        (row,) = task_rows(q)
        assert row['quantity_kg'] == 12.5
        assert row['preferred_robot'] == 'hauler_02'
        assert row['assigned_robot'] == 'hauler_02'
        assert row['progress'] == 0.4
        assert row['auction_rounds'] == 1
        assert row['target_location'] == (-8.0, -14.0)

    def test_completed_tasks_stay_in_the_table(self):
        """Nothing is removed from the queue, so a browser that loads
        mid-mission still sees the full history."""
        q = TaskQueue()
        q.add_task('t1', 'prospect', 0.0, 0.0)
        q.mark_complete('t1')
        assert [r['status'] for r in task_rows(q)] == ['COMPLETED']


# --------------------------------------------------- the constrained auction

class TestResolveAuctionWinner:

    def test_no_preference_highest_bid_wins(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        bids = [_Bid('t1', 'a', 0.4), _Bid('t1', 'b', 0.9), _Bid('t1', 'c', 0.7)]
        winner, outcome, reason = resolve_auction_winner(q.get_task('t1'), bids, 3)
        assert winner.robot_id == 'b'
        assert outcome == OUTCOME_ASSIGN
        assert reason == ''

    def test_no_preference_no_bids_requeues_as_pending(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        winner, outcome, reason = resolve_auction_winner(q.get_task('t1'), [], 3)
        assert winner is None
        assert outcome == OUTCOME_REQUEUE
        assert reason == 'auction_no_bids'
        assert REQUEUE_STATUS_BY_REASON[reason] == TaskStatus.PENDING

    def test_preferred_robot_wins_even_with_the_worst_score(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        q.begin_auction('t1')
        bids = [_Bid('t1', 'hauler_01', 0.99), _Bid('t1', 'hauler_02', 0.01)]
        winner, outcome, reason = resolve_auction_winner(q.get_task('t1'), bids, 3)
        assert winner.robot_id == 'hauler_02'
        assert outcome == OUTCOME_ASSIGN
        assert reason == 'preferred_robot'

    def test_preferred_robot_absent_under_max_rounds_waits_for_it(self):
        """Not "assign to somebody else": silently substituting a different
        robot is the behaviour the operator used the field to prevent."""
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        q.begin_auction('t1')                       # round 1 of 3
        bids = [_Bid('t1', 'hauler_01', 0.99)]
        winner, outcome, reason = resolve_auction_winner(q.get_task('t1'), bids, 3)
        assert winner is None
        assert outcome == OUTCOME_REQUEUE
        assert reason == 'preferred_robot_absent'
        # It rests in INTERRUPTED, which is re-auctionable, so it keeps moving.
        assert REQUEUE_STATUS_BY_REASON[reason] == TaskStatus.INTERRUPTED
        assert TaskStatus.INTERRUPTED in REQUEUEABLE_STATUSES

    def test_preference_is_dropped_at_max_rounds(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        for _ in range(3):
            q.begin_auction('t1')
        bids = [_Bid('t1', 'hauler_01', 0.99)]
        winner, outcome, reason = resolve_auction_winner(q.get_task('t1'), bids, 3)
        assert winner is None
        assert outcome == OUTCOME_PREFERENCE_DROPPED
        assert reason == 'preference_dropped'
        assert REQUEUE_STATUS_BY_REASON[reason] == TaskStatus.PENDING

    def test_max_rounds_of_one_drops_at_the_first_missed_auction(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        q.begin_auction('t1')
        _, outcome, _ = resolve_auction_winner(q.get_task('t1'), [], 1)
        assert outcome == OUTCOME_PREFERENCE_DROPPED


# ------------------------------------------------------- D3(c): dead bidders

class TestLivenessFilter:
    """A bid from a robot the fleet monitor has DECLARED OFFLINE must not win.

    A bid does not refresh a heartbeat -- only ``FleetMonitor.update_robot``
    does -- so a robot whose state stream is lost while its bid traffic survives
    is declared OFFLINE and can still bid. Electing it writes ASSIGNED plus
    ``assigned_robot`` onto a robot ``check_heartbeats`` will never report again.

    These drive the PURE function. ``test_robot_dropout_recovery.py`` proves the
    predicate is actually wired into ``_resolve_auction``, which is the separate
    claim this repository has been bitten seven times for conflating.
    """

    @staticmethod
    def _live_except(*offline):
        dead = set(offline)
        return lambda rid: rid not in dead

    def test_an_offline_high_bid_loses_to_a_live_low_one(self):
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        bids = [_Bid('t1', 'scout_01', 0.9), _Bid('t1', 'scout_02', 0.1)]
        winner, outcome, reason = resolve_auction_winner(
            q.get_task('t1'), bids, 3, is_live=self._live_except('scout_01'))
        assert winner.robot_id == 'scout_02'
        assert outcome == OUTCOME_ASSIGN
        assert reason == ''

    def test_an_all_offline_bid_list_requeues_as_pending(self):
        """No new reason string: it lands on auction_no_bids and backs off."""
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        bids = [_Bid('t1', 'scout_01', 0.9), _Bid('t1', 'scout_02', 0.5)]
        winner, outcome, reason = resolve_auction_winner(
            q.get_task('t1'), bids, 3,
            is_live=self._live_except('scout_01', 'scout_02'))
        assert winner is None
        assert outcome == OUTCOME_REQUEUE
        assert reason == 'auction_no_bids'
        assert REQUEUE_STATUS_BY_REASON[reason] is TaskStatus.PENDING

    def test_an_offline_preferred_robot_does_not_win(self):
        """The filter runs BEFORE the preferred-robot scan, which ignores score.

        Left after it, the operator's preference would be exactly the path that
        still elects a corpse -- and it is the path an operator uses when a
        specific robot matters most.
        """
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0, preferred_robot='hauler_02')
        q.begin_auction('t1')
        bids = [_Bid('t1', 'hauler_02', 0.8)]
        winner, outcome, reason = resolve_auction_winner(
            q.get_task('t1'), bids, 3, is_live=self._live_except('hauler_02'))
        assert winner is None
        assert outcome == OUTCOME_REQUEUE
        assert reason == 'preferred_robot_absent'

    def test_is_live_none_asks_nothing_and_reproduces_today(self):
        """What keeps the existing three-argument call sites meaningful."""
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        bids = [_Bid('t1', 'scout_01', 0.9), _Bid('t1', 'scout_02', 0.1)]
        assert resolve_auction_winner(q.get_task('t1'), bids, 3)[0].robot_id \
            == 'scout_01'
        assert resolve_auction_winner(
            q.get_task('t1'), bids, 3, is_live=None)[0].robot_id == 'scout_01'

    def test_a_live_robot_that_withdrew_is_still_dropped(self):
        """VL-29 and D3(c) COMPOSE; the second filter does not replace the first.

        Whichever of the two landed second had to compose with the other, so this
        pins the conjunction rather than either clause: ``scout_09`` is alive and
        withdrew, ``scout_01`` is offline and did not.
        """
        q = TaskQueue()
        q.add_task('t1', 'haul', 0.0, 0.0)
        bids = [_Bid('t1', 'scout_09', 0.9), _Bid('t1', 'scout_09', -1.0),
                _Bid('t1', 'scout_01', 0.8), _Bid('t1', 'scout_02', 0.2)]
        winner, outcome, _ = resolve_auction_winner(
            q.get_task('t1'), bids, 3, is_live=self._live_except('scout_01'))
        assert winner.robot_id == 'scout_02'
        assert outcome == OUTCOME_ASSIGN


# --------------------------------------------------------- requeue statuses

def test_interrupted_is_returned_by_get_next_ready_and_completed_is_not():
    """The change that turns INTERRUPTED from a microsecond into a state.

    Before D-03 every caller of interrupt_task immediately overwrote the result
    with PENDING, because get_next_ready() only considered PENDING and an
    INTERRUPTED task would otherwise have been stranded forever.
    """
    q = TaskQueue()
    q.add_task('cancelled', 'prospect', 0.0, 0.0, priority=1.0)
    q.add_task('done', 'prospect', 0.0, 0.0, priority=9.0)
    q.assign_to_robot('cancelled', 'scout_01')
    q.interrupt_task('cancelled', {'reason': 'operator_cancel_task'},
                     reason='operator_cancel_task')
    q.mark_complete('done')

    ready = q.get_next_ready()
    assert ready is not None
    assert ready.task_id == 'cancelled'


def test_a_failed_task_is_never_re_auctioned():
    q = TaskQueue()
    q.add_task('t1', 'excavate', 0.0, 0.0)
    q.mark_failed('t1', 'drill stalled')
    assert q.get_next_ready() is None
