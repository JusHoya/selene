"""The fleet must notice when the simulator stops — deviation D-21.

WHAT HAPPENED, live, 2026-07-31. Launching the ten-robot fleet
``selene_sim/config/spawn_positions.yaml`` describes for NFR-1.4 ("up to 10
robots") — ``num_scouts:=4 num_excavators:=3 num_haulers:=3`` — produced, about
five minutes in::

    [gazebo-1] ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact &&
              aabbBound < dMaxIntExact" failed in collide()
              [collision_space.cpp:460]
    [ERROR] [gazebo-1]: process has died [pid 13489, exit code 134,
              cmd 'ruby .../gz sim -s -r ...lunar_psr.sdf --force-version 8']

``ros2 launch`` SURVIVED. So did every agent: they kept ticking at 10 Hz and
kept publishing RobotState at 2 Hz, so ``heartbeat_timeout_sec`` saw a
completely healthy fleet. Navigation then failed fleet-wide with "Path blocked,
no alternate route" as odom froze, scouts 02/03/04 went to ERROR, and the
orchestrator carried on auctioning into a dead simulation. **Nothing in the
system noticed.** A 4-robot run (2/1/1) was stable for 21+ minutes.

The ODE fault itself is NOT addressed here and is not addressable from Python;
what is addressed is that the degradation was silent. The detector is
deliberately ignorant of Gazebo: it watches the poses on ``/<robot>/state``,
which is data the orchestrator already receives, and asks whether the WHOLE
fleet has stopped while at least one robot is supposed to be driving.

Nothing here was run against ROS, and no simulator was killed to produce it.
The pose freeze is reproduced by feeding the real ``FleetMonitor`` the same
RobotState pose twice, which is exactly what a frozen odom bridge does.
"""

import ast
import pathlib

import pytest

from selene_orchestrator.fleet_monitor import (
    MOTION_STATES,
    POSE_MOTION_EPSILON_M,
    FleetMonitor,
)

SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')

#: orchestrator_params.yaml's sim_stall_timeout_sec.
STALL_SEC = 20.0


class _Sim:
    """Feeds a real FleetMonitor RobotState-shaped samples at 2 Hz."""

    def __init__(self, monitor: FleetMonitor, t0: float = 1000.0):
        self._m = monitor
        self.t = t0
        self._pose: dict[str, tuple[float, float]] = {}
        self._state: dict[str, str] = {}

    def spawn(self, robot_id, fsm_state='IDLE', x=0.0, y=0.0):
        self._pose[robot_id] = (x, y)
        self._state[robot_id] = fsm_state
        self._push(robot_id)

    def set_state(self, robot_id, fsm_state):
        self._state[robot_id] = fsm_state

    def _push(self, robot_id):
        x, y = self._pose[robot_id]
        self._m.update_robot(
            robot_id=robot_id, robot_type='scout',
            fsm_state=self._state[robot_id],
            pose_x=x, pose_y=y, pose_theta=0.0,
            battery_level=0.8, current_task_id='',
            capabilities=['prospect'], timestamp=self.t)

    def step(self, seconds, moving=(), speed=0.3):
        """Advance *seconds* of 2 Hz samples; only *moving* robots move."""
        for _ in range(int(seconds * 2)):
            self.t += 0.5
            for rid in self._pose:
                if rid in moving:
                    x, y = self._pose[rid]
                    self._pose[rid] = (x + speed * 0.5, y)
                self._push(rid)


def _fleet(*robots, fsm_state='NAVIGATING'):
    m = FleetMonitor()
    sim = _Sim(m)
    for i, rid in enumerate(robots):
        sim.spawn(rid, fsm_state=fsm_state, x=float(i * 10), y=0.0)
    return m, sim


# --------------------------------------------------------------------------- #
#  The detector                                                                #
# --------------------------------------------------------------------------- #

