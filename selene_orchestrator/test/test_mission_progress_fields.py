"""MissionProgress carries the ledger's real numbers — D-06 / FR-DASH-7.

Drives ``build_mission_progress``, which is factored out of
``OrchestratorNode._publish_mission_progress`` precisely so this lane can reach
it: ``conftest.py``'s fake node cannot construct an OrchestratorNode at all.

Four of these fields did not exist before 2026-07-30, and the three that did
were structurally 0.0 in every live run because MaterialInventory had no
production writers.
"""

import types

import pytest

from selene_isru.inventory import MaterialInventory
from selene_orchestrator.fleet_monitor import FleetMonitor
from selene_orchestrator.orchestrator_node import build_mission_progress


def _blank():
    """A field bag standing in for a generated MissionProgress message."""
    return types.SimpleNamespace()


def _build(**overrides):
    kwargs = dict(
        objective_description='PSR Ice Prospecting Survey',
        target_kg=100.0,
        ledger={'extracted': 0.0, 'at_site': 0.0, 'in_transit': 0.0,
                'deposited': 0.0, 'unaccounted': 0.0},
        fleet_distance_m=0.0,
        fleet_energy_wh=0.0,
        elapsed_sec=0.0,
        fleet_uptime_sec=0.0,
        material_events_applied=0,
    )
    kwargs.update(overrides)
    return build_mission_progress(_blank(), **kwargs)


def test_every_published_field_is_set():
    """A field left unset on a real message keeps its default silently."""
    msg = _build()
    for name in ('objective_description', 'target_quantity',
                 'extracted_quantity', 'in_transit_quantity',
                 'deposited_quantity', 'fleet_distance_total',
                 'fleet_energy_total', 'elapsed_sim_time',
                 'fleet_uptime_sec', 'material_events_applied',
                 'at_site_quantity', 'unaccounted_quantity'):
        assert hasattr(msg, name), name


def test_the_four_new_fields_carry_the_ledgers_values():
    """The whole point of D-06: real masses, from a real ledger."""
    inv = MaterialInventory()
    inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction('site_A', 'excavator_01', 40.0)
    inv.record_load('hauler_01', 'site_A', 25.0)
    inv.record_unload('hauler_01', 10.0)

    msg = _build(ledger=inv.get_mission_progress(),
                 material_events_applied=3)

    assert msg.extracted_quantity == pytest.approx(40.0)
    assert msg.at_site_quantity == pytest.approx(15.0)
    assert msg.in_transit_quantity == pytest.approx(15.0)
    assert msg.deposited_quantity == pytest.approx(10.0)
    assert msg.unaccounted_quantity == pytest.approx(0.0)
    # The conservation identity the dashboard's chip recomputes client-side.
    assert msg.extracted_quantity == pytest.approx(
        msg.at_site_quantity + msg.in_transit_quantity
        + msg.deposited_quantity)


def test_unaccounted_surfaces_an_instrument_disagreement():
    inv = MaterialInventory()
    inv.register_site('site_A', (0.0, 0.0), estimated_kg=100.0)
    inv.record_extraction('site_A', 'excavator_01', 10.0)
    inv.record_load('hauler_01', 'site_A', 25.0)      # load cell over-reports

    msg = _build(ledger=inv.get_mission_progress())
    assert msg.unaccounted_quantity == pytest.approx(15.0)


def test_material_events_applied_replaces_the_dashboards_guess():
    """MissionProgress.jsx's massInstrumented used to test whether any mass was
    > 0, which reports a CORRECTLY instrumented mission as uninstrumented for
    its whole first minute of drilling."""
    assert _build(material_events_applied=0).material_events_applied == 0
    assert _build(material_events_applied=7).material_events_applied == 7


def test_fleet_uptime_comes_from_the_first_robot_heartbeat():
    """FleetMonitor.get_uptime_sec() had no production caller until now, and
    MissionProgress had no field to put it in."""
    fm = FleetMonitor()
    fm.update_robot('scout_01', 'scout', 'IDLE', 0, 0, 0, 0.9, '',
                    timestamp=1000.0)
    uptime = fm.get_uptime_sec(current_time=1042.0)
    assert uptime == pytest.approx(42.0)

    msg = _build(fleet_uptime_sec=uptime, elapsed_sec=55.0)
    assert msg.fleet_uptime_sec == pytest.approx(42.0)
    # DISTINCT from elapsed_sim_time, which is measured from orchestrator node
    # start -- several seconds earlier, before any robot exists.
    assert msg.elapsed_sim_time == pytest.approx(55.0)
    assert msg.fleet_uptime_sec != msg.elapsed_sim_time


def test_uptime_is_zero_before_any_robot_has_reported():
    assert FleetMonitor().get_uptime_sec(current_time=1e9) == 0.0


def test_units_are_carried_through_unchanged():
    """Distance is METRES and energy is WATT-HOURS at this boundary; the
    dashboard does the /1000 in formatKm and the Wh->kWh promotion in
    formatWh. Anything scaling here would double-convert."""
    msg = _build(fleet_distance_m=1234.5, fleet_energy_wh=2500.0)
    assert msg.fleet_distance_total == pytest.approx(1234.5)
    assert msg.fleet_energy_total == pytest.approx(2500.0)


def test_target_quantity_is_a_mass_not_a_task_count():
    """It briefly carried TaskQueue.get_total_count(), which the dashboard
    rendered through a kg formatter."""
    msg = _build(target_kg=100.0)
    assert msg.target_quantity == pytest.approx(100.0)
