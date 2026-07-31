"""The fraction -> kilogram contract, checked at the HAL boundary.

WHY THIS EXISTS
``FillLevelReading`` carries two numbers in two different units and exactly one
relationship between them: ``mass_kg = level * capacity_kg``, where
``capacity_kg`` comes from the sensor's own RCDL entry. Before 2026-07-30
NEITHER backend performed that multiplication -- ``StubFillLevelSensor.read``
returned an all-default reading and ``GazeboFillLevelSensor._cb`` set only
``level`` -- so ``mass_kg`` was 0.0 for every sensor in the system and
``ExcavateSkill`` computed its extracted mass as ``0.0 - 0.0``. That is the
numerator of the mission progress bar (deviation D-06).

These tests fail against the pre-2026-07-30 HAL: every assertion on ``mass_kg``
below would read 0.0.

The Gazebo half of the same arithmetic cannot be exercised on a Windows box
without ROS; it lives in ``test_gazebo_fill_level.py`` behind an importorskip.
"""

import os

import pytest
import yaml

from selene_hal.hal_factory import create_hal

CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'config')

# Every RCDL in the package. Named rather than globbed so a new robot type is a
# deliberate addition to this list, not an invisible one.
RCDL_FILES = ('scout.yaml', 'excavator.yaml', 'hauler.yaml')


def _config_path(filename):
    return os.path.join(CONFIG_DIR, filename)


def _stub_hal(filename, robot_id):
    return create_hal(_config_path(filename), robot_id, backend='stub')


def test_excavator_hopper_fraction_becomes_kilograms():
    """0.95 of a 20 kg hopper is 19 kg -- the FILL_THRESHOLD case.

    ``ExcavateSkill.FILL_THRESHOLD`` is 0.95 and is compared against ``level``.
    Its meaning changed from "0.95 kg of 20" to "19 kg of 20" without the
    constant itself moving, which is only true if this conversion holds.
    """
    sensor = _stub_hal('excavator.yaml', 'excavator_01').get_sensor('hopper_fill')

    sensor.set_level(0.95)
    reading = sensor.read()

    assert reading.level == pytest.approx(0.95)
    assert reading.mass_kg == pytest.approx(19.0)
    assert reading.is_valid


def test_hauler_load_cell_fraction_becomes_kilograms():
    """Half of a 50 kg transport bin is 25 kg."""
    sensor = _stub_hal('hauler.yaml', 'hauler_01').get_sensor('load_cell')

    sensor.set_level(0.5)
    reading = sensor.read()

    assert reading.level == pytest.approx(0.5)
    assert reading.mass_kg == pytest.approx(25.0)


def test_empty_container_reports_zero_mass():
    sensor = _stub_hal('excavator.yaml', 'excavator_01').get_sensor('hopper_fill')

    reading = sensor.read()

    assert reading.level == 0.0
    assert reading.mass_kg == 0.0


def test_full_container_reports_the_rcdl_capacity():
    sensor = _stub_hal('hauler.yaml', 'hauler_01').get_sensor('load_cell')

    sensor.set_level(1.0)

    assert sensor.read().mass_kg == pytest.approx(50.0)


def test_level_is_clamped_to_the_wire_range():
    """The published quantity is 0.0-1.0; a stub must not accept more."""
    sensor = _stub_hal('excavator.yaml', 'excavator_01').get_sensor('hopper_fill')

    sensor.set_level(1.7)
    assert sensor.read().level == 1.0
    assert sensor.read().mass_kg == pytest.approx(20.0)

    sensor.set_level(-0.3)
    assert sensor.read().level == 0.0
    assert sensor.read().mass_kg == 0.0


def test_mass_is_a_delta_across_two_readings():
    """The pattern the skills actually use, end to end.

    ``ExcavateSkill`` records ``mass_kg`` before drilling and subtracts it from
    the reading at hopper-full. That difference is what reaches the
    orchestrator's ledger, so it is the thing worth pinning.
    """
    sensor = _stub_hal('excavator.yaml', 'excavator_01').get_sensor('hopper_fill')

    sensor.set_level(0.10)
    initial = sensor.read().mass_kg
    sensor.set_level(0.95)
    final = sensor.read().mass_kg

    assert final - initial == pytest.approx(17.0)


def test_no_declared_capacity_reports_zero_not_a_guess():
    """A sensor with no RCDL capacity must report 0.0 kg, never an invented one.

    Shipped configs never hit this path -- ``test_every_fill_level_sensor_
    declares_capacity`` below keeps it unreachable -- but the failure mode
    matters: a guessed capacity fabricates masses the orchestrator's ledger
    would treat as measurements, whereas a zero is visible as "nothing was
    extracted".
    """
    from selene_hal.data_types import SensorType
    from selene_hal.sensor_interface import SensorConfig
    from selene_hal.stub_hal import StubFillLevelSensor

    sensor = StubFillLevelSensor(SensorConfig(
        name='hopper_fill', sensor_type=SensorType.FILL_LEVEL,
        topic='/excavator_01/sensors/hopper_fill',
    ))
    sensor.set_level(0.95)

    assert sensor.read().level == pytest.approx(0.95)
    assert sensor.read().mass_kg == 0.0


def test_every_fill_level_sensor_declares_capacity():
    """No shipped RCDL may rely on the HAL's zero-capacity fallback.

    The fallback exists so a third-party descriptor degrades loudly instead of
    inventing kilograms. This asserts that no descriptor IN THIS REPOSITORY
    needs it, which is what keeps the warning path a genuine edge case rather
    than the normal one.
    """
    offenders = []
    checked = 0

    for filename in RCDL_FILES:
        with open(_config_path(filename), 'r') as f:
            rcdl = yaml.safe_load(f)
        for sensor in rcdl.get('sensors', []):
            if sensor.get('type') != 'fill_level':
                continue
            checked += 1
            capacity = sensor.get('capacity_kg')
            if not isinstance(capacity, (int, float)) or capacity <= 0:
                offenders.append(
                    f'{filename}: sensor {sensor.get("name")!r} declares '
                    f'capacity_kg={capacity!r}')

    assert not offenders, (
        'fill_level sensors without a usable capacity_kg:\n  '
        + '\n  '.join(offenders))
    # Guards against the loop silently checking nothing if a type spelling
    # changes: excavator hopper_fill and hauler load_cell are the two known.
    assert checked == 2, f'expected 2 fill_level sensors across RCDLs, found {checked}'
