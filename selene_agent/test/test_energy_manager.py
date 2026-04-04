"""Tests for the SELENE agent energy manager.

Uses a lightweight stub battery (no RobotDescriptor dependency) so the
test suite stays fast and self-contained.
"""

import math

import pytest

from selene_hal.battery_interface import BatteryInterface
from selene_hal.data_types import BatteryState
from selene_agent.energy_manager import EnergyManager


# ---- Stub battery for unit tests --------------------------------------------

class _TestBattery(BatteryInterface):
    """Minimal in-test battery stub with mutable charge level."""

    def __init__(
        self,
        capacity_wh: float = 500.0,
        remaining_wh: float = 500.0,
        charge_fraction: float = 1.0,
        idle_draw: float = 10.0,
        locomotion_draw: float = 30.0,
    ):
        self._capacity = capacity_wh
        self._remaining = remaining_wh
        self._charge_fraction = charge_fraction
        self._idle_draw = idle_draw
        self._locomotion_draw = locomotion_draw

    def get_state(self) -> BatteryState:
        return BatteryState(
            charge_fraction=self._charge_fraction,
            capacity_wh=self._capacity,
            remaining_wh=self._remaining,
        )

    def get_capacity_wh(self) -> float:
        return self._capacity

    def get_idle_draw_w(self) -> float:
        return self._idle_draw

    def get_locomotion_draw_w(self) -> float:
        return self._locomotion_draw

    # --- helpers for tests ---
    def set_charge(self, fraction: float, remaining_wh: float | None = None) -> None:
        self._charge_fraction = fraction
        if remaining_wh is not None:
            self._remaining = remaining_wh
        else:
            self._remaining = self._capacity * fraction


# ---- Fixtures ---------------------------------------------------------------

@pytest.fixture
def battery():
    return _TestBattery()


@pytest.fixture
def em(battery):
    return EnergyManager(battery)


# ---- Critical / charged checks ---------------------------------------------

def test_is_critical_at_threshold(battery):
    battery.set_charge(0.15)
    em = EnergyManager(battery, critical_threshold=0.15)
    assert em.is_critical() is True


def test_is_critical_below_threshold(battery):
    battery.set_charge(0.05)
    em = EnergyManager(battery, critical_threshold=0.15)
    assert em.is_critical() is True


def test_not_critical_above_threshold(battery):
    battery.set_charge(0.50)
    em = EnergyManager(battery, critical_threshold=0.15)
    assert em.is_critical() is False


def test_is_fully_charged_at_target(battery):
    battery.set_charge(0.90)
    em = EnergyManager(battery, recharge_target=0.90)
    assert em.is_fully_charged() is True


def test_not_fully_charged_below_target(battery):
    battery.set_charge(0.85)
    em = EnergyManager(battery, recharge_target=0.90)
    assert em.is_fully_charged() is False


# ---- can_afford_task --------------------------------------------------------

def test_can_afford_nearby_task(battery, em):
    """Full battery, short task at the base -- should be affordable."""
    battery.set_charge(1.0, remaining_wh=500.0)
    em.update(battery.get_state())
    assert em.can_afford_task(
        current_position=(39.0, 40.0),
        task_position=(40.0, 40.0),
        task_energy_wh=1.0,
    ) is True


def test_cannot_afford_distant_task(battery):
    """Nearly empty battery, very distant task -- should NOT be affordable."""
    battery.set_charge(0.01, remaining_wh=5.0)
    em = EnergyManager(battery)
    em.update(battery.get_state())
    assert em.can_afford_task(
        current_position=(0.0, 0.0),
        task_position=(10000.0, 10000.0),
        task_energy_wh=100.0,
    ) is False


# ---- energy cost computation ------------------------------------------------

def test_energy_cost_computation(battery, em):
    """Verify the analytic energy model.

    distance=30 m, speed=0.3 m/s -> travel_time=100 s
    locomotion_wh = 30 W * 0.3 m/s * 100 s / 3600 = 0.25 Wh
    idle_wh       = 10 W * 100 s / 3600 ~= 0.2778 Wh
    task_energy   = 5.0 Wh
    total ~= 5.5278 Wh
    """
    cost = em.compute_energy_cost_wh(distance_m=30.0, task_energy_wh=5.0)
    # locomotion: 30*0.3*100/3600 = 0.25
    # idle:       10*100/3600     = 0.27778
    expected = 0.25 + 10.0 * 100.0 / 3600.0 + 5.0
    assert cost == pytest.approx(expected, rel=1e-6)


# ---- distance to base -------------------------------------------------------

def test_distance_to_base(em):
    # default base at (40, 40), robot at (0, 0)
    dist = em.get_distance_to_base((0.0, 0.0))
    assert dist == pytest.approx(math.hypot(40.0, 40.0), rel=1e-9)


# ---- range estimate ----------------------------------------------------------

def test_range_estimate(battery, em):
    battery.set_charge(1.0, remaining_wh=500.0)
    rng = em.estimate_range_m(speed=0.3)
    # From BatteryInterface.estimate_range_m:
    # total_draw = idle(10) + locomotion(30)*0.3 = 19 W
    # hours_remaining = 500 / 19
    # range = hours * 0.3 * 3600
    expected = (500.0 / 19.0) * 0.3 * 3600.0
    assert rng == pytest.approx(expected, rel=1e-6)


# ---- Edge cases -------------------------------------------------------------

def test_zero_battery_edge_case():
    """Zero remaining energy -- critical, can't afford anything."""
    bat = _TestBattery(capacity_wh=500.0, remaining_wh=0.0, charge_fraction=0.0)
    em = EnergyManager(bat)
    em.update(bat.get_state())
    assert em.is_critical() is True
    assert em.get_remaining_wh() == 0.0
    assert em.can_afford_task((0.0, 0.0), (10.0, 10.0)) is False


# ---- update caching ---------------------------------------------------------

def test_update_caches_state(battery, em):
    """After update(), queries should use cached state, not a live read."""
    battery.set_charge(0.5, remaining_wh=250.0)
    em.update(battery.get_state())
    assert em.get_charge_fraction() == pytest.approx(0.5)
    assert em.get_remaining_wh() == pytest.approx(250.0)
