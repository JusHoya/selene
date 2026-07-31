"""Tests for ProspectSkill, RechargeSkill, ExcavateSkill, and HaulSkill."""

import math
import os
from dataclasses import dataclass

import pytest

from selene_hal import create_hal
from selene_hal.stub_hal import StubTransferActuator
from selene_agent.skills.prospect import ProspectSkill, ProspectResult
from selene_agent.skills.recharge import RechargeSkill
from selene_agent.skills.excavate import (
    ExcavateSkill, ExcavateResult, ExcavatePhase,
)
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


def _excavator_hal():
    return create_hal(_config('excavator.yaml'), 'excavator_01', backend='stub')


# Capacities read straight out of the RCDLs these HALs are built from --
# selene_hal/config/excavator.yaml:29 and hauler.yaml:29. Repeated here so the
# expected kilogram figures below are traceable to a file rather than being
# magic numbers; StubFillLevelSensor derives mass_kg from the same values.
HOPPER_CAPACITY_KG = 20.0
BIN_CAPACITY_KG = 50.0


def _run_excavate_cycle(skill, nav, hal, fill_fraction=0.96, max_ticks=400):
    """Drive one excavate from NAVIGATING through DUMPING to COMPLETE.

    Stands in for ``selene_sim/hopper_node.py``, which the stub HAL has no
    equivalent of: the hopper fills while the drill runs and drains once the
    hopper transfer actuator has been triggered. The level is only moved
    *after* the skill has taken the reading that phase depends on -- the
    drilling baseline and the pre-dump peak are both measurements the skill
    makes on its own first tick in a phase, and pre-empting them would make
    this driver test itself instead of the skill.

    Returns ``skill.get_result()``.
    """
    sensor = hal.get_sensor("hopper_fill")
    nav.set_status("goal_reached")
    for _ in range(max_ticks):
        if skill.is_complete() or skill.has_failed():
            break
        skill.update(0.1)
        if skill._phase == ExcavatePhase.DRILLING:
            sensor.set_level(fill_fraction)
        elif skill._phase == ExcavatePhase.DUMPING and skill._dump_triggered:
            sensor.set_level(0.0)
    return skill.get_result()


def _run_haul_cycle(skill, nav, hal, load_fraction=0.24, unload_fraction=0.0,
                    max_ticks=1000):
    """Drive one haul from NAVIGATING_TO_PICKUP to COMPLETE.

    Stands in for ``selene_sim/bin_load_node.py``: the bin fills once the
    load command has been issued and empties once the unload command has.
    Both are gated on the skill's own ``_load_triggered`` / ``_unload_triggered``
    flags, because the skill reads its baseline mass on the tick it issues
    each command and moving the level first would zero the delta under test.

    ``unload_fraction`` is what the bin still reads after the dump -- non-zero
    models a partial delivery, which is the case that tells ``delivered_kg``
    (an unload delta) apart from the post-load reading it used to be.

    Returns ``skill.get_result()``.
    """
    sensor = hal.get_sensor("load_cell")
    nav.set_status("goal_reached")
    for _ in range(max_ticks):
        if skill.is_complete() or skill.has_failed():
            break
        skill.update(0.1)
        if skill._phase == HaulPhase.LOADING:
            nav.set_status("navigating")
            if skill._load_triggered:
                sensor.set_level(load_fraction)
        elif skill._phase == HaulPhase.NAVIGATING_TO_DEPOT:
            nav.set_status("goal_reached")
        elif skill._phase == HaulPhase.UNLOADING:
            if skill._unload_triggered:
                sensor.set_level(unload_fraction)
    return skill.get_result()


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

    result = _run_excavate_cycle(skill, nav, hal, fill_fraction=0.96)

    assert skill.is_complete()
    assert skill.get_progress() == 1.0
    assert isinstance(result, ExcavateResult)
    assert result.hopper_full is True
    assert result.deposit_exhausted is False


def test_excavate_reports_extracted_mass_as_a_delta():
    """extracted_kg is (peak - baseline) kg, not the hopper's absolute mass.

    The hopper starts at 0.25 of its 20 kg RCDL capacity, i.e. 5 kg of
    residue this task did not produce, and is drilled to 0.96 (19.2 kg). A
    correct report credits this task with 14.2 kg. Before D-06 was closed the
    HAL never populated mass_kg at all, so this figure was 0.0 - 0.0.
    """
    hal = _excavator_hal()
    nav = MockNavigator()
    hal.get_sensor("hopper_fill").set_level(0.25)

    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))
    result = _run_excavate_cycle(skill, nav, hal, fill_fraction=0.96)

    assert result is not None
    assert result.extracted_kg == pytest.approx(
        0.96 * HOPPER_CAPACITY_KG - 0.25 * HOPPER_CAPACITY_KG
    )


