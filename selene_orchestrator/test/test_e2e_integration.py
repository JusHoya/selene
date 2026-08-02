"""Phase 6 entry-criteria E2E integration test for SELENE.

Exercises the pure-Python coordination layer end-to-end:

    operator inject_task
          -> orchestrator TaskQueue + TaskAuction
          -> agent bid submission
          -> winner assignment
          -> TaskResult termination
          -> MaterialEvent -> MaterialInventory conservation

Runs in well under a second with no ROS/Gazebo/launch dependencies so
it is safe for a pre-commit or per-push CI gate. What it catches:

- Regressions in ``inject_task_logic`` (capability validation, FSM
  guards, quantity validation, the constrained auction, monotonic manual IDs).
- Regressions in ``TaskAuction`` state machine + winner selection.
- Regressions in ``TaskQueue`` lifecycle (PENDING -> AUCTIONING ->
  ASSIGNED -> IN_PROGRESS -> COMPLETED, and FAILED / INTERRUPTED). The
  IN_PROGRESS step is driven through ``apply_robot_progress`` from a
  RobotState-shaped input; this harness used to call
  ``set_status(..., IN_PROGRESS)`` itself, which meant the fixture was the
  only thing in the repository that produced that status at all (D-03).
- Regressions in the D-06 haul authorisation gate: a haul the ledger cannot
  cover is withheld from the auction and re-queued rather than assigned,
  because ``quantity_kg`` 0.0 means "fill to capacity" on the wire.
- ``MaterialInventory`` conservation breaks after an extract/load/
  unload round-trip driven through ``material_event_logic``.
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
    _InjectTaskContext,
    _MaterialEventContext,
    apply_robot_progress,
    authorise_task_quantity,
    inject_task_logic,
    material_event_logic,
)
from selene_orchestrator.task_auction import TaskAuction, Bid  # noqa: E402
from selene_orchestrator.task_feed import (  # noqa: E402
    AUCTION_PREEMPTED,
    REQUEUE_STATUS_BY_REASON,
    TaskEventLog,
    resolve_auction_winner,
    should_preempt,
)
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


class _MaterialEvent(types.SimpleNamespace):
    """Field bag matching selene_msgs/msg/MaterialEvent."""

    def __init__(self, event_id, robot_id, task_id, event_type, mass_kg,
                 residual_mass_kg=0.0):
        super().__init__(event_id=event_id, robot_id=robot_id,
                         task_id=task_id, event_type=event_type,
                         mass_kg=mass_kg, residual_mass_kg=residual_mass_kg)


class _Orchestrator:
    """Wires TaskQueue + TaskAuction + MaterialInventory + a fake FleetMonitor
    into the same shape orchestrator_node uses internally, so inject_task_logic,
    the auction-resolve flow and material_event_logic all run on real classes."""

    #: Mirrors OrchestratorNode's inject_preferred_robot_max_rounds default.
    PREFERRED_MAX_ROUNDS = 3

    #: Stands in for HTNPlanner.get_site_id() after SelectSite has resolved.
    #: The production handler reads it off the planner; an injected
    #: excavate/haul without one is rejected outright (D-06).
    SITE_ID = 'site_A'

    def __init__(self, robots):
        self.task_queue = TaskQueue()
        self.auction = TaskAuction(timeout_sec=5.0)
        self.inventory = MaterialInventory()
        self.events = TaskEventLog(capacity=32)
        self.task_queue.set_status_listener(
            lambda task, previous: self.events.append(
                kind='status', action=task.status.name, task_id=task.task_id,
                robot_id=task.assigned_robot, actor='orchestrator',
                detail=task.status_reason))
        self._robots = {r.robot_id: r for r in robots}
        self.announcements = []
        self.assignments = []
        self.alerts = []
        #: (victim_task_id, emergency_task_id) per preemption, so a test can
        #: assert the slot changed hands rather than inferring it from status.
        self.preemptions = []
        self._next_id_counter = 0
        self._clock = 1000.0
        self.material_ctx = _MaterialEventContext(
            task_queue=self.task_queue,
            inventory=self.inventory,
            publish_alert=lambda sev, rid, msg:
                self.alerts.append((sev, rid, msg)),
            residual_tolerance_kg=0.5,
            dedupe_size=64,
        )

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
               assigned_robot_id='', emergency=False):
        req = types.SimpleNamespace(
            task_type=task_type,
            target_location=types.SimpleNamespace(x=x, y=y, z=0.0),
            quantity=quantity,
            assigned_robot_id=assigned_robot_id,
            # Present rather than left to inject_task_logic's getattr default,
            # so an emergency path driven through this harness is really
            # driven and not merely defaulted.
            emergency=emergency,
        )
        resp = types.SimpleNamespace(success=False, task_id='', message='')
        fleet_monitor = types.SimpleNamespace(get_robot=self.get_robot)
        ctx = _InjectTaskContext(
            task_queue=self.task_queue,
            fleet_monitor=fleet_monitor,
            next_task_id=self._next_task_id,
            now_stamp=MagicMock(),
            publish_alert=lambda sev, msg:
                self.alerts.append((sev, assigned_robot_id, msg)),
            site_id=self.SITE_ID,
        )
        inject_task_logic(ctx, req, resp)
        return resp

    def haul_block_reason(self, task) -> str:
        """D-06 gate: why this task must not be dispatched, or ''."""
        return authorise_task_quantity(
            task, self.inventory.get_site_available)[1]

    def tick_auction(self):
        """Run one cycle of the auction state machine (copies _auction_tick
        logic). Starts an auction if idle work exists, or resolves a
        timed-out one.

        IT IS A COPY AND NOTHING COMPARES THE TWO. That is worth saying out
        loud every time this method is extended: a behaviour added to
        ``_auction_tick`` and not added here makes every e2e test of it green
        against a re-implementation. The 2026-08-01 emergency preemption is
        mirrored below through the SAME production helpers the node uses
        (``should_preempt``, ``TaskQueue.abort_auction``) rather than
        re-decided here, so the decision itself cannot drift even though the
        control flow around it is duplicated. The tick-level assertions on the
        real ``_auction_tick`` live in test_emergency_preemption.py.
        """
        self._clock += 1.0

        if self.auction.is_active():
            if self.auction.is_timed_out(self._clock):
                self._resolve()
                return
            running_id = self.auction.get_task_id()
            candidate = self.task_queue.get_next_ready()
            if not should_preempt(self.task_queue.get_task(running_id),
                                  candidate):
                return
            self.task_queue.abort_auction(running_id, AUCTION_PREEMPTED)
            self.auction.reset()
            self.preemptions.append((running_id, candidate.task_id))
            # Fall through and open the emergency's auction in this same tick.

        idle = self.get_idle_robots()
        if not idle:
            return
        next_task = self.task_queue.get_next_ready()
        if next_task is None:
            return
        if next_task.task_type == 'select_site':
            return
        if self.haul_block_reason(next_task):
            return

        self.task_queue.begin_auction(next_task.task_id)
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
        # A COPY OF ``_resolve_auction``, AND IT DOES NOT MODEL D3(c). This
        # harness has no FleetMonitor, so it cannot answer the liveness
        # question and passes no ``is_live``; production does, at
        # orchestrator_node's ``_resolve_auction``. The divergence is recorded
        # rather than papered over -- copying the rule into a copy is how the
        # two drift. ``test_robot_dropout_recovery.py`` drives the shipped
        # function for that claim.
        task_id = self.auction.get_task_id()
        task = self.task_queue.get_task(task_id)
        winner, outcome, reason = resolve_auction_winner(
            task, self.auction.get_bids(), self.PREFERRED_MAX_ROUNDS)
        blocked = self.haul_block_reason(task) if winner is not None else ''
        if blocked:
            winner, outcome, reason = None, 'requeue', blocked
        if winner is None:
            if outcome == 'preference_dropped' and task is not None:
                task.preferred_robot = ''
            status = REQUEUE_STATUS_BY_REASON.get(reason, TaskStatus.PENDING)
            self.task_queue.set_status(task_id, status, reason)
        else:
            self.task_queue.assign_to_robot(task_id, winner.robot_id, reason)
            self._robots[winner.robot_id].fsm_state = 'ASSIGNED'
            self._robots[winner.robot_id].current_task_id = task_id
            self.assignments.append((task_id, winner.robot_id))
        self.auction.reset()

    def report_result(self, task_id, robot_id, success=True,
                      failure_reason=''):
        """What ``_on_task_result`` does: terminate on the agent's own word.

        A COPY, AND IT DOES NOT MODEL THE D4 RE-ENTRY GUARD. Production returns
        early when ``terminal_reported`` is already set (orchestrator_node's
        ``_on_task_result``); this sets it unconditionally. Nothing in this file
        reports twice for one task, so the two agree on every sequence exercised
        here -- but they are not the same code, and asserting on the guard here
        would be asserting about the copy. ``test_task_result_reentry.py``
        drives the shipped function.
        """
        task = self.task_queue.get_task(task_id)
        task.terminal_reported = True
        if success:
            self.task_queue.mark_complete(task_id, 'skill_complete')
        else:
            self.task_queue.mark_failed(task_id, failure_reason or 'skill_failed')
        self._robots[robot_id].fsm_state = 'IDLE'
        self._robots[robot_id].current_task_id = ''

    def material_event(self, event_id, robot_id, task_id, event_type, mass_kg,
                       residual_mass_kg=0.0):
        return material_event_logic(self.material_ctx, _MaterialEvent(
            event_id, robot_id, task_id, event_type, mass_kg,
            residual_mass_kg))

    def robot_state(self, robot_id, fsm_state, current_task_id='',
                    task_progress=0.0):
        """Feed one RobotState-shaped message through the production helper.

        This is the ONLY way this harness may reach IN_PROGRESS. It used to
        call ``set_status(task_id, TaskStatus.IN_PROGRESS)`` directly, which
        made the transition exist nowhere but here: no production writer of
        that status existed anywhere in the repository (D-03).
        """
        robot = self._robots[robot_id]
        robot.fsm_state = fsm_state
        robot.current_task_id = current_task_id
        return apply_robot_progress(self.task_queue, types.SimpleNamespace(
            robot_id=robot_id, fsm_state=fsm_state,
            current_task_id=current_task_id, task_progress=task_progress))

    def complete_task(self, task_id, robot_id):
        """Simulate the agent finishing: work it, then mark COMPLETED."""
        self.robot_state(robot_id, 'WORKING', task_id, task_progress=0.75)
        self.report_result(task_id, robot_id, success=True)


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
    inv = orch.inventory
    inv.register_site('site_A', position=(-50.0, -100.0), estimated_kg=200.0)

    # 1) Operator injects an excavate task.
    resp = orch.inject('excavate', x=-50.0, y=-100.0, quantity=25.0)
    assert resp.success, resp.message
    task_id = resp.task_id
    assert orch.task_queue.get_task(task_id).status == TaskStatus.PENDING
    assert orch.task_queue.get_task(task_id).required_capabilities == ['excavate']
    # D-04: the operator quantity is now read and stored.
    assert orch.task_queue.get_task(task_id).quantity_kg == 25.0
    # D-06: the injection is stamped with the mission's ledger site by the
    # handler. This line used to read ``task.site_id = 'site_A'`` -- the test
    # supplying what production did not, which is exactly how the defect
    # survived: every operator-injected task's MaterialEvent was dropped.
    assert orch.task_queue.get_task(task_id).site_id == 'site_A'

    # 2) Orchestrator auction tick starts the auction + announces.
    orch.tick_auction()
    assert orch.auction.is_active()
    assert orch.task_queue.get_task(task_id).status == TaskStatus.AUCTIONING
    assert orch.task_queue.get_task(task_id).auction_rounds == 1
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

    # 5) The excavator starts working it: ASSIGNED -> IN_PROGRESS, driven from
    #    a RobotState rather than by calling set_status. That transition had no
    #    production writer anywhere in the repository (D-03), and it is the
    #    only status the dashboard draws a progress bar for
    #    (TaskQueue.jsx:120,173-182), so TaskStatus.progress reached the
    #    browser and was discarded.
    orch.robot_state('excavator_01', 'NAVIGATING', task_id, task_progress=0.1)
    assert orch.task_queue.get_task(task_id).status == TaskStatus.IN_PROGRESS
    assert orch.task_queue.get_task(task_id).progress == pytest.approx(0.1)

    # 6) The agent measures 25 kg out of the ground and says so on the wire.
    assert orch.material_event('excavator_01:1:000001', 'excavator_01',
                               task_id, 'extracted', 25.0)
    orch.report_result(task_id, 'excavator_01', success=True)

    assert orch.task_queue.get_task(task_id).status == TaskStatus.COMPLETED
    assert orch.task_queue.get_completed_count() == 1
    assert inv.check_conservation(), inv.get_mission_progress()
    assert inv.get_total_extracted() == pytest.approx(25.0)
    # Extracted but not yet loaded: this is the term the shipped
    # check_conservation() omitted entirely.
    assert inv.get_total_at_site() == pytest.approx(25.0)
    assert inv.get_total_in_transit() == pytest.approx(0.0)

    # 7) Hauler loads and deposits -> conservation still holds.
    assert orch.material_event('hauler_01:1:000001', 'hauler_01', task_id,
                               'loaded', 25.0)
    assert inv.get_total_in_transit() == pytest.approx(25.0)
    assert inv.get_total_at_site() == pytest.approx(0.0)

    assert orch.material_event('hauler_01:1:000002', 'hauler_01', task_id,
                               'unloaded', 25.0, residual_mass_kg=0.0)
    assert inv.get_total_deposited() == pytest.approx(25.0)
    assert inv.get_total_in_transit() == pytest.approx(0.0)
    assert inv.check_conservation()
    assert inv.get_unaccounted_kg() == pytest.approx(0.0)
    assert orch.material_ctx.events_applied == 3


def test_e2e_task_result_failure_is_not_a_completion():
    """D-03: FAILED was unreachable, so a failed task read as done.

    The agent fires FSMEvent.TASK_COMPLETE on skill failure as well as success,
    so the orchestrator's positional heuristic saw an idle robot with no task
    and called mark_complete(). TaskResult is what makes the distinction
    representable at all.
    """
    orch = _Orchestrator([_Robot('excavator_01', ['excavate'])])
    resp = orch.inject('excavate', x=1.0, y=2.0)
    task_id = resp.task_id

    orch.tick_auction()
    orch.submit_bid(task_id, 'excavator_01', score=0.9)
    orch.close_auction()
    assert orch.task_queue.get_task(task_id).status == TaskStatus.ASSIGNED

    orch.report_result(task_id, 'excavator_01', success=False,
                       failure_reason='drill stalled')

    task = orch.task_queue.get_task(task_id)
    assert task.status == TaskStatus.FAILED
    assert task.status_reason == 'drill stalled'
    assert task.terminal_reported is True
    assert orch.task_queue.get_completed_count() == 0


def test_e2e_cancelled_task_is_distinguishable_from_a_completed_one():
    """D-03's headline defect, at the queue level."""
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    resp = orch.inject('prospect', x=5.0, y=5.0)
    task_id = resp.task_id
    orch.tick_auction()
    orch.submit_bid(task_id, 'scout_01', score=0.8)
    orch.close_auction()

    orch.task_queue.interrupt_task(
        task_id, {'reason': 'operator_cancel_task'},
        reason='operator_cancel_task')

    task = orch.task_queue.get_task(task_id)
    assert task.status == TaskStatus.INTERRUPTED
    assert task.status_reason == 'operator_cancel_task'
    # And it is still work the fleet owes: an INTERRUPTED task is re-auctioned.
    orch._robots['scout_01'].fsm_state = 'IDLE'
    assert orch.task_queue.get_next_ready() is not None
    assert orch.task_queue.get_next_ready().task_id == task_id


