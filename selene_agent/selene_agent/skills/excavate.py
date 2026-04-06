"""Excavate skill -- navigate to extraction site, drill until hopper full."""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from selene_agent.skills.base_skill import BaseSkill, SkillState


class ExcavatePhase(str, Enum):
    NAVIGATING = "navigating"
    POSITIONING = "positioning"   # 1s stabilization at drill site
    DRILLING = "drilling"         # drill active, monitoring hopper fill
    STOPPING = "stopping"         # drill shutdown


@dataclass(frozen=True)
class ExcavateResult:
    position: tuple[float, float]
    extracted_kg: float
    hopper_full: bool
    deposit_exhausted: bool
    timestamp: float


class ExcavateSkill(BaseSkill):
    """Drive to an extraction site, drill regolith, fill hopper.

    Internal phases: NAVIGATING -> POSITIONING (1s) -> DRILLING -> STOPPING -> COMPLETE
    """

    POSITIONING_TIME = 1.0        # seconds to stabilize before drilling
    FILL_THRESHOLD = 0.95         # fraction of capacity to consider hopper full
    DEPLETION_TIMEOUT = 60.0      # max drill time before assuming deposit exhausted

    def __init__(self):
        super().__init__("excavate")
        self._target = (0.0, 0.0)
        self._phase = ExcavatePhase.NAVIGATING
        self._phase_timer = 0.0
        self._drill_timer = 0.0
        self._initial_distance = 1.0
        self._initial_mass = 0.0
        self._extracted_kg = 0.0
        self._hopper_full = False
        self._deposit_exhausted = False
        self._result: Optional[ExcavateResult] = None
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, target: tuple[float, float] = (0.0, 0.0),
              **params) -> None:
        self._hal = hal
        self._navigator = navigator
        self._target = target
        self._phase = ExcavatePhase.NAVIGATING
        self._state = SkillState.RUNNING
        self._progress = 0.0
        self._phase_timer = 0.0
        self._drill_timer = 0.0
        self._initial_mass = 0.0
        self._extracted_kg = 0.0
        self._hopper_full = False
        self._deposit_exhausted = False
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

        if self._phase == ExcavatePhase.NAVIGATING:
            self._update_navigating(dt)
        elif self._phase == ExcavatePhase.POSITIONING:
            self._update_positioning(dt)
        elif self._phase == ExcavatePhase.DRILLING:
            self._update_drilling(dt)
        elif self._phase == ExcavatePhase.STOPPING:
            self._update_stopping(dt)

    def _update_navigating(self, dt: float) -> None:
        nav_status = self._navigator.update(dt)
        dist = self._navigator.get_distance_to_goal()
        self._progress = max(0.0, 0.3 * (1.0 - dist / self._initial_distance))

        if nav_status == "goal_reached":
            self._phase = ExcavatePhase.POSITIONING
            self._phase_timer = 0.0
            self._hal.get_actuator("drive").stop()
        elif nav_status == "blocked":
            self._state = SkillState.FAILED
            self._error_message = "Path blocked, no alternate route"

    def _update_positioning(self, dt: float) -> None:
        self._phase_timer += dt
        self._progress = 0.3 + 0.05 * min(
            self._phase_timer / self.POSITIONING_TIME, 1.0
        )
        if self._phase_timer >= self.POSITIONING_TIME:
            self._phase = ExcavatePhase.DRILLING
            self._drill_timer = 0.0
            # Record initial hopper mass before drilling
            try:
                reading = self._hal.get_sensor("hopper_fill").read()
                self._initial_mass = reading.mass_kg
            except (KeyError, AttributeError):
                self._initial_mass = 0.0

    def _update_drilling(self, dt: float) -> None:
        # Start drill on first tick of drilling phase
        if self._drill_timer == 0.0:
            try:
                drill = self._hal.get_actuator("drill")
                drill.set_power_level(1.0)
                drill.start_drilling()
            except (KeyError, AttributeError):
                self._state = SkillState.FAILED
                self._error_message = "Drill actuator unavailable"
                return

        self._drill_timer += dt

        # Read hopper fill level
        try:
            hopper = self._hal.get_sensor("hopper_fill").read()
            fill_level = hopper.level
            current_mass = hopper.mass_kg
        except (KeyError, AttributeError):
            fill_level = 0.0
            current_mass = 0.0

        # Progress: 35-95% based on fill fraction
        self._progress = 0.35 + 0.6 * min(fill_level / self.FILL_THRESHOLD, 1.0)

        hopper_full = fill_level >= self.FILL_THRESHOLD
        timed_out = self._drill_timer >= self.DEPLETION_TIMEOUT

        if hopper_full or timed_out:
            self._phase = ExcavatePhase.STOPPING
            self._extracted_kg = current_mass - self._initial_mass
            self._hopper_full = hopper_full
            self._deposit_exhausted = timed_out and not hopper_full

    def _update_stopping(self, dt: float) -> None:
        # Stop the drill
        try:
            self._hal.get_actuator("drill").stop_drilling()
        except (KeyError, AttributeError):
            pass

        # Record result
        try:
            odom = self._hal.get_sensor("odometry").read()
            pos = (odom.x, odom.y)
        except KeyError:
            pos = self._target

        self._result = ExcavateResult(
            position=pos,
            extracted_kg=self._extracted_kg,
            hopper_full=self._hopper_full,
            deposit_exhausted=self._deposit_exhausted,
            timestamp=time.time(),
        )

        self._state = SkillState.COMPLETE
        self._progress = 1.0

    def get_result(self) -> Optional[ExcavateResult]:
        return self._result

    def abort(self) -> None:
        # Stop drill if we were drilling
        if self._hal:
            try:
                drill = self._hal.get_actuator("drill")
                if drill.is_drilling():
                    drill.stop_drilling()
            except (KeyError, AttributeError):
                pass
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
