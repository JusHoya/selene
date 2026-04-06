"""Tests for ProspectSkill, RechargeSkill, ExcavateSkill, and HaulSkill."""

import os
from dataclasses import dataclass

import pytest

from selene_hal import create_hal
from selene_hal.data_types import FillLevelReading
from selene_agent.skills.prospect import ProspectSkill, ProspectResult
from selene_agent.skills.recharge import RechargeSkill
from selene_agent.skills.excavate import ExcavateSkill, ExcavateResult
from selene_agent.skills.haul import HaulSkill, HaulResult, HaulPhase
from selene_agent.skills.base_skill import SkillState


@dataclass
class PlanResult:
    """Minimal stand-in for navigator.PlanResult (navigator not yet available)."""
    path: list
    cost: float
    success: bool
    failure_reason: str = ""


class MockNavigator:
    """Test navigator that can be driven through states programmatically."""

    def __init__(self):
        self._status = "navigating"
        self._distance = 100.0
        self._path = []

    def plan_to(self, goal):
        return PlanResult(path=[goal], cost=10.0, success=True)

    def start_following(self, path):
        self._path = path
        self._status = "navigating"

    def update(self, dt):
        return self._status

    def get_distance_to_goal(self):
        return self._distance

    def stop(self):
        self._status = "idle"

    def set_status(self, status):
        self._status = status

    def set_distance(self, dist):
        self._distance = dist


def _config(name):
    return os.path.join(
        os.path.dirname(__file__), '..', '..', 'selene_hal', 'config', name
    )


# --- ProspectSkill Tests ---


def test_prospect_starts_running():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))
    assert skill.is_running()
    assert skill.get_name() == "prospect"


def test_prospect_navigation_progress():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))
    nav.set_distance(50.0)
    skill.update(0.1)
    assert 0.0 < skill.get_progress() < 0.6


def test_prospect_completes_full_cycle():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))

    # Navigate to arrival
    nav.set_status("goal_reached")
    skill.update(0.1)

    # Settling phase (need >= 1.0s)
    for _ in range(12):
        skill.update(0.1)

    # Sensing phase (need >= 2.0s)
    for _ in range(25):
        skill.update(0.1)

    assert skill.is_complete()
    assert skill.get_progress() == 1.0
    result = skill.get_result()
    assert isinstance(result, ProspectResult)


def test_prospect_result_has_zero_ice_in_stub():
    """StubHal returns value=0.0, so no readings pass the >0 filter."""
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))

    nav.set_status("goal_reached")
    skill.update(0.1)
    for _ in range(12):
        skill.update(0.1)
    for _ in range(25):
        skill.update(0.1)

    result = skill.get_result()
    assert result.ice_concentration == 0.0
    assert result.uncertainty == float("inf")


def test_prospect_abort():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))
    skill.abort()
    assert skill.has_failed()
    assert skill.get_state() == SkillState.ABORTED


def test_prospect_fails_on_blocked():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = ProspectSkill()
    skill.start(hal, nav, target=(-80, -140))
    nav.set_status("blocked")
    skill.update(0.1)
    assert skill.has_failed()


def test_prospect_fails_on_bad_plan():
    """Plan failure should set skill to FAILED immediately."""
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')

    class FailNav(MockNavigator):
        def plan_to(self, goal):
            return PlanResult(path=[], cost=0.0, success=False,
                              failure_reason="no path")

    skill = ProspectSkill()
    skill.start(hal, FailNav(), target=(999, 999))
    assert skill.has_failed()
    assert "no path" in skill.get_error()


# --- RechargeSkill Tests ---


def test_recharge_starts_running():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = RechargeSkill()
    skill.start(hal, nav)
    assert skill.is_running()


def test_recharge_completes_when_charged():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = RechargeSkill(recharge_target=0.9)
    skill.start(hal, nav)

    # Arrive at station
    nav.set_status("goal_reached")
    skill.update(0.1)

    # StubBattery returns charge_fraction=1.0 (>= 0.9 target)
    skill.update(0.1)
    assert skill.is_complete()


def test_recharge_abort():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = RechargeSkill()
    skill.start(hal, nav)
    skill.abort()
    assert skill.get_state() == SkillState.ABORTED


def test_recharge_navigation_progress():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = RechargeSkill()
    skill.start(hal, nav)

    nav.set_distance(50.0)
    skill.update(0.1)
    assert 0.0 < skill.get_progress() <= 0.3


def test_recharge_fails_on_blocked():
    hal = create_hal(_config('scout.yaml'), 'scout_01', backend='stub')
    nav = MockNavigator()
    skill = RechargeSkill()
    skill.start(hal, nav)
    nav.set_status("blocked")
    skill.update(0.1)
    assert skill.has_failed()
    assert "Cannot reach" in skill.get_error()


# --- BaseSkill state tests ---


def test_skill_initial_state():
    skill = ProspectSkill()
    assert skill.get_state() == SkillState.IDLE
    assert skill.get_progress() == 0.0
    assert not skill.is_running()
    assert not skill.is_complete()
    assert not skill.has_failed()
    assert skill.get_error() == ""


# --- ExcavateSkill Tests ---


class MockFillLevelSensor:
    """Fill level sensor mock that allows programmatic level changes."""

    def __init__(self):
        self._level = 0.0
        self._mass = 0.0

    def read(self):
        return FillLevelReading(
            sensor_name="hopper_fill", is_valid=True,
            level=self._level, mass_kg=self._mass,
        )

    def set_level(self, level, mass):
        self._level = level
        self._mass = mass

    def get_config(self):
        return None

    def is_active(self):
        return True

    def activate(self):
        pass

    def deactivate(self):
        pass