def test_e2e_material_event_for_a_siteless_task_is_dropped():
    """Never invent a site: an invented bucket makes conservation trivial.

    The siteless task is added DIRECTLY here rather than injected, because as
    of D-06 the inject path can no longer produce one: an excavate or haul
    without a ledger site is refused outright (see the test below). The guard
    still has to hold for a task that reaches the queue another way.
    """
    orch = _Orchestrator([_Robot('excavator_01', ['excavate'])])
    orch.task_queue.add_task('siteless_0001', 'excavate', 0.0, 0.0,
                             required_capabilities=['excavate'])

    applied = orch.material_event('e:1:1', 'excavator_01', 'siteless_0001',
                                  'extracted', 10.0)
    assert applied is False
    assert orch.inventory.get_total_extracted() == 0.0
    assert any(sev == 'WARNING' and 'site' in msg
               for sev, _rid, msg in orch.alerts), orch.alerts


def test_e2e_injected_excavate_without_a_site_is_refused():
    """D-06 at the operator boundary: say no now, not with a WARNING later.

    Before this, the injection succeeded, the robot really drilled, the task
    really completed, and the MaterialEvent was dropped with an alert reading
    like a fault while the progress bar stayed at zero.
    """
    orch = _Orchestrator([_Robot('excavator_01', ['excavate'])])
    orch.SITE_ID = ''                      # SelectSite has not resolved yet

    resp = orch.inject('excavate', x=0.0, y=0.0, quantity=10.0)
    assert resp.success is False
    assert 'site' in resp.message
    assert orch.task_queue.get_total_count() == 0


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

    # Task must return to PENDING, not rot in AUCTIONING. PENDING rather than
    # INTERRUPTED: nobody bid, so it was never started, and INTERRUPTED would
    # be a lie about it.
    task = orch.task_queue.get_task(task_id)
    assert task.status == TaskStatus.PENDING
    assert task.status_reason == 'auction_no_bids'
    assert not orch.auction.is_active()


