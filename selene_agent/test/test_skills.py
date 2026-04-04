"""Tests for ProspectSkill and RechargeSkill."""

import os
from dataclasses import dataclass

import pytest

from selene_hal import create_hal
from selene_agent.skills.prospect import ProspectSkill, ProspectResult
from selene_agent.skills.recharge import RechargeSkill
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
