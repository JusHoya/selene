"""Unit tests for ``inject_task_logic`` (OrchestratorNode operator service).

These tests exercise the pure-Python decision tree underlying the
``/orchestrator/inject_task`` service handler. They avoid standing up a
real ROS node by:

  1. Relying on ``test/conftest.py``, which installs minimal ``rclpy`` /
     ``selene_msgs`` / ``geometry_msgs`` stand-ins in ``sys.modules``
     before this module is imported, and on ``sys.path`` setup done in
     the same place. Only genuinely-missing modules are stubbed, so
     inside a colcon workspace the real ones take precedence and nothing
     is shadowed for other packages' tests.

  2. Driving ``inject_task_logic`` directly with an ``_InjectTaskContext``
     wrapping a real ``TaskQueue`` + a mocked ``FleetMonitor`` +
     ``MagicMock`` publishers.

REWRITTEN 2026-07-30 for D-04. The previous version of this file asserted the
force-assign behaviour: a named robot got ``TaskAssignment`` published straight
at it, its running task pre-empted, and ``response.message == 'force-assigned'``.
That behaviour is deliberately gone -- FR-DASH-5(b) says an injected task
"enters the auction", and the force-assign path was already broken for the only
case it existed to serve (it pre-empted a busy robot and then published an
assignment ``agent_node`` discards for any robot not in BIDDING or ASSIGNED).
These tests now pin the constrained auction and the quantity validation that
replaced it.
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

from selene_orchestrator.orchestrator_node import (  # noqa: E402
    inject_task_logic,
    _InjectTaskContext,
    MANUAL_TASK_CAPABILITIES,
)
from selene_orchestrator.task_queue import TaskQueue, TaskStatus  # noqa: E402


# --------------------------------------------------------------------------- #
#  Fixtures                                                                     #
# --------------------------------------------------------------------------- #

class _FakeInjectRequest:
    def __init__(self, task_type='prospect', x=0.0, y=0.0,
                 quantity=0.0, assigned_robot_id='', emergency=False):
        self.task_type = task_type
        self.target_location = types.SimpleNamespace(x=x, y=y, z=0.0)
        self.quantity = quantity
        self.assigned_robot_id = assigned_robot_id
        # SET, not omitted, even though inject_task_logic reads it with a
        # getattr default. Omitting it would make every emergency assertion in
        # this file pass against a request that never carried the field --
        # exactly the vacuous green the srv half of
        # test_conftest_mirrors_msgs.py was added to prevent.
        self.emergency = emergency


class _FakeInjectResponse:
    def __init__(self):
        self.success = False
        self.task_id = ''
        self.message = ''


@pytest.fixture
def task_queue():
    return TaskQueue()


@pytest.fixture
def fleet_monitor():
    """Mock FleetMonitor with a ``get_robot`` that returns dicts."""
    fm = MagicMock()
    fm._robots = {}

    def _get(rid):
        return fm._robots.get(rid)
    fm.get_robot.side_effect = _get
    return fm


def _add_robot(fm, robot_id, fsm_state='IDLE', capabilities=None,
               current_task_id=''):
    fm._robots[robot_id] = {
        'robot_id': robot_id,
        'fsm_state': fsm_state,
        'capabilities': list(capabilities or []),
        'current_task_id': current_task_id,
        'battery_level': 0.9,
        'pose': (0.0, 0.0, 0.0),
    }


@pytest.fixture
def publish_alert():
    return MagicMock()


#: Stands in for HTNPlanner.get_site_id() after SelectSite has resolved. The
#: production handler sources it from the planner (orchestrator_node
#: _handle_inject_task); an excavate or haul injected without one is rejected,
#: which is what the TestLedgerSite class below pins.
_MISSION_SITE_ID = 'site_0001'


@pytest.fixture
def inject_ctx(task_queue, fleet_monitor, publish_alert):
    # Monotonic id generator delegates to the real TaskQueue helper so
    # collisions against any pre-existing ids are impossible.
    return _InjectTaskContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        next_task_id=lambda: task_queue.make_unique_task_id('manual'),
        now_stamp=MagicMock(),
        publish_alert=publish_alert,
        site_id=_MISSION_SITE_ID,
    )


@pytest.fixture
def siteless_ctx(task_queue, fleet_monitor, publish_alert):
    """A context from before SelectSite resolved: no ledger site exists yet."""
    return _InjectTaskContext(
        task_queue=task_queue,
        fleet_monitor=fleet_monitor,
        next_task_id=lambda: task_queue.make_unique_task_id('manual'),
        now_stamp=MagicMock(),
        publish_alert=publish_alert,
        site_id='',
    )


# --------------------------------------------------------------------------- #
#  Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestInjectTaskHandler:

    def test_inject_valid_task_no_assignment(self, inject_ctx, task_queue,
                                             publish_alert):
        req = _FakeInjectRequest(task_type='prospect', x=30.0, y=-110.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert out.task_id.startswith('manual_')
        # The emergency clause is stated in BOTH directions (2026-08-01): an
        # operator reading "priority 10" would reasonably assume it jumps the
        # auction in flight, and it does not unless the flag is set.
        assert out.message == (
            'queued; not an emergency: waits for any auction already in flight')

        task = task_queue.get_task(out.task_id)
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.task_type == 'prospect'
        assert task.target_x == 30.0
        assert task.target_y == -110.0
        assert task.priority == 10.0
        assert task.preferred_robot == ''
        assert task.required_capabilities == \
            MANUAL_TASK_CAPABILITIES['prospect']
        publish_alert.assert_called_once()
        severity, msg = publish_alert.call_args[0]
        assert severity == 'INFO'
        assert 'queued' in msg

    def test_inject_invalid_task_type(self, inject_ctx, task_queue):
        req = _FakeInjectRequest(task_type='dance')
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'invalid' in out.message
        # No task should have been added on the failure path.
        assert task_queue.get_total_count() == 0

    def test_inject_unknown_robot_rejected(self, inject_ctx, task_queue):
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='ghost_99',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'unknown' in out.message
        # Task was added before validation, then marked FAILED.
        task = task_queue.get_task(out.task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.status_reason == 'inject_rejected'

    def test_inject_robot_in_error_rejected(self, inject_ctx, task_queue,
                                            fleet_monitor):
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='ERROR',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'ERROR' in out.message
        assert task_queue.get_task(out.task_id).status == TaskStatus.FAILED

    def test_inject_robot_recharging_rejected(
            self, inject_ctx, task_queue, fleet_monitor):
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='RECHARGING',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='prospect', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'RECHARGING' in out.message

    def test_inject_capability_mismatch_rejected(
            self, inject_ctx, task_queue, fleet_monitor):
        # Haul task requires 'haul' capability, scout only has 'prospect'.
        _add_robot(
            fleet_monitor, 'scout_01',
            fsm_state='IDLE',
            capabilities=['prospect'],
        )
        req = _FakeInjectRequest(
            task_type='haul', assigned_robot_id='scout_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'capabilities' in out.message
        assert 'haul' in out.message
        assert task_queue.get_task(out.task_id).status == TaskStatus.FAILED

    def test_inject_monotonic_task_ids(self, inject_ctx, task_queue):
        req1 = _FakeInjectRequest(task_type='prospect')
        resp1 = _FakeInjectResponse()
        inject_task_logic(inject_ctx, req1, resp1)

        req2 = _FakeInjectRequest(task_type='prospect')
        resp2 = _FakeInjectResponse()
        inject_task_logic(inject_ctx, req2, resp2)

        assert resp1.task_id != resp2.task_id
        assert resp1.task_id.startswith('manual_')
        assert resp2.task_id.startswith('manual_')
        # IDs should be numerically ordered.
        n1 = int(resp1.task_id.split('_')[-1])
        n2 = int(resp2.task_id.split('_')[-1])
        assert n2 > n1

    def test_inject_excavate_capability_mismatch(
            self, inject_ctx, task_queue, fleet_monitor):
        _add_robot(
            fleet_monitor, 'excavator_01',
            fsm_state='IDLE',
            capabilities=['prospect'],  # wrong capability for excavate
        )
        req = _FakeInjectRequest(
            task_type='excavate', assigned_robot_id='excavator_01',
        )
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'excavate' in out.message


class TestConstrainedAuction:
    """D-04: a targeted injection is a PREFERENCE, not a force-assignment."""

    def test_named_robot_gets_a_preference_not_an_assignment(
            self, inject_ctx, task_queue, fleet_monitor):
        _add_robot(fleet_monitor, 'hauler_01', fsm_state='IDLE',
                   capabilities=['haul'])
        req = _FakeInjectRequest(task_type='haul', x=-80.0, y=-140.0,
                                 assigned_robot_id='hauler_01')
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert out.message.startswith('queued (preferred hauler_01)')

        task = task_queue.get_task(out.task_id)
        # The task waits for an auction. It is NOT assigned.
        assert task.status == TaskStatus.PENDING
        assert task.assigned_robot == ''
        assert task.preferred_robot == 'hauler_01'

    def test_a_busy_preferred_robot_keeps_its_running_task(
            self, inject_ctx, task_queue, fleet_monitor):
        """The removed force-assign path pre-empted here and gained nothing.

        It published a TaskAssignment that ``agent_node._on_task_assigned``
        discards for any robot not in BIDDING or ASSIGNED -- i.e. exactly the
        busy robot it had just taken the work away from.
        """
        task_queue.add_task('auto_0001', 'haul', 0.0, 0.0, priority=5.0,
                            required_capabilities=['haul'])
        task_queue.assign_to_robot('auto_0001', 'hauler_01')
        _add_robot(fleet_monitor, 'hauler_01', fsm_state='WORKING',
                   capabilities=['haul'], current_task_id='auto_0001')

        req = _FakeInjectRequest(task_type='haul', x=10.0, y=20.0,
                                 assigned_robot_id='hauler_01')
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        running = task_queue.get_task('auto_0001')
        assert running.status == TaskStatus.ASSIGNED
        assert running.assigned_robot == 'hauler_01'
        assert task_queue.get_task(out.task_id).assigned_robot == ''

    def test_no_task_assignment_is_published_by_this_handler(
            self, task_queue, fleet_monitor, publish_alert):
        """The context no longer even carries a publish_assignment callable."""
        import dataclasses

        from selene_orchestrator.orchestrator_node import _InjectTaskContext

        names = {f.name for f in dataclasses.fields(_InjectTaskContext)}
        assert 'publish_assignment' not in names


class TestQuantityValidation:
    """D-04: InjectTask.quantity was carried and never read."""

    def test_positive_quantity_is_stored_on_the_entry(
            self, inject_ctx, task_queue):
        req = _FakeInjectRequest(task_type='excavate', quantity=12.5)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert task_queue.get_task(out.task_id).quantity_kg == 12.5
        assert 'target 12.5 kg' in out.message

    def test_zero_quantity_means_unconstrained(self, inject_ctx, task_queue):
        req = _FakeInjectRequest(task_type='excavate', quantity=0.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert task_queue.get_task(out.task_id).quantity_kg == 0.0
        # No 'target N kg' clause: 0.0 is unconstrained, not a target of zero.
        assert out.message == (
            'queued; not an emergency: waits for any auction already in '
            f'flight; credited to {_MISSION_SITE_ID}')

    def test_negative_quantity_is_rejected_before_the_task_exists(
            self, inject_ctx, task_queue):
        req = _FakeInjectRequest(task_type='excavate', quantity=-1.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is False
        assert 'quantity' in out.message
        assert out.task_id == ''
        assert task_queue.get_total_count() == 0

    def test_non_finite_quantity_is_rejected(self, inject_ctx, task_queue):
        for bad in (float('nan'), float('inf'), float('-inf')):
            req = _FakeInjectRequest(task_type='excavate', quantity=bad)
            resp = _FakeInjectResponse()
            out = inject_task_logic(inject_ctx, req, resp)
            assert out.success is False, bad
        assert task_queue.get_total_count() == 0

    def test_quantity_on_prospect_is_accepted_and_said_to_be_ignored(
            self, inject_ctx, task_queue):
        """A survey has no mass. Not an error; just discarded, out loud."""
        req = _FakeInjectRequest(task_type='prospect', quantity=40.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert 'ignored' in out.message
        assert task_queue.get_task(out.task_id).quantity_kg == 0.0


class TestLedgerSite:
    """D-06: a manual excavate/haul must name the site its mass belongs to.

    Injected tasks were created with no ``site_id`` at all, so every
    MaterialEvent they produced hit ``material_event_logic``'s step-4 guard and
    was dropped with a WARNING. The operator saw a robot that really drilled
    the mass it was asked for, a task that completed, an alert that reads like
    a fault, and a mission-progress bar that never moved.
    """

    @pytest.mark.parametrize('task_type', ['excavate', 'haul'])
    def test_material_task_is_stamped_with_the_mission_site(
            self, inject_ctx, task_queue, task_type):
        req = _FakeInjectRequest(task_type=task_type, x=-80.0, y=-140.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)

        assert out.success is True
        assert task_queue.get_task(out.task_id).site_id == _MISSION_SITE_ID
        # Said out loud: the ledger site is not necessarily where the operator
        # clicked, because sites are keyed by id and never by position.
        assert _MISSION_SITE_ID in out.message

    def test_a_stamped_excavate_event_is_applied_not_dropped(
            self, inject_ctx, task_queue):
        """The end the defect was actually felt at: the ledger credits it.

        Drives the real ``material_event_logic`` against the real
        ``MaterialInventory``, because "the task carries a site_id" is only
        interesting if the event that quotes it survives step 4.
        """
        from selene_isru.inventory import MaterialInventory
        from selene_orchestrator.orchestrator_node import (
            _MaterialEventContext, material_event_logic,
        )

        req = _FakeInjectRequest(task_type='excavate', x=-80.0, y=-140.0,
                                 quantity=12.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(inject_ctx, req, resp)
        assert out.success is True

        inventory = MaterialInventory()
        inventory.register_site(_MISSION_SITE_ID, (-80.0, -140.0),
                                estimated_kg=100.0)
        alerts = []
        ctx = _MaterialEventContext(
            task_queue=task_queue,
            inventory=inventory,
            publish_alert=lambda sev, rid, msg: alerts.append((sev, rid, msg)),
            residual_tolerance_kg=0.5,
            dedupe_size=64,
        )
        event = types.SimpleNamespace(
            event_id='excavator_01:1:000001', robot_id='excavator_01',
            task_id=out.task_id, event_type='extracted', mass_kg=12.0,
            residual_mass_kg=0.0)

        assert material_event_logic(ctx, event) is True
        assert inventory.get_total_extracted() == 12.0
        assert [a for a in alerts if a[0] == 'WARNING'] == []

    @pytest.mark.parametrize('task_type', ['excavate', 'haul'])
    def test_material_task_is_rejected_before_a_site_exists(
            self, siteless_ctx, task_queue, task_type):
        req = _FakeInjectRequest(task_type=task_type, x=1.0, y=2.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(siteless_ctx, req, resp)

        assert out.success is False
        assert 'site' in out.message
        # Rejected before the row exists, like the quantity rejection, so no
        # phantom FAILED entry is left in the queue.
        assert out.task_id == ''
        assert task_queue.get_total_count() == 0

    def test_prospect_needs_no_site(self, siteless_ctx, task_queue):
        """A survey moves no mass, so it publishes no MaterialEvent."""
        req = _FakeInjectRequest(task_type='prospect', x=1.0, y=2.0)
        resp = _FakeInjectResponse()
        out = inject_task_logic(siteless_ctx, req, resp)

        assert out.success is True
        assert task_queue.get_task(out.task_id).site_id == ''
