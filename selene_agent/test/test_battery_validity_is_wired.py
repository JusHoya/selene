"""The D-42 battery-validity gate, and a guard that it is still CALLED.

WHY THIS FILE EXISTS
--------------------
Register D-42: ``agent_scout_02`` acted on ``percentage = 0.0`` 6.152 s after
startup, three times, and took the 2026-08-01 exit gate's check 11 down with it.
The protection that was supposed to prevent this was a five-second wall-clock
grace period on the ENERGY_CRITICAL check, guarded by comments in two files
asserting that "the HAL reports a phantom 0%" before its first message.

**That mechanism never existed.** ``GazeboBattery.__init__`` has constructed its
cache from the RCDL capacity — i.e. FULL — since the class was first written,
``BatteryState.charge_fraction`` has defaulted to 1.0 since the dataclass was
defined, and ``StubBattery`` does the same. A HAL that has received nothing has
always reported 100%, never 0%. The grace period was protection against a
misremembered failure, and a clock cannot express the condition anyway: the
robot fired at 6.152 s, 1.15 s past a threshold chosen from n = 1.

What replaced it is two conditions that are about the DATA rather than the clock:

* ``BatteryState.is_valid`` — false until a message has actually been handled,
  so the agent can tell "full" from "no reading";
* ``AgentNode._battery_channel_attributable`` — false while the battery topic
  has more than one publisher, because ``GazeboBattery._cb`` caches whichever
  message arrived last with no notion of source.

THE GUARD AT THE BOTTOM IS THE POINT OF THIS FILE. This repository has been
bitten SIX times by code that is wired and never called, and the seventh
instance was found inside the exit-gate probe during this same work
(``battery_level`` recorded on every sample, read only by a ``[0, 1]`` range
assertion that ``0.0`` satisfies). A new flag that nothing consults would be the
eighth. ``test_energy_critical_branch_consults_both_gates`` AST-walks
``agent_node.py`` and fails if either condition stops guarding the
ENERGY_CRITICAL branch — including if someone "simplifies" it back to a clock.
"""

import ast
import os

import pytest

from selene_hal.data_types import BatteryState
from selene_agent.energy_manager import EnergyManager


class _FakeBattery:
    """Minimal BatteryInterface. Defaults come from BatteryInterface itself."""

    def __init__(self, state=None, publishers=1):
        self._state = state if state is not None else BatteryState()
        self._publishers = publishers

    def get_state(self):
        return self._state

    def get_capacity_wh(self):
        return 50.0

    def get_idle_draw_w(self):
        return 10.0

    def get_locomotion_draw_w(self):
        return 150.0

    def publisher_count(self):
        return self._publishers

    def message_count(self):
        return 1

    def seconds_since_last_message(self):
        return 0.0


def _manager(**kw):
    return EnergyManager(_FakeBattery(), **kw)


# ---------------------------------------------------------------------------
# BatteryState.is_valid — the flag itself
# ---------------------------------------------------------------------------

def test_the_default_is_valid_because_the_fail_safe_lives_at_one_site():
    """True by default, exactly like SensorReading.is_valid.

    A dataclass default of False would make every BatteryState() in a stub or a
    test silently invalid and would suspend the energy policy on healthy robots.
    The fail-safe belongs at the one construction site that means "I have
    nothing" — GazeboBattery.__init__ — which passes is_valid=False explicitly.
    """
    assert BatteryState().is_valid is True
    assert BatteryState(is_valid=False).is_valid is False


def test_charge_fraction_is_still_populated_when_invalid():
    """The FLAG carries the meaning, not the value — same contract as pose_valid."""
    state = BatteryState(charge_fraction=1.0, is_valid=False)
    assert state.charge_fraction == 1.0


def test_the_hal_interface_reports_health_by_default():
    """A backend with no concept of "a message arrived" still answers.

    StubBattery models its own charge and is authoritative about it; it must not
    have to pretend to be a bus subscriber to satisfy the interface.
    """
    from selene_hal.battery_interface import BatteryInterface
    assert BatteryInterface.publisher_count(object()) == 1
    assert BatteryInterface.message_count(object()) == 1
    assert BatteryInterface.seconds_since_last_message(object()) == 0.0


# ---------------------------------------------------------------------------
# EnergyManager — the policy refuses to decide on a reading it never got
# ---------------------------------------------------------------------------

def test_is_critical_is_false_on_an_unvalidated_zero():
    """THE D-42 CASE. 0.0 with is_valid False must not fire the emergency."""
    em = _manager()
    em.update(BatteryState(charge_fraction=0.0, is_valid=False))
    assert em.has_valid_reading() is False
    assert em.is_critical() is False


def test_is_critical_is_true_on_a_validated_zero():
    """A battery that really is flat still fires. The gate is validity, not value."""
    em = _manager()
    em.update(BatteryState(charge_fraction=0.0, is_valid=True))
    assert em.has_valid_reading() is True
    assert em.is_critical() is True


def test_is_critical_still_respects_the_configured_threshold():
    em = _manager(critical_threshold=0.25)
    em.update(BatteryState(charge_fraction=0.24, is_valid=True))
    assert em.is_critical() is True
    em.update(BatteryState(charge_fraction=0.26, is_valid=True))
    assert em.is_critical() is False


def test_recharge_reason_is_empty_on_an_unvalidated_reading():
    """Same answer the tiers would give, a different STATEMENT.

    An unvalidated state reports 1.0, which is above every tier, so the tiers
    would also return ''. The difference is between "I decided, and the battery
    is fine" and "I have nothing to decide on" — and only one of those is true.
    """
    em = _manager(recharge_threshold=0.30)
    em.update(BatteryState(charge_fraction=0.05, is_valid=False))
    assert em.recharge_reason((0.0, 0.0)) == ''


