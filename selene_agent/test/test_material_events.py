"""Unit tests for ``selene_agent.material_events``.

The module has zero rclpy / selene_msgs / selene_hal imports precisely so
that the id scheme and the validation rules behind every ``MaterialEvent``
the fleet publishes can be exercised without a ROS install -- the same split
``test_agent_operator_callback.py`` relies on for ``operator_command_logic``.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

# Make the agent package importable when running pytest from outside the repo.
_REPO_PKG_PARENT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..'),
)
if _REPO_PKG_PARENT not in sys.path:
    sys.path.insert(0, _REPO_PKG_PARENT)

from selene_agent.material_events import (  # noqa: E402
    MATERIAL_EVENT_TYPES,
    MaterialEventIdGenerator,
    build_material_event_fields,
)


# --- MaterialEventIdGenerator ---


def test_ids_are_unique_and_ordered():
    gen = MaterialEventIdGenerator('excavator_01', 1_700_000_000_000_000_000)
    ids = [gen.next() for _ in range(1000)]
    assert len(set(ids)) == 1000
    # The counter is zero-padded, so lexicographic order matches issue order
    # for the whole six-digit range. That is a readability property, not one
    # the orchestrator relies on -- it dedupes on equality only.
    assert ids == sorted(ids)
    assert gen.count == 1000


def test_id_format_is_robot_epoch_counter():
    gen = MaterialEventIdGenerator('hauler_02', 42)
    assert gen.next() == 'hauler_02:42:000001'
    assert gen.next() == 'hauler_02:42:000002'


def test_a_restart_produces_ids_disjoint_from_the_previous_run():
    """The epoch term is what makes an agent restart safe.

    Both generators start their counter at 1. Without the epoch in the id, a
    restarted agent would re-issue ':000001' on top of history a
    TRANSIENT_LOCAL subscriber may still hold, and the orchestrator's dedupe
    would discard the new event as a replay of the old one -- silently losing
    mass rather than double-counting it, but losing it all the same.
    """
    before = MaterialEventIdGenerator('excavator_01', 1_000)
    after = MaterialEventIdGenerator('excavator_01', 2_000)
    first_run = {before.next() for _ in range(50)}
    second_run = {after.next() for _ in range(50)}
    assert first_run.isdisjoint(second_run)


def test_two_robots_never_collide():
    a = MaterialEventIdGenerator('excavator_01', 7)
    b = MaterialEventIdGenerator('excavator_02', 7)
    assert {a.next() for _ in range(20)}.isdisjoint({b.next() for _ in range(20)})


def test_ids_stay_unique_past_the_padding_width():
    """Six digits is presentation, not a modulus."""
    gen = MaterialEventIdGenerator('scout_01', 1)
    gen._counter = 999_998
    assert gen.next().endswith(':999999')
    assert gen.next().endswith(':1000000')


# --- build_material_event_fields ---


def _fields(**overrides):
    kwargs = dict(
        event_id='excavator_01:1:000001',
        robot_id='excavator_01',
        task_id='excavate_ab12',
        event_type='extracted',
        mass_kg=19.0,
        residual_mass_kg=0.0,
    )
    kwargs.update(overrides)
    return build_material_event_fields(**kwargs)


def test_every_declared_event_type_is_accepted():
    assert MATERIAL_EVENT_TYPES == ('extracted', 'loaded', 'unloaded')
    for event_type in MATERIAL_EVENT_TYPES:
        assert _fields(event_type=event_type)['event_type'] == event_type


def test_returns_every_material_event_field_except_stamp():
    """The node supplies `stamp`; everything else is decided here."""
    assert set(_fields()) == {
        'event_id', 'robot_id', 'task_id', 'event_type',
        'mass_kg', 'residual_mass_kg',
    }


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        _fields(event_type='delivered')
    assert 'delivered' in str(excinfo.value)


def test_negative_mass_is_clamped_to_zero():
    """MaterialEvent.mass_kg is documented on the wire as >= 0.

    A small negative delta is the expected shape of sensor noise around an
    empty bin. A large one is a fault, and clamping hides it -- the
    residual_mass_kg cross-check on the orchestrator side is what stays able
    to see that.
    """
    out = _fields(mass_kg=-0.004, residual_mass_kg=-1.0)
    assert out['mass_kg'] == 0.0
    assert out['residual_mass_kg'] == 0.0


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_non_finite_mass_is_rejected_not_clamped(bad):
    """The reason this raises instead of clamping.

    ``max(0.0, float('nan'))`` evaluates to ``0.0`` in Python -- every
    comparison against NaN is False, so ``max`` returns its first argument. A
    clamp written the obvious way would therefore turn "this sensor was never
    read" into "this transfer moved zero kilograms", which is a fabricated
    measurement in a ledger whose whole acceptance criterion is that no mass
    is lost or duplicated.
    """
    assert max(0.0, float('nan')) == 0.0  # the trap this guards, made explicit

    with pytest.raises(ValueError):
        _fields(mass_kg=bad)
    with pytest.raises(ValueError):
        _fields(residual_mass_kg=bad)


def test_values_are_coerced_to_str_and_float():
    out = _fields(mass_kg=19, residual_mass_kg=0)
    assert isinstance(out['mass_kg'], float)
    assert isinstance(out['residual_mass_kg'], float)
    assert all(isinstance(out[k], str) for k in
               ('event_id', 'robot_id', 'task_id', 'event_type'))
    assert math.isfinite(out['mass_kg'])
