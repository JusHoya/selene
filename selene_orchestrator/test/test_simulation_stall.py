"""The fleet must notice when robots stop moving — deviations D-21 and D-30.

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
kept publishing RobotState, so ``heartbeat_timeout_sec`` saw a completely
healthy fleet. Navigation then failed fleet-wide with "Path blocked, no
alternate route" as odom froze, scouts 02/03/04 went to ERROR, and the
orchestrator carried on auctioning into a dead simulation. **Nothing in the
system noticed.** A 4-robot run (2/1/1) was stable for 21+ minutes.

The ODE fault itself is NOT addressed here and is not addressable from Python;
what is addressed is that the degradation was silent. The detector is
deliberately ignorant of Gazebo: it watches ``/<robot>/state``, which is data
the orchestrator already receives.

THEN THE DETECTOR ITSELF WAS WRONG — D-30, and the reason this file was
rewritten. The first version measured "time since this robot last moved 1 cm"
and compared it against a threshold. That clock RUNS WHILE A ROBOT IS PARKED,
and two false positives followed from it:

* a robot that had sat in IDLE for 60 s carried a 60 s-stale pose clock into
  NAVIGATING, so it was "stalled" at the first sample in the motion state, with
  ZERO seconds of actual failure, and cleared one heartbeat later;
* parked robots are stalled by construction, so "every online robot is stalled"
  was satisfied for free by the nine parked members of a ten-robot fleet. One
  wedged scout among them produced predicate output BIT-IDENTICAL to a dead
  simulator — and the alert asserted "this is not a robot fault: the simulator
  has stopped".

The measurement is now "how long has this robot been EXPECTED to move and not
moved", and the alert reports what was observed instead of naming a cause. The
old suite could not have caught either defect: every fixture drove the robots
before freezing them, so the stale-clock path was never constructed, and
``test_one_robot_still_driving_is_enough_to_arm_it`` pinned the second false
positive as CORRECT behaviour, green. It is deleted; the quorum test below
replaces it.

Nothing here was run against ROS, and no simulator was killed to produce it.
The pose freeze is reproduced by feeding the real ``FleetMonitor`` the same
RobotState pose twice, which is exactly what a frozen odom bridge does.
"""

import ast
import inspect
import math
import pathlib

import pytest
import yaml

from selene_orchestrator.fleet_monitor import (
    MOTION_STATES,
    POSE_MOTION_EPSILON_M,
    WHEEL_MOTION_EPSILON_MPS,
    FleetMonitor,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / 'selene_orchestrator' / 'orchestrator_node.py')
PARAMS = REPO / 'selene_orchestrator' / 'config' / 'orchestrator_params.yaml'


def _configured(name: str):
    """Read a value from the shipped params file rather than duplicating it.

    The old version of this file carried ``STALL_SEC = 20.0`` as a literal with
    a comment saying it mirrored the params file. A mirror maintained by
    comment drifts; this one cannot.
    """
    doc = yaml.safe_load(PARAMS.read_text(encoding='utf-8'))
    (node,) = doc.keys()
    return doc[node]['ros__parameters'][name]


#: orchestrator_params.yaml's sim_stall_timeout_sec, read from the file.
STALL_SEC = float(_configured('sim_stall_timeout_sec'))
#: orchestrator_params.yaml's sim_stall_min_movers.
MIN_MOVERS = int(_configured('sim_stall_min_movers'))

#: The RobotState timer period. NOT the sample interval — RobotState is also
#: published on every FSM transition, so the real spacing is irregular and at
#: least this fast. Used only where "the slowest the topic can be" is the
#: quantity that matters, i.e. in the epsilon derivations.
STATE_TIMER_PERIOD_S = 0.5


class _Sim:
    """Feeds a real FleetMonitor RobotState-shaped samples.

    Pose, FSM state, wheel speed and position-fix validity are held per robot
    and pushed together, because that is how they arrive on the wire: one
    message carries all four. In particular a robot's twist does NOT reset when
    its pose stops changing — a dead producer leaves the HAL's cached reading
    exactly as it was, twist included, which is the property the wheels-turning-
    body-not clause depends on.
    """

    def __init__(self, monitor: FleetMonitor, t0: float = 1000.0):
        self._m = monitor
        self.t = t0
        self._pose: dict[str, tuple[float, float]] = {}
        self._state: dict[str, str] = {}
        self._vel: dict[str, float] = {}
        self._fix: dict[str, bool] = {}

    def spawn(self, robot_id, fsm_state='IDLE', x=0.0, y=0.0,
              velocity=0.0, pose_valid=True):
        self._pose[robot_id] = (x, y)
        self._state[robot_id] = fsm_state
        self._vel[robot_id] = velocity
        self._fix[robot_id] = pose_valid
        self._push(robot_id)

    def set_state(self, robot_id, fsm_state):
        self._state[robot_id] = fsm_state

    def set_velocity(self, robot_id, velocity):
        self._vel[robot_id] = velocity

    def set_fix(self, robot_id, pose_valid):
        self._fix[robot_id] = pose_valid

    def _push(self, robot_id):
        x, y = self._pose[robot_id]
        self._m.update_robot(
            robot_id=robot_id, robot_type='scout',
            fsm_state=self._state[robot_id],
            pose_x=x, pose_y=y, pose_theta=0.0,
            battery_level=0.8, current_task_id='',
            capabilities=['prospect'], timestamp=self.t,
            pose_valid=self._fix[robot_id],
            velocity_linear=self._vel[robot_id])

    def step(self, seconds, moving=(), speed=0.3):
        """Advance *seconds* of 2 Hz samples; only *moving* robots move.

        Wheel speed is NOT touched here. A test that wants "wheels turning,
        body not" sets the velocity once and then stops moving the pose.
        """
        for _ in range(int(seconds * 2)):
            self.t += STATE_TIMER_PERIOD_S
            for rid in self._pose:
                if rid in moving:
                    x, y = self._pose[rid]
                    self._pose[rid] = (x + speed * STATE_TIMER_PERIOD_S, y)
                self._push(rid)


