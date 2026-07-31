"""The simulation's mass arithmetic, checked without Gazebo.

WHY THIS EXISTS
The hopper and the transport bin decide two things no other file can see: how
many kilograms they hold, and what fraction of capacity that is. That
arithmetic lived inside ``rclpy.Node`` subclasses, unreachable from any test on
a machine without ROS -- and it was wrong for two phases. Both nodes published
KILOGRAMS on topics the HAL reads as a 0.0-1.0 fraction, so a 20 kg hopper
crossed ``ExcavateSkill.FILL_THRESHOLD`` (0.95) at 0.95 kg and reported that as
a full load (deviation D-06).

WHAT IT ASSERTS
  * the fraction/kilogram identity holds at every step, for every operation
  * the fill timing the RCDL and BASE_EXTRACTION_RATE imply
  * both containers clamp at their capacity and at zero
  * ``load_toward`` honours an authorised bound below capacity -- the mechanism
    that stops a bin loading material no excavator extracted
  * the RCDL readers return the numbers the shipped configs declare, and RAISE
    rather than default when they cannot

WHAT IT CANNOT ASSERT
Nothing here runs against Gazebo. That an excavator physically sits over 10 wt%
ground long enough to fill, that the tick period is honoured under load, and
that 20 kg / 50 kg correspond to any geometry in ``models/*/model.sdf`` are all
unchecked. The timings below are arithmetic from the configuration, not
observations.
"""

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
# `python -m pytest selene_sim/test` puts the repo root on sys.path, where
# `selene_sim` is only a namespace directory; the importable package is one
# level down. Same construction as test_heightmap_datum.py.
sys.path.insert(0, _PKG)

from selene_sim.fill_model import (              # noqa: E402
    FillModel, PEAK_CONCENTRATION_WT, parse_transfer_command,
    read_fill_capacity_kg, read_transfer_rate,
)

_RCDL_DIR = os.path.join(_HERE, '..', '..', 'selene_hal', 'config')

EXCAVATOR_RCDL = os.path.join(_RCDL_DIR, 'excavator.yaml')
HAULER_RCDL = os.path.join(_RCDL_DIR, 'hauler.yaml')
SCOUT_RCDL = os.path.join(_RCDL_DIR, 'scout.yaml')


# ---------------------------------------------------------------------------
# FillModel
# ---------------------------------------------------------------------------

def test_new_model_is_empty():
    model = FillModel(capacity_kg=20.0)

    assert model.mass_kg == 0.0
    assert model.fraction == 0.0
    assert model.is_empty
    assert not model.is_full


def test_capacity_must_be_positive_and_finite():
    for bad in (0.0, -1.0, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            FillModel(capacity_kg=bad)


def test_fill_reaches_the_threshold_fraction_on_the_expected_schedule():
    """0.5 kg/s at 10 wt% into a 20 kg hopper: 19.0 kg / 0.95 after 38 s.

    ARITHMETIC, NOT AN OBSERVATION. 0.5 kg/s x 38 s = 19 kg, and 19/20 = 0.95,
    which is ``ExcavateSkill.FILL_THRESHOLD``. It is worth pinning because the
    threshold's MEANING changed with this work -- from 0.95 kg of 20 to 19 kg of
    20 -- without the constant itself moving.
    """
    model = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5)

    for _ in range(380):                      # 38 s at the nodes' 10 Hz tick
        model.fill(0.1, PEAK_CONCENTRATION_WT)

    assert model.mass_kg == pytest.approx(19.0)
    assert model.fraction == pytest.approx(0.95)


def test_fill_rate_scales_with_concentration():
    """Barren ground adds nothing; half the peak fills at half the rate."""
    barren = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5)
    half = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5)
    peak = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5)

    assert barren.fill(1.0, 0.0) == 0.0
    assert half.fill(1.0, PEAK_CONCENTRATION_WT / 2.0) == pytest.approx(0.25)
    assert peak.fill(1.0, PEAK_CONCENTRATION_WT) == pytest.approx(0.5)