def test_recharge_reason_still_fires_on_a_validated_low_battery():
    from selene_agent.energy_manager import (
        RECHARGE_BELOW_THRESHOLD, RECHARGE_CRITICAL,
    )
    em = _manager(critical_threshold=0.15, recharge_threshold=0.30)
    em.update(BatteryState(charge_fraction=0.10, is_valid=True))
    assert em.recharge_reason() == RECHARGE_CRITICAL
    em.update(BatteryState(charge_fraction=0.25, is_valid=True))
    assert em.recharge_reason() == RECHARGE_BELOW_THRESHOLD


def test_an_unvalidated_reading_does_not_become_valid_by_being_cached():
    """update() must not launder the flag."""
    em = _manager()
    em.update(BatteryState(charge_fraction=0.0, is_valid=False))
    em.update(BatteryState(charge_fraction=0.0, is_valid=False))
    assert em.has_valid_reading() is False


# ---------------------------------------------------------------------------
# THE WIRING GUARD — the reason this file exists
# ---------------------------------------------------------------------------

def _agent_node_source():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, 'selene_agent', 'agent_node.py')
    with open(path, encoding='utf-8') as handle:
        return path, handle.read()


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_energy_critical_branch_consults_both_gates():
    """The ENERGY_CRITICAL branch must be guarded by validity AND attributability.

    THE GUARD, not the behaviour: this walks the real source of ``_tick`` and
    fails if the branch that fires ENERGY_CRITICAL stops testing either
    condition. A flag that nothing reads is this repository's characteristic
    defect — six instances in production code and a seventh inside the exit-gate
    probe — and both of these were added on 2026-08-01, which is exactly when
    that mistake gets made.
    """
    path, source = _agent_node_source()
    tick = _find_function(ast.parse(source), '_tick')
    assert tick is not None, 'AgentNode._tick not found in %s' % (path,)

    critical_branch = None
    for node in ast.walk(tick):
        if not isinstance(node, ast.If):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if 'ENERGY_CRITICAL' in body:
            critical_branch = node
            break
    assert critical_branch is not None, (
        'no branch inside _tick fires ENERGY_CRITICAL; if it moved, move this '
        'guard with it rather than deleting it')

    test_src = ast.dump(critical_branch.test)
    assert 'is_critical' in test_src, (
        'the ENERGY_CRITICAL branch no longer consults EnergyManager.is_critical')
    assert '_battery_channel_attributable' in test_src, (
        'the ENERGY_CRITICAL branch no longer consults '
        '_battery_channel_attributable, so a battery topic with two publishers '
        'can again drive this robot to the charger on another stack\'s '
        'telemetry. That is register D-42.')


def test_the_wall_clock_grace_no_longer_gates_the_energy_rule():
    """_startup_grace_ticks must not be back in the ENERGY_CRITICAL test.

    It was protection against a mechanism that does not exist, and it failed on
    the one occasion it was needed: the robot fired 1.15 s past it. Its only
    remaining reader is _note_unaffordable_announcement, where elapsed time is
    genuinely the question being asked.
    """
    _path, source = _agent_node_source()
    tree = ast.parse(source)
    tick = _find_function(tree, '_tick')
    for node in ast.walk(tick):
        if isinstance(node, ast.If) and 'ENERGY_CRITICAL' in ast.dump(
                ast.Module(body=node.body, type_ignores=[])):
            assert '_startup_grace_ticks' not in ast.dump(node.test), (
                'the wall-clock grace period is back in the energy-critical '
                'branch; see register D-42 for why a clock cannot express this')

    readers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute)
               and n.attr == '_startup_grace_ticks']
    assert len(readers) <= 3, (
        '_startup_grace_ticks has grown new readers (%d); it is meant to have '
        'one assignment and one reader, in _note_unaffordable_announcement'
        % (len(readers),))


def test_check_battery_health_is_called_from_the_tick():
    """A watchdog nobody runs is the pattern this project keeps repeating."""
    _path, source = _agent_node_source()
    tick = _find_function(ast.parse(source), '_tick')
    calls = [n for n in ast.walk(tick)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == '_check_battery_health']
    assert calls, ('_check_battery_health is defined but never called from '
                   '_tick; see CLAUDE.md on "wired but never called"')


def test_the_health_check_runs_before_the_energy_branch():
    """Order matters: the flag it sets is read on the SAME tick.

    If the branch ran first it would consult the previous tick's attributability
    — one tick of stale trust, every tick, which is precisely the window a
    10 Hz interleaved stream lives in.
    """
    _path, source = _agent_node_source()
    tick = _find_function(ast.parse(source), '_tick')

    health_line = None
    critical_line = None
    for node in ast.walk(tick):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == '_check_battery_health'):
            health_line = node.lineno
        if isinstance(node, ast.If) and '_battery_channel_attributable' in \
                ast.dump(node.test):
            critical_line = node.lineno
    assert health_line is not None and critical_line is not None
    assert health_line < critical_line, (
        '_check_battery_health must run before the branch that reads the flag '
        'it sets')


@pytest.mark.parametrize('name', [
    'publisher_count', 'message_count', 'seconds_since_last_message',
])
def test_the_hal_health_methods_have_a_production_caller(name):
    """Each new HAL method must be read by agent_node, not just defined.

    ``AdaptiveSurveyPlanner``, ``MaterialInventory``'s writers,
    ``resource_map_publish_rate``, ``recharge_threshold``,
    ``max_traversable_slope_deg`` and ``FleetMonitor.get_robot_distance`` were
    all shipped with green tests and zero call sites. This is the guard for the
    three methods added on 2026-08-01.
    """
    _path, source = _agent_node_source()
    assert name in source, (
        'BatteryInterface.%s has no reader in agent_node.py' % (name,))
