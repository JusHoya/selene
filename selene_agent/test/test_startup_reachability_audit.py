"""The startup reachability audit, and the one recharge coordinate it names.

WHY THIS EXISTS
---------------
Two deviations meet here.

D-28: the slope limit had no reader, so nothing in SELENE could say whether the
places the mission REQUIRES a robot to reach were reachable. On 2026-07-31 a
hauler was routed at a 34 degree crater wall, pinned, kept turning its wheels
for 320.7 s while its body moved 6.6 cm, and reported success. The audit exists
so that the reason is in the log BEFORE the robot sets off rather than being
reconstructed afterwards from a pinned robot's odometry.

D-32: three recharge coordinates disagreed and only one was read --
``agent_node``'s ``recharge_x``/``recharge_y`` defaults at (-30, -100),
``nav_params.yaml``'s ``mission.recharge_position`` at (-75, -100) which nothing
read and which sits on 33.91 degree ground, and ``RechargeSkill``'s (40, 40)
constructor default. This file pins the reconciliation so it cannot come apart.

WHAT THE AUDIT IS NOT. It is a REPORT and it can never refuse to start an agent.
That is asserted here, by AST, because the tempting next change is to make it a
gate -- and a startup check that aborted a fleet on the strength of arithmetic
over a heightmap would be a worse failure than the one it guards against. The
shipped terrain has been through three different beliefs about what is climbable
in two days.

AST, NOT IMPORT, FOR THE NODE. ``agent_node.py`` imports ``rclpy`` and
``selene_msgs`` at module scope and cannot be imported in the pure-Python lanes
that produce this repository's baselines. Reading the module as text is the
idiom this repository already uses -- see
``selene_agent/test/test_agent_state_publish_wiring.py`` and
``selene_orchestrator/test/test_no_orphan_parameters.py``.

CROSS-PACKAGE FILES ARE READ BY PATH, NEVER IMPORTED. Every lane has the whole
checkout on disk; only ``sys.path`` differs between them. So reading
``selene_orchestrator/config/orchestrator_params.yaml`` as a file is safe in the
two-package gate lane, where importing ``selene_orchestrator`` would not be.
That distinction is register D-36, from the safe side.

MUTATIONS RUN AGAINST THIS FILE (house rule 2), each applied then reverted on
2026-08-01. Counts are MEASURED; the baseline is 13 passed.

* delete ``self._run_terrain_audit_once()`` from ``AgentNode._tick``
  -> 1 failed, 12 passed (``..._is_actually_called_from_the_tick_loop``).
* ``audit_terrain_reachability``'s ``reachable[name]`` -> ``True``
  -> 3 failed, 10 passed.
* ``per_step_components``'s admissibility -> ignore elevation
  -> 2 failed, 11 passed here, and 1 failed in
  ``test_navigator_slope_enforcement.py``.
* change ``agent_node``'s ``depot_x`` default to -50.0
  -> 1 failed, 12 passed.
* delete ``recharge_position=`` from the ``RechargeSkill(...)`` call
  -> 1 failed, 12 passed.

ONE MUTATION THAT DID NOT KILL ANYTHING HERE, recorded because a mutation that
survives is information: ``is_step_traversable -> return True`` leaves this file
at 13 passed. It kills 5 tests in ``test_navigator_slope_enforcement.py``. The
audit does not route through that method -- ``per_step_components`` compares
elevations itself, vectorised -- so this file cannot see it, which is exactly
why ``test_the_component_labelling_and_the_planner_agree`` exists over there.
"""

from __future__ import annotations

import ast
import math
import os
import re

import numpy as np
import yaml

