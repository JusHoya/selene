"""The robot energy model, and the D-42 mechanism it produces.

The arithmetic in ``selene_sim/selene_sim/battery_model.py`` had NO TESTS OF ANY
KIND until 2026-08-01, while it lived inline in ``battery_node._update`` behind
that file's module-level ``import rclpy``. The only occurrence of
``battery_state`` under any ``test/`` directory was a string in an allow-list.
Register entry D-42 therefore had to re-derive this model by hand, twice, to
decide whether the simulator could have produced the ``0.0%`` a scout acted on.

WHAT EACH TEST BELOW IS FOR, since "the battery drains" is not worth pinning:

* The lower clamp returns **exactly** 0.0. D-42's whole signature is the literal
  ``Battery critical (0.0%)``, and every consumer downstream compares against
  0.15, so 0.0 and 1e-9 are indistinguishable to the system and completely
  different to a person trying to find out where a zero came from.
* Speed is an input that is never decayed, so a caller that stops updating it
  integrates a stale value forever. That is the mechanism, and it is the one
  behaviour here that reads like an oversight and is load-bearing.
* The numbers reproduce a LIVE MEASUREMENT rather than each other. An orphaned
  ``battery_scout_02`` was sampled every 30 s on 2026-08-01 with its simulator
  dead: 0.014165 of capacity per 30 s, i.e. 85.0 W. Two robots in the same
  measurement sat pinned at exactly 1.0.
* The bound that let D-42 rule the healthy node out is still true.
"""

import math

import pytest

from selene_sim.battery_model import (
    BatteryModel,
    MAX_SLOPE_FACTOR,
    MIN_SLOPE_FACTOR,
    is_in_psr,
    slope_factor,
)


# The PSR disc from selene_sim/config/world_params.yaml, checked against the
# file in test_psr_disc_matches_world_params rather than trusted.
PSR = [{'name': 'psr_alpha', 'type': 'circle',
        'center': [-100, -150], 'radius': 60}]

#: Inside the disc -- its centre.
IN_PSR = (-100.0, -150.0, 0.0)

#: Outside it -- the recharge pad, 86.0 m from the centre.
IN_SUN = (-30.0, -100.0, 0.0)

#: Scout parameters, from BatteryNode.ENERGY_PARAMS. Pinned against it below.
SCOUT = dict(capacity_wh=50.0, idle_draw_w=10.0,
             locomotion_draw_w_per_ms=150.0, solar_recharge_w=40.0)


def _scout(position, speed, **kw):
    model = BatteryModel(psr_zones=PSR, **{**SCOUT, **kw})
    model.last_position = position      # no first-step jump
    return model


def _run(model, position, speed, seconds, dt=0.1, actuator_draw_w=0.0):
    ticks = int(round(seconds / dt))
    last = None
    for _ in range(ticks):
        last = model.step(dt, speed, position, actuator_draw_w)
    return last


# ---------------------------------------------------------------------------
# The constants are the world's, not this file's
# ---------------------------------------------------------------------------

def test_psr_disc_matches_world_params():
    import os
    import yaml
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'config', 'world_params.yaml')) as handle:
        zones = yaml.safe_load(handle)['world']['psr_zones']
    assert zones[0]['center'] == PSR[0]['center']
    assert zones[0]['radius'] == PSR[0]['radius']
    assert is_in_psr(IN_PSR[0], IN_PSR[1], zones) is True
    assert is_in_psr(IN_SUN[0], IN_SUN[1], zones) is False


def test_scout_parameters_match_the_node():
    """This file's SCOUT dict is BatteryNode's, or the arithmetic is fiction.

    Read out of the source rather than imported, because importing
    ``battery_node`` needs ``rclpy`` and this lane does not have it -- which is
    the whole reason the model was extracted.
    """
    import ast
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, 'selene_sim', 'battery_node.py')
    with open(path) as handle:
        tree = ast.parse(handle.read())
    params = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', '') == 'ENERGY_PARAMS' for t in node.targets):
            params = ast.literal_eval(node.value)
    assert params is not None, 'ENERGY_PARAMS not found in battery_node.py'
    assert params['scout'] == SCOUT


