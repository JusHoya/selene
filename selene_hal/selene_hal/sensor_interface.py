"""Abstract sensor interfaces for the SELENE HAL.

Sensors operate in a non-blocking cached-read model: the HAL driver
receives data via ROS 2 subscriptions and caches the latest reading.
read() returns the most recent cached value.
"""

from abc import ABC, abstractmethod
from typing import Callable
from selene_hal.data_types import (
    SensorReading, ScalarFieldReading, DepthImageReading,
    IMUReading, FillLevelReading, OdometryReading, SensorType,
)


class SensorConfig:
    """Configuration for one sensor from RCDL.

    ``extra`` is an untyped kwargs bag holding whatever optional RCDL fields a
    backend chose to forward. Two of its keys are LOAD-BEARING -- a sensor that
    does not receive them still constructs, and still reads, but reports a
    value that is silently wrong rather than absent:

    ``noise_stddev``  From ``SensorDescriptor.noise_stddev``
                      (``selene_hal/config/scout.yaml:16``, 0.5 wt%). Read by
                      ``GazeboScalarFieldSensor`` and reported as
                      ``ScalarFieldReading.uncertainty``. Missing means 0.0,
                      which claims a noise-free instrument and collapses the
                      orchestrator's Bayesian map update to last-sample-wins.

    ``capacity_kg``   From ``SensorDescriptor.capacity_kg``
                      (``excavator.yaml:29`` hopper_fill 20,
                      ``hauler.yaml:29`` load_cell 50). Read by the fill-level
                      sensors and used for the ONLY fraction -> kilogram
                      conversion in the system:
                      ``FillLevelReading.mass_kg = level * capacity_kg``.
                      Missing means ``mass_kg`` is 0.0 forever, which is how
                      deviation D-06's "structurally zero numerator" arose.

    Both backends must forward both keys or a green stub-HAL test proves
    nothing about the Gazebo path.
    """

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
