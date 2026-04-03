"""Abstract sensor interfaces for the SELENE HAL.

Sensors operate in a non-blocking cached-read model: the HAL driver
receives data via ROS 2 subscriptions and caches the latest reading.
read() returns the most recent cached value.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from selene_hal.data_types import (
    SensorReading, ScalarFieldReading, DepthImageReading,
    IMUReading, FillLevelReading, OdometryReading, SensorType,
)


class SensorConfig:
    """Configuration for one sensor from RCDL."""

    def __init__(self, name: str, sensor_type: SensorType, topic: str,
                 power_draw: float = 0.0, **kwargs):
        self.name = name
        self.sensor_type = sensor_type
        self.topic = topic
        self.power_draw = power_draw
        self.extra = kwargs


class SensorInterface(ABC):
    """Abstract sensor reader."""

    @abstractmethod
    def read(self) -> SensorReading:
        """Return the most recent sensor reading (non-blocking)."""
        ...

    @abstractmethod
    def get_config(self) -> SensorConfig:
        """Return the RCDL-declared configuration."""
        ...

    @abstractmethod
    def is_active(self) -> bool:
        """Whether the sensor is currently powered on."""
        ...

    @abstractmethod
    def activate(self) -> None:
        """Power on the sensor."""
        ...

    @abstractmethod
    def deactivate(self) -> None:
        """Power off the sensor."""
        ...

    def register_callback(
        self, callback: Callable[[SensorReading], None]
    ) -> None:
        """Register a callback invoked on each new reading (optional)."""
        pass


class ScalarFieldSensor(SensorInterface):
    """Sensor returning a single scalar value with uncertainty."""

    @abstractmethod
    def read(self) -> ScalarFieldReading:
        ...


class DepthImageSensor(SensorInterface):
    """Sensor returning a depth image."""

    @abstractmethod
    def read(self) -> DepthImageReading:
        ...


class IMUSensor(SensorInterface):
    """Inertial measurement unit."""

    @abstractmethod
    def read(self) -> IMUReading:
        ...


class FillLevelSensor(SensorInterface):
    """Fill level sensor (hopper/bin)."""

    @abstractmethod
    def read(self) -> FillLevelReading:
        ...


class OdometrySensor(SensorInterface):
    """Wheel odometry sensor."""

    @abstractmethod
    def read(self) -> OdometryReading:
        ...