# ---------------------------------------------------------------------------
# The clamp -- D-42's exact-zero signature
# ---------------------------------------------------------------------------

def test_drain_clamps_to_exactly_zero_never_negative():
    model = _scout(IN_PSR, 0.5, remaining_wh=0.001)
    tick = _run(model, IN_PSR, 0.5, seconds=0.5)

    assert model.remaining_wh == 0.0
    assert model.charge_fraction == 0.0
    assert tick.at_empty_clamp is True
    # Exactly the float. A reader chasing "Battery critical (0.0%)" through a
    # log needs to be able to rely on this being the clamp and not a residue.
    assert repr(model.charge_fraction) in ('0.0', '-0.0')


def test_a_clamped_battery_keeps_reporting_zero_indefinitely():
    """It does not recover, drift or wrap. It publishes 0.0 for as long as it runs.

    This is what makes an orphaned node dangerous rather than merely wrong: the
    zero is stable, so a consumer sampling it at any later moment sees the same
    confident value.
    """
    model = _scout(IN_PSR, 0.5, remaining_wh=0.0)
    for _ in range(600):
        model.step(0.1, 0.5, IN_PSR)
    assert model.charge_fraction == 0.0


def test_charge_clamps_to_capacity():
    model = _scout(IN_SUN, 0.0)
    _run(model, IN_SUN, 0.0, seconds=60)
    assert model.remaining_wh == model.capacity_wh
    assert model.charge_fraction == 1.0


# ---------------------------------------------------------------------------
# The latch -- how an orphaned node reaches the clamp
# ---------------------------------------------------------------------------

def test_speed_is_never_decayed_by_the_model():
    """Feed the same speed forever and it is integrated forever.

    ``battery_node._cmd_vel_callback`` assigns ``current_speed`` on message and
    nothing anywhere ages it out, so with the simulator gone this is exactly
    what the node does: integrate the last commanded speed indefinitely.
    """
    model = _scout(IN_PSR, 0.5)
    before = model.remaining_wh
    tick = _run(model, IN_PSR, 0.5, seconds=10.0)
    drawn_w = (before - model.remaining_wh) * 3600.0 / 10.0

    assert tick.slope_factor == 1.0          # stationary position => flat
    assert drawn_w == pytest.approx(85.0, abs=0.5)
    assert tick.power_w == pytest.approx(85.0, abs=1e-9)


def test_orphan_drain_reproduces_the_2026_08_01_live_measurement():
    """0.014165 of capacity per 30 s, measured on an orphaned battery_scout_02.

    The live sample: 0.88065 at t=0.28 s, 0.85237 at t=59.95 s, then a steady
    0.014165 per 30 s for the following 17 minutes. This asserts the shipped
    constants reproduce that, so the register's figure and the source are pinned
    to one another instead of merely not contradicting.
    """
    model = _scout(IN_PSR, 0.5)
    start = model.charge_fraction
    _run(model, IN_PSR, 0.5, seconds=30.0)
    assert (start - model.charge_fraction) == pytest.approx(0.014165, abs=2e-4)


def test_full_to_clamp_takes_about_35_minutes():
    """2118 s at 85 W from 50 Wh -- an unattended coffee break, not a long weekend.

    This is why nobody noticed: the failure needs half an hour of nothing
    happening, which is precisely the interval a forgotten stack occupies.
    """
    model = _scout(IN_PSR, 0.5)
    ticks = 0
    while model.remaining_wh > 0.0 and ticks < 200_000:
        model.step(0.1, 0.5, IN_PSR)
        ticks += 1
    assert model.remaining_wh == 0.0
    assert ticks * 0.1 == pytest.approx(50.0 / 85.0 * 3600.0, rel=0.02)