def _fleet(*robots, fsm_state='NAVIGATING', velocity=0.0):
    m = FleetMonitor()
    sim = _Sim(m)
    for i, rid in enumerate(robots):
        sim.spawn(rid, fsm_state=fsm_state, x=float(i * 10), y=0.0,
                  velocity=velocity)
    return m, sim


# --------------------------------------------------------------------------- #
#  D-30: the two false positives                                               #
# --------------------------------------------------------------------------- #

class TestTheFalsePositivesThatOpenedD30:

    def test_entering_a_motion_state_with_a_stale_pose_clock_does_not_fire(self):
        """RUN B, reproduced and repaired.

        Nine robots parked in non-motion states for 60 s, then ONE flips to
        NAVIGATING without moving. The shipped predicate returned frozen=True on
        the FIRST sample in NAVIGATING -- 0.0 s of actual failure against a
        60.0 s stale pose clock -- and cleared one heartbeat later. Nothing may
        fire until the robot has been stationary WHILE EXPECTED TO MOVE for the
        whole threshold.

        The fixture the old suite structurally could not build: every fixture
        there drove the robots (``sim.step(30.0, moving=(...))``) before
        freezing them, so a robot never entered a motion state carrying a stale
        clock.
        """
        parked = [f'parked_{i:02d}' for i in range(9)]
        m, sim = _fleet(*parked, 'scout_00', fsm_state='WORKING')
        sim.step(60.0)                       # everybody parked, nobody moves

        sim.set_state('scout_00', 'NAVIGATING')
        sim.step(STATE_TIMER_PERIOD_S)       # first sample in the motion state
        entered = sim.t

        # Every sample from the transition up to the threshold, not just the
        # first: the shipped predicate fired on sample one, but a fix that
        # merely delayed it by a tick would look the same at one sample.
        while sim.t - entered <= STALL_SEC:
            assert m.assess_motion(STALL_SEC, sim.t).stalled == [], (
                'fired %.1f s after entering the motion state, with a %.1f s '
                'threshold; the pose clock from BEFORE the state change is '
                'being counted as evidence of failure again (D-30 run B)'
                % (sim.t - entered, STALL_SEC))
            sim.step(STATE_TIMER_PERIOD_S)

        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.stalled_ids == ['scout_00'], report.stalled_ids
        assert report.movers == ['scout_00'], report.movers
        # And the parked nine contribute nothing at all, in either direction.
        assert len(report.online) == 10

    def test_one_wedged_robot_among_a_parked_fleet_is_not_a_fleet_claim(self):
        """RUN A, reproduced and repaired.

        Nine robots in non-motion states plus one NAVIGATING robot whose pose is
        frozen. The shipped predicate returned frozen=True -- output identical
        to a dead simulator -- and the alert asserted the simulator had stopped.
        The per-robot ERROR must still fire; only the FLEET claim is withheld.
        """
        parked = [f'parked_{i:02d}' for i in range(9)]
        m, sim = _fleet(*parked, 'scout_04', fsm_state='WORKING')
        sim.set_state('scout_04', 'NAVIGATING')
        sim.step(60.0)

        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == ['scout_04']
        assert report.stalled_ids == ['scout_04']
        assert report.stalled[0].stationary_sec >= 59.0
        assert report.fleet_wide(MIN_MOVERS) is False, (
            'one wedged robot among a parked fleet is being reported as a '
            'fleet-wide condition; that is D-30 run A, where the predicate '
            'output was bit-identical to a dead simulator')


# --------------------------------------------------------------------------- #
#  D-21 coverage the repair must not lose                                      #
# --------------------------------------------------------------------------- #

