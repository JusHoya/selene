"""Tests for TaskAuction."""

from selene_orchestrator.task_auction import TaskAuction, Bid


class TestTaskAuction:

    def test_start_activates(self):
        a = TaskAuction(timeout_sec=5.0)
        a.start('t1', start_time=100.0)
        assert a.is_active()
        assert a.get_task_id() == 't1'

    def test_add_bid(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        a.add_bid(Bid('t1', 'scout_01', 0.8, 10.0, 0.5))
        assert a.get_bid_count() == 1

    def test_ignore_bid_wrong_task(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        a.add_bid(Bid('t2', 'scout_01', 0.8, 10.0, 0.5))
        assert a.get_bid_count() == 0

    def test_ignore_bid_inactive(self):
        a = TaskAuction()
        a.add_bid(Bid('t1', 'scout_01', 0.8, 10.0, 0.5))
        assert a.get_bid_count() == 0

    def test_timeout(self):
        a = TaskAuction(timeout_sec=5.0)
        a.start('t1', 100.0)
        assert not a.is_timed_out(104.0)
        assert a.is_timed_out(105.0)
        assert a.is_timed_out(110.0)

    def test_select_winner_highest(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        a.add_bid(Bid('t1', 's1', 0.5, 10.0, 0.3))
        a.add_bid(Bid('t1', 's2', 0.9, 8.0, 0.6))
        a.add_bid(Bid('t1', 's3', 0.7, 12.0, 0.4))
        winner = a.select_winner()
        assert winner.robot_id == 's2'
        assert winner.bid_score == 0.9

    def test_select_winner_no_bids(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        assert a.select_winner() is None

    def test_reset(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        a.add_bid(Bid('t1', 's1', 0.8, 10.0, 0.5))
        a.reset()
        assert not a.is_active()
        assert a.get_bid_count() == 0
        assert a.get_task_id() == ''

    def test_tiebreak_first_bid_wins(self):
        a = TaskAuction()
        a.start('t1', 100.0)
        a.add_bid(Bid('t1', 's1', 0.8, 10.0, 0.5))
        a.add_bid(Bid('t1', 's2', 0.8, 8.0, 0.6))
        winner = a.select_winner()
        # max() returns first max element
        assert winner.robot_id == 's1'
