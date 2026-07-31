"""HaulSkill driven against the simulation's own fill arithmetic, at 10 Hz.

WHY THIS EXISTS SEPARATELY FROM test_skills.py
``_run_haul_cycle`` (``test_skills.py:277-308``) moves the load cell straight
to the value under test -- ``sensor.set_level(unload_fraction)`` -- so the
level jumps from full to the target in a single tick and the skill never sees
the samples in between. The real bin does not do that: ``bin_load_node``
drains its ``FillModel`` at the RCDL ``transfer_rate`` on a 10 Hz timer, so the
level walks down 1.0 kg at a time and the skill stops on the FIRST sample its
stop condition accepts.

That difference hid the residual half of deviation D-06. With a fraction-only
stop condition at ``EMPTY_THRESHOLD`` 0.02, the 50 kg transport bin was called
empty at 1.0 kg -- twice the orchestrator's ``material_residual_tolerance_kg``
-- so the haul reported a residual that tripped a false FR-ISRU-2
instrument-disagreement alert (``orchestrator_node.py:783``) and
``delivered_kg``, a delta against that same reading, was short by up to 1.0 kg
per haul. MEASURED WITH THIS DRIVER against the pre-fix skill: authorised
19.0 kg -> delivered 18.0000, residual 1.0000; authorised 17.633 kg ->
delivered 17.0000, residual 0.6330; 20 of 40 hauls stepped by 0.37 kg reported
a residual above the 0.5 kg tolerance.

WHAT THIS DRIVES
The whole chain that is reachable without ROS: HaulSkill -> the transfer
actuator's payload (``load:<kg>`` | ``unload`` | ``stop``, the exact strings
``GazeboTransferActuator`` publishes, ``gazebo_hal.py:494-515``) ->
``fill_model.parse_transfer_command`` -> ``FillModel`` -> the published
fraction -> ``StubFillLevelSensor`` -> HaulSkill. Capacity and transfer rate
are read from ``selene_hal/config/hauler.yaml``, the same RCDL the HAL and the
sim node read, so no number below is a local copy of one.

WHAT IT CANNOT ASSERT
Nothing here runs against ROS, Gazebo or DDS; none of it was observed on a
live system. Sample timing is exact -- one sim step per skill tick -- where
the real system has a transport, jitter, and no ordering guarantee between the
agent's 10 Hz tick and the sim node's 10 Hz timer. What is checked is the
ARITHMETIC of the stop condition against the real drain law, which is where
the defect was.
"""

import importlib.util
import os

import pytest
import yaml

from selene_hal import create_hal
from selene_hal.stub_hal import StubTransferActuator
from selene_agent.skills.excavate import ExcavateSkill
from selene_agent.skills.haul import HaulSkill, HaulPhase

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, '..', '..'))