class TestADeadSimulatorIsStillDetected:

    def test_a_dead_simulator_is_still_detected(self):
        """THE OBSERVED FAILURE, reproduced from the wire.

        Three robots drive normally, then every pose freezes while every twist
        stays where it was -- which is what a dead producer leaves behind, since
        ``GazeboOdometrySensor.read()`` returns its cached reading and never
        raises. The fleet claim must fire, and it must fire at the threshold,
        not later.
        """
        m, sim = _fleet('scout_01', 'scout_02', 'excavator_01',
                        velocity=0.3)
        movers = ('scout_01', 'scout_02', 'excavator_01')
        sim.step(30.0, moving=movers)
        assert m.assess_motion(STALL_SEC, sim.t).fleet_wide(MIN_MOVERS) is False

        # Gazebo dies. Poses freeze; twists do not.
        sim.step(STALL_SEC - 0.5)
        assert m.assess_motion(STALL_SEC, sim.t).fleet_wide(MIN_MOVERS) is False, (
            'fired before the configured threshold')

        sim.step(1.0)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.fleet_wide(MIN_MOVERS) is True
        assert sorted(report.movers) == sorted(movers)
        assert sorted(report.stalled_ids) == sorted(movers)
        assert report.longest_stationary_sec > STALL_SEC
        assert all(s.wheel_speed_mps == pytest.approx(0.3)
                   for s in report.stalled), (
            'the frozen twist was lost, so the alert cannot say "wheels '
            'turning, body not"')

    def test_it_fires_sooner_than_the_threshold_it_replaced(self):
        """The tightening, stated as a comparison rather than as a constant.

        20.0 s was the previous value and it sat exactly on
        ``(MAX_REPLAN_ATTEMPTS + 1) x stall_timeout``, the point at which the
        agent abandons the motion state and the detector goes blind -- zero
        margin. This is not what removes the false positives; it is what stops
        the detector racing the thing it is watching.
        """
        m, sim = _fleet('scout_01', 'scout_02', velocity=0.3)
        sim.step(30.0, moving=('scout_01', 'scout_02'))
        sim.step(20.0)                        # the OLD threshold
        assert STALL_SEC < 20.0
        assert m.assess_motion(STALL_SEC, sim.t).fleet_wide(MIN_MOVERS) is True

    def test_heartbeats_stay_healthy_throughout(self):
        """WHY THE EXISTING CHECK COULD NOT SEE THIS.

        The agents survived the simulator, so check_heartbeats reports nothing
        for the entire freeze. Asserting it here is the point: the two
        detectors do not overlap, and a reader deciding this one is redundant
        should see that first.
        """
        m, sim = _fleet('scout_01', 'scout_02')
        sim.step(30.0, moving=('scout_01', 'scout_02'))
        sim.step(60.0)
        assert m.check_heartbeats(sim.t) == []
        assert m.assess_motion(STALL_SEC, sim.t).fleet_wide(MIN_MOVERS) is True

    def test_the_fleet_claim_needs_a_quorum(self):
        """The coverage trade, pinned explicitly instead of left implied.

        The same freeze with only ONE mover: no fleet claim, but the per-robot
        alert still fires. Fails if someone lowers the quorum to 1 -- which is
        exactly the claim D-30 was opened for.
        """
        m, sim = _fleet('scout_01', 'excavator_01', 'hauler_01',
                        fsm_state='WORKING')
        sim.set_state('scout_01', 'NAVIGATING')
        sim.step(30.0, moving=('scout_01',))
        sim.step(STALL_SEC + 1.0)

        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == ['scout_01']
        assert report.stalled_ids == ['scout_01']
        assert report.fleet_wide(MIN_MOVERS) is False
        assert report.fleet_wide(1) is False, (
            'the quorum floor of 2 can be configured away; one witness cannot '
            'support a fleet-wide cause')

    def test_an_idle_fleet_at_the_depot_never_trips_it(self):
        """The clause without which this fires on every completed mission.

        A fleet that has finished its survey sits IDLE and does not move. That
        is not a fault, and a CRITICAL alert for it is how an alert log becomes
        wallpaper.
        """
        m, sim = _fleet('scout_01', 'scout_02', fsm_state='IDLE')
        sim.step(300.0)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == []
        assert report.stalled == []
        assert report.fleet_wide(MIN_MOVERS) is False

    @pytest.mark.parametrize('state', ['WORKING', 'RECHARGING', 'BIDDING',
                                       'ASSIGNED', 'ERROR'])
    def test_states_that_hold_still_with_the_wheels_stopped_are_not_movers(
            self, state):
        """WORKING in particular: an excavator drilling does not move.

        The old version of this test asserted the same thing about the
        PREDICATE. It now asserts it about the MEASUREMENT, which is stronger:
        these robots are not merely "not enough to fire", they contribute no
        evidence at all and are absent from ``movers``.
        """
        m, sim = _fleet('scout_01', 'scout_02', fsm_state=state)
        sim.step(300.0)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == []
        assert report.stalled == []

    def test_an_offline_robot_does_not_hold_the_detector_down(self):
        """OFFLINE is already reported by the heartbeat check."""
        m, sim = _fleet('scout_01', 'scout_02', velocity=0.3)
        sim.step(30.0, moving=('scout_01', 'scout_02'))
        sim.step(STALL_SEC + 1.0)
        m.mark_offline('scout_02')
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.online == ['scout_01']
        assert report.movers == ['scout_01']
        assert report.stalled_ids == ['scout_01']
        # One mover is below the quorum, so no fleet claim -- and that is the
        # honest answer: one robot is not evidence about the fleet.
        assert report.fleet_wide(MIN_MOVERS) is False

    def test_an_empty_fleet_is_not_stalled(self):
        report = FleetMonitor().assess_motion(STALL_SEC, 1000.0)
        assert report.online == []
        assert report.fleet_wide(MIN_MOVERS) is False

    def test_a_robot_seen_once_is_not_immediately_stalled(self):
        """Startup must not read as a freeze."""
        m, sim = _fleet('scout_01')
        assert m.assess_motion(STALL_SEC, sim.t).stalled == []