from selene_agent.navigator import (
    OccupancyGrid,
    ReachabilityAudit,
    audit_terrain_reachability,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
AGENT_NODE_PY = os.path.join(REPO, 'selene_agent', 'selene_agent', 'agent_node.py')
AGENT_LAUNCH_PY = os.path.join(REPO, 'selene_agent', 'launch', 'agent.launch.py')
NAV_PARAMS = os.path.join(REPO, 'selene_agent', 'config', 'nav_params.yaml')
ORCH_PARAMS = os.path.join(
    REPO, 'selene_orchestrator', 'config', 'orchestrator_params.yaml')
WORLD_PARAMS = os.path.join(REPO, 'selene_sim', 'config', 'world_params.yaml')
WORLD_SDF = os.path.join(REPO, 'selene_sim', 'worlds', 'lunar_psr.sdf')

#: The physical recharge pad: the ``recharge_pad`` <include> in lunar_psr.sdf.
RECHARGE_PAD = (-30.0, -100.0)
#: The depot on the crater floor.
DEPOT = (-100.0, -150.0)


# ---------------------------------------------------------------------------
# Synthetic worlds
# ---------------------------------------------------------------------------

class _Lattice:
    """The duck type ``load_terrain`` consumes."""

    def __init__(self, elevation, slope, resolution=1.0, origin_x=0.0,
                 origin_y=0.0):
        self.elevation_m = np.asarray(elevation, dtype=np.float64)
        self.slope_deg = np.asarray(slope, dtype=np.float64)
        self.height, self.width = self.elevation_m.shape
        self.resolution = resolution
        self.origin_x = origin_x
        self.origin_y = origin_y


def _split_world(limit=20.0):
    """Two flats separated by a 5 m cliff: genuinely two worlds.

    ``recharge_pad`` is planted on the west flat and ``depot`` on the east one,
    which is the shape D-32 believed the shipped terrain had.
    """
    size = 20
    column_z = np.array([0.0 if gx < 10 else 5.0 for gx in range(size)])
    elevation = np.repeat(column_z[None, :], size, axis=0)
    grid = OccupancyGrid(width=size, height=size, resolution=1.0,
                         origin_x=0.0, origin_y=0.0)
    grid.load_terrain(_Lattice(elevation, np.zeros((size, size))), limit)
    return grid


# ---------------------------------------------------------------------------
# The audit itself
# ---------------------------------------------------------------------------

def test_the_audit_reports_the_shape_of_a_split_world():
    """Two components, and it names which landmark is on the wrong side."""
    grid = _split_world()
    audit = audit_terrain_reachability(
        grid, (2.5, 2.5),
        {'recharge_pad': (4.5, 4.5), 'depot': (15.5, 15.5)})
    assert audit.limit_deg == 20.0
    assert audit.component_count == 2
    assert audit.total_cells == 400
    assert audit.start_component_cells == 200
    assert audit.landmark_reachable == {'recharge_pad': True, 'depot': False}
    assert audit.unreachable_landmarks == ['depot']


def test_the_audit_names_the_landmark_it_cannot_reach():
    """"3 components" is a statistic; "depot NOT REACHABLE" is an action.

    The whole reason the node passes landmarks at all is that an operator has to
    be able to read one line and know the mission cannot close.
    """
    grid = _split_world()
    audit = audit_terrain_reachability(
        grid, (2.5, 2.5), {'depot': (15.5, 15.5)})
    text = '\n'.join(audit.lines())
    assert 'depot (15.5, 15.5): NOT REACHABLE' in text
    assert '20.0 deg' in text and 'PER STEP' in text
    assert 'per-CELL' in text, (
        'the excluded-cell count is a per-cell reading and is NOT the rule in '
        'force; a log line that does not say so invites exactly the confusion '
        'that made a 34 deg rim look like a wall')


def test_the_audit_is_loud_when_there_is_no_terrain_at_all():
    """The state that IS D-28, reported as such.

    A grid with no terrain enforces nothing, and the one thing the log must not
    do is stay quiet about it -- a silent "0 cells excluded" reads like a clean
    bill of health.
    """
    audit = audit_terrain_reachability(
        OccupancyGrid(width=10, height=10), (0.0, 0.0), {'depot': DEPOT})
    assert audit.limit_deg is None
    assert audit.unreachable_landmarks == ['depot']
    text = '\n'.join(audit.lines())
    assert 'NO SLOPE LIMIT IS BEING ENFORCED' in text
    assert 'D-28' in text


def test_report_emits_one_call_per_line_through_the_injected_logger():
    """How the node's logger is captured, and why the function takes one.

    ``audit_terrain_reachability`` is pure and ``report`` writes through a
    callable, so the whole audit is assertable without rclpy -- which is not
    importable in the lanes that produce this repository's baselines.
    """
    captured: list[str] = []
    audit = audit_terrain_reachability(
        _split_world(), (2.5, 2.5), {'depot': (15.5, 15.5)})
    audit.report(captured.append)
    assert len(captured) == 4
    assert captured == audit.lines()
    assert all(line.startswith('[TERRAIN]') for line in captured), (
        'the block is prefixed so an operator can grep one launch log for it')


def test_a_start_off_the_grid_is_reported_rather_than_raising():
    """This runs in a node constructor's tick loop; it may not raise.

    An audit that could abort an agent is a gate, and this is not one.
    """
    audit = audit_terrain_reachability(
        _split_world(), (10_000.0, 10_000.0), {'depot': (15.5, 15.5)})
    assert audit.start_component_cells == 0
    assert audit.unreachable_landmarks == ['depot']
    assert isinstance(audit, ReachabilityAudit)
    assert audit.lines()


def test_the_audit_costs_what_it_says_it_costs():
    """A characterization pin on the startup budget, not a performance gate.

    ``per_step_components`` is iterated minimum-label propagation over numpy and
    measured 2.0 s on the shipped 500 x 500 lattice; it runs inside the 10 Hz
    tick callback, so that tick is that late, once, inside the 5 s startup grace
    window. The bound here is deliberately loose -- this asserts the algorithm
    has not become quadratic, not that a particular machine is fast.
    """
    import time
    size = 200
    gx = np.arange(size, dtype=np.float64)[None, :]
    grid = OccupancyGrid(width=size, height=size, resolution=1.0)
    grid.load_terrain(
        _Lattice(np.repeat(gx * 0.05, size, axis=0), np.zeros((size, size)),
                 origin_x=-250.0, origin_y=-250.0),
        20.0)
    started = time.perf_counter()
    audit = audit_terrain_reachability(grid, (-249.5, -249.5), {})
    assert audit.component_count == 1
    assert time.perf_counter() - started < 30.0


# ---------------------------------------------------------------------------
# The node's wiring, read as source
# ---------------------------------------------------------------------------

def _agent_tree():
    with open(AGENT_NODE_PY, 'r', encoding='utf-8') as handle:
        return ast.parse(handle.read())


def _method(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'AgentNode.{name} not found in agent_node.py')


def _calls(node):
    """Every ``foo(...)``/``self.foo(...)``/``a.b.foo(...)`` name called under *node*."""
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def test_the_audit_is_actually_called_from_the_tick_loop():
    """The assertion this whole repository exists to make.

    ``AdaptiveSurveyPlanner`` shipped with green unit tests and zero call sites.
    ``MaterialInventory``'s writers had none. So did
    ``resource_map_publish_rate``, ``recharge_threshold`` and
    ``max_traversable_slope_deg`` itself. A green
    ``test_the_audit_reports_the_shape_of_a_split_world`` proves the function
    works and proves NOTHING about the node calling it.
    """
    tree = _agent_tree()
    assert '_run_terrain_audit_once' in _calls(_method(tree, '_tick')), (
        'AgentNode._tick does not call _run_terrain_audit_once; the audit is '
        'the sixth instance of "wired but never called"')
    audit_method = _method(tree, '_run_terrain_audit_once')
    called = _calls(audit_method)
    assert 'audit_terrain_reachability' in called
    assert 'report' in called, (
        'the audit is computed and never emitted, which is worse than not '
        'computing it')

    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    assert 'audit_terrain_reachability' in imported


def test_the_audit_reports_and_never_refuses():
    """It may not fault the robot, stop the tick, or raise.

    Enforced by reading the method: no ``handle_event``, no ``FSMEvent``, no
    ``raise``, and every ``return`` bare. The tempting next change is to make
    this a gate; the reason not to is that the shipped terrain has had three
    different beliefs about what is climbable in two days, and this audit is
    arithmetic over a PNG.
    """
    method = _method(_agent_tree(), '_run_terrain_audit_once')
    called = _calls(method)
    assert 'handle_event' not in called, (
        'the audit fires an FSM event; it is a gate now, not a report')
    for node in ast.walk(method):
        assert not isinstance(node, ast.Raise), (
            'the audit raises. It runs inside a timer callback in a node '
            'constructor path and can only ever report.')
        if isinstance(node, ast.Return):
            assert node.value is None, (
                'the audit returns a value, so a caller could branch on it')
    logged = {node.func.attr for node in ast.walk(method)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr in ('info', 'warn', 'error')}
    assert {'info', 'error'} <= logged, (
        'an unreachable depot must be an ERROR, not another info line in a '
        'launch log nobody greps')


def test_the_audit_waits_for_a_valid_pose():
    """It asks about THIS ROBOT'S position, so it must have one.

    ``GazeboOdometrySensor.read()`` hands back a cached reading with
    ``is_valid=False`` and x, y at 0.0 until the first ``/odom_world`` message
    arrives (register D-31). An audit run in ``__init__`` would have reported
    reachability from the world origin for every robot in the fleet -- a
    confident answer about a place none of them is, which is D-31's defect in
    new clothes.
    """
    source = ast.unparse(_method(_agent_tree(), '_run_terrain_audit_once'))
    assert 'is_valid' in source, (
        'the audit does not check odometry validity, so it measures from '
        'wherever the HAL happens to be caching -- (0, 0) at startup')
    assert '_terrain_audit_done' in source, 'the audit is not once-only'


def test_the_recharge_skill_is_never_left_on_its_own_default():
    """``RechargeSkill``'s constructor default is (40, 40) and always overridden.

    That default is 300 m from the pad and is D-32's third coordinate. It is NOT
    fixed here -- ``selene_agent/selene_agent/skills/recharge.py`` was outside
    the change that closed D-32 -- so what is asserted instead is that the one
    production construction always supplies the real station. If someone drops
    the keyword, every robot in the fleet drives to (40, 40) and this fails.
    """
    tree = _agent_tree()
    constructions = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)
                     and node.func.id == 'RechargeSkill']
    assert constructions, 'agent_node no longer constructs a RechargeSkill'
    for call in constructions:
        keywords = {kw.arg for kw in call.keywords}
        assert 'recharge_position' in keywords, (
            'a RechargeSkill is built without recharge_position, so it falls '
            'back to the (40, 40) constructor default')