def _excavator_hal():
    return create_hal(_config('excavator.yaml'), 'excavator_01', backend='stub')


def test_excavate_starts_running():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))
    assert skill.is_running()
    assert skill.get_name() == "excavate"


def test_excavate_navigates_then_drills():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))

    # Arrive at goal
    nav.set_status("goal_reached")
    skill.update(0.1)

    # Complete positioning phase (>= 1.0s)
    for _ in range(12):
        skill.update(0.1)

    # Now in drilling phase -- drill should be active
    skill.update(0.1)
    drill = hal.get_actuator("drill")
    assert drill.is_drilling()


def test_excavate_completes_on_hopper_full():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))

    # Navigate to goal
    nav.set_status("goal_reached")
    skill.update(0.1)

    # Complete positioning (>= 1.0s)
    for _ in range(12):
        skill.update(0.1)

    # Swap in a mock fill sensor that we can control
    mock_sensor = MockFillLevelSensor()
    hal._sensors["hopper_fill"] = mock_sensor

    # First drill tick starts the drill
    skill.update(0.1)
    assert hal.get_actuator("drill").is_drilling()

    # Simulate hopper filling up
    mock_sensor.set_level(0.96, 19.2)
    skill.update(0.1)

    # Should now be in STOPPING phase, next update completes
    skill.update(0.1)
    assert skill.is_complete()
    assert skill.get_progress() == 1.0

    result = skill.get_result()
    assert isinstance(result, ExcavateResult)
    assert result.hopper_full is True
    assert result.deposit_exhausted is False


def test_excavate_abort_stops_drill():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))

    # Navigate and position
    nav.set_status("goal_reached")
    skill.update(0.1)
    for _ in range(12):
        skill.update(0.1)

    # Start drilling
    skill.update(0.1)
    drill = hal.get_actuator("drill")
    assert drill.is_drilling()

    # Abort mid-drilling
    skill.abort()
    assert skill.get_state() == SkillState.ABORTED
    assert not drill.is_drilling()


def test_excavate_fails_on_blocked_path():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))

    nav.set_status("blocked")
    skill.update(0.1)
    assert skill.has_failed()
    assert skill.get_state() == SkillState.FAILED
    assert "blocked" in skill.get_error().lower()


def test_excavate_fails_on_bad_plan():
    """Plan failure should set skill to FAILED immediately."""
    hal = _excavator_hal()

    class FailNav(MockNavigator):
        def plan_to(self, goal):
            return PlanResult(path=[], cost=0.0, success=False,
                              failure_reason="no path")

    skill = ExcavateSkill()
    skill.start(hal, FailNav(), target=(999, 999))
    assert skill.has_failed()
    assert "no path" in skill.get_error()


def test_excavate_navigation_progress():
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))
    nav.set_distance(50.0)
    skill.update(0.1)
    assert 0.0 < skill.get_progress() < 0.3


# --- HaulSkill Tests ---


def test_haul_starts_running():
    """HaulSkill starts in RUNNING state with hauler HAL."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))
    assert skill.is_running()
    assert skill.get_name() == "haul"


def test_haul_navigates_to_pickup():
    """First navigation phase drives progress 0-25%."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    # Partially there
    nav.set_distance(50.0)
    skill.update(0.1)
    assert 0.0 < skill.get_progress() < 0.25

    # Arrive at pickup
    nav.set_status("goal_reached")
    skill.update(0.1)
    assert skill._phase == HaulPhase.LOADING


def test_haul_loads_then_navigates_to_depot():
    """After loading at pickup, plans and navigates to depot."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    # Arrive at pickup
    nav.set_status("goal_reached")
    skill.update(0.1)
    assert skill._phase == HaulPhase.LOADING

    # StubTransferActuator completes immediately, so one update should
    # transition through LOADING -> NAVIGATING_TO_DEPOT
    nav.set_status("navigating")
    skill.update(0.1)
    assert skill._phase == HaulPhase.NAVIGATING_TO_DEPOT

    # Arrive at depot
    nav.set_status("goal_reached")
    skill.update(0.1)
    assert skill._phase == HaulPhase.UNLOADING

    # Unload completes immediately (stub)
    skill.update(0.1)
    assert skill.is_complete()
    assert skill.get_progress() == 1.0
    result = skill.get_result()
    assert isinstance(result, HaulResult)
    assert result.pickup_position == (10.0, 20.0)
    assert result.depot_position == (50.0, 50.0)


def test_haul_abort_cancels_transfer():
    """Abort during loading cancels the active transfer."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    # Arrive at pickup, enter loading
    nav.set_status("goal_reached")
    skill.update(0.1)
    assert skill._phase == HaulPhase.LOADING

    # Abort mid-load
    skill.abort()
    assert skill.get_state() == SkillState.ABORTED
    assert skill.has_failed()


def test_haul_fails_on_bad_pickup_plan():
    """Plan failure to pickup sets skill to FAILED immediately."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')

    class FailNav(MockNavigator):
        def plan_to(self, goal):
            return PlanResult(path=[], cost=0.0, success=False,
                              failure_reason="no path to pickup")

    skill = HaulSkill()
    skill.start(hal, FailNav(), pickup=(999.0, 999.0), depot=(50.0, 50.0))
    assert skill.has_failed()
    assert "no path" in skill.get_error()


def test_haul_fails_on_blocked_to_pickup():
    """Blocked navigation to pickup sets skill to FAILED."""
    hal = create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))
    nav.set_status("blocked")
    skill.update(0.1)
    assert skill.has_failed()
    assert "blocked" in skill.get_error().lower()