class TestFleetFreezeDetection:

    def test_a_dead_simulator_is_detected(self):
        """THE OBSERVED FAILURE, reproduced from the wire.

        Every agent keeps publishing at 2 Hz with an unchanging pose, which is
        exactly what a frozen odometry bridge produces, and the robots are
        still NAVIGATING because they have not given up yet.
        """
        m, sim = _fleet('scout_01', 'scout_02', 'excavator_01')
        sim.step(30.0, moving=('scout_01', 'scout_02', 'excavator_01'))
        frozen, _online, _moving = m.is_fleet_frozen(STALL_SEC, sim.t)
        assert frozen is False

        sim.step(STALL_SEC + 1.0)          # gazebo dies: nobody moves
        frozen, online, moving = m.is_fleet_frozen(STALL_SEC, sim.t)
        assert frozen is True
        assert sorted(online) == ['excavator_01', 'scout_01', 'scout_02']
        assert sorted(moving) == ['excavator_01', 'scout_01', 'scout_02']

    def test_heartbeats_stay_healthy_throughout(self):
        """WHY THE EXISTING CHECK COULD NOT SEE THIS.

        The agents survived the simulator, so check_heartbeats reports nothing
        for the entire freeze. Asserting it here is the point: the two
        detectors do not overlap, and a reader deciding this one is redundant
        should see that first.
        """
        m, sim = _fleet('scout_01', 'scout_02')
        sim.step(60.0)
        assert m.check_heartbeats(sim.t) == []
        assert m.is_fleet_frozen(STALL_SEC, sim.t)[0] is True

    def test_one_wedged_robot_is_not_a_dead_simulator(self):
        """A robot stuck against a rock is a navigation fault.

        It already surfaces as that robot's own ERROR, and calling it a
        simulator death would make the CRITICAL alert untrustworthy.
        """
        m, sim = _fleet('scout_01', 'scout_02')
        sim.step(STALL_SEC + 5.0, moving=('scout_02',))
        assert m.get_stalled_robots(STALL_SEC, sim.t) == ['scout_01']
        assert m.is_fleet_frozen(STALL_SEC, sim.t)[0] is False

    def test_an_idle_fleet_at_the_depot_never_trips_it(self):
        """The clause without which this fires on every completed mission.

        A fleet that has finished its survey sits IDLE and does not move. That
        is not a fault, and a CRITICAL alert for it is how an alert log becomes
        wallpaper.
        """
        m, sim = _fleet('scout_01', 'scout_02', fsm_state='IDLE')
        sim.step(300.0)
        assert len(m.get_stalled_robots(STALL_SEC, sim.t)) == 2
        assert m.is_fleet_frozen(STALL_SEC, sim.t)[0] is False

    @pytest.mark.parametrize('state', ['WORKING', 'RECHARGING', 'BIDDING',
                                       'ASSIGNED', 'ERROR'])
    def test_states_that_legitimately_hold_still_do_not_trip_it(self, state):
        """WORKING in particular: an excavator drilling does not move.

        The detector's window is the interval during which the fleet is still
        TRYING to drive. Once every robot has given up and gone to ERROR it
        stops firing — the alert dates the failure, it does not track it, and
        that is deliberate.
        """
        m, sim = _fleet('scout_01', 'scout_02', fsm_state=state)
        sim.step(300.0)
        assert m.is_fleet_frozen(STALL_SEC, sim.t)[0] is False

    def test_one_robot_still_driving_is_enough_to_arm_it(self):
        """Mixed fleet: the parked robots do not disarm the detector."""
        m, sim = _fleet('scout_01', 'excavator_01', 'hauler_01',
                        fsm_state='WORKING')
        sim.set_state('scout_01', 'NAVIGATING')
        sim.step(STALL_SEC + 1.0)
        frozen, _online, moving = m.is_fleet_frozen(STALL_SEC, sim.t)
        assert frozen is True
        assert moving == ['scout_01']

    def test_an_offline_robot_does_not_hold_the_detector_down(self):
        """OFFLINE is already reported by the heartbeat check.

        Its pose is stale by definition, and requiring it to be "moving" would
        make one dead agent permanently mask a dead simulator.
        """
        m, sim = _fleet('scout_01', 'scout_02')
        sim.step(STALL_SEC + 1.0)
        m.mark_offline('scout_02')
        frozen, online, _moving = m.is_fleet_frozen(STALL_SEC, sim.t)
        assert online == ['scout_01']
        assert frozen is True

    def test_an_empty_fleet_is_not_frozen(self):
        assert FleetMonitor().is_fleet_frozen(STALL_SEC, 1000.0)[0] is False

    def test_a_robot_seen_once_is_not_immediately_stalled(self):
        """Startup must not read as a freeze."""
        m, sim = _fleet('scout_01')
        assert m.get_stalled_robots(STALL_SEC, sim.t) == []


