"""Gazebo HAL implementation placeholder -- Phase 2."""

from selene_hal.hal_interface import HalInterface


class GazeboHal(HalInterface):
    """Gazebo Harmonic HAL driver. Implemented in Phase 2."""

    def __init__(self, **kwargs):
        raise NotImplementedError("GazeboHal is a Phase 2 deliverable")

    def get_sensor(self, name):
        raise NotImplementedError

    def get_actuator(self, name):
        raise NotImplementedError

    def get_kinematics(self):
        raise NotImplementedError

    def get_battery(self):
        raise NotImplementedError

    def get_capabilities(self):
        raise NotImplementedError

    def list_sensors(self):
        raise NotImplementedError

    def list_actuators(self):
        raise NotImplementedError

    def shutdown(self):
        raise NotImplementedError
