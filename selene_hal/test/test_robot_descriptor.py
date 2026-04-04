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
    assert desc.battery.capacity == 500
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
