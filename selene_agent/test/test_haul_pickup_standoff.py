"""The haul rendezvous standoff -- deviation D-22.

Two robots were being commanded to one point: ``HTNPlanner`` gave a haul the
same target coordinate as the excavate it depends on, and since the D-19
recharge fix the excavator stays parked on that coordinate instead of driving
home. Measured live twice on 2026-07-31 (ROS 2 Jazzy / Gazebo Harmonic), the
hauler drove into it and gz-sim's ODE collision space aborted the simulator on
``assertion "aabbBound >= dMinIntExact && aabbBound < dMaxIntExact" failed in
collide()`` -- SIGABRT, exit 134, the next Gazebo line after this skill logged
``phase=loading``.

Two things are pinned here.

1. **The behaviour**: ``HaulSkill`` begins LOADING at a standoff and never
   drives onto the pickup coordinate. Both the planner's hauls and an
   operator-injected one (FR-DASH-5) go through this path.
2. **The number**: ``PICKUP_STANDOFF_M`` is re-derived, in this file, from the
   collision geometry in ``selene_sim/models/*/model.sdf``, the arrival
   tolerance in ``selene_agent/navigator.py``, the speeds in
   ``selene_hal/config/*.yaml``, the acceleration limits in the same
   ``.sdf`` files, the agent tick rate in ``agent_node.py`` and the planner's
   own ``HAUL_PICKUP_OFFSET_M``. Change any one of those and this fails,
   rather than leaving a standoff that quietly no longer clears anything.

``htn_planner.py`` is read as TEXT (``ast``), not imported: the agent package
does not depend on the orchestrator package and must not start doing so for a
test. The point is only that the two constants cannot drift apart in silence
-- which is the failure mode ``docs/phase5_deviation_register.md`` D-02
correction 3 was opened for.

NOTHING HERE WAS RUN AGAINST ROS, GAZEBO OR ODE. It is arithmetic against the
shipped configuration plus the real skill driven by a navigator double. That
the simulator no longer aborts is a live check, not something this file can
claim.
"""

import ast
import math
import os
import xml.etree.ElementTree as ET
from inspect import signature

import pytest

from selene_hal import create_hal
from selene_agent.navigator import PathFollower
from selene_agent.skills import HaulSkill
from selene_agent.skills.base_skill import SkillState
from selene_agent.skills.haul import HaulPhase


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HTN_PLANNER_PY = os.path.join(
    REPO, 'selene_orchestrator', 'selene_orchestrator', 'htn_planner.py')
AGENT_NODE_PY = os.path.join(
    REPO, 'selene_agent', 'selene_agent', 'agent_node.py')


# ---------------------------------------------------------------------------
# Reading the shipped configuration
# ---------------------------------------------------------------------------

def _sdf(model: str) -> ET.Element:
    return ET.parse(
        os.path.join(REPO, 'selene_sim', 'models', model, 'model.sdf')
    ).getroot()


def _pose_xy(element) -> tuple[float, float]:
    """XY of an SDF ``<pose>``, or (0, 0) when there is none.

    Every wheel link in these models declares ``relative_to="base_link"``, and
    every base_link sits at XY (0, 0) of its model, so a relative pose and an
    absolute one are the same two numbers here. Asserted below rather than
    assumed.
    """
    if element is None:
        return 0.0, 0.0
    values = [float(token) for token in element.text.split()]
    return values[0], values[1]


def footprint_radius(model: str) -> float:
    """Circumscribed XY radius of *model*'s collision geometry, in metres.

    For each collision link: ``|link origin|`` plus the largest distance from
    that link's own origin to any point of its shape -- the half-diagonal of a
    box, ``hypot(r, l/2)`` of a cylinder. Both are upper bounds under ANY
    rotation of the link, so nothing here depends on the wheels' -pi/2 roll
    and a future model that rotates a body cannot silently shrink the answer.

    Circumscribed rather than exact because the guarantee wanted is
    yaw-independent: two robots at an arbitrary relative heading must not
    overlap, and neither the planner nor the skill knows either heading.
    """
    best = 0.0
    for link in _sdf(model).iter('link'):
        lx, ly = _pose_xy(link.find('pose'))
        for collision in link.findall('collision'):
            cx, cy = _pose_xy(collision.find('pose'))
            ox, oy = lx + cx, ly + cy
            geometry = collision.find('geometry')
            box = geometry.find('box')
            cylinder = geometry.find('cylinder')
            if box is not None:
                sx, sy, _sz = [float(t) for t in box.find('size').text.split()]
                half = math.hypot(sx / 2.0, sy / 2.0)
            elif cylinder is not None:
                half = math.hypot(
                    float(cylinder.find('radius').text),
                    float(cylinder.find('length').text) / 2.0,
                )
            else:  # pragma: no cover - no sphere/mesh collision in these models
                raise AssertionError(
                    f'{model}: collision {collision.get("name")} uses a shape '
                    f'this derivation does not cover; extend it rather than '
                    f'letting the standoff be derived from a partial model')
            best = max(best, math.hypot(ox, oy) + half)
    return best


