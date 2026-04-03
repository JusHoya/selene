"""Abstract battery interface for the SELENE HAL."""

from abc import ABC, abstractmethod
from selene_hal.data_types import BatteryState


class BatteryInterface(ABC):
    """Battery state reader and energy estimator."""

    @abstractmethod
    def get_state(self) -> BatteryState:
        ...

    @abstractmethod
    def get_capacity_wh(self) -> float:
        ...

    @abstractmethod
    def get_idle_draw_w(self) -> float:
        ...

    @abstractmethod
    def get_locomotion_draw_w(self) -> float:
        ...

    def estimate_range_m(self, speed: float) -> float:
        """Estimate remaining range in meters at given speed."""
        state = self.get_state()
        total_draw = self.get_idle_draw_w() + self.get_locomotion_draw_w() * abs(speed)
        if total_draw <= 0:
            return float('inf')
        hours_remaining = state.remaining_wh / total_draw
        return hours_remaining * abs(speed) * 3600.0