def test_e2e_preferred_robot_wins_regardless_of_score():
    """D-04: a targeted injection is a constrained auction, not a force-assign."""
    orch = _Orchestrator([
        _Robot('hauler_01', ['haul']),
        _Robot('hauler_02', ['haul']),
    ])
    # D-06: a haul is only dispatchable against mass the ledger has actually
    # been told about. Without this the task is withheld from the auction and
    # this test would pass for the wrong reason.
    orch.inventory.register_site(orch.SITE_ID, (1.0, 1.0), estimated_kg=100.0)
    orch.inventory.record_extraction(orch.SITE_ID, 'excavator_01', 30.0)

    resp = orch.inject('haul', x=1.0, y=1.0, assigned_robot_id='hauler_02')
    task_id = resp.task_id
    assert orch.task_queue.get_task(task_id).preferred_robot == 'hauler_02'
    assert orch.task_queue.get_task(task_id).assigned_robot == ''

    orch.tick_auction()
    orch.submit_bid(task_id, 'hauler_01', score=0.99)
    orch.submit_bid(task_id, 'hauler_02', score=0.10)
    orch.close_auction()

    assert orch.task_queue.get_task(task_id).assigned_robot == 'hauler_02'


def test_e2e_haul_against_an_empty_site_is_never_assigned():
    """D-06: 0.0 kg on the wire means "fill the bin", not "carry nothing".

    ``TaskAssignment.quantity_kg`` 0.0 is documented as *unconstrained -- fill
    to the robot's own RCDL capacity*, and the agent implements it:
    ``HaulSkill._clamp_quantity`` maps a non-positive request to 0.0 and
    ``trigger_load(max_kg=-1.0)`` reaches the sim as a bare "load", which fills
    to ``capacity_kg`` (50 kg, hauler.yaml:29). So a haul the ledger cannot
    cover must not be dispatched at all -- publishing it would fabricate a bin
    of material no excavator extracted and then blame the instruments for the
    resulting conservation breach.
    """
    orch = _Orchestrator([_Robot('hauler_01', ['haul'])])
    orch.inventory.register_site(orch.SITE_ID, (1.0, 1.0), estimated_kg=100.0)
    # Site registered, but nothing has been extracted into it yet.

    resp = orch.inject('haul', x=1.0, y=1.0)
    assert resp.success is True
    task_id = resp.task_id
    assert orch.haul_block_reason(orch.task_queue.get_task(task_id)) == \
        'haul_no_material'

    orch.tick_auction()
    assert not orch.auction.is_active()
    assert orch.announcements == []
    assert orch.task_queue.get_task(task_id).status == TaskStatus.PENDING

    # One excavate later, the same haul is dispatchable and carries the
    # MEASURED mass rather than a capacity-shaped guess.
    orch.inventory.record_extraction(orch.SITE_ID, 'excavator_01', 18.0)
    task = orch.task_queue.get_task(task_id)
    assert orch.haul_block_reason(task) == ''
    assert authorise_task_quantity(
        task, orch.inventory.get_site_available) == (18.0, '')

    orch.tick_auction()
    assert orch.auction.is_active()
    orch.submit_bid(task_id, 'hauler_01', score=0.7)
    orch.close_auction()
    assert orch.task_queue.get_task(task_id).assigned_robot == 'hauler_01'