def _sdf_float(model: str, tag: str) -> float:
    """First occurrence of a scalar plugin element, e.g. max_linear_acceleration."""
    for element in _sdf(model).iter(tag):
        return float(element.text)
    raise AssertionError(f'{model}/model.sdf declares no <{tag}>')


def _rcdl_max_speed(robot_type: str) -> float:
    import yaml
    path = os.path.join(REPO, 'selene_hal', 'config', f'{robot_type}.yaml')
    with open(path, encoding='utf-8') as handle:
        return float(yaml.safe_load(handle)['max_speed'])


def _module_constant(path: str, name: str):
    """Value of a module-level literal constant, read without importing."""
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        targets = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        for target in targets:
            if getattr(target, 'id', None) == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f'{path} declares no module-level {name}')


def _declared_parameter_default(path: str, name: str):
    """Default of a ``declare_parameter("<name>", <literal>)`` call."""
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'attr', None) != 'declare_parameter':
            continue
        if len(node.args) < 2:
            continue
        try:
            declared = ast.literal_eval(node.args[0])
        except ValueError:
            continue
        if declared == name:
            return ast.literal_eval(node.args[1])
    raise AssertionError(f'{path} declares no parameter {name!r} with a default')


# ---------------------------------------------------------------------------
# Navigator doubles
# ---------------------------------------------------------------------------

class _Plan:
    def __init__(self, goal):
        self.path = [goal]
        self.cost = 10.0
        self.success = True
        self.failure_reason = ''


class _ApproachNavigator:
    """Drives straight at the goal and reports REAL distances.

    ``MockNavigator`` in ``test_skills.py`` reports a constant distance and is
    arrived by setting a status, which is right for the phase machine and
    useless for a standoff: a standoff is a statement about distance. This one
    integrates position, so where the skill stops is an outcome rather than a
    fixture. Deliberately local -- ``test_skills.py``'s double has no reason to
    grow a position.

    ``goal_reached`` fires inside ``PathFollower``'s own waypoint tolerance, so
    the two arrival rules compete here exactly as they do on a robot.
    """

    WAYPOINT_TOLERANCE = signature(
        PathFollower.__init__).parameters['waypoint_tolerance'].default

    def __init__(self, start, speed):
        self.position = (float(start[0]), float(start[1]))
        self._goal = self.position
        self._speed = float(speed)
        self._status = 'idle'
        self.stop_calls = 0
        #: Latched, not sampled. ``_arrive_at_pickup`` calls ``stop()``, which
        #: clears the status, so reading ``status`` afterwards cannot tell a
        #: standoff arrival from an arrival at the navigator's own goal.
        self.reached_goal = False

    # -- navigator API ----------------------------------------------------
    def plan_to(self, goal):
        self._goal = (float(goal[0]), float(goal[1]))
        return _Plan(self._goal)

    def start_following(self, path):
        self._status = 'navigating'

    def update(self, dt):
        if self._status != 'navigating':
            return self._status
        dx = self._goal[0] - self.position[0]
        dy = self._goal[1] - self.position[1]
        remaining = math.hypot(dx, dy)
        if remaining > 0.0:
            step = min(self._speed * dt, remaining)
            self.position = (self.position[0] + dx / remaining * step,
                             self.position[1] + dy / remaining * step)
        if self.get_distance_to_goal() < self.WAYPOINT_TOLERANCE:
            self._status = 'goal_reached'
            self.reached_goal = True
        return self._status

    def get_distance_to_goal(self):
        return math.hypot(self._goal[0] - self.position[0],
                          self._goal[1] - self.position[1])

    def stop(self):
        self.stop_calls += 1
        self._status = 'idle'

    # -- assertions -------------------------------------------------------
    @property
    def status(self):
        return self._status

    def distance_from(self, point):
        return math.hypot(point[0] - self.position[0],
                          point[1] - self.position[1])


def _hauler_hal():
    return create_hal(
        os.path.join(REPO, 'selene_hal', 'config', 'hauler.yaml'),
        'hauler_01', backend='stub')


