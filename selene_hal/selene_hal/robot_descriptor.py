"""RCDL (Robot Capability Descriptor Language) parser and validator.

Uses Pydantic v2 models for YAML schema validation.
"""

from __future__ import annotations
from pathlib import Path
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml


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


class BatteryDescriptor(BaseModel):
    capacity: float = Field(gt=0, description="Battery capacity in Wh")
    idle_draw: float = Field(ge=0, description="Idle power in W")
    locomotion_draw: float = Field(ge=0, description="Locomotion power in W per m/s")


class SensorDescriptor(BaseModel):
    name: str = Field(min_length=1)
    type: SensorType
    topic: str = Field(min_length=1)
    frame: str = Field(default="base_link")
    power_draw: float = Field(ge=0, default=0.0)
    range: Optional[float] = Field(default=None, ge=0)
    noise_stddev: Optional[float] = Field(default=None, ge=0)
    fov: Optional[float] = Field(default=None, gt=0, le=360)
    resolution: Optional[list[int]] = Field(default=None)
    update_rate: Optional[float] = Field(default=None, gt=0)
    capacity_kg: Optional[float] = Field(default=None, gt=0)


class ActuatorDescriptor(BaseModel):
    name: str = Field(min_length=1)
    type: ActuatorType
    topic: str = Field(min_length=1)
    frame: str = Field(default="base_link")
    power_draw: float = Field(ge=0, default=0.0)
    max_power: Optional[float] = Field(default=None, gt=0)
    capacity_kg: Optional[float] = Field(default=None, gt=0)
    transfer_rate: Optional[float] = Field(default=None, gt=0)


class RobotDescriptor(BaseModel):
    robot_type: str = Field(min_length=1)
    kinematic_model: str = Field(default="differential_drive")
    max_speed: float = Field(gt=0)
    turn_radius: float = Field(ge=0)
    mass: float = Field(gt=0)
    battery: BatteryDescriptor
    sensors: list[SensorDescriptor] = Field(default_factory=list)
    actuators: list[ActuatorDescriptor] = Field(default_factory=list)
    capabilities: list[str] = Field(min_length=1)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        valid = {"prospect", "excavate", "haul", "recharge", "relay"}
        for cap in v:
            if cap not in valid:
                raise ValueError(f"Unknown capability '{cap}'. Valid: {valid}")
        return v

    @model_validator(mode="after")
    def validate_unique_names(self) -> "RobotDescriptor":
        sensor_names = [s.name for s in self.sensors]
        if len(sensor_names) != len(set(sensor_names)):
            raise ValueError("Duplicate sensor names in RCDL")
        actuator_names = [a.name for a in self.actuators]
        if len(actuator_names) != len(set(actuator_names)):
            raise ValueError("Duplicate actuator names in RCDL")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RobotDescriptor":
        """Load and validate an RCDL YAML file."""
        path = Path(path)
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def get_sensor_descriptor(self, name: str) -> SensorDescriptor:
        for s in self.sensors:
            if s.name == name:
                return s
        raise KeyError(f"No sensor '{name}' in {self.robot_type}")

    def get_actuator_descriptor(self, name: str) -> ActuatorDescriptor:
        for a in self.actuators:
            if a.name == name:
                return a
        raise KeyError(f"No actuator '{name}' in {self.robot_type}")