def _load_fill_model():
    """Import ``selene_sim/selene_sim/fill_model.py`` BY PATH.

    The PYTHONPATH this suite runs under does not carry ``selene_sim``, and
    the obvious fix -- inserting that directory on ``sys.path``, as
    ``selene_sim/test/test_fill_model.py:35-40`` does for its own tests --
    would put ``launch/``, ``test/`` and ``resource/`` on the import path for
    the rest of the session and shadow ROS 2's own ``launch`` package for
    anything imported after it. ``fill_model.py`` is stdlib plus PyYAML and
    imports nothing from its own package, so loading it standalone yields the
    same module object with none of that reach.
    """
    path = os.path.join(_REPO, 'selene_sim', 'selene_sim', 'fill_model.py')
    spec = importlib.util.spec_from_file_location('_selene_sim_fill_model',
                                                  path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fill_model = _load_fill_model()
FillModel = _fill_model.FillModel
parse_transfer_command = _fill_model.parse_transfer_command
read_fill_capacity_kg = _fill_model.read_fill_capacity_kg
read_transfer_rate = _fill_model.read_transfer_rate

HAULER_RCDL = os.path.join(_REPO, 'selene_hal', 'config', 'hauler.yaml')
EXCAVATOR_RCDL = os.path.join(_REPO, 'selene_hal', 'config', 'excavator.yaml')
ORCH_PARAMS = os.path.join(
    _REPO, 'selene_orchestrator', 'config', 'orchestrator_params.yaml')

BIN_CAPACITY_KG = read_fill_capacity_kg(HAULER_RCDL, 'load_cell')
BIN_TRANSFER_RATE = read_transfer_rate(HAULER_RCDL, 'transport_bin')

# The agent ticks its skills at its `tick_rate` parameter, default 10.0
# (agent_node.py:111,251-252), and both simulation fill nodes default to
# `update_rate` 10.0 (bin_load_node.py:45, hopper_node.py).
DT = 0.1


def _residual_tolerance_kg() -> float:
    """The orchestrator's fault threshold, read from its own parameter file.

    Read rather than restated so the two cannot drift apart silently: the
    whole defect these tests cover is a stop condition that disagreed with
    this number.
    """
    with open(ORCH_PARAMS, 'r') as f:
        params = yaml.safe_load(f)
    return float(
        params['orchestrator_node']['ros__parameters'][
            'material_residual_tolerance_kg'])


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

class _Plan:
    def __init__(self, goal):
        self.path = [goal]
        self.cost = 10.0
        self.success = True
        self.failure_reason = ''


class _Navigator:
    """Minimal navigator double.

    Deliberately local rather than imported from test_skills.py: this module
    is about the fill chain, and importing another test module to borrow a
    double couples two files that have no other reason to know about each
    other.
    """

    def __init__(self):
        self._status = 'navigating'

    def plan_to(self, goal):
        return _Plan(goal)

    def start_following(self, path):
        self._status = 'navigating'

    def update(self, dt):
        return self._status

    def get_distance_to_goal(self):
        return 100.0

    def stop(self):
        self._status = 'idle'

    def set_status(self, status):
        self._status = status


class _SimBin:
    """Stands in for selene_sim/bin_load_node.py, minus rclpy.

    Command handling mirrors ``BinLoadNode._load_cmd_callback`` and the tick
    mirrors ``BinLoadNode._update``; the arithmetic is the real ``FillModel``,
    so a change to the drain law shows up here.
    """

    def __init__(self, drain_enabled: bool = True):
        self.model = FillModel(capacity_kg=BIN_CAPACITY_KG,
                               transfer_rate_kg_s=BIN_TRANSFER_RATE)
        self.mode = None
        self.target_kg = 0.0
        self.commands = []
        self._drain_enabled = drain_enabled

    def command(self, payload: str) -> None:
        self.commands.append(payload)
        parsed = parse_transfer_command(payload, self.model.capacity_kg)
        if parsed.error is not None:
            return
        if parsed.mode == 'loading':
            self.target_kg = parsed.target_kg
        if parsed.mode == 'unloading' and not self._drain_enabled:
            # A bin that acknowledges the command and moves nothing: the
            # jammed-chute case the orchestrator's residual alert exists for.
            return
        self.mode = None if parsed.mode == 'idle' else parsed.mode

    def step(self, dt: float) -> float:
        if self.mode == 'loading':
            if self.model.load_toward(dt, self.target_kg) <= 0.0:
                self.mode = None
        elif self.mode == 'unloading':
            self.model.drain(dt)
            if self.model.is_empty:
                self.mode = None
        return self.model.fraction


class _SimBinActuator(StubTransferActuator):
    """Emits the payloads GazeboTransferActuator publishes, into a _SimBin."""

    def __init__(self, config, sim_bin: _SimBin):
        super().__init__(config)
        self._bin = sim_bin

    def trigger_load(self, max_kg: float = -1.0) -> None:
        super().trigger_load(max_kg)
        self._bin.command('load' if max_kg < 0.0 else f'load:{max_kg:.3f}')

    def trigger_unload(self) -> None:
        super().trigger_unload()
        self._bin.command('unload')

    def cancel_transfer(self) -> None:
        super().cancel_transfer()
        self._bin.command('stop')


def _run_haul(authorised_kg: float, drain_enabled: bool = True,
              max_ticks: int = 2000):
    """One haul, skill and simulated bin stepped in lockstep at 10 Hz.

    The sensor is updated from the bin AFTER the skill's tick, so the skill
    always reads the previous sample -- the one-sample lag a subscriber has.

    Returns ``(skill, result, sim_bin)``.
    """
    hal = create_hal(HAULER_RCDL, 'hauler_01', backend='stub')
    sim_bin = _SimBin(drain_enabled=drain_enabled)
    config = hal.get_actuator('transport_bin').get_config()
    hal._actuators['transport_bin'] = _SimBinActuator(config, sim_bin)
    sensor = hal.get_sensor('load_cell')

    nav = _Navigator()
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0),
                quantity_kg=authorised_kg)
    nav.set_status('goal_reached')

    for _ in range(max_ticks):
        if skill.is_complete() or skill.has_failed():
            break
        skill.update(DT)
        if skill._phase == HaulPhase.LOADING:
            nav.set_status('navigating')
        elif skill._phase == HaulPhase.NAVIGATING_TO_DEPOT:
            nav.set_status('goal_reached')
        sensor.set_level(sim_bin.step(DT))

    return skill, skill.get_result(), sim_bin


# ---------------------------------------------------------------------------
# The regression this file was written for
# ---------------------------------------------------------------------------