def _drive_to_pickup(pickup, start, max_ticks=20000, dt=0.1):
    """Start a haul and tick it until it leaves NAVIGATING_TO_PICKUP."""
    hal = _hauler_hal()
    nav = _ApproachNavigator(start, speed=_rcdl_max_speed('hauler'))
    skill = HaulSkill()
    skill.start(hal, nav, pickup=pickup, depot=(50.0, 50.0))
    assert skill.get_state() == SkillState.RUNNING
    for _ in range(max_ticks):
        if skill._phase != HaulPhase.NAVIGATING_TO_PICKUP or skill.has_failed():
            break
        skill.update(dt)
    return skill, nav


# ---------------------------------------------------------------------------
# The number
# ---------------------------------------------------------------------------

def test_the_two_footprint_radii_are_what_the_standoff_was_derived_from():
    """0.5847 m each, both set by a front wheel, from the shipped SDFs."""
    assert footprint_radius('excavator') == pytest.approx(0.5847, abs=5e-5)
    assert footprint_radius('hauler') == pytest.approx(0.5847, abs=5e-5)
    # Recorded because it is the number the whole derivation rests on and it is
    # NOT the chassis: the base_link boxes give 0.500 and 0.541.
    assert footprint_radius('scout') == pytest.approx(0.4361, abs=5e-5)


def test_the_planners_clearance_constant_matches_the_collision_geometry():
    """``HTNPlanner.FOOTPRINT_CLEARANCE_M`` is the SDF sum, rounded up to 10 mm."""
    derived = footprint_radius('excavator') + footprint_radius('hauler')
    declared = _module_constant(HTN_PLANNER_PY, 'FOOTPRINT_CLEARANCE_M')
    assert declared >= derived, (
        f'FOOTPRINT_CLEARANCE_M {declared} is below the {derived:.4f} m the '
        f'models actually need; an excavator and a hauler this far apart are '
        f'interpenetrating')
    assert declared - derived < 0.01, (
        f'FOOTPRINT_CLEARANCE_M {declared} has drifted {declared - derived:.4f} '
        f'm above the geometry -- re-derive it rather than padding it, or the '
        f'padding starts standing in for the error budget that belongs in '
        f'PICKUP_STANDOFF_M')


def test_the_planner_offset_clears_two_footprints():
    """A plan that names one coordinate for two robots is wrong on its face."""
    offset = _module_constant(HTN_PLANNER_PY, 'HAUL_PICKUP_OFFSET_M')
    clearance = _module_constant(HTN_PLANNER_PY, 'FOOTPRINT_CLEARANCE_M')
    assert offset >= clearance


def test_the_standoff_covers_clearance_error_budget_and_planner_offset():
    """Re-derive PICKUP_STANDOFF_M from the files every term comes out of.

    The worst case is the far-side approach: the hauler's stopping sphere is
    centred on the PICKUP, so its nearest point to the extraction site is
    ``|standoff - planner offset|``, and the excavator may be its own arrival
    error nearer still.
    """
    tick_rate = _declared_parameter_default(AGENT_NODE_PY, 'tick_rate')
    waypoint_tolerance = _ApproachNavigator.WAYPOINT_TOLERANCE

    def rest_error(robot_type, arrival_tolerance):
        speed = _rcdl_max_speed(robot_type)
        accel = _sdf_float(robot_type, 'max_linear_acceleration')
        return (arrival_tolerance                    # navigator's arrival rule
                + speed / tick_rate                  # one tick of travel
                + speed ** 2 / (2.0 * accel))        # coast at the accel limit

    excavator_rest = rest_error('excavator', waypoint_tolerance)
    # The hauler has no arrival tolerance of its own on this leg: the standoff
    # IS the arrival rule, and it is evaluated on the distance directly.
    hauler_overshoot = rest_error('hauler', 0.0)

    clearance = _module_constant(HTN_PLANNER_PY, 'FOOTPRINT_CLEARANCE_M')
    planner_offset = _module_constant(HTN_PLANNER_PY, 'HAUL_PICKUP_OFFSET_M')
    required = clearance + excavator_rest + hauler_overshoot + planner_offset

    assert excavator_rest == pytest.approx(1.180, abs=5e-4)
    assert hauler_overshoot == pytest.approx(0.307, abs=5e-4)
    assert required == pytest.approx(3.856, abs=5e-3)
    assert HaulSkill.PICKUP_STANDOFF_M >= required, (
        f'PICKUP_STANDOFF_M {HaulSkill.PICKUP_STANDOFF_M} is under the '
        f'{required:.3f} m this fleet needs; a hauler can reach a parked '
        f'excavator, which is what aborted gz-sim')


