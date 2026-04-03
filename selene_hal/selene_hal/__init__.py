"""SELENE Hardware Abstraction Layer."""

from selene_hal.hal_interface import HalInterface
from selene_hal.hal_factory import create_hal, register_hal_backend
from selene_hal.robot_descriptor import RobotDescriptor
import selene_hal.stub_hal  # noqa: F401 — triggers backend registration

__all__ = ['HalInterface', 'create_hal', 'register_hal_backend', 'RobotDescriptor']
