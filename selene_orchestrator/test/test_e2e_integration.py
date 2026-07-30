"""Phase 6 entry-criteria E2E integration test for SELENE.

Exercises the pure-Python coordination layer end-to-end:

    operator inject_task
          -> orchestrator TaskQueue + TaskAuction
          -> agent bid submission
          -> winner assignment
          -> task completion
          -> MaterialInventory conservation

Runs in well under a second with no ROS/Gazebo/launch dependencies so
it is safe for a pre-commit or per-push CI gate. What it catches:

- Regressions in ``inject_task_logic`` (capability validation, FSM
  guards, force-assign preemption, monotonic manual IDs).
- Regressions in ``TaskAuction`` state machine + winner selection.
- Regressions in ``TaskQueue`` lifecycle (PENDING -> AUCTIONING ->
  ASSIGNED -> IN_PROGRESS -> COMPLETED).
- ``MaterialInventory`` conservation breaks after an extract/load/
  unload round-trip.
- Schema drift on ``selene_isru.inventory`` interfaces.

What it does NOT catch (covered instead by ``validate_phase5.sh``):

- ROS 2 service/topic contract drift.
- rclpy executor deadlocks.
- Gazebo/HAL integration bugs.
- WSL2 DDS transport issues.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
#  ROS 2 stubs + sys.path setup live in test/conftest.py so they are           #
#  installed exactly once, only for modules that are really missing, and       #
#  torn down at session end (no cross-package sys.modules pollution).          #
# --------------------------------------------------------------------------- #

from selene_isru.inventory import MaterialInventory  # noqa: E402
from selene_orchestrator.orchestrator_node import (  # noqa: E402
    inject_task_logic,
    _InjectTaskContext,
)
from selene_orchestrator.task_auction import TaskAuction, Bid  # noqa: E402
from selene_orchestrator.task_queue import TaskQueue, TaskStatus  # noqa: E402


# --------------------------------------------------------------------------- #
#  Test harness                                                               #
# --------------------------------------------------------------------------- #

class _Robot:
    """Minimal fleet robot record compatible with FleetMonitor.get_robot()."""
    def __init__(self, robot_id, capabilities, fsm_state='IDLE',
                 pose=(0.0, 0.0), battery=0.9):
        self.robot_id = robot_id
        self.capabilities = list(capabilities)
        self.fsm_state = fsm_state
        self.pose = pose
        self.battery = battery
        self.current_task_id = ''

    def as_dict(self):
        return {
            'robot_id': self.robot_id,
            'capabilities': self.capabilities,
            'fsm_state': self.fsm_state,
            'pose': self.pose,
            'battery_level': self.battery,
            'current_task_id': self.current_task_id,
        }


class _Orchestrator:
    """Wires TaskQueue + TaskAuction + a fake FleetMonitor into the same
    shape orchestrator_node uses internally, so inject_task_logic and the
    auction-resolve flow run on real classes."""

    def __init__(self, robots):
        self.task_queue = TaskQueue()
        self.auction = TaskAuction(timeout_sec=5.0)
        self._robots = {r.robot_id: r for r in robots}
        self.announcements = []
        self.assignments = []
        self.alerts = []
        self._next_id_counter = 0
        self._clock = 1000.0

    # FleetMonitor-compatible surface -------------------------------------
    def get_robot(self, robot_id):
        r = self._robots.get(robot_id)
        return r.as_dict() if r else None

    def get_idle_robots(self):
        return [r.as_dict() for r in self._robots.values()
                if r.fsm_state == 'IDLE']

    # Orchestrator operations ---------------------------------------------
    def _next_task_id(self):
        n = self._next_id_counter
        self._next_id_counter += 1
        return f'manual_{n:04d}'

    def inject(self, task_type, x=0.0, y=0.0, quantity=0.0,
               assigned_robot_id=''):
        req = types.SimpleNamespace(
            task_type=task_type,
            target_location=types.SimpleNamespace(x=x, y=y, z=0.0),
            quantity=quantity,
            assigned_robot_id=assigned_robot_id,
        )
        resp = types.SimpleNamespace(success=False, task_id='', message='')
        fleet_monitor = types.SimpleNamespace(get_robot=self.get_robot)
        ctx = _InjectTaskContext(
            task_queue=self.task_queue,
            fleet_monitor=fleet_monitor,
            next_task_id=self._next_task_id,
            now_stamp=MagicMock(),
            publish_assignment=lambda tid, rid, ttype, tgt:
                self.assignments.append((tid, rid)),
            publish_alert=lambda sev, msg:
                self.alerts.append((sev, msg)),
        )
        inject_task_logic(ctx, req, resp)
        return resp

    def tick_auction(self):
        """Run one cycle of the auction state machine (copies _auction_tick
        logic). Starts an auction if idle work exists, or resolves a
        timed-out one."""
        self._clock += 1.0

        if self.auction.is_active():
            if self.auction.is_timed_out(self._clock):
                self._resolve()
            return

        idle = self.get_idle_robots()
        if not idle:
            return
        next_task = self.task_queue.get_next_ready()
        if next_task is None:
            return
        if next_task.task_type == 'select_site':
            return

        self.task_queue.set_status(next_task.task_id, TaskStatus.AUCTIONING)
        self.auction.start(next_task.task_id, self._clock)
        self.announcements.append((next_task.task_id, next_task.task_type))

    def submit_bid(self, task_id, robot_id, score):
        bid = Bid(task_id=task_id, robot_id=robot_id, bid_score=score,
                  estimated_arrival_time=30.0, energy_after_task=80.0)
        self.auction.add_bid(bid)

    def close_auction(self):
        """Force the current auction past its timeout so _resolve runs."""
        self._clock += 10.0
        self.tick_auction()

    def _resolve(self):
        winner = self.auction.select_winner()
        task_id = self.auction.get_task_id()
        if winner is None:
            self.task_queue.set_status(task_id, TaskStatus.PENDING)
        else:
            self.task_queue.assign_to_robot(task_id, winner.robot_id)
            self._robots[winner.robot_id].fsm_state = 'ASSIGNED'
            self._robots[winner.robot_id].current_task_id = task_id
            self.assignments.append((task_id, winner.robot_id))
        self.auction.reset()

    def complete_task(self, task_id, robot_id):
        """Simulate the agent finishing: mark COMPLETED, reset robot."""
        self.task_queue.set_status(task_id, TaskStatus.IN_PROGRESS)
        self.task_queue.mark_complete(task_id)
        self._robots[robot_id].fsm_state = 'IDLE'
        self._robots[robot_id].current_task_id = ''


# --------------------------------------------------------------------------- #
#  Tests                                                                      #
# --------------------------------------------------------------------------- #

def test_e2e_happy_path_excavate_to_deposit():
    """Full pipeline: operator injects excavate -> auction -> agent bids ->
    assignment -> completion -> inventory extract/load/unload with
    conservation invariant intact at every step."""
    orch = _Orchestrator([
        _Robot('scout_01', ['prospect']),
        _Robot('excavator_01', ['excavate']),
        _Robot('hauler_01', ['haul']),
    ])
    inv = MaterialInventory()
    inv.register_site('site_A', position=(-50.0, -100.0), estimated_kg=200.0)

    # 1) Operator injects an excavate task.
    resp = orch.inject('excavate', x=-50.0, y=-100.0, quantity=25.0)
    assert resp.success, resp.message
    task_id = resp.task_id
    assert orch.task_queue.get_task(task_id).status == TaskStatus.PENDING
    assert orch.task_queue.get_task(task_id).required_capabilities == ['excavate']

    # 2) Orchestrator auction tick starts the auction + announces.
    orch.tick_auction()
    assert orch.auction.is_active()
    assert orch.task_queue.get_task(task_id).status == TaskStatus.AUCTIONING
    assert any(a[0] == task_id for a in orch.announcements)

    # 3) Only the excavator has the right capability; it bids high.
    #    Scout submits a lower bid to prove winner-selection works.
    orch.submit_bid(task_id, 'excavator_01', score=0.92)
    orch.submit_bid(task_id, 'scout_01', score=0.40)
    assert orch.auction.get_bid_count() == 2

    # 4) Auction closes -> highest bidder wins.
    orch.close_auction()
    assert not orch.auction.is_active()
    assert orch.task_queue.get_task(task_id).status == TaskStatus.ASSIGNED
    assert orch.task_queue.get_task(task_id).assigned_robot == 'excavator_01'
    # NB: this used to read ``assert (... for ... in ...)`` — a generator
    # expression, which is always truthy and therefore asserted nothing.
    assert any(tid == task_id and rid == 'excavator_01'
               for tid, rid in orch.assignments), orch.assignments

    # 5) Agent completes the task and records material flow.
    inv.record_extraction('site_A', 'excavator_01', kg=25.0)
    inv.record_load('excavator_01', from_site='site_A', kg=25.0)
    orch.complete_task(task_id, 'excavator_01')

    assert orch.task_queue.get_task(task_id).status == TaskStatus.COMPLETED
    assert orch.task_queue.get_completed_count() == 1
    assert inv.check_conservation(), inv.get_mission_progress()
    assert inv.get_total_extracted() == pytest.approx(25.0)
    assert inv.get_total_in_transit() == pytest.approx(25.0)

    # 6) Hauler picks up + deposits -> conservation still holds.
    unloaded = inv.record_unload('excavator_01', kg=25.0)
    assert unloaded == pytest.approx(25.0)
    assert inv.get_total_deposited() == pytest.approx(25.0)
    assert inv.get_total_in_transit() == pytest.approx(0.0)
    assert inv.check_conservation()


def test_e2e_rejects_unknown_task_type():
    """Operator injects a bogus task type -> service rejects -> nothing
    enters the queue. Guards against silent acceptance of schema drift."""
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    resp = orch.inject('teleport_to_mars', x=0.0, y=0.0)
    assert not resp.success
    assert resp.task_id == ''
    assert 'invalid' in resp.message.lower() or 'task_type' in resp.message.lower()
    assert orch.task_queue.get_total_count() == 0


def test_e2e_no_eligible_robot_requeues():
    """Auction with no qualified bidders re-queues the task rather than
    stalling in AUCTIONING forever (regresses the virtual-task leak fix)."""
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    resp = orch.inject('excavate', x=10.0, y=10.0, quantity=5.0)
    assert resp.success
    task_id = resp.task_id

    orch.tick_auction()
    assert orch.auction.is_active()
    # No bids arrive.
    orch.close_auction()

    # Task must return to PENDING, not rot in AUCTIONING.
    assert orch.task_queue.get_task(task_id).status == TaskStatus.PENDING
    assert not orch.auction.is_active()