def test_the_standoff_still_clears_an_operator_injected_haul():
    """FR-DASH-5 hauls carry no planner offset -- the standoff must cover them."""
    tick_rate = _declared_parameter_default(AGENT_NODE_PY, 'tick_rate')
    clearance = _module_constant(HTN_PLANNER_PY, 'FOOTPRINT_CLEARANCE_M')
    speed = _rcdl_max_speed('hauler')
    accel = _sdf_float('hauler', 'max_linear_acceleration')
    excavator_rest = (_ApproachNavigator.WAYPOINT_TOLERANCE
                      + _rcdl_max_speed('excavator') / tick_rate
                      + _rcdl_max_speed('excavator') ** 2
                      / (2.0 * _sdf_float('excavator', 'max_linear_acceleration')))
    overshoot = speed / tick_rate + speed ** 2 / (2.0 * accel)
    assert HaulSkill.PICKUP_STANDOFF_M >= clearance + excavator_rest + overshoot


# ---------------------------------------------------------------------------
# The behaviour
# ---------------------------------------------------------------------------

def test_the_haul_stops_short_of_the_pickup_instead_of_driving_onto_it():
    """The defect, directly: the hauler used to arrive AT the coordinate."""
    pickup = (10.0, 20.0)
    skill, nav = _drive_to_pickup(pickup, start=(-60.0, -40.0))

    assert skill._phase == HaulPhase.LOADING
    assert not skill.has_failed()

    stopped_at = nav.distance_from(pickup)
    # Upper bound: it did stop, at the standoff and not somewhere arbitrary.
    assert stopped_at <= HaulSkill.PICKUP_STANDOFF_M
    # Lower bound: within one tick of travel of the standoff radius. This is
    # the assertion that fails on the pre-D-22 tree, where the hauler carried
    # on to inside the navigator's 1.0 m waypoint tolerance.
    one_tick = _rcdl_max_speed('hauler') * 0.1
    assert stopped_at >= HaulSkill.PICKUP_STANDOFF_M - one_tick
    assert stopped_at > _ApproachNavigator.WAYPOINT_TOLERANCE


def test_arrival_does_not_wait_for_the_navigators_own_goal():
    """The navigator never reports goal_reached on the pickup leg any more.

    Pinned because it is the difference between "we stop short" and "we stop
    short unless the navigator gets there first", and the second is what a
    later refactor would quietly restore.
    """
    _skill, nav = _drive_to_pickup((10.0, 20.0), start=(-60.0, -40.0))
    assert nav.reached_goal is False
    assert nav.stop_calls == 1
    assert nav.status == 'idle'


def test_a_hauler_already_inside_the_standoff_loads_where_it_stands():
    """It has not driven anywhere, so it cannot have driven into anything.

    Backing off to the exact radius would be motion undertaken only to satisfy
    an inequality, and motion is the thing that hit the excavator. The one
    tick of approach below is unavoidable and not a policy: the phase reads the
    distance after ticking the navigator, exactly as the pre-existing
    ``goal_reached`` branch does.
    """
    pickup = (10.0, 20.0)
    start = (10.0, 23.0)          # 3.0 m out: inside the standoff, outside
    skill, nav = _drive_to_pickup(pickup, start=start)   # the 1.0 m tolerance

    assert skill._phase == HaulPhase.LOADING
    one_tick = _rcdl_max_speed('hauler') * 0.1
    assert nav.distance_from(pickup) == pytest.approx(3.0 - one_tick)
    assert nav.distance_from(pickup) < HaulSkill.PICKUP_STANDOFF_M


def test_the_standoff_does_not_apply_to_the_depot_leg():
    """A hauler must still reach the depot; only the pickup has a robot on it.

    Also the regression guard for the obvious wrong fix -- applying the
    standoff in ``_update_navigating_to_depot`` too, which would leave every
    delivery 4.5 m short of the marker.
    """
    import selene_agent.skills.haul as haul_module
    with open(haul_module.__file__, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    depot_leg = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name == '_update_navigating_to_depot']
    assert len(depot_leg) == 1
    assert 'PICKUP_STANDOFF_M' not in ast.dump(depot_leg[0])


def test_blocked_still_fails_the_haul():
    """The standoff must not swallow a genuine navigation failure."""
    hal = _hauler_hal()

    class _BlockedNavigator(_ApproachNavigator):
        def update(self, dt):
            super().update(dt)
            return 'blocked'

    nav = _BlockedNavigator((-60.0, -40.0), speed=_rcdl_max_speed('hauler'))
    skill = HaulSkill()
    skill.start(hal, nav, pickup=(10.0, 20.0), depot=(50.0, 50.0))
    skill.update(0.1)
    assert skill.has_failed()
    assert 'blocked' in skill.get_error().lower()