def test_fill_clamps_at_capacity_and_reports_what_it_added():
    model = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5)
    model.set_mass(19.8)

    added = model.fill(10.0, PEAK_CONCENTRATION_WT)   # would be 5.0 kg unclamped

    assert added == pytest.approx(0.2)
    assert model.mass_kg == pytest.approx(20.0)
    assert model.fraction == 1.0
    assert model.is_full
    assert model.fill(10.0, PEAK_CONCENTRATION_WT) == 0.0


def test_drain_empties_at_the_rcdl_rate_and_reports_the_mass_removed():
    """The excavator hopper: 20 kg at 5 kg/s is 4 s of dumping."""
    model = FillModel(capacity_kg=20.0, transfer_rate_kg_s=5.0)
    model.set_mass(20.0)

    removed = sum(model.drain(0.1) for _ in range(40))

    assert removed == pytest.approx(20.0)
    assert model.mass_kg == pytest.approx(0.0)
    assert model.is_empty
    assert model.drain(1.0) == 0.0            # nothing left to move


def test_drain_never_goes_negative():
    model = FillModel(capacity_kg=20.0, transfer_rate_kg_s=5.0)
    model.set_mass(1.0)

    removed = model.drain(10.0)               # would be 50 kg unclamped

    assert removed == pytest.approx(1.0)
    assert model.mass_kg == 0.0


def test_load_toward_stops_at_the_authorised_mass():
    """The bound is what stops a bin loading material nobody extracted.

    ``bin_load_node`` used to fill to BIN_CAPACITY_KG on any bare "load",
    regardless of whether an excavator had produced anything -- 50 kg created
    from nothing, which breaks the conservation identity FR-ISRU-2 is accepted
    on.
    """
    model = FillModel(capacity_kg=50.0, transfer_rate_kg_s=10.0)

    for _ in range(100):                      # 10 s: unbounded this is 100 kg
        model.load_toward(0.1, 12.0)

    assert model.mass_kg == pytest.approx(12.0)
    assert model.fraction == pytest.approx(0.24)
    assert model.load_toward(0.1, 12.0) == 0.0


def test_load_toward_is_capped_by_capacity():
    model = FillModel(capacity_kg=50.0, transfer_rate_kg_s=10.0)

    for _ in range(100):
        model.load_toward(0.1, 900.0)

    assert model.mass_kg == pytest.approx(50.0)
    assert model.fraction == 1.0


def test_load_toward_below_current_mass_moves_nothing():
    """An absolute target, not an increment: it never removes material."""
    model = FillModel(capacity_kg=50.0, transfer_rate_kg_s=10.0)
    model.set_mass(30.0)

    assert model.load_toward(1.0, 12.0) == 0.0
    assert model.mass_kg == pytest.approx(30.0)


def test_set_mass_clamps_to_the_container():
    model = FillModel(capacity_kg=20.0)

    model.set_mass(999.0)
    assert model.mass_kg == 20.0

    model.set_mass(-5.0)
    assert model.mass_kg == 0.0


def test_fraction_times_capacity_is_mass_at_every_step():
    """The identity the whole units contract rests on, across a full cycle."""
    model = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5,
                      transfer_rate_kg_s=5.0)

    for _ in range(400):
        model.fill(0.1, PEAK_CONCENTRATION_WT)
        assert model.fraction * model.capacity_kg == pytest.approx(model.mass_kg)
        assert 0.0 <= model.fraction <= 1.0

    for _ in range(60):
        model.drain(0.1)
        assert model.fraction * model.capacity_kg == pytest.approx(model.mass_kg)
        assert 0.0 <= model.fraction <= 1.0

    assert model.is_empty


def test_zero_and_negative_dt_are_no_ops():
    model = FillModel(capacity_kg=20.0, fill_rate_kg_s=0.5,
                      transfer_rate_kg_s=5.0)
    model.set_mass(10.0)

    assert model.fill(0.0, PEAK_CONCENTRATION_WT) == 0.0
    assert model.fill(-1.0, PEAK_CONCENTRATION_WT) == 0.0
    assert model.drain(0.0) == 0.0
    assert model.load_toward(0.0, 20.0) == 0.0
    assert model.mass_kg == pytest.approx(10.0)


