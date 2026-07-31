"""Excavate skill -- navigate to extraction site, drill, then dump the hopper."""

import math
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
    DUMPING = "dumping"           # hopper transfer actuator emptying the hopper


@dataclass(frozen=True)
class ExcavateResult:
    position: tuple[float, float]
    # Mass drilled during this task, kg: the hopper reading at the moment
    # drilling stopped minus the reading taken when it started. NaN when the
    # hopper fill sensor could not be read -- see ExcavateSkill._read_fill.
    # agent_node publishes no MaterialEvent for a non-finite mass, because a
    # missing measurement is honest and a fabricated 0.0 is not.
    extracted_kg: float
    hopper_full: bool
    deposit_exhausted: bool
    timestamp: float
    # Hopper mass left after the DUMPING phase, kg. Expected near zero; the
    # orchestrator cross-checks it against the delta above so a hopper that
    # reports 19 kg extracted while still holding 19 kg is visible as a fault
    # rather than as successful production. NaN carries the same "not
    # measured" meaning as extracted_kg.
    residual_mass_kg: float


class ExcavateSkill(BaseSkill):
    """Drive to an extraction site, drill regolith, fill and empty the hopper.

    Internal phases:
    NAVIGATING -> POSITIONING (1s) -> DRILLING -> STOPPING -> DUMPING -> COMPLETE

    DUMPING exists for two reasons, both of which produce a silent zero
    without it:

    1. The hopper has no other way to empty. ``selene_hal/config/excavator.yaml``
       has declared a ``hopper`` transfer actuator on ``actuators/hopper_cmd``
       since Phase 1 and nothing has ever commanded it. A robot whose hopper
       is left at 0.95 of capacity starts its *next* excavate task already
       above FILL_THRESHOLD, stops on the first drilling tick and reports a
       delta of ~0 kg.
    2. The measurement has to be taken before the dump, not after. The mass
       the ledger wants is the peak, so ``_extracted_kg`` is computed in
       ``_update_drilling`` at the moment drilling stops, and the dump then
       runs against a number that is already recorded.
    """

    POSITIONING_TIME = 1.0        # seconds to stabilize before drilling
    FILL_THRESHOLD = 0.95         # fraction of capacity to consider hopper full
    EMPTY_THRESHOLD = 0.02        # fraction at or below which the hopper is empty
    DEPLETION_TIMEOUT = 60.0      # max drill time before assuming deposit exhausted
    HOPPER_DUMP_TIMEOUT = 15.0    # max time to wait for the hopper to empty

    def __init__(self):
        super().__init__("excavate")
        self._target = (0.0, 0.0)
        self._phase = ExcavatePhase.NAVIGATING
        self._phase_timer = 0.0
        self._drill_timer = 0.0
        self._dump_timer = 0.0
        self._initial_distance = 1.0
        self._initial_mass = 0.0
        self._quantity_kg = 0.0
        self._extracted_kg = 0.0
        self._residual_mass_kg = 0.0
        self._hopper_full = False
        self._deposit_exhausted = False
        self._dump_triggered = False
        self._end_position = (0.0, 0.0)
        self._result: Optional[ExcavateResult] = None
        self._hal = None
        self._navigator = None

    def start(self, hal, navigator, target: tuple[float, float] = (0.0, 0.0),
              quantity_kg: float = 0.0, **params) -> None:
        """Begin an excavation.

        ``quantity_kg`` is the mass this assignment authorises
        (``TaskAssignment.quantity_kg``, ultimately ``InjectTask.quantity``).
        0.0 means unconstrained -- drill until the hopper is full, which is
        the behaviour every task had before the field existed. A positive
        value is clamped to the hopper's own RCDL ``capacity_kg``
        (``selene_hal/config/excavator.yaml:29``, 20 kg): the orchestrator
        deliberately does not clamp it because it has neither a HAL nor an
        RCDL, so this is the only place the robot's real limit is known.
        """
        self._hal = hal
        self._navigator = navigator
        self._target = target
        self._phase = ExcavatePhase.NAVIGATING
        self._state = SkillState.RUNNING
        self._progress = 0.0
        self._phase_timer = 0.0
        self._drill_timer = 0.0
        self._dump_timer = 0.0
        self._initial_mass = 0.0
        self._extracted_kg = 0.0
        self._residual_mass_kg = 0.0
        self._hopper_full = False
        self._deposit_exhausted = False
        self._dump_triggered = False
        self._end_position = target
        self._result = None
        self._quantity_kg = self._clamp_quantity(quantity_kg)

        result = navigator.plan_to(target)
        if not result.success:
            self._state = SkillState.FAILED
            self._error_message = (
                f"Cannot plan path to {target}: {result.failure_reason}"
            )
            return

        self._initial_distance = max(navigator.get_distance_to_goal(), 1.0)
        navigator.start_following(result.path)

    # -------------------------------------------------------------------
    # HAL reads
    # -------------------------------------------------------------------

    def _clamp_quantity(self, quantity_kg) -> float:
        """Clamp an authorised mass to the hopper's RCDL capacity.

        Returns 0.0 (unconstrained) for a missing, negative or non-finite
        request. The capacity comes from the sensor's own ``SensorConfig``,
        which the HAL populates from ``capacity_kg`` in the RCDL -- the
        single source of truth for this number (contract §3). If the HAL
        does not expose it, the request is honoured unclamped rather than
        being zeroed: an unclamped quota still terminates on FILL_THRESHOLD.
        """
        try:
            requested = float(quantity_kg)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(requested) or requested <= 0.0:
            return 0.0

        capacity = 0.0
        try:
            config = self._hal.get_sensor("hopper_fill").get_config()
            capacity = float(getattr(config, 'extra', {}).get('capacity_kg', 0.0))
        except (KeyError, AttributeError, TypeError, ValueError):
            capacity = 0.0
        if math.isfinite(capacity) and capacity > 0.0:
            return min(requested, capacity)
        return requested

    def _read_fill(self) -> tuple[bool, float, float]:
        """Read the hopper fill sensor as ``(is_valid, level, mass_kg)``.

        ``level`` is the documented 0.0-1.0 fraction of the RCDL capacity;
        ``mass_kg`` is the HAL-derived mass. An unreadable or invalid sensor
        yields ``mass_kg = NaN`` so that every mass derived from it is NaN
        too and reaches agent_node as "not measured" rather than as zero.
        ``level`` is still returned for progress reporting but callers must
        gate any threshold decision on ``is_valid``.
        """
        try:
            reading = self._hal.get_sensor("hopper_fill").read()
        except (KeyError, AttributeError):
            return False, 0.0, float('nan')
        level = float(getattr(reading, 'level', 0.0) or 0.0)
        if not getattr(reading, 'is_valid', False):
            return False, level, float('nan')
        return True, level, float(getattr(reading, 'mass_kg', 0.0) or 0.0)

    # -------------------------------------------------------------------
    # Tick
    # -------------------------------------------------------------------

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
        elif self._phase == ExcavatePhase.DUMPING:
            self._update_dumping(dt)

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
            # Record hopper mass before drilling. This is the baseline the
            # reported mass is a delta from, so a hopper that starts partly
            # full is not credited to this task.
            _valid, _level, self._initial_mass = self._read_fill()

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

        valid, fill_level, current_mass = self._read_fill()

        # Progress: 35-95% based on fill fraction
        self._progress = 0.35 + 0.6 * min(fill_level / self.FILL_THRESHOLD, 1.0)

        hopper_full = valid and fill_level >= self.FILL_THRESHOLD

        # Operator/ledger quota. Only a finite delta can satisfy it: with an
        # unreadable sensor `drilled` is NaN and every comparison is False,
        # so the task falls through to DEPLETION_TIMEOUT instead of stopping
        # on a quota it cannot prove it met.
        drilled = current_mass - self._initial_mass
        quota_met = (
            self._quantity_kg > 0.0
            and math.isfinite(drilled)
            and drilled >= self._quantity_kg
        )

        timed_out = self._drill_timer >= self.DEPLETION_TIMEOUT

        if hopper_full or quota_met or timed_out:
            self._phase = ExcavatePhase.STOPPING
            # Take the measurement BEFORE the dump. _update_dumping drains
            # the hopper, so reading the sensor after it would report ~0 kg
            # extracted for a task that moved a full load.
            self._extracted_kg = drilled
            self._hopper_full = hopper_full
            self._deposit_exhausted = (
                timed_out and not hopper_full and not quota_met
            )

    def _update_stopping(self, dt: float) -> None:
        # Stop the drill
        try:
            self._hal.get_actuator("drill").stop_drilling()
        except (KeyError, AttributeError):
            pass

        # Record where the extraction happened, for the log line. This is not
        # on the wire: MaterialEvent deliberately carries no position, because
        # every pose in this system is dead-reckoned from a spawn point
        # (register D-08) and keying a site on one would split one deposit
        # into several with nothing logged.
        try:
            odom = self._hal.get_sensor("odometry").read()
            self._end_position = (odom.x, odom.y)
        except (KeyError, AttributeError):
            self._end_position = self._target

        self._progress = 0.95
        self._phase = ExcavatePhase.DUMPING
        self._dump_timer = 0.0
        self._dump_triggered = False

    def _update_dumping(self, dt: float) -> None:
        """Empty the hopper through the ``hopper`` transfer actuator.

        Completion is observed from the fill sensor, not from
        ``is_transfer_complete()``. On the Gazebo backend that flag is set
        True only in the constructor and in ``cancel_transfer``
        (``selene_hal/selene_hal/gazebo_hal.py:491,512``) while
        ``trigger_unload`` sets it False, so gating on it would hold this
        phase until HOPPER_DUMP_TIMEOUT on every single task. (Static
        argument from reading gazebo_hal.py -- not observed on a running
        system; the stub backend returns True unconditionally and hides it.)
        """
        if not self._dump_triggered:
            self._dump_triggered = True
            try:
                self._hal.get_actuator("hopper").trigger_unload()
            except (KeyError, AttributeError):
                # No hopper actuator declared for this robot type. Nothing
                # can empty the hopper, so finish with whatever the sensor
                # reads rather than burning HOPPER_DUMP_TIMEOUT waiting for
                # a mechanism that does not exist.
                self._finish_dump()
                return

        self._dump_timer += dt
        valid, level, current_mass = self._read_fill()

        self._progress = 0.95 + 0.05 * min(
            self._dump_timer / self.HOPPER_DUMP_TIMEOUT, 1.0
        )

        emptied = valid and level <= self.EMPTY_THRESHOLD
        if emptied or self._dump_timer >= self.HOPPER_DUMP_TIMEOUT:
            self._finish_dump()

    def _finish_dump(self) -> None:
        """Stop the transfer, read the residual mass, publish the result."""
        try:
            self._hal.get_actuator("hopper").cancel_transfer()
        except (KeyError, AttributeError):
            pass

        _valid, _level, self._residual_mass_kg = self._read_fill()

        self._result = ExcavateResult(
            position=self._end_position,
            extracted_kg=self._extracted_kg,
            hopper_full=self._hopper_full,
            deposit_exhausted=self._deposit_exhausted,
            timestamp=time.time(),
            residual_mass_kg=self._residual_mass_kg,
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
                self._hal.get_actuator("hopper").cancel_transfer()
            except (KeyError, AttributeError):
                pass
            try:
                self._hal.get_actuator("drive").stop()
            except (KeyError, AttributeError):
                pass
        if self._navigator:
            self._navigator.stop()
        self._state = SkillState.ABORTED