def test_excavate_dumps_the_hopper_before_completing():
    """The hopper transfer actuator is commanded and residual_mass_kg is ~0.

    selene_hal/config/excavator.yaml:44-49 has declared a `hopper` transfer
    actuator since Phase 1 with no caller anywhere in the repository. Without
    the DUMPING phase the hopper has no way to empty at all.
    """
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))

    result = _run_excavate_cycle(skill, nav, hal, fill_fraction=0.96)

    assert result is not None
    assert result.residual_mass_kg == pytest.approx(0.0)
    assert hal.get_sensor("hopper_fill").read().level == pytest.approx(0.0)


def test_second_excavate_on_the_same_robot_does_not_report_zero():
    """The dump is what makes the excavator reusable.

    With no DUMPING phase the hopper is left at 0.96 after the first task, so
    the second task's very first drilling tick already reads >= FILL_THRESHOLD,
    stops immediately, and reports a delta of 0 kg for a robot that produced
    nothing. Both cycles here must report the same full load.
    """
    hal = _excavator_hal()
    nav = MockNavigator()

    first = ExcavateSkill()
    first.start(hal, nav, target=(10, 20))
    first_result = _run_excavate_cycle(first, nav, hal, fill_fraction=0.96)

    nav = MockNavigator()
    second = ExcavateSkill()
    second.start(hal, nav, target=(11, 21))
    second_result = _run_excavate_cycle(second, nav, hal, fill_fraction=0.96)

    assert first_result.extracted_kg == pytest.approx(0.96 * HOPPER_CAPACITY_KG)
    assert second_result.extracted_kg == pytest.approx(first_result.extracted_kg)


def test_excavate_stops_on_the_authorised_quantity():
    """quantity_kg ends drilling before the hopper is full (FR-DASH-5)."""
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20), quantity_kg=5.0)

    # 0.30 of 20 kg = 6.0 kg, over the 5 kg quota but well under the 0.95
    # FILL_THRESHOLD, so only the quota can be what stopped it.
    result = _run_excavate_cycle(skill, nav, hal, fill_fraction=0.30)

    assert result is not None
    assert result.hopper_full is False
    assert result.deposit_exhausted is False
    assert result.extracted_kg == pytest.approx(0.30 * HOPPER_CAPACITY_KG)


def test_excavate_clamps_quantity_to_the_rcdl_capacity():
    """The agent, not the orchestrator, applies the robot's own capacity.

    The orchestrator validates quantity >= 0 and finite and no more: it has
    neither a HAL nor an RCDL. 500 kg is clamped here to the hopper's
    capacity_kg (excavator.yaml:29).
    """
    hal = _excavator_hal()
    nav = MockNavigator()
    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20), quantity_kg=500.0)
    assert skill._quantity_kg == pytest.approx(HOPPER_CAPACITY_KG)

    unconstrained = ExcavateSkill()
    unconstrained.start(hal, MockNavigator(), target=(10, 20))
    assert unconstrained._quantity_kg == 0.0

    negative = ExcavateSkill()
    negative.start(hal, MockNavigator(), target=(10, 20), quantity_kg=-3.0)
    assert negative._quantity_kg == 0.0


def test_excavate_reports_nan_mass_when_the_hopper_sensor_is_dead():
    """A skill that cannot read its fill sensor must not report a zero.

    NaN is the "not measured" sentinel agent_node checks before publishing a
    MaterialEvent; a 0.0 here would enter the ledger as a real measurement of
    nothing.
    """
    hal = _excavator_hal()
    nav = MockNavigator()
    hal.get_sensor("hopper_fill").deactivate()

    skill = ExcavateSkill()
    skill.start(hal, nav, target=(10, 20))
    # The hopper never reads valid, so nothing stops drilling before
    # DEPLETION_TIMEOUT (60 s at dt=0.1 -> 600 ticks) plus the dump.
    result = _run_excavate_cycle(skill, nav, hal, max_ticks=1200)

    assert result is not None
    assert math.isnan(result.extracted_kg)
    assert result.deposit_exhausted is True


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


def _hauler_hal():
    return create_hal(_config('hauler.yaml'), 'hauler_01', backend='stub')


def test_haul_loads_then_navigates_to_depot():
    """Full pickup -> load -> depot -> unload cycle reaches COMPLETE."""
    hal = _hauler_hal()
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    result = _run_haul_cycle(skill, nav, hal, load_fraction=0.24)

    assert skill.is_complete()
    assert skill.get_progress() == 1.0
    assert isinstance(result, HaulResult)
    assert result.pickup_position == (10.0, 20.0)
    assert result.depot_position == (50.0, 50.0)


def test_haul_authorised_quantity_reaches_the_actuator():
    """quantity_kg travels start() -> trigger_load(max_kg=...) (FR-DASH-5).

    This is the bound that stops bin_load_node filling to BIN_CAPACITY_KG on
    command regardless of whether any excavator ever produced the material.
    """
    hal = _hauler_hal()
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0),
                quantity_kg=12.0)

    _run_haul_cycle(skill, nav, hal, load_fraction=12.0 / BIN_CAPACITY_KG)

    actuator = hal.get_actuator("transport_bin")
    assert actuator.load_call_count == 1
    assert actuator.last_max_kg == pytest.approx(12.0)