# ---------------------------------------------------------------------------
# One recharge station, one depot  (deviation D-32)
# ---------------------------------------------------------------------------

def _sdf_marker(name):
    text = open(WORLD_SDF).read()
    for block in re.findall(r'<include>(.*?)</include>', text, re.S):
        found = re.search(r'<name>\s*(\w+)\s*</name>', block)
        if found and found.group(1) == name:
            pose = re.search(r'<pose>\s*(-?[\d.]+)\s+(-?[\d.]+)', block)
            return (float(pose.group(1)), float(pose.group(2)))
    return None


def _node_parameter_defaults():
    """``{name: value}`` for every ``self.declare_parameter('x', <literal>)``."""
    defaults = {}
    for node in ast.walk(_agent_tree()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'declare_parameter'
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)):
            try:
                defaults[node.args[0].value] = ast.literal_eval(node.args[1])
            except ValueError:                      # pragma: no cover
                pass
    return defaults


def _launch_parameter_dict():
    """``{name: value}`` for the parameter dict in agent.launch.py."""
    with open(AGENT_LAUNCH_PY, 'r', encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    out[key.value] = ast.literal_eval(value)
                except ValueError:
                    pass
    return out


def test_there_is_exactly_one_recharge_station_and_it_is_the_physical_pad():
    """FOUR statements of it, and D-32's third coordinate is gone.

    The authority is the object in the world. Everything else has to point at
    it, and ``mission.recharge_position`` -- which pointed 45 m away, at 33.91
    degree ground, and which nothing read -- is deleted rather than corrected:
    promoting an unread key to authority is the same defect from the other end.
    """
    assert _sdf_marker('recharge_pad') == RECHARGE_PAD

    with open(WORLD_PARAMS) as handle:
        world = yaml.safe_load(handle)['world']
    assert tuple(world['recharge_station']['position'][:2]) == RECHARGE_PAD

    defaults = _node_parameter_defaults()
    assert (defaults['recharge_x'], defaults['recharge_y']) == RECHARGE_PAD

    launch = _launch_parameter_dict()
    assert (launch['recharge_x'], launch['recharge_y']) == RECHARGE_PAD, (
        'the launch file does not pass the recharge station, so the number '
        'exists only as a constructor default and cannot be changed -- which '
        'is deviation D-13, verbatim, with a different name')

    with open(NAV_PARAMS) as handle:
        mission = (yaml.safe_load(handle) or {}).get('mission') or {}
    assert 'recharge_position' not in mission, (
        'mission.recharge_position is back in nav_params.yaml. It is a fourth '
        'coordinate nothing reads; if it is meant to be authoritative, give it '
        'a reader and delete the parameter defaults instead.')


def test_the_agents_depot_agrees_with_the_orchestrators():
    """A fourth copy of the depot is allowed only because this test exists.

    ``depot_x``/``depot_y`` on the agent are read by the startup audit and
    nothing else. The authority is the orchestrator's pair -- that is what rides
    on ``TaskAssignment.depot_location`` and directs a real haul. A disagreement
    would make the audit certify or condemn a place no hauler is going, which is
    worse than not auditing.
    """
    with open(ORCH_PARAMS) as handle:
        params = yaml.safe_load(handle)['orchestrator_node']['ros__parameters']
    authority = (float(params['depot_x']), float(params['depot_y']))
    assert authority == DEPOT

    defaults = _node_parameter_defaults()
    assert (defaults['depot_x'], defaults['depot_y']) == authority
    launch = _launch_parameter_dict()
    assert (launch['depot_x'], launch['depot_y']) == authority

    with open(WORLD_PARAMS) as handle:
        world = yaml.safe_load(handle)['world']
    assert tuple(world['depot']['position'][:2]) == authority
    assert _sdf_marker('depot') == authority


def test_the_pad_and_the_depot_are_still_different_places():
    """Guards the four assertions above against collapsing into one.

    If a future edit made every coordinate equal, both agreement tests would
    pass and the mission would have no plain-side charger. They were 234 m apart
    once, by accident.
    """
    assert RECHARGE_PAD != DEPOT
    assert math.hypot(RECHARGE_PAD[0] - DEPOT[0],
                      RECHARGE_PAD[1] - DEPOT[1]) > 50.0
