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
    """Hopper / transport-bin fill, carrying both units with one conversion.

    ``level``   -- dimensionless fraction 0.0-1.0 of that sensor's RCDL
                   ``capacity_kg``. This is the quantity that travels on the
                   wire: the simulation publishes it raw as a
                   ``std_msgs/Float32`` on ``/{robot_id}/{sensor topic}`` and
                   the HAL stores it verbatim. It is what
                   ``ExcavateSkill.FILL_THRESHOLD`` (0.95) and
                   ``HaulSkill``'s empty threshold are compared against.

    ``mass_kg`` -- kilograms, DERIVED BY THE HAL as ``level * capacity_kg``.
                   ``capacity_kg`` comes from the sensor's own RCDL entry
                   (``selene_hal/config/excavator.yaml:29`` hopper_fill 20 kg,
                   ``hauler.yaml:29`` load_cell 50 kg) and reaches the sensor
                   through ``SensorConfig.extra['capacity_kg']``. It is never
                   on the wire and is never recomputed downstream: everything
                   above the HAL treats it as a measurement.

    A sensor whose RCDL declares no usable ``capacity_kg`` warns loudly at
    construction and reports ``mass_kg = 0.0`` for the life of the process --
    the same "loud zero" convention ``_resolve_noise_stddev`` already uses for
    scalar fields (``gazebo_hal.py``).

    WHY THIS DOCSTRING IS EMPHATIC. Until 2026-07-30 it read only "Fill level
    as fraction 0.0-1.0", and that single line was the *only* place the
    contract was written down. Both simulation nodes published KILOGRAMS into
    ``level`` for two phases -- so an excavator with a 20 kg hopper reported
    "full" at 0.95 kg, and no HAL populated ``mass_kg`` at all, which is why
    ``excavate.py`` computed its extracted mass as ``0.0 - 0.0``. See
    ``docs/phase5_deviation_register.md`` D-06.
    """
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

    # ---- Added 2026-08-01 closing D-42. ----
    #
    # True iff ``charge_fraction`` above came from a battery message this HAL has
    # ACTUALLY RECEIVED. Before the first message, ``GazeboBattery`` constructs
    # its cache from the RCDL capacity and reports a confident 100% -- so an
    # agent could not distinguish "the battery is full" from "no data has ever
    # arrived", and there was no way for it to say which it was looking at.
    #
    # THE DEFAULT IS TRUE, DELIBERATELY, and this is the same decision
    # ``SensorReading.is_valid`` made at :39. A dataclass default of False would
    # make every ``BatteryState()`` in a test or a stub silently invalid and the
    # agent would refuse to act on a battery that is fine. The fail-safe lives at
    # the ONE construction site that means "I have nothing" --
    # ``GazeboBattery.__init__`` -- which passes ``is_valid=False`` explicitly.
    # Contrast RobotState.pose_valid (D-31), which is a ROS message field where
    # the language default IS false and a partially rebuilt workspace therefore
    # reports "no fix"; this is a Python dataclass inside one process, both
    # producer and consumer move together, and that exposure does not exist here.
    #
    # ``charge_fraction`` IS STILL POPULATED when this is false. The flag carries
    # the meaning, not the value -- same contract as pose_valid.
    is_valid: bool = True


@dataclass(frozen=True)
class ActuatorState:
    timestamp: Timestamp = Timestamp()
    actuator_name: str = ""
    is_active: bool = False
    power_level: float = 0.0
    error_code: int = 0