# ---------------------------------------------------------------------------
# The asymmetry -- why one robot and not the fleet
# ---------------------------------------------------------------------------

def test_a_robot_that_never_moved_stays_pinned_at_full():
    """Latched speed 0, outside the PSR: charging, so exactly 1.0.

    Measured on the same orphaned stack: excavator_01 and hauler_01 reported
    1.0 for the whole observation while both scouts drained. Neither had left
    IDLE, so neither had ever been sent a cmd_vel, and both spawned outside the
    disc. That is the answer to "why scout_02 and not the fleet", and it is a
    property of this model rather than of anything about scouts.
    """
    model = _scout(IN_SUN, 0.0)
    tick = _run(model, IN_SUN, 0.0, seconds=60.0)
    assert model.charge_fraction == 1.0
    assert tick.is_charging is True


def test_stationary_inside_the_psr_still_drains():
    """Not moving is not enough. A permanently shadowed region has no sun."""
    model = _scout(IN_PSR, 0.0)
    before = model.remaining_wh
    tick = _run(model, IN_PSR, 0.0, seconds=60.0)
    assert tick.is_charging is False
    drawn_w = (before - model.remaining_wh) * 3600.0 / 60.0
    assert drawn_w == pytest.approx(10.0, abs=0.2)      # idle only


def test_moving_in_sunlight_gets_no_solar():
    """Solar needs BOTH conditions; a driving robot in daylight still drains."""
    fast = _scout(IN_SUN, 0.5)
    tick = _run(fast, IN_SUN, 0.5, seconds=10.0)
    assert tick.is_charging is False
    assert tick.power_w == pytest.approx(85.0)


# ---------------------------------------------------------------------------
# The bound that ruled the healthy node out
# ---------------------------------------------------------------------------

def test_slope_factor_is_bounded():
    """1 + 2 sin(theta), floored -- so draw cannot run away on any geometry.

    This is the half of D-42's ruling that closes off "the healthy node
    overflowed to the clamp". Pinned so a future change to the slope law cannot
    quietly falsify a conclusion the register still cites.
    """
    for dz in (-1e9, -100.0, -1.0, 0.0, 1.0, 100.0, 1e9):
        for horiz in (0.0, 1e-4, 0.5, 10.0):
            f = slope_factor(dz, horiz)
            assert MIN_SLOPE_FACTOR <= f <= MAX_SLOPE_FACTOR + 1e-12, (dz, horiz)
    assert slope_factor(1.0, 1.0) == pytest.approx(1.0 + 2.0 * math.sin(math.pi / 4))
    assert slope_factor(0.0, 0.0005) == 1.0          # below the flat epsilon


def test_a_healthy_scout_cannot_reach_the_clamp_in_the_d42_window():
    """18.50 s of the worst modelled draw is under 5% of a scout, not 100%.

    D-42 ruled the healthy node out by this arithmetic before any instrumentation
    existed, and that ruling was correct: whatever delivered 0.0 to
    ``agent_scout_02`` 18.50 s after its battery node started, it was not this
    model running normally.
    """
    worst_w = (SCOUT['idle_draw_w']
               + SCOUT['locomotion_draw_w_per_ms'] * 0.5 * MAX_SLOPE_FACTOR
               + 200.0)                                  # drill, which a scout lacks
    assert worst_w == pytest.approx(435.0)

    model = _scout(IN_PSR, 0.5)
    _run(model, IN_PSR, 0.5, seconds=18.50, actuator_draw_w=200.0)
    assert model.charge_fraction > 0.95


def test_non_circular_psr_zones_are_ignored_not_guessed():
    """An unknown zone type must not silently become a disc."""
    zones = [{'type': 'polygon', 'center': [0, 0], 'radius': 1000}]
    assert is_in_psr(0.0, 0.0, zones) is False
    assert is_in_psr(0.0, 0.0, []) is False
    assert is_in_psr(0.0, 0.0, None) is False
