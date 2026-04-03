"""Tests for HAL factory."""

import os
from selene_hal.hal_factory import create_hal


def _get_config_path(filename):
    return os.path.join(
        os.path.dirname(__file__), '..', 'config', filename)


def test_create_stub_hal_scout():
    hal = create_hal(_get_config_path('scout.yaml'), 'scout_01', backend='stub')
    assert 'prospect' in hal.get_capabilities()
    assert 'neutron_spectrometer' in hal.list_sensors()
    assert 'drive' in hal.list_actuators()


def test_create_stub_hal_excavator():
    hal = create_hal(_get_config_path('excavator.yaml'), 'excavator_01', backend='stub')
    assert 'excavate' in hal.get_capabilities()
    assert 'drill' in hal.list_actuators()


def test_create_stub_hal_hauler():
    hal = create_hal(_get_config_path('hauler.yaml'), 'hauler_01', backend='stub')
    assert 'haul' in hal.get_capabilities()
    assert 'transport_bin' in hal.list_actuators()
