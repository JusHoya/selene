"""Auction window management for task allocation."""

from dataclasses import dataclass


@dataclass
class Bid:
    task_id: str
    robot_id: str
    bid_score: float
    estimated_arrival_time: float
    energy_after_task: float


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
        if not self._active:
            return
        if bid.task_id != self._task_id:
            return
        self._bids.append(bid)

    def is_active(self) -> bool:
        return self._active

    def is_timed_out(self, current_time: float) -> bool:
        if not self._active:
            return False
        return (current_time - self._start_time) >= self._timeout

    def select_winner(self) -> Bid | None:
        if not self._bids:
            return None
        return max(self._bids, key=lambda b: b.bid_score)

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
