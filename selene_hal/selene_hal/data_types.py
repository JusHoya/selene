"""Data types for the SELENE Hardware Abstraction Layer.

Frozen dataclasses used as return types for sensor readings,
battery state, and actuator state. Immutable to prevent mutation bugs.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np


class SensorType(str, Enum):
    SCALAR_FIELD = "scalar_field"
    DEPTH_IMAGE = "depth_image"
    IMU = "imu"
    FILL_LEVEL = "fill_level"
    ODOMETRY = "odometry"


class ActuatorType(str, Enum):
    DRIVE = "drive"
    DRILL = "drill"
    TRANSFER = "transfer"


@dataclass(frozen=True)
class Timestamp:
    sec: int = 0
    nanosec: int = 0


@dataclass(frozen=True)
class SensorReading:
    """Base class for all sensor readings."""
    timestamp: Timestamp = Timestamp()
    sensor_name: str = ""
    is_valid: bool = True


@dataclass(frozen=True)
class ScalarFieldReading(SensorReading):
    """Single scalar value (e.g., neutron spectrometer ice concentration wt%)."""
    value: float = 0.0
    uncertainty: float = 0.0


@dataclass(frozen=True)
class DepthImageReading(SensorReading):
    """Depth image from stereo camera."""
    image: Optional[np.ndarray] = None
    fov_deg: float = 0.0
    max_range: float = 0.0


@dataclass(frozen=True)
class IMUReading(SensorReading):
    """Orientation and acceleration from IMU."""
    orientation_quaternion: tuple = (0.0, 0.0, 0.0, 1.0)
    angular_velocity: tuple = (0.0, 0.0, 0.0)
    linear_acceleration: tuple = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class FillLevelReading(SensorReading):
    """Fill level as fraction 0.0-1.0 (hopper, transport bin)."""
    level: float = 0.0
    mass_kg: float = 0.0


@dataclass(frozen=True)
class OdometryReading(SensorReading):
    """Pose and velocity from wheel odometry."""
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    linear_velocity: float = 0.0
    angular_velocity: float = 0.0


@dataclass(frozen=True)
class BatteryState:
    timestamp: Timestamp = Timestamp()
    charge_fraction: float = 1.0
    voltage: float = 48.0
    current_draw: float = 0.0
    capacity_wh: float = 500.0
    remaining_wh: float = 500.0
    is_charging: bool = False


@dataclass(frozen=True)
class ActuatorState:
    timestamp: Timestamp = Timestamp()
    actuator_name: str = ""
    is_active: bool = False
    power_level: float = 0.0
    error_code: int = 0
