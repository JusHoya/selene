"""Tests for stub HAL implementation."""

import os
from selene_hal.hal_factory import create_hal
from selene_hal.data_types import ScalarFieldReading, BatteryState


def _get_config_path(filename):
    return os.path.join(
        os.path.dirname(__file__), '..', 'config', filename)


def test_stub_sensor_read():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    sensor = hal.get_sensor('neutron_spectrometer')
    reading = sensor.read()
    assert isinstance(reading, ScalarFieldReading)
    assert reading.is_valid


def test_stub_battery():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    battery = hal.get_battery()
    state = battery.get_state()
    assert isinstance(state, BatteryState)
    assert state.capacity_wh == 500.0
    assert state.remaining_wh == 500.0


def test_stub_kinematics():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    kin = hal.get_kinematics()
    assert kin.get_max_speed() == 0.5
    assert kin.can_point_turn()


def test_stub_drive_actuator():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    drive = hal.get_actuator('drive')
    drive.command_velocity(0.5, 0.0)  # should not raise
    drive.stop()


def test_stub_range_estimate():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    battery = hal.get_battery()
    range_m = battery.estimate_range_m(0.5)
    assert range_m > 0
