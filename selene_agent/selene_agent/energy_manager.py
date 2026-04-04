"""Energy tracking and budget decisions for SELENE agents.

Pure Python -- zero ROS dependencies.  Wraps a HAL BatteryInterface
to provide higher-level affordability checks and range estimation.
"""

from __future__ import annotations

import math
from typing import Optional

from selene_hal.battery_interface import BatteryInterface
from selene_hal.data_types import BatteryState


# Default assumed locomotion speed when computing energy costs (m/s).
_DEFAULT_SPEED = 0.3

# Safety margin multiplier applied to total mission energy budget.
_SAFETY_MARGIN = 1.10  # 10%


class EnergyManager:
    """Energy bookkeeper for a single lunar robot.

    Parameters
    ----------
    battery:
        HAL battery interface providing raw state and power parameters.
    critical_threshold:
        Charge fraction at or below which ENERGY_CRITICAL fires.
    recharge_target:
        Charge fraction at or above which the robot is "fully charged".
    recharge_station:
        (x, y) coordinates of the recharge station on the surface.
    """

    def __init__(
        self,
        battery: BatteryInterface,
        critical_threshold: float = 0.15,
        recharge_target: float = 0.90,
        recharge_station: tuple[float, float] = (40.0, 40.0),
    ):
        self._battery = battery
        self._critical_threshold = critical_threshold
        self._recharge_target = recharge_target
        self._recharge_station = recharge_station
        self._cached_state: Optional[BatteryState] = None

    # -- State updates --------------------------------------------------------

    def update(self, state: BatteryState) -> None:
        """Cache the latest battery state snapshot."""
        self._cached_state = state

    # -- Queries --------------------------------------------------------------

    def _current_state(self) -> BatteryState:
        """Return cached state, falling back to a live read."""
        if self._cached_state is not None:
            return self._cached_state
        return self._battery.get_state()

    def is_critical(self) -> bool:
        """True when charge fraction is at or below the critical threshold."""
        return self._current_state().charge_fraction <= self._critical_threshold

    def is_fully_charged(self) -> bool:
        """True when charge fraction is at or above the recharge target."""
        return self._current_state().charge_fraction >= self._recharge_target

    def get_charge_fraction(self) -> float:
        """Return current charge as a 0-1 fraction."""
        return self._current_state().charge_fraction

    def get_remaining_wh(self) -> float:
        """Return remaining energy in watt-hours."""
        return self._current_state().remaining_wh

    def estimate_range_m(self, speed: float = _DEFAULT_SPEED) -> float:
        """Estimated remaining travel range in meters at *speed*."""
        return self._battery.estimate_range_m(speed)

    # -- Budget checks --------------------------------------------------------

    def compute_energy_cost_wh(
        self,
        distance_m: float,
        task_energy_wh: float = 0.0,
    ) -> float:
        """Compute total energy cost for travelling *distance_m* and performing a task.

        Energy model:
            travel_time_s  = distance_m / speed
            locomotion_wh  = locomotion_draw_w * speed * travel_time_s / 3600
            idle_wh        = idle_draw_w * travel_time_s / 3600
            total          = locomotion_wh + idle_wh + task_energy_wh
        """
        speed = _DEFAULT_SPEED
        if speed <= 0:
            return task_energy_wh

        travel_time_s = distance_m / speed
        locomotion_wh = (
            self._battery.get_locomotion_draw_w() * speed * travel_time_s / 3600.0
        )
        idle_wh = self._battery.get_idle_draw_w() * travel_time_s / 3600.0
        return locomotion_wh + idle_wh + task_energy_wh

    def can_afford_task(
        self,
        current_position: tuple[float, float],
        task_position: tuple[float, float],
        task_energy_wh: float = 0.0,
    ) -> bool:
        """Return True if the robot can go to the task, do it, and return to base.

        Budget:
            go_distance   = ||current_position - task_position||
            return_dist   = ||task_position - recharge_station||
            total_energy  = cost(go_distance + return_dist, task_energy) * 1.10
        """
        go_dist = _euclidean(current_position, task_position)
        return_dist = _euclidean(task_position, self._recharge_station)
        total_distance = go_dist + return_dist
        cost = self.compute_energy_cost_wh(total_distance, task_energy_wh)
        budget = cost * _SAFETY_MARGIN
        return self.get_remaining_wh() >= budget

    def get_distance_to_base(
        self, current_position: tuple[float, float]
    ) -> float:
        """Euclidean distance from *current_position* to the recharge station."""
        return _euclidean(current_position, self._recharge_station)


# -- Helpers ------------------------------------------------------------------


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    """2D Euclidean distance."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)
