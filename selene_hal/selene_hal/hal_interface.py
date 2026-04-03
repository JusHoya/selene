"""Main HAL interface -- entry point for hardware abstraction."""

from abc import ABC, abstractmethod
from selene_hal.sensor_interface import SensorInterface
from selene_hal.actuator_interface import ActuatorInterface
from selene_hal.battery_interface import BatteryInterface
from selene_hal.kinematics_interface import KinematicsInterface


class HalInterface(ABC):
    """Main entry point for hardware abstraction.

    One instance per robot. Constructed from an RCDL RobotDescriptor.
    """

    @abstractmethod
    def get_sensor(self, name: str) -> SensorInterface:
        """Return sensor reader by RCDL name. Raises KeyError."""
        ...

    @abstractmethod
    def get_actuator(self, name: str) -> ActuatorInterface:
        """Return actuator commander by RCDL name. Raises KeyError."""
        ...

    @abstractmethod
    def get_kinematics(self) -> KinematicsInterface:
        ...

    @abstractmethod
    def get_battery(self) -> BatteryInterface:
        ...

    @abstractmethod
    def get_capabilities(self) -> list:
        ...

    @abstractmethod
    def list_sensors(self) -> list:
        ...

    @abstractmethod
    def list_actuators(self) -> list:
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Release all hardware resources."""
        ...