def test_a_model_with_no_rate_cannot_move_material():
    """Defaults are zero, so an unconfigured rate is inert rather than fast."""
    model = FillModel(capacity_kg=20.0)
    model.set_mass(10.0)

    assert model.fill(1.0, PEAK_CONCENTRATION_WT) == 0.0
    assert model.drain(1.0) == 0.0
    assert model.load_toward(1.0, 20.0) == 0.0


# ---------------------------------------------------------------------------
# parse_transfer_command -- the authorised-payload wire format
# ---------------------------------------------------------------------------

def test_bare_load_fills_to_capacity():
    """Backward compatibility: an unpatched publisher still works."""
    command = parse_transfer_command('load', 50.0)

    assert command.mode == 'loading'
    assert command.target_kg == 50.0
    assert command.error is None


def test_bounded_load_is_an_absolute_target():
    command = parse_transfer_command('load:12.500', 50.0)

    assert command.mode == 'loading'
    assert command.target_kg == pytest.approx(12.5)
    assert command.error is None


def test_bounded_load_is_capped_by_capacity():
    """A bin cannot be authorised to hold more than it holds."""
    command = parse_transfer_command('load:900', 50.0)

    assert command.mode == 'loading'
    assert command.target_kg == 50.0


def test_unload_and_stop_are_distinct_from_each_other():
    assert parse_transfer_command('unload', 50.0).mode == 'unloading'
    assert parse_transfer_command('stop', 50.0).mode == 'idle'


def test_commands_are_case_and_whitespace_insensitive():
    assert parse_transfer_command('  UNLOAD \n', 50.0).mode == 'unloading'
    assert parse_transfer_command('Load:3', 50.0).target_kg == pytest.approx(3.0)


@pytest.mark.parametrize('payload', [
    'load:abc', 'load:', 'load:-1', 'load:nan', 'lod', '', 'load 12',
])
def test_a_malformed_payload_is_rejected_not_treated_as_a_full_load(payload):
    """The single most important property in this file.

    Falling back to "fill to capacity" on a bad payload would re-create the
    fabricated 50 kg that ``bin_load_node`` produced on every bare load --
    material created from nothing, which is exactly what FR-ISRU-2's acceptance
    ("no material is lost or duplicated") forbids. A rejection is visible: it
    surfaces as a warning and a haul that fails at its load timeout.

    ``mode is None`` also means the node leaves any transfer already in
    progress alone, rather than aborting it on a garbled message.
    """
    command = parse_transfer_command(payload, 50.0)

    assert command.mode is None
    assert command.target_kg == 0.0
    assert command.error


def test_load_nan_does_not_slip_through_the_comparison():
    """NaN fails every ordinary >= check, so the guard is written negated."""
    command = parse_transfer_command('load:nan', 50.0)

    assert command.mode is None
    assert not math.isnan(command.target_kg)


def test_zero_authorised_mass_loads_nothing_rather_than_everything():
    """An honest zero: the ledger said this site holds nothing."""
    command = parse_transfer_command('load:0', 50.0)

    assert command.mode == 'loading'
    assert command.target_kg == 0.0
    assert command.error is None


def test_the_gazebo_hal_wire_format_round_trips():
    """``GazeboTransferActuator`` formats ``f"load:{max_kg:.3f}"``.

    Both halves of this contract are unit-tested, but in different packages and
    neither against a live DDS graph -- this pins the format they must agree
    on, from the parsing side, using the exact expression the HAL uses.
    """
    for max_kg in (0.0, 1.0, 12.5, 19.999, 49.9995):
        payload = f'load:{max_kg:.3f}'
        command = parse_transfer_command(payload, 50.0)
        assert command.mode == 'loading'
        assert command.target_kg == pytest.approx(round(max_kg, 3))


