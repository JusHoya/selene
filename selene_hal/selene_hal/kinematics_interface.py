"""Abstract kinematics interface for the SELENE HAL."""

from abc import ABC, abstractmethod


class KinematicsInterface(ABC):
    """Motion constraints from RCDL kinematic properties."""

    @abstractmethod
    def get_max_speed(self) -> float:
        ...

    @abstractmethod
    def get_turn_radius(self) -> float:
        ...

    @abstractmethod
    def get_kinematic_model(self) -> str:
        ...

    @abstractmethod
    def get_mass(self) -> float:
        ...

    def can_point_turn(self) -> bool:
        return self.get_turn_radius() == 0.0
