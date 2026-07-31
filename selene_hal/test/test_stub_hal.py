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
    assert state.capacity_wh == 50.0
    assert state.remaining_wh == 50.0


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


def test_stub_transfer_actuator_records_the_authorised_bound():
    """The bound must survive the whole call chain, not just the ABC signature.

    ``TaskAssignment.quantity_kg`` is the mass the orchestrator's ledger says a
    site actually holds. It reaches the simulation only if the skill passes it
    to ``trigger_load``, so recording it here is what lets a skill test assert
    the number arrived rather than assert that a method exists.
    """
    hal = create_hal(_get_config_path('hauler.yaml'), 'hauler_01', backend='stub')
    bin_actuator = hal.get_actuator('transport_bin')

    assert bin_actuator.load_call_count == 0
    assert bin_actuator.last_max_kg == -1.0

    bin_actuator.trigger_load(max_kg=12.0)

    assert bin_actuator.load_call_count == 1
    assert bin_actuator.last_max_kg == 12.0


def test_stub_transfer_actuator_defaults_to_unbounded():
    """A caller that passes nothing still means "fill to capacity"."""
    hal = create_hal(_get_config_path('hauler.yaml'), 'hauler_01', backend='stub')
    bin_actuator = hal.get_actuator('transport_bin')

    bin_actuator.trigger_load()

    assert bin_actuator.load_call_count == 1
    assert bin_actuator.last_max_kg < 0.0
