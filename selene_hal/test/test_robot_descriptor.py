"""Tests for RCDL loading and validation."""

import os
import pytest
from selene_hal.robot_descriptor import RobotDescriptor


def _get_config_path(filename):
    """Get path to config file relative to this test."""
    return os.path.join(
        os.path.dirname(__file__), '..', 'config', filename)


def test_load_scout_rcdl():
    desc = RobotDescriptor.from_yaml(_get_config_path('scout.yaml'))
    assert desc.robot_type == 'scout'
    assert desc.max_speed == 0.5
    assert desc.mass == 50
    assert desc.battery.capacity == 50
    assert len(desc.sensors) == 4
    assert len(desc.actuators) == 0
    assert 'prospect' in desc.capabilities


def test_load_excavator_rcdl():
    desc = RobotDescriptor.from_yaml(_get_config_path('excavator.yaml'))
    assert desc.robot_type == 'excavator'
    assert desc.max_speed == 0.3
    assert len(desc.actuators) == 2
    assert 'excavate' in desc.capabilities


def test_load_hauler_rcdl():
    desc = RobotDescriptor.from_yaml(_get_config_path('hauler.yaml'))
    assert desc.robot_type == 'hauler'
    assert desc.max_speed == 0.4
    assert 'haul' in desc.capabilities


def test_sensor_lookup():
    desc = RobotDescriptor.from_yaml(_get_config_path('scout.yaml'))
    sensor = desc.get_sensor_descriptor('neutron_spectrometer')
    assert sensor.type.value == 'scalar_field'
    assert sensor.power_draw == 10


def test_sensor_lookup_missing():
    desc = RobotDescriptor.from_yaml(_get_config_path('scout.yaml'))
    with pytest.raises(KeyError):
        desc.get_sensor_descriptor('nonexistent')


def test_fill_level_sensors_surface_capacity_kg():
    """``capacity_kg`` must reach the HAL as a number, not be dropped by Pydantic.

    ``SensorDescriptor`` is the only route by which a capacity gets from the
    RCDL into ``SensorConfig.extra['capacity_kg']``, and from there into the
    single ``mass_kg = level * capacity_kg`` conversion in the system. A
    Pydantic model that discarded the key would leave both HAL backends
    reporting 0.0 kg with nothing failing anywhere -- which is deviation D-06
    exactly.
    """
    excavator = RobotDescriptor.from_yaml(_get_config_path('excavator.yaml'))
    hauler = RobotDescriptor.from_yaml(_get_config_path('hauler.yaml'))

    assert excavator.get_sensor_descriptor('hopper_fill').capacity_kg == 20
    assert hauler.get_sensor_descriptor('load_cell').capacity_kg == 50


def test_transfer_actuators_surface_transfer_rate():
    """The drain/load rate the sim nodes read out of the same file."""
    excavator = RobotDescriptor.from_yaml(_get_config_path('excavator.yaml'))
    hauler = RobotDescriptor.from_yaml(_get_config_path('hauler.yaml'))

    assert excavator.get_actuator_descriptor('hopper').transfer_rate == 5
    assert hauler.get_actuator_descriptor('transport_bin').transfer_rate == 10


def test_sensors_without_a_capacity_leave_it_none():
    """The optional field stays optional: a scout has no container."""
    scout = RobotDescriptor.from_yaml(_get_config_path('scout.yaml'))

    assert scout.get_sensor_descriptor('neutron_spectrometer').capacity_kg is None
