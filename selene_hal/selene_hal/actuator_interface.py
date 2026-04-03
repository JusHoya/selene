"""Abstract actuator interfaces for the SELENE HAL."""

from abc import ABC, abstractmethod
from selene_hal.data_types import ActuatorState, ActuatorType


class ActuatorConfig:
    """Configuration for one actuator from RCDL."""

    def __init__(self, name: str, actuator_type: ActuatorType, topic: str,
                 power_draw: float = 0.0, **kwargs):
        self.name = name
        self.actuator_type = actuator_type
        self.topic = topic
        self.power_draw = power_draw
        self.extra = kwargs


class ActuatorInterface(ABC):
    """Abstract actuator commander."""

    @abstractmethod
    def get_config(self) -> ActuatorConfig:
        ...

    @abstractmethod
    def get_state(self) -> ActuatorState:
        ...

    @abstractmethod
    def is_active(self) -> bool:
        ...

    @abstractmethod
    def activate(self) -> None:
        ...

    @abstractmethod
    def deactivate(self) -> None:
        ...


class DriveActuator(ActuatorInterface):
    """Differential drive actuator."""

    @abstractmethod
    def command_velocity(self, linear_x: float, angular_z: float) -> None:
        """Send velocity command (m/s, rad/s)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop the robot."""
        ...


class DrillActuator(ActuatorInterface):
    """Drill/heater actuator for excavation."""

    @abstractmethod
    def set_power_level(self, level: float) -> None:
        """Set drill power 0.0-1.0."""
        ...

    @abstractmethod
    def start_drilling(self) -> None:
        ...

    @abstractmethod
    def stop_drilling(self) -> None:
        ...

    @abstractmethod
    def is_drilling(self) -> bool:
        ...


class TransferActuator(ActuatorInterface):
    """Hopper/bin load/unload mechanism."""

    @abstractmethod
    def trigger_load(self) -> None:
        ...

    @abstractmethod
    def trigger_unload(self) -> None:
        ...

    @abstractmethod
    def is_transfer_complete(self) -> bool:
        ...

    @abstractmethod
    def cancel_transfer(self) -> None:
        ...
