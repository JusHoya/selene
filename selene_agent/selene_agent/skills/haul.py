"""Haul skill -- pickup material from site, deliver to depot."""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from selene_agent.skills.base_skill import BaseSkill, SkillState


class HaulPhase(str, Enum):
    NAVIGATING_TO_PICKUP = "navigating_to_pickup"
    LOADING = "loading"
    NAVIGATING_TO_DEPOT = "navigating_to_depot"
    UNLOADING = "unloading"


@dataclass(frozen=True)
class HaulResult:
    pickup_position: tuple[float, float]
    depot_position: tuple[float, float]
    delivered_kg: float
    timestamp: float


class HaulSkill(BaseSkill):
    """Drive to a pickup site, load material, drive to depot, unload.

    Internal phases:
    NAVIGATING_TO_PICKUP (0-25%) -> LOADING (25-50%) ->
    NAVIGATING_TO_DEPOT (50-75%) -> UNLOADING (75-100%) -> COMPLETE
    """

    LOAD_TIMEOUT = 30.0
    UNLOAD_TIMEOUT = 30.0

    def __init__(self):
        super().__init__("haul")
        self._pickup = (0.0, 0.0)
        self._depot = (50.0, 50.0)
        self._phase = HaulPhase.NAVIGATING_TO_PICKUP
        self._phase_timer = 0.0
        self._initial_distance = 1.0
        self._load_triggered = False
        self._unload_triggered = False
        self._delivered_kg = 0.0
        self._result: Optional[HaulResult] = None
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, pickup: tuple[float, float] = (0.0, 0.0),
              depot: tuple[float, float] = (50.0, 50.0), **params) -> None:
        self._hal = hal
        self._navigator = navigator
        self._pickup = pickup
        self._depot = depot
        self._phase = HaulPhase.NAVIGATING_TO_PICKUP
        self._state = SkillState.RUNNING
        self._progress = 0.0
        self._phase_timer = 0.0
        self._load_triggered = False
        self._unload_triggered = False
        self._delivered_kg = 0.0
        self._result = None

        result = navigator.plan_to(pickup)
        if not result.success:
            self._state = SkillState.FAILED
            self._error_message = (
                f"Cannot plan path to pickup {pickup}: {result.failure_reason}"
            )
            return

        self._initial_distance = max(navigator.get_distance_to_goal(), 1.0)
        navigator.start_following(result.path)

    def update(self, dt: float) -> None:
        if self._state != SkillState.RUNNING:
            return

        if self._phase == HaulPhase.NAVIGATING_TO_PICKUP:
            self._update_navigating_to_pickup(dt)
        elif self._phase == HaulPhase.LOADING:
            self._update_loading(dt)
        elif self._phase == HaulPhase.NAVIGATING_TO_DEPOT:
            self._update_navigating_to_depot(dt)
        elif self._phase == HaulPhase.UNLOADING:
            self._update_unloading(dt)

    def _update_navigating_to_pickup(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(0.0, 0.25 * (1.0 - dist / self._initial_distance))

        if nav_status == "goal_reached":
            self._phase = HaulPhase.LOADING
            self._phase_timer = 0.0
            self._load_triggered = False
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked on route to pickup"

    def _update_loading(self, dt: float) -> None:
        self._phase_timer += dt

        if not self._load_triggered:
            self._hal.get_actuator("transport_bin").trigger_load()
            self._load_triggered = True

        if self._hal.get_actuator("transport_bin").is_transfer_complete():
            # Read the load cell to determine how much was loaded
            try:
                reading = self._hal.get_sensor("load_cell").read()
                self._delivered_kg = reading.mass_kg
            except (KeyError, AttributeError):
                self._delivered_kg = 0.0

            self._progress = 0.5

            # Plan path to depot
            result = self._navigator.plan_to(self._depot)
            if not result.success:
                self._state = SkillState.FAILED
                self._error_message = (
                    f"Cannot plan to depot: {result.failure_reason}"
                )
                return

            self._initial_distance = max(
                self._navigator.get_distance_to_goal(), 1.0
            )
            self._navigator.start_following(result.path)
            self._phase = HaulPhase.NAVIGATING_TO_DEPOT
            return

        # Progress 25-50% based on timeout
        load_frac = min(self._phase_timer / self.LOAD_TIMEOUT, 1.0)
        self._progress = max(0.0, 0.25 + 0.25 * load_frac)

        if self._phase_timer >= self.LOAD_TIMEOUT:
            self._state = SkillState.FAILED
            self._error_message = "Loading timed out"

    def _update_navigating_to_depot(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(
            0.0, 0.5 + 0.25 * (1.0 - dist / self._initial_distance)
        )

        if nav_status == "goal_reached":
            self._phase = HaulPhase.UNLOADING
            self._phase_timer = 0.0
            self._unload_triggered = False
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked on route to depot"

    def _update_unloading(self, dt: float) -> None:
        self._phase_timer += dt

        if not self._unload_triggered:
            self._hal.get_actuator("transport_bin").trigger_unload()
            self._unload_triggered = True

        if self._hal.get_actuator("transport_bin").is_transfer_complete():
            self._state = SkillState.COMPLETE
            self._progress = 1.0
            self._result = HaulResult(
                pickup_position=self._pickup,
                depot_position=self._depot,
                delivered_kg=self._delivered_kg,
                timestamp=time.time(),
            )
            return

        # Progress 75-100% based on timeout
        unload_frac = min(self._phase_timer / self.UNLOAD_TIMEOUT, 1.0)
        self._progress = max(0.0, 0.75 + 0.25 * unload_frac)

        if self._phase_timer >= self.UNLOAD_TIMEOUT:
            self._state = SkillState.FAILED
            self._error_message = "Unloading timed out"

    def get_result(self) -> Optional[HaulResult]:
        return self._result

    def abort(self) -> None:
        if self._hal:
            try:
                self._hal.get_actuator("transport_bin").cancel_transfer()
            except (KeyError, AttributeError):
                pass
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
