"""Prospect skill -- navigate to waypoint, sense ice concentration, record result."""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from selene_agent.skills.base_skill import BaseSkill, SkillState


class ProspectPhase(str, Enum):
    NAVIGATING = "navigating"
    SETTLING = "settling"
    SENSING = "sensing"
    RECORDING = "recording"


@dataclass(frozen=True)
class ProspectResult:
    position: tuple[float, float]
    ice_concentration: float
    uncertainty: float
    timestamp: float


class ProspectSkill(BaseSkill):
    """Drive to a waypoint, activate neutron spectrometer, record ice concentration.

    Internal phases: NAVIGATING -> SETTLING (1s) -> SENSING (2s) -> RECORDING -> COMPLETE
    """

    SETTLING_TIME = 1.0   # seconds to wait after arrival
    SENSING_TIME = 2.0    # seconds of spectrometer sensing

    def __init__(self):
        super().__init__("prospect")
        self._target = (0.0, 0.0)
        self._phase = ProspectPhase.NAVIGATING
        self._phase_timer = 0.0
        self._initial_distance = 1.0
        self._readings = []
        self._result: Optional[ProspectResult] = None
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, target: tuple[float, float] = (0.0, 0.0),
              **params) -> None:
        self._hal = hal
        self._navigator = navigator
        self._target = target
        self._phase = ProspectPhase.NAVIGATING
        self._state = SkillState.RUNNING
        self._progress = 0.0
        self._readings = []
        self._result = None

        result = navigator.plan_to(target)
        if not result.success:
            self._state = SkillState.FAILED
            self._error_message = (
                f"Cannot plan path to {target}: {result.failure_reason}"
            )
            return

        self._initial_distance = max(navigator.get_distance_to_goal(), 1.0)
        navigator.start_following(result.path)

    def update(self, dt: float) -> None:
        if self._state != SkillState.RUNNING:
            return

        if self._phase == ProspectPhase.NAVIGATING:
            self._update_navigating(dt)
        elif self._phase == ProspectPhase.SETTLING:
            self._update_settling(dt)
        elif self._phase == ProspectPhase.SENSING:
            self._update_sensing(dt)
        elif self._phase == ProspectPhase.RECORDING:
            self._state = SkillState.COMPLETE
            self._progress = 1.0

    def _update_navigating(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = 0.6 * (1.0 - dist / self._initial_distance)

        if nav_status == "goal_reached":
            self._phase = ProspectPhase.SETTLING
            self._phase_timer = 0.0
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked, no alternate route"

    def _update_settling(self, dt: float) -> None:
        self._phase_timer += dt
        self._progress = 0.6
        if self._phase_timer >= self.SETTLING_TIME:
            self._phase = ProspectPhase.SENSING
            self._phase_timer = 0.0
            self._readings.clear()
            # Activate spectrometer if available
            try:
                self._hal.get_sensor("neutron_spectrometer").activate()
            except (KeyError, AttributeError):
                pass

    def _update_sensing(self, dt: float) -> None:
        self._phase_timer += dt
        try:
            reading = self._hal.get_sensor("neutron_spectrometer").read()
            if reading.is_valid and reading.value > 0:
                self._readings.append(reading)
        except KeyError:
            pass
        self._progress = 0.6 + 0.3 * min(
            self._phase_timer / self.SENSING_TIME, 1.0
        )

        if self._phase_timer >= self.SENSING_TIME:
            self._phase = ProspectPhase.RECORDING
            self._record_result()

    def _record_result(self):
        if self._readings:
            avg_value = sum(r.value for r in self._readings) / len(self._readings)
            avg_uncertainty = (
                sum(r.uncertainty for r in self._readings) / len(self._readings)
            )
        else:
            avg_value = 0.0
            avg_uncertainty = float("inf")

        try:
            odom = self._hal.get_sensor("odometry").read()
            pos = (odom.x, odom.y)
        except KeyError:
            pos = self._target

        self._result = ProspectResult(
            position=pos,
            ice_concentration=avg_value,
            uncertainty=avg_uncertainty,
            timestamp=time.time(),
        )

    def get_result(self) -> Optional[ProspectResult]:
        return self._result

    def abort(self) -> None:
        if self._hal:
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