def test_haul_unconstrained_quantity_loads_unbounded():
    """0.0 means "fill to capacity" -- the pre-FR-DASH-5 behaviour."""
    hal = _hauler_hal()
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    _run_haul_cycle(skill, nav, hal, load_fraction=1.0)

    actuator = hal.get_actuator("transport_bin")
    assert actuator.load_call_count == 1
    assert actuator.last_max_kg == -1.0


def test_haul_clamps_quantity_to_the_rcdl_capacity():
    """500 kg is clamped to the load cell's capacity_kg (hauler.yaml:29)."""
    hal = _hauler_hal()
    skill = HaulSkill()
    skill.start(hal, MockNavigator(), pickup=(10.0, 20.0), depot=(50.0, 50.0),
                quantity_kg=500.0)
    assert skill._quantity_kg == pytest.approx(BIN_CAPACITY_KG)


def test_haul_advances_when_the_actuator_never_reports_complete():
    """The one that covers the live Gazebo defect.

    GazeboTransferActuator._complete is set True only in its constructor and
    in cancel_transfer, while trigger_load and trigger_unload set it False and
    nothing sets it back (selene_hal/selene_hal/gazebo_hal.py). A skill gating
    on is_transfer_complete() therefore stalls in LOADING and fails at
    LOAD_TIMEOUT on every haul the real system runs -- a defect the suite could
    never see, because StubTransferActuator returns True unconditionally.

    This double has the Gazebo shape. The haul must still complete, because it
    now watches the load cell instead.
    """
    class NeverCompletingTransferActuator(StubTransferActuator):
        def is_transfer_complete(self) -> bool:
            return False

    hal = _hauler_hal()
    bin_config = hal.get_actuator("transport_bin").get_config()
    hal._actuators["transport_bin"] = NeverCompletingTransferActuator(bin_config)

    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0),
                quantity_kg=12.0)

    result = _run_haul_cycle(skill, nav, hal, load_fraction=12.0 / BIN_CAPACITY_KG)

    assert skill.is_complete(), skill.get_error()
    assert result.loaded_kg == pytest.approx(12.0)


def test_haul_delivered_kg_is_the_unload_delta():
    """delivered_kg measures what was put DOWN, not what was picked up.

    haul.py used to assign delivered_kg from the load cell at LOAD time, so a
    hauler that dropped half its bin still reported a full delivery. Here the
    bin is loaded to 24 kg and dumped down to 4 kg: delivered is 20 kg,
    loaded is 24 kg, residual is 4 kg, and all three are different numbers.
    """
    hal = _hauler_hal()
    nav = MockNavigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))

    result = _run_haul_cycle(
        skill, nav, hal,
        load_fraction=24.0 / BIN_CAPACITY_KG,
        unload_fraction=4.0 / BIN_CAPACITY_KG,
    )

    assert result.loaded_kg == pytest.approx(24.0)
    assert result.bin_mass_after_load_kg == pytest.approx(24.0)
    assert result.delivered_kg == pytest.approx(20.0)
    assert result.residual_mass_kg == pytest.approx(4.0)


def test_haul_loaded_kg_excludes_residue_already_in_the_bin():
    """loaded_kg is a delta; bin_mass_after_load_kg is the absolute reading.

    The bin arrives holding 5 kg it did not pick up here and leaves holding
    24 kg, so this pickup is worth 19 kg. The two numbers differ precisely
    when the bin was not empty on arrival, which is the case that would
    otherwise credit one site with another site's material.
    """
    hal = _hauler_hal()
    nav = MockNavigator()
    hal.get_sensor("load_cell").set_level(5.0 / BIN_CAPACITY_KG)

    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))
    result = _run_haul_cycle(
        skill, nav, hal, load_fraction=24.0 / BIN_CAPACITY_KG,
    )

    assert result.loaded_kg == pytest.approx(19.0)
    assert result.bin_mass_after_load_kg == pytest.approx(24.0)
    # Everything in the bin is dumped, residue included.
    assert result.delivered_kg == pytest.approx(24.0)
    assert result.residual_mass_kg == pytest.approx(0.0)


def test_haul_reports_nan_mass_when_the_load_cell_is_dead():
    """An unreadable load cell fails the task rather than reporting 0 kg."""
    hal = _hauler_hal()
    nav = MockNavigator()
    hal.get_sensor("load_cell").deactivate()

    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))
    _run_haul_cycle(skill, nav, hal, load_fraction=0.24, max_ticks=1000)

    # Nothing can end LOADING: quota is unset, the fraction is never valid and
    # settle detection refuses to arm on an invalid reading, so LOAD_TIMEOUT
    # is the only exit. A failed haul is the honest outcome -- the alternative
    # is a COMPLETE with a fabricated mass.
    assert skill.has_failed()
    assert "timed out" in skill.get_error().lower()


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