def test_e2e_haul_drained_during_its_own_auction_is_requeued():
    """The race the pre-auction gate cannot catch, so the assign gate must.

    Another hauler loads the site's mass while this auction is open. Resolving
    it must re-queue rather than assign, for the same reason as above.
    """
    orch = _Orchestrator([
        _Robot('hauler_01', ['haul']),
        _Robot('hauler_02', ['haul']),
    ])
    orch.inventory.register_site(orch.SITE_ID, (1.0, 1.0), estimated_kg=100.0)
    orch.inventory.record_extraction(orch.SITE_ID, 'excavator_01', 12.0)

    resp = orch.inject('haul', x=1.0, y=1.0)
    task_id = resp.task_id
    orch.tick_auction()
    assert orch.auction.is_active()
    orch.submit_bid(task_id, 'hauler_01', score=0.9)

    # hauler_02 takes the whole 12 kg while the auction is still open.
    orch.inventory.record_load('hauler_02', orch.SITE_ID, 12.0)

    orch.close_auction()
    task = orch.task_queue.get_task(task_id)
    assert task.assigned_robot == ''
    assert task.status == TaskStatus.PENDING
    assert task.status_reason == 'haul_no_material'
    assert orch.assignments == []


def test_e2e_operator_events_reach_the_history():
    """D-05: status transitions land in the ring the dashboard replays."""
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    resp = orch.inject('prospect', x=1.0, y=1.0)
    orch.tick_auction()
    orch.submit_bid(resp.task_id, 'scout_01', score=0.5)
    orch.close_auction()

    actions = [e['action'] for e in orch.events.snapshot()
               if e['task_id'] == resp.task_id]
    assert 'AUCTIONING' in actions
    assert 'ASSIGNED' in actions
    assert orch.events.seq_next == len(orch.events.snapshot())