# ---------------------------------------------------------------------------
# RCDL readers -- the single source of truth for capacity and rate
# ---------------------------------------------------------------------------

def test_readers_return_the_shipped_rcdl_values():
    """These are the same numbers the HAL puts in SensorConfig.extra."""
    assert read_fill_capacity_kg(EXCAVATOR_RCDL, 'hopper_fill') == 20.0
    assert read_transfer_rate(EXCAVATOR_RCDL, 'hopper') == 5.0
    assert read_fill_capacity_kg(HAULER_RCDL, 'load_cell') == 50.0
    assert read_transfer_rate(HAULER_RCDL, 'transport_bin') == 10.0


def test_reader_raises_on_an_unknown_sensor_naming_the_file():
    with pytest.raises(ValueError) as excinfo:
        read_fill_capacity_kg(EXCAVATOR_RCDL, 'not_a_sensor')

    message = str(excinfo.value)
    assert 'not_a_sensor' in message
    assert 'excavator.yaml' in message


def test_reader_raises_when_the_key_is_absent():
    """A scout's neutron spectrometer declares no capacity, and must not get one."""
    with pytest.raises(ValueError) as excinfo:
        read_fill_capacity_kg(SCOUT_RCDL, 'neutron_spectrometer')

    assert 'capacity_kg' in str(excinfo.value)


def test_reader_raises_on_an_unknown_actuator():
    with pytest.raises(ValueError):
        read_transfer_rate(HAULER_RCDL, 'not_an_actuator')


def test_reader_raises_on_an_empty_path_rather_than_defaulting():
    """No default capacity anywhere: a missing rcdl_path must fail the node."""
    with pytest.raises(ValueError) as excinfo:
        read_fill_capacity_kg('', 'hopper_fill')

    assert 'rcdl_path' in str(excinfo.value)


def test_reader_raises_on_a_non_positive_capacity(tmp_path):
    rcdl = tmp_path / 'broken.yaml'
    rcdl.write_text(
        'sensors:\n'
        '  - name: hopper_fill\n'
        '    type: fill_level\n'
        '    capacity_kg: 0\n'
    )

    with pytest.raises(ValueError) as excinfo:
        read_fill_capacity_kg(str(rcdl), 'hopper_fill')

    assert 'capacity_kg' in str(excinfo.value)


def test_reader_raises_on_a_non_numeric_capacity(tmp_path):
    rcdl = tmp_path / 'broken.yaml'
    rcdl.write_text(
        'sensors:\n'
        '  - name: hopper_fill\n'
        '    type: fill_level\n'
        '    capacity_kg: twenty\n'
    )

    with pytest.raises(ValueError):
        read_fill_capacity_kg(str(rcdl), 'hopper_fill')


def test_the_two_readers_agree_with_the_hal_on_capacity():
    """One capacity per container in the whole system, read two ways.

    The sim reads the RCDL with yaml.safe_load; the HAL reads the same file
    through Pydantic and hands it to the sensor. If those ever disagree the sim
    publishes a fraction of one capacity and the HAL multiplies by another,
    with no error anywhere -- so the agreement is asserted, not assumed.

    SKIPPED unless selene_hal is importable, which on a bare checkout means
    running with it on PYTHONPATH; under colcon it always is. The skip is
    deliberate: selene_sim must not gain a build-time dependency on the HAL
    just to keep this cross-check.
    """
    robot_descriptor = pytest.importorskip(
        'selene_hal.robot_descriptor',
        reason='selene_hal is not on the path in this lane',
    )

    for rcdl_path, sensor_name in ((EXCAVATOR_RCDL, 'hopper_fill'),
                                   (HAULER_RCDL, 'load_cell')):
        descriptor = robot_descriptor.RobotDescriptor.from_yaml(rcdl_path)
        hal_capacity = descriptor.get_sensor_descriptor(sensor_name).capacity_kg
        assert math.isclose(read_fill_capacity_kg(rcdl_path, sensor_name),
                            float(hal_capacity))
