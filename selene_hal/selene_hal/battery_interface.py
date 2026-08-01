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

    # ---- Health reporting, added 2026-08-01 closing D-42. ----
    #
    # NOT abstract, and given working defaults, so a backend that has no
    # concept of "a message arrived" (StubBattery integrates its own model and
    # is always authoritative about it) does not have to pretend otherwise.
    # GazeboBattery overrides all three with real measurements.
    #
    # These exist because D-42 asked for exactly this and the HAL could not
    # answer: an agent had no way to tell a full battery from a battery it had
    # never heard about, no way to notice that readings had stopped, and no way
    # to notice that something OTHER than its own simulator was asserting its
    # charge. See GazeboBattery for what the third one is defending against.

    def message_count(self) -> int:
        """Battery readings received, ever. A source that models rather than
        receives reports 1: it has an answer, and it did not come from a bus."""
        return 1

    def seconds_since_last_message(self) -> float | None:
        """Age of the newest reading, or None if none has ever arrived."""
        return 0.0

    def publisher_count(self) -> int:
        """Publishers asserting this robot's charge; -1 if unknowable.

        Anything other than 1 is a fault on a Gazebo-backed robot. A modelled
        source is its own single publisher.
        """
        return 1

    def estimate_range_m(self, speed: float) -> float:
        """Estimate remaining range in meters at given speed."""
        state = self.get_state()
        total_draw = self.get_idle_draw_w() + self.get_locomotion_draw_w() * abs(speed)
        if total_draw <= 0:
            return float('inf')
        hours_remaining = state.remaining_wh / total_draw
        return hours_remaining * abs(speed) * 3600.0