# --------------------------------------------------------------------------- #
#  The wheel-speed clause                                                      #
# --------------------------------------------------------------------------- #

class TestTheWheelSpeedClause:

    def test_a_pinned_hauler_is_caught_although_its_state_is_WORKING(self):
        """NEW COVERAGE, and the reason the clause exists.

        The FSM leaves NAVIGATING as soon as the haul skill's phase is no longer
        NAVIGATING_TO_PICKUP, so HaulPhase.NAVIGATING_TO_DEPOT reports fsm_state
        WORKING. That is the leg on which the D-23/D-25 hauler pinned against
        the crater wall for 320.7 s with its wheels at the commanded 0.395 m/s
        and its body moving 6.6 cm. MOTION_STATES alone cannot see it.
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('hauler_01', fsm_state='WORKING', x=-57.5, y=-90.0,
                  velocity=0.395)
        sim.step(STALL_SEC + 1.0)             # wheels turning, body frozen

        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == ['hauler_01'], (
            'a robot reporting 0.395 m/s of wheel speed is not being counted '
            'as expected to move; the velocity clause has been dropped and '
            'the whole haul-to-depot leg is invisible again')
        assert report.stalled_ids == ['hauler_01']
        assert report.stalled[0].fsm_state == 'WORKING'
        assert report.stalled[0].wheel_speed_mps == pytest.approx(0.395)
        assert report.stalled[0].wheel_yaw_rate == pytest.approx(0.0), (
            'a hauler pinned on a wall reports forward speed and no yaw; the '
            'alert distinguishes that from a pivot, so the field must survive')

    def test_a_drilling_excavator_is_not_a_mover(self):
        """The guard against the velocity clause making every robot a witness."""
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('excavator_01', fsm_state='WORKING', velocity=0.0)
        sim.step(300.0)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == []
        assert report.stalled == []

    def test_the_wheel_epsilon_is_bracketed_by_the_repositorys_own_numbers(self):
        """Stated as a derivation so shrinking either bound fails here.

        Floor: POSE_MOTION_EPSILON_M over the RobotState timer period is the
        slowest motion the pose test can resolve at all. Ceiling: the slowest
        RCDL max_speed in the fleet (excavator, 0.3 m/s).
        """
        floor = POSE_MOTION_EPSILON_M / STATE_TIMER_PERIOD_S
        assert WHEEL_MOTION_EPSILON_MPS > floor, (
            f'{WHEEL_MOTION_EPSILON_MPS} m/s is at or below the {floor} m/s '
            f'the 1 cm pose test can resolve, so a robot creeping slower than '
            f'the pose check can see would be called a mover and then '
            f'immediately called stalled')
        assert WHEEL_MOTION_EPSILON_MPS < 0.3, (
            'the wheel epsilon is at or above the slowest RCDL max_speed, so '
            'an excavator at full speed would not count as being driven')

    def test_a_non_finite_wheel_speed_does_not_silently_disable_the_clause(self):
        """NaN fails every ``>`` test, so it would read as "not driven".

        The twist comes from a HAL read inside the agent's try/except, so a NaN
        is possible. It must not turn the clause off silently.
        """
        m = FleetMonitor()
        m.update_robot('h1', 'hauler', 'WORKING', 0, 0, 0, 0.8, '',
                       timestamp=0.0, velocity_linear=float('nan'))
        assert m.get_robot('h1')['wheel_speed_mps'] == 0.0
        m.update_robot('h1', 'hauler', 'WORKING', 0, 0, 0, 0.8, '',
                       timestamp=1.0, velocity_linear=float('inf'))
        assert m.get_robot('h1')['wheel_speed_mps'] == 0.0

    def test_a_reversing_robot_counts_as_being_driven(self):
        """Magnitude, not sign. A robot backing out of an obstacle is moving."""
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='WORKING', velocity=-0.3)
        sim.step(STALL_SEC + 1.0)
        assert m.assess_motion(STALL_SEC, sim.t).movers == ['scout_01']


# --------------------------------------------------------------------------- #
#  D-31: a robot with no position fix                                          #
# --------------------------------------------------------------------------- #

class TestNoPositionFix:

    def test_a_robot_with_no_fix_is_neither_a_mover_nor_stalled(self):
        """There is no position measurement, so there is nothing to judge.

        It is reported under ``no_fix`` rather than dropped, so that "the whole
        fleet lost its position source" cannot look like "the whole fleet is
        fine".
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='NAVIGATING', pose_valid=False)
        sim.step(120.0)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.online == ['scout_01']
        assert report.no_fix == ['scout_01']
        assert report.movers == []
        assert report.stalled == []

    def test_regaining_a_fix_does_not_brand_the_robot_stalled(self):
        """The gap is not evidence of failure, so it must not be counted.

        A sample with no position in it says nothing about whether the robot
        moved. If the stall clock ran across the gap, the first valid sample
        after it would arrive already past the threshold.
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='NAVIGATING', pose_valid=False)
        sim.step(120.0)
        sim.set_fix('scout_01', True)
        sim.step(0.5)
        report = m.assess_motion(STALL_SEC, sim.t)
        assert report.movers == ['scout_01']
        assert report.stalled == [], (
            'a robot that has just regained its position fix is being reported '
            'as stalled for a window nothing measured')


# --------------------------------------------------------------------------- #
#  The motion epsilon                                                          #
# --------------------------------------------------------------------------- #

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
            sim.t += STATE_TIMER_PERIOD_S
            sim._pose['scout_01'] = (1e-9 * i, -1e-9 * i)
            sim._push('scout_01')
        assert m.assess_motion(STALL_SEC, sim.t).stalled_ids == ['scout_01']

    def test_a_slow_crawl_still_counts_as_motion(self):
        """The epsilon must not be so large that a slow robot reads as dead.

        1 cm per 0.5 s sample is 0.02 m/s — a fifteenth of the navigator's
        0.3 m/s planning speed.
        """
        m = FleetMonitor()
        sim = _Sim(m)
        sim.spawn('scout_01', fsm_state='NAVIGATING')
        sim.step(60.0, moving=('scout_01',), speed=0.02)
        assert m.assess_motion(STALL_SEC, sim.t).stalled == []

    def test_the_epsilon_is_far_below_a_sample_of_normal_travel(self):
        """Stated as a ratio so shrinking the tick rate fails here, not live."""
        travel_per_sample = 0.3 * STATE_TIMER_PERIOD_S
        assert travel_per_sample / POSE_MOTION_EPSILON_M >= 15.0

    def test_working_is_not_a_motion_state(self):
        assert 'WORKING' not in MOTION_STATES
        assert set(MOTION_STATES) == {'NAVIGATING', 'RETURNING'}


# --------------------------------------------------------------------------- #
#  Cross-package: the threshold is not chosen from a run                       #
# --------------------------------------------------------------------------- #

def _navigator():
    """selene_agent.navigator, or skip — D-36.

    The gate lane is ``PYTHONPATH="selene_orchestrator;selene_isru"``, which is
    the lane CI's ``e2e-integration`` job declares. ``selene_agent`` is not on
    it, so a cross-package check must SKIP there rather than error. It runs on
    the cross-package lane, which is where the agreement is actually made. A
    skip is only safe while some lane still makes the assertion.
    """
    return pytest.importorskip(
        'selene_agent.navigator',
        reason='cross-package derivation check; selene_agent is not on the '
               'gate lane PYTHONPATH (D-36). Runs on the cross-package lane.',
    )


def test_the_threshold_sits_inside_the_agents_own_recovery_budget():
    """This is what makes 10.0 s a derivation rather than a taste.

    Lower bound: one PathFollower stall-and-replan cycle, so a single
    legitimate recovery never alerts. Upper bound: the point at which the agent
    gives up, leaves the motion state and the detector goes blind. Read out of
    the agent's own source, so it breaks if either package moves its number.
    """
    navigator = _navigator()
    stall_timeout = inspect.signature(
        navigator.PathFollower.__init__).parameters['stall_timeout'].default
    attempts = navigator.Navigator.MAX_REPLAN_ATTEMPTS
    blind_after = (attempts + 1) * stall_timeout

    assert stall_timeout < STALL_SEC < blind_after, (
        f'sim_stall_timeout_sec={STALL_SEC} is outside the agent\'s own '
        f'recovery budget: one replan cycle is {stall_timeout} s and the agent '
        f'abandons the motion state after {blind_after} s, past which this '
        f'detector cannot see anything at all')
    assert STALL_SEC >= 2 * stall_timeout, (
        'less than two replan cycles of margin over a single legitimate '
        'recovery')


def test_a_full_reversal_from_rest_never_produces_a_stationary_sample():
    """Turn-in-place costs ZERO stationary seconds — the load-bearing half.

    If a legitimate about-turn produced samples under POSE_MOTION_EPSILON_M,
    the threshold would have to cover the turn and the derivation above would
    collapse. It does not: PathFollower always commands a non-zero linear
    velocity while FOLLOWING (the worst-case speed_scale is 0.3 above 45 deg of
    heading error), so the body arcs rather than pivoting.

    Driven through the REAL PathFollower on an ideal unicycle at the 10 Hz
    agent tick, sampled at the RobotState timer period, on the slowest RCDL
    (excavator, 0.3 m/s). D-35 measured the same thing on a live run from the
    other direction: a 164.8 deg about-turn carried the body up to 3.745 m from
    where it started over ~10.2 s, i.e. ~0.37 m/s of mean body speed, ~18x the
    epsilon per sample.
    """
    navigator = _navigator()

    class _Drive:
        def __init__(self):
            self.v = self.w = 0.0

        def command_velocity(self, linear, angular):
            self.v, self.w = linear, angular

    class _Odom:
        def __init__(self, state):
            self._s = state

        def read(self):
            return self._s

    class _State:
        x = 0.0
        y = 0.0
        theta = 0.0
        linear_velocity = 0.0

    class _Kin:
        def __init__(self, max_speed):
            self._v = max_speed

        def get_max_speed(self):
            return self._v

    state = _State()
    drive = _Drive()
    follower = navigator.PathFollower(drive, _Odom(state), _Kin(0.3))
    follower.set_path([(-30.0, 0.0)])        # straight behind: a 180 deg case

    dt = 0.1                                  # the agent tick
    per_sample = STATE_TIMER_PERIOD_S / dt
    assert per_sample == int(per_sample)
    per_sample = int(per_sample)

    worst = float('inf')
    swept = 0.0
    anchor = (state.x, state.y)
    for tick in range(600):                   # 60 s ceiling; the turn is ~3 s
        status = follower.update(dt)
        if status != navigator.PathFollowerStatus.FOLLOWING:
            break
        state.x += drive.v * math.cos(state.theta) * dt
        state.y += drive.v * math.sin(state.theta) * dt
        state.theta += drive.w * dt
        state.linear_velocity = drive.v
        swept += abs(drive.w) * dt
        if (tick + 1) % per_sample == 0:
            moved = math.hypot(state.x - anchor[0], state.y - anchor[1])
            worst = min(worst, moved)
            anchor = (state.x, state.y)

    assert swept > math.radians(150.0), (
        f'the fixture did not actually reverse: only {math.degrees(swept):.1f} '
        f'deg swept')
    assert worst >= 10.0 * POSE_MOTION_EPSILON_M, (
        f'the smallest displacement in any {STATE_TIMER_PERIOD_S} s sample of a '
        f'full reversal was {worst:.4f} m, only '
        f'{worst / POSE_MOTION_EPSILON_M:.1f}x POSE_MOTION_EPSILON_M. If a '
        f'legitimate turn can go under the epsilon, the stall threshold has to '
        f'cover the turn and its derivation from the replan budget is void.')


# --------------------------------------------------------------------------- #
#  The alerts, EXECUTED rather than inspected                                  #
# --------------------------------------------------------------------------- #

class _Logger:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def error(self, msg):
        self.lines.append(('error', msg))

    def warn(self, msg):
        self.lines.append(('warn', msg))

    def info(self, msg):
        self.lines.append(('info', msg))


class _ClockedFleet:
    """FleetMonitor proxy that pins ``assess_motion`` to the fixture's clock.

    ``_check_motion_stalls`` calls ``assess_motion(timeout)`` with no
    ``current_time``, so production reads ``time.monotonic()``. The fixtures
    here run on their own 1000.0-based clock, and mixing the two would compare
    a fake timestamp against a real one — which, on this machine, silently makes
    every robot look stalled by half a million seconds and would have made the
    recovery tests unfalsifiable. Same quantity, controlled source.
    """

    def __init__(self, fleet, sim):
        self._fleet = fleet
        self._sim = sim

    def assess_motion(self, stale_after_sec, current_time=None):
        return self._fleet.assess_motion(stale_after_sec, self._sim.t)


class _FakeNode:
    """The minimum surface ``_check_motion_stalls`` touches.

    The alert methods are pure given a FleetMonitor and four attributes, so
    they can be driven without rclpy by binding them to this. That matters:
    every other check on the alert text in this file is a string match over
    source, and a string match cannot tell you the f-string interpolates, that
    the latch works, or that the branch is reachable at all.
    """

    def __init__(self, fleet, sim, timeout=STALL_SEC, min_movers=MIN_MOVERS):
        self._fleet = _ClockedFleet(fleet, sim)
        self._sim_stall_timeout = timeout
        self._sim_stall_min_movers = min_movers
        self._sim_stalled = False
        self._stalled_robots = set()
        self._distance_rejections_reported = 0
        self.alerts: list[tuple[str, str, str]] = []
        self._logger = _Logger()

    def get_logger(self):
        return self._logger

    def _publish_alert(self, severity, source_robot_id, message):
        self.alerts.append((severity, source_robot_id, message))

    def check(self):
        from selene_orchestrator.orchestrator_node import OrchestratorNode
        # Bound explicitly rather than by subclassing OrchestratorNode, whose
        # __init__ needs a live rclpy context. Naming the three methods here
        # means the test breaks loudly if the call graph is restructured,
        # rather than silently exercising less than it claims to.
        self._report_per_robot_stalls = (
            lambda r: OrchestratorNode._report_per_robot_stalls(self, r))
        self._report_fleet_motion_stall = (
            lambda r: OrchestratorNode._report_fleet_motion_stall(self, r))
        OrchestratorNode._check_motion_stalls(self)

    def of(self, severity):
        return [a for a in self.alerts if a[0] == severity]


class TestTheAlertsAreReachableAndSayWhatWasObserved:

    def _dead_simulator(self):
        m, sim = _fleet('scout_01', 'scout_02', 'excavator_01', velocity=0.3)
        movers = ('scout_01', 'scout_02', 'excavator_01')
        sim.step(30.0, moving=movers)
        sim.step(STALL_SEC + 1.0)             # everything freezes
        return m, sim

    def test_the_critical_reports_a_count_and_names_no_cause(self):
        m, sim = self._dead_simulator()
        node = _FakeNode(m, sim)
        node.check()

        (critical,) = node.of('CRITICAL')
        _sev, source, message = critical
        assert source == '', 'a fleet-level alert must not blame one robot'
        assert '3 of 3 robot(s) expected to be moving' in message, message
        assert 'OBSERVED, NOT DIAGNOSED' in message
        assert 'wheels turning at up to 0.30 m/s' in message
        for forbidden in ('FLEET-WIDE ODOMETRY FREEZE',
                          'The whole fleet has stopped moving',
                          'this is not a robot fault'):
            assert forbidden not in message, forbidden

    def test_every_stalled_robot_also_gets_its_own_error(self):
        m, sim = self._dead_simulator()
        node = _FakeNode(m, sim)
        node.check()

        errors = node.of('ERROR')
        assert sorted(a[1] for a in errors) == [
            'excavator_01', 'scout_01', 'scout_02']
        assert all('wheels are turning and the body is not' in a[2]
                   for a in errors), errors
        assert all('0.30 m/s and 0.00 rad/s' in a[2] for a in errors), (
            'the yaw rate is missing from the alert, so a robot pushing into '
            'an obstacle reads the same as one pivoting against it -- and the '
            'field would then be stored with no production reader at all')

    def test_both_alerts_are_latched_against_a_1_hz_flood(self):
        m, sim = self._dead_simulator()
        node = _FakeNode(m, sim)
        for _ in range(10):
            node.check()
        assert len(node.of('CRITICAL')) == 1
        assert len(node.of('ERROR')) == 3

    def test_recovery_is_announced_once_and_names_who_resumed(self):
        m, sim = self._dead_simulator()
        node = _FakeNode(m, sim)
        node.check()
        node.alerts.clear()

        sim.step(5.0, moving=('scout_01', 'scout_02', 'excavator_01'))
        for _ in range(5):
            node.check()

        infos = node.of('INFO')
        fleet_infos = [a for a in infos if a[1] == '']
        robot_infos = [a for a in infos if a[1] != '']
        assert len(fleet_infos) == 1, infos
        assert 'has cleared' in fleet_infos[0][2]
        assert sorted(a[1] for a in robot_infos) == [
            'excavator_01', 'scout_01', 'scout_02']
        # And it can fire again on the next episode.
        sim.step(STALL_SEC + 1.0)
        node.check()
        assert len(node.of('CRITICAL')) == 1

    def test_one_wedged_robot_produces_an_error_and_no_critical(self):
        """D-30 run A, end to end through the message layer."""
        parked = [f'parked_{i:02d}' for i in range(9)]
        m, sim = _fleet(*parked, 'scout_04', fsm_state='WORKING')
        sim.set_state('scout_04', 'NAVIGATING')
        sim.step(60.0)

        node = _FakeNode(m, sim)
        node.check()
        assert node.of('CRITICAL') == []
        (error,) = node.of('ERROR')
        assert error[1] == 'scout_04'
        assert '1 of 1 robot(s) expected to be moving' in error[2]
        assert 'not being driven either' in error[2], (
            'a robot with its wheels stopped is being described as slipping')

    def test_a_non_positive_timeout_disables_the_check(self):
        """The documented way to turn it off, exercised rather than assumed."""
        m, sim = self._dead_simulator()
        node = _FakeNode(m, sim, timeout=0.0)
        node.check()
        assert node.alerts == []


# --------------------------------------------------------------------------- #
#  The wiring                                                                  #
# --------------------------------------------------------------------------- #

def _func(name: str) -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TestWiring:
    """A detector nothing calls would leave the degradation just as silent."""

    def test_the_stall_check_runs_on_the_heartbeat_timer(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        heartbeat = _func('_heartbeat_check')
        called = {n.func.attr for n in ast.walk(heartbeat)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert '_check_motion_stalls' in called, (
            'nothing runs the motion-stall check, so a dead simulator is as '
            'silent as it was on 2026-07-31. Calls found: %s'
            % (sorted(called),))

        timer_targets = {a.attr for n in ast.walk(tree)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr == 'create_timer'
                         for a in n.args if isinstance(a, ast.Attribute)}
        assert '_heartbeat_check' in timer_targets

    def test_the_orchestrator_feeds_the_velocity_clause(self):
        """Without this the new clause is a declared-and-never-fed input.

        That is the pattern that has bitten this repository at least five
        times, and one of those cost the mission its whole ISRU cycle. The
        orchestrator dropped ``msg.velocity`` entirely until 2026-07-31.
        """
        on_state = _func('_on_robot_state')
        call = next(n for n in ast.walk(on_state)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == 'update_robot')
        kwargs = {k.arg: ast.unparse(k.value) for k in call.keywords}
        for name in ('velocity_linear', 'velocity_angular', 'pose_valid'):
            assert name in kwargs, (
                f'update_robot is not passed {name}; '
                f'passed: {sorted(kwargs)}')
        assert 'msg.velocity.linear' in kwargs['velocity_linear']
        assert 'msg.velocity.angular' in kwargs['velocity_angular']
        assert 'msg.pose_valid' in kwargs['pose_valid']

    def test_the_alert_is_critical(self):
        """AlertLog.jsx styles CRITICAL differently from WARNING/ERROR.

        A fleet that has all stopped moving makes everything it reports
        meaningless, which is the one thing in this system that warrants the
        top severity.
        """
        check = _func('_report_fleet_motion_stall')
        severities = {n.args[0].value for n in ast.walk(check)
                      if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute)
                      and n.func.attr == '_publish_alert'
                      and n.args and isinstance(n.args[0], ast.Constant)}
        assert 'CRITICAL' in severities, severities

    def test_the_per_robot_alert_is_an_error_not_a_critical(self):
        """One wedged robot is a robot fault, and must not read as more."""
        check = _func('_report_per_robot_stalls')
        severities = {n.args[0].value for n in ast.walk(check)
                      if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute)
                      and n.func.attr == '_publish_alert'
                      and n.args and isinstance(n.args[0], ast.Constant)}
        assert severities == {'ERROR', 'INFO'}, severities

    def test_both_alerts_are_latched(self):
        """1 Hz x an alert is the flood D-20 exists to prevent.

        Checked by the presence of the latch state on both sides of each
        decision rather than by counting publishes, because the publish itself
        needs a node.
        """
        src = SOURCE.read_text(encoding='utf-8')
        assert src.count('self._sim_stalled') >= 4, (
            'the fleet-level alert does not look latched; a CRITICAL '
            'republished at 1 Hz for the rest of the mission is worse than no '
            'alert at all.')
        assert src.count('self._stalled_robots') >= 4, (
            'the per-robot alert does not look latched; one wedged robot would '
            'produce an ERROR every second for the rest of the mission.')

    def test_the_message_reports_a_count_not_a_cause(self):
        """A STRING TEST, and weak — say so rather than pretend otherwise.

        It stops the specific regression D-30 names and nothing more: it cannot
        tell an honest message from a differently-worded dishonest one. It is
        here because the sentence it forbids is the reason the deviation was
        opened -- the alert asserted a cause its measurement could not support.
        """
        src = ast.unparse(_func('_report_fleet_motion_stall'))
        for forbidden in ('FLEET-WIDE ODOMETRY FREEZE',
                          'The whole fleet has stopped moving',
                          'this is not a robot fault'):
            assert forbidden not in src, forbidden
        assert 'OBSERVED, NOT DIAGNOSED' in src
        # The N-of-M shape: both halves of the count must be in the message.
        assert 'len(report.stalled)' in src
        assert 'len(report.movers)' in src

    def test_both_parameters_are_declared_and_read(self):
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
        for name in ('sim_stall_timeout_sec', 'sim_stall_min_movers'):
            assert name in declared, name
            assert name in read, (
                f'{name} is declared and never read — a knob that silently '
                f'does nothing, which is how FR-MAP-1(e) was lost for two '
                f'phases')

    def test_the_declared_default_matches_the_shipped_params_file(self):
        """Two places publish the same number; nothing was checking they agree.

        Not a substitute for test_params_files_are_applied.py, which checks the
        file reaches the node at all. This checks the VALUES have not drifted,
        which is what happens when a threshold is tuned in one of them.
        """
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        defaults = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'declare_parameter'
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[1], ast.Constant)):
                defaults[node.args[0].value] = node.args[1].value
        assert defaults['sim_stall_timeout_sec'] == STALL_SEC
        assert defaults['sim_stall_min_movers'] == MIN_MOVERS

    def test_the_agent_gains_no_simulator_dependency(self):
        """The detector must stay inside the ROS graph.

        The requirement was explicit: do not teach the agent about Gazebo. It
        could not work there anyway — a single robot cannot tell "the simulator
        died" from "I am parked", because its own odometry standing still is
        the normal state of a robot that is idle, charging or drilling. The
        discriminator is that the freeze spans the robots that were driving,
        and only the orchestrator sees the whole fleet.

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
            'motion-stall detector is orchestrator-side precisely so the '
            'agent never has to know what is producing its odometry.'
            % (sorted(offenders),))

        # And the detector itself must not have leaked into the agent.
        agent_text = '\n'.join(
            p.read_text(encoding='utf-8') for p in agent_pkg.rglob('*.py'))
        for symbol in ('assess_motion', 'FleetMotionReport'):
            assert symbol not in agent_text, symbol