class TestMotionEpsilon:

    def test_odometry_jitter_does_not_count_as_motion(self):
        """Without an epsilon the detector could never fire.

        A stationary Gazebo model's dead-reckoned odometry moves in the last
        float bits, so an exact pose comparison reports every parked robot as
        moving.
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='NAVIGATING')
        for i in range(200):
            sim.t += 0.5
            sim._pose['scout_01'] = (1e-9 * i, -1e-9 * i)
            sim._push('scout_01')
        assert m.get_stalled_robots(STALL_SEC, sim.t) == ['scout_01']

    def test_a_slow_crawl_still_counts_as_motion(self):
        """The epsilon must not be so large that a slow robot reads as dead.

        1 cm per 0.5 s sample is 0.02 m/s — a fifteenth of the navigator's
        0.3 m/s planning speed.
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='NAVIGATING')
        sim.step(60.0, moving=('scout_01',), speed=0.02)
        assert m.get_stalled_robots(STALL_SEC, sim.t) == []

    def test_the_epsilon_is_far_below_a_sample_of_normal_travel(self):
        """Stated as a ratio so shrinking the tick rate fails here, not live."""
        travel_per_sample = 0.3 * 0.5      # planning speed x 2 Hz state period
        assert travel_per_sample / POSE_MOTION_EPSILON_M >= 15.0

    def test_working_is_not_a_motion_state(self):
        assert 'WORKING' not in MOTION_STATES
        assert set(MOTION_STATES) == {'NAVIGATING', 'RETURNING'}


# --------------------------------------------------------------------------- #
#  The wiring                                                                  #
# --------------------------------------------------------------------------- #

class TestWiring:
    """A detector nothing calls would leave the degradation just as silent."""

    def test_the_stall_check_runs_on_the_heartbeat_timer(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        heartbeat = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == '_heartbeat_check')
        called = {n.func.attr for n in ast.walk(heartbeat)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert '_check_simulation_stall' in called, (
            'nothing runs the fleet-freeze check, so a dead simulator is as '
            'silent as it was on 2026-07-31. Calls found: %s'
            % (sorted(called),))

        timer_targets = {a.attr for n in ast.walk(tree)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr == 'create_timer'
                         for a in n.args if isinstance(a, ast.Attribute)}
        assert '_heartbeat_check' in timer_targets

    def test_the_alert_is_critical(self):
        """AlertLog.jsx styles CRITICAL differently from WARNING/ERROR.

        A dead simulator makes everything the fleet reports meaningless, which
        is the one thing in this system that warrants the top severity.
        """
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        check = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == '_check_simulation_stall')
        severities = {n.args[0].value for n in ast.walk(check)
                      if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute)
                      and n.func.attr == '_publish_alert'
                      and n.args and isinstance(n.args[0], ast.Constant)}
        assert 'CRITICAL' in severities, severities

    def test_the_alert_is_latched(self):
        """1 Hz x a CRITICAL alert is the flood D-20 exists to prevent.

        Checked by the presence of the latch flag on both sides of the
        decision rather than by counting publishes, because the publish itself
        needs a node.
        """
        src = SOURCE.read_text(encoding='utf-8')
        assert src.count('self._sim_stalled') >= 4, (
            'the fleet-freeze alert does not look latched; a CRITICAL alert '
            'republished at 1 Hz for the rest of the mission is worse than no '
            'alert at all.')

    def test_the_timeout_parameter_is_declared_and_read(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        declared, read = set(), set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            name = node.args[0].value
            if not isinstance(name, str):
                continue
            if node.func.attr == 'declare_parameter':
                declared.add(name)
            elif node.func.attr == 'get_parameter':
                read.add(name)
        assert 'sim_stall_timeout_sec' in declared
        assert 'sim_stall_timeout_sec' in read

    def test_the_agent_gains_no_simulator_dependency(self):
        """The detector must stay inside the ROS graph.

        The requirement was explicit: do not teach the agent about Gazebo. It
        could not work there anyway — a single robot cannot tell "the simulator
        died" from "I am parked", because its own odometry standing still is
        the normal state of a robot that is idle, charging or drilling. The
        discriminator is that the freeze is fleet-wide, and only the
        orchestrator sees the whole fleet.

        Checked by IMPORTS rather than by text: the agent legitimately mentions
        'gazebo' as a HAL backend name, and a substring search for it (or for
        'ode', which is inside 'node') proves nothing.
        """
        agent_pkg = (pathlib.Path(__file__).resolve().parents[2]
                     / 'selene_agent' / 'selene_agent')
        imported = set()
        for source in sorted(agent_pkg.rglob('*.py')):
            for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split('.')[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split('.')[0])
        offenders = {m for m in imported
                     if m.startswith('gz') or 'gazebo' in m or m == 'ode'}
        assert not offenders, (
            'selene_agent imports simulator-specific module(s) %s. The '
            'fleet-freeze detector is orchestrator-side precisely so the '
            'agent never has to know what is producing its odometry.'
            % (sorted(offenders),))

        # And the detector itself must not have leaked into the agent.
        agent_text = '\n'.join(
            p.read_text(encoding='utf-8') for p in agent_pkg.rglob('*.py'))
        for symbol in ('is_fleet_frozen', 'get_stalled_robots'):
            assert symbol not in agent_text, symbol