def test_e2e_an_emergency_injection_takes_the_auction_slot_and_is_assigned():
    """The whole path an operator emergency travels, 2026-08-01.

    inject(emergency=True) -> the running auction is aborted -> the emergency
    is announced in the SAME tick -> a robot bids -> it is assigned. The victim
    is not cancelled and not charged: it goes back to PENDING with its round
    refunded, and it is auctioned again afterwards.
    """
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    ordinary = orch.inject('prospect', x=1.0, y=1.0)
    orch.tick_auction()
    assert orch.auction.get_task_id() == ordinary.task_id
    # An operator injection is priority 10.0, so drop the victim below it --
    # a preemption requires a STRICTLY lower priority and two injections are
    # always equal.
    orch.task_queue.get_task(ordinary.task_id).priority = 5.0

    urgent = orch.inject('prospect', x=2.0, y=2.0, emergency=True)
    orch.tick_auction()

    assert orch.preemptions == [(ordinary.task_id, urgent.task_id)]
    assert orch.auction.get_task_id() == urgent.task_id
    victim = orch.task_queue.get_task(ordinary.task_id)
    assert victim.status == TaskStatus.PENDING
    assert victim.status_reason == AUCTION_PREEMPTED
    assert victim.auction_rounds == 0, 'the aborted round must be refunded'
    assert victim.failed_auctions == 0
    assert victim.auction_backoff_until == 0.0

    orch.submit_bid(urgent.task_id, 'scout_01', score=0.5)
    orch.close_auction()
    assert orch.task_queue.get_task(urgent.task_id).status == TaskStatus.ASSIGNED

    # The victim is still live work and is auctioned again once the slot frees.
    orch.robot_state('scout_01', 'IDLE', '')
    orch.tick_auction()
    assert orch.auction.get_task_id() == ordinary.task_id


def test_e2e_a_non_emergency_injection_waits_for_the_auction_in_flight():
    """The operator's decision, at the e2e altitude.

    Identical to the test above except for the flag. Priority 10.0 alone
    preempts nothing, which is the behaviour every injection has always had.
    """
    orch = _Orchestrator([_Robot('scout_01', ['prospect'])])
    ordinary = orch.inject('prospect', x=1.0, y=1.0)
    orch.tick_auction()
    orch.task_queue.get_task(ordinary.task_id).priority = 5.0

    urgent = orch.inject('prospect', x=2.0, y=2.0, emergency=False)
    orch.tick_auction()

    assert orch.preemptions == []
    assert orch.auction.get_task_id() == ordinary.task_id
    assert orch.task_queue.get_task(ordinary.task_id).status == \
        TaskStatus.AUCTIONING
    assert orch.task_queue.get_task(urgent.task_id).status == TaskStatus.PENDING