# 19.0 and 20.0 are whole multiples of the 1.0 kg drained per sample, so the
# level lands exactly on EMPTY_THRESHOLD (1.0 / 50.0 = 0.02) -- the worst case
# for a fraction-only stop condition. 17.633 and 12.37 leave a remainder, and
# 0.0 means unconstrained: fill to capacity.
@pytest.mark.parametrize('authorised_kg', [0.0, 12.37, 17.633, 19.0, 20.0])
def test_haul_residual_stays_inside_the_orchestrator_tolerance(authorised_kg):
    """The bin the skill calls empty must satisfy the orchestrator's check.

    ``abs(residual_mass_kg) > material_residual_tolerance_kg`` raises a
    WARNING FleetAlert naming the robot (orchestrator_node.py:783-788). Before
    the kilogram gate, a completed haul produced a residual of up to 1.0 kg
    and roughly half of all hauls raised that alert against a bin that was
    physically empty.
    """
    tolerance = _residual_tolerance_kg()
    skill, result, sim_bin = _run_haul(authorised_kg)

    assert skill.is_complete(), skill.get_error()
    assert result.residual_mass_kg <= tolerance
    # And the bin really is empty, so the residual is not merely small.
    assert sim_bin.model.mass_kg == pytest.approx(0.0)


@pytest.mark.parametrize('authorised_kg', [12.37, 17.633, 19.0, 20.0])
def test_haul_delivers_every_kilogram_it_loaded(authorised_kg):
    """delivered_kg must not be short by the mass left below the stop point.

    The shortfall was permanent ledger drift, not a display error:
    ``record_unload(delivered)`` leaves the difference in ``RobotCargo`` for
    the rest of the mission, so ``MissionProgress.in_transit_quantity``
    accumulates on haulers that are physically empty.
    """
    _skill, result, _sim_bin = _run_haul(authorised_kg)

    assert result.loaded_kg == pytest.approx(authorised_kg)
    assert result.delivered_kg == pytest.approx(authorised_kg)


def test_a_bin_that_does_not_drain_still_reports_the_fault():
    """The kilogram gate must not have removed the fault it is measured by.

    The bin acknowledges ``unload`` and moves nothing. The phase ends on
    ``_settled`` instead, and the haul reports the mass it is still holding --
    which is what makes the orchestrator's instrument-disagreement alert fire
    on a real jam.
    """
    tolerance = _residual_tolerance_kg()
    skill, result, sim_bin = _run_haul(19.0, drain_enabled=False)

    assert skill.is_complete(), skill.get_error()
    assert 'unload' in sim_bin.commands
    assert result.residual_mass_kg == pytest.approx(19.0)
    assert result.residual_mass_kg > tolerance
    assert result.delivered_kg == pytest.approx(0.0)


def test_authorised_mass_reaches_the_bin_as_an_absolute_target():
    """The `load:<kg>` payload is what stops a bin loading unextracted mass."""
    _skill, result, sim_bin = _run_haul(12.37)

    assert 'load:12.370' in sim_bin.commands
    assert result.bin_mass_after_load_kg == pytest.approx(12.37)


def test_unconstrained_load_fills_to_the_rcdl_capacity():
    """0.0 keeps the pre-FR-DASH-5 behaviour: the bare `load` payload."""
    _skill, result, _sim_bin = _run_haul(0.0)

    assert result.loaded_kg == pytest.approx(BIN_CAPACITY_KG)


# ---------------------------------------------------------------------------
# The two stop conditions against the orchestrator's tolerance
# ---------------------------------------------------------------------------

def test_empty_stop_conditions_are_inside_the_orchestrator_tolerance():
    """Both skills' stop conditions, converted to kg, must fit the tolerance.

    HaulSkill stops on ``level <= EMPTY_THRESHOLD and mass <= EMPTY_MASS_KG``,
    so its effective bound is the smaller of the two in kilograms.
    ExcavateSkill stops on the fraction alone, which is inside the tolerance
    only because the hopper is 20 kg -- 0.02 x 20 = 0.4 kg against a 0.5 kg
    tolerance. That is arithmetic on a capacity, not a property of the
    threshold, so raising ``excavator.yaml`` hopper_fill ``capacity_kg`` above
    25 kg silently re-creates the haul defect on the excavator. This test is
    where that shows up.
    """
    tolerance = _residual_tolerance_kg()
    hopper_capacity = read_fill_capacity_kg(EXCAVATOR_RCDL, 'hopper_fill')

    haul_bound_kg = min(
        HaulSkill.EMPTY_THRESHOLD * BIN_CAPACITY_KG, HaulSkill.EMPTY_MASS_KG)
    excavate_bound_kg = ExcavateSkill.EMPTY_THRESHOLD * hopper_capacity

    assert haul_bound_kg <= tolerance, (
        f'HaulSkill calls a bin empty at {haul_bound_kg} kg, above the '
        f'orchestrator tolerance of {tolerance} kg')
    assert excavate_bound_kg <= tolerance, (
        f'ExcavateSkill calls a hopper empty at {excavate_bound_kg} kg, above '
        f'the orchestrator tolerance of {tolerance} kg')
