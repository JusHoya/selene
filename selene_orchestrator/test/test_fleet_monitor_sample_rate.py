"""FleetMonitor must survive a faster, irregular RobotState — contract C4.

WHY THIS FILE EXISTS. RobotState used to arrive only on a 0.5 s timer. It is now
published on every FSM transition as well (D-34: a 0.25-0.30 s IDLE hand-off is
invisible to a 0.5 s sampler, so a consumer of ``/<rid>/state`` -- the gate probe
and the dashboard included -- could not see a task change hands). Every consumer
therefore sees a HIGHER and IRREGULAR sample rate: bursts of two or three
messages milliseconds apart, then a normal timer tick.

``FleetMonitor`` is the orchestrator's consumer and it publishes four numbers
that could plausibly depend on how often it is fed: fleet distance, fleet
energy, the IDLE-arrival counter that D-20's auction backoff wakes on, and the
motion-stall assessment. This file asserts that none of them does.

READ THE LABELS. Some of these are REGRESSION tests -- they fail on a plausible
wrong implementation. Others are CHARACTERIZATION PINS: they pass on the code as
it stands and on the code as it stood before, and they exist so that a future
change cannot quietly introduce a rate dependence. Each says which it is, in its
own docstring, because a pin presented as a regression test is a claim about
evidence that is not true.

AND READ THE LIMIT. Sample count has no effect on distance ONLY because the
accumulator integrates increments between successive poses and the trajectories
here are noiseless. With per-sample noise, more samples DO integrate more path
-- that is arithmetic, not a defect, and
``test_more_samples_integrate_more_noise`` measures it rather than leaving it
implied. The system's real defence against that is the localisation pose being
the simulator's true world pose (D-24), not anything in this class.

Nothing here was run against ROS.
"""

import math

import pytest

from selene_orchestrator.fleet_monitor import FleetMonitor

STALL_SEC = 10.0


def _push(m, rid, x, y, ts, *, fsm_state='NAVIGATING', battery=0.8,
          velocity=0.0, pose_valid=True):
    m.update_robot(
        robot_id=rid, robot_type='scout', fsm_state=fsm_state,
        pose_x=x, pose_y=y, pose_theta=0.0,
        battery_level=battery, current_task_id='', capabilities=[],
        timestamp=ts, pose_valid=pose_valid, velocity_linear=velocity)


def _straight_line_distance(samples: int) -> float:
    """Integrate a 100 m straight line at *samples* evenly spaced points."""
    m = FleetMonitor()
    for i in range(samples + 1):
        _push(m, 'scout_01', 100.0 * i / samples, 0.0, 10.0 * i / samples)
    return m.get_total_distance()


class TestDistance:

    def test_distance_does_not_depend_on_sample_count(self):
        """CHARACTERIZATION PIN, not a regression test.

        It passes on the pre-change code as well, because the accumulator sums
        |Δpose| between successive samples and the sum of the parts of a
        straight segment is the segment. Measured before this change at 200 and
        1600 samples: exactly 100.0000 m at both. It is pinned because the
        obvious wrong implementations -- multiplying a speed by a fixed period,
        or dividing by an assumed sample count -- would be invisible under the
        old fixed-rate topic and would go wrong the moment transition publishing
        landed.
        """
        reference = _straight_line_distance(200)
        assert reference == pytest.approx(100.0, abs=1e-9)
        for samples in (2, 20, 200, 1600):
            assert _straight_line_distance(samples) == pytest.approx(
                reference, abs=1e-9), samples

    def test_a_transition_burst_between_timer_ticks_adds_nothing(self):
        """REGRESSION test for the shape transition publishing actually has.

        Not "more samples along the path" but "several samples at almost the
        same instant", which is what an FSM transition produces: the state
        changed, the pose did not have time to. If anything in the accumulator
        booked a per-message constant, this would show it and the smooth-path
        test above would not.
        """
        timer_only = FleetMonitor()
        with_bursts = FleetMonitor()
        for i in range(20):
            x = 0.5 * i
            ts = 0.5 * i
            _push(timer_only, 'scout_01', x, 0.0, ts)
            _push(with_bursts, 'scout_01', x, 0.0, ts)
            # Two extra messages 1 ms apart, as a state change would produce.
            _push(with_bursts, 'scout_01', x, 0.0, ts + 0.001,
                  fsm_state='WORKING')
            _push(with_bursts, 'scout_01', x, 0.0, ts + 0.002,
                  fsm_state='NAVIGATING')

        assert with_bursts.get_total_distance() == pytest.approx(
            timer_only.get_total_distance(), abs=1e-9)

    def test_more_samples_integrate_more_noise(self):
        """THE LIMIT OF THE PIN ABOVE, measured rather than assumed.

        Sampling a noisy pose more often integrates more of the noise. This is
        arithmetic and it is not repaired by anything in FleetMonitor; it is why
        the pin above uses a noiseless trajectory and why the honest description
        of ``fleet_distance_total`` is "the polyline of the poses it was given".
        Under ``pose_source: localisation`` the pose is the simulator's true
        world pose, so the noise term is ~0; under dead_reckoning it is not.
        """
        def integrate(samples):
            m = FleetMonitor()
            for i in range(samples + 1):
                jitter = 0.002 * math.sin(i * 12.9898)
                _push(m, 'scout_01', 100.0 * i / samples + jitter, jitter,
                      10.0 * i / samples)
            return m.get_total_distance()

        sparse = integrate(50)
        dense = integrate(2000)
        assert dense > sparse, (
            'the noise term vanished; either the fixture stopped being noisy '
            'or a motion floor was added to the accumulator, which would '
            'discard real slow motion')


class TestIdleArrivals:
    """D-20's auction wake. The counter that a burst could plausibly double."""

    def test_an_idle_arrival_is_counted_once_however_many_samples_carry_it(
            self):
        """REGRESSION test: the counter is a TRANSITION, not a membership.

        ``_wake_on_fleet_change`` re-opens every abandoned task when this rises,
        so counting IDLE membership rather than IDLE arrivals would reset the
        auction backoff on every tick -- the exact 261-round flood D-20 was
        opened for. With transition publishing there are now MORE samples in
        IDLE, so the distinction went from theoretical to load-bearing.
        """
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0, fsm_state='WORKING')
        before = m.idle_arrivals

        # The transition sample, then eight timer samples in the same state.
        for i in range(9):
            _push(m, 'scout_01', 0.0, 0.0, 1.0 + 0.5 * i, fsm_state='IDLE')

        assert m.idle_arrivals == before + 1

    def test_a_short_idle_now_visible_to_transition_publishing_is_counted(self):
        """A BEHAVIOUR CHANGE, asserted so it is not mistaken for a defect.

        D-34 measured that a 0.25-0.30 s IDLE hand-off between two tasks cannot
        be seen by a 0.5 s sampler. Transition publishing makes it visible, so
        ``idle_arrivals`` now rises on hand-offs the orchestrator previously
        missed entirely and abandoned tasks are re-auctioned more promptly. That
        is the correct direction -- the counter's job is to notice that the
        fleet changed -- but it IS a change in observed behaviour, not a no-op.
        """
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0, fsm_state='WORKING')
        before = m.idle_arrivals
        # A transition pair the 0.5 s timer would have straddled entirely.
        _push(m, 'scout_01', 0.0, 0.0, 0.10, fsm_state='IDLE')
        _push(m, 'scout_01', 0.0, 0.0, 0.38, fsm_state='BIDDING')
        assert m.idle_arrivals == before + 1


class TestEnergy:

    def test_energy_does_not_depend_on_sample_count(self):
        """CHARACTERIZATION PIN. Monotone discharge only.

        Positive battery drops telescope, so splitting one drop into many
        gives the same Wh. It stops being true if the reported state of charge
        ever oscillates, which is a property of ``selene_sim/battery_node.py``
        and not of this class -- ``get_total_energy_consumed``'s own docstring
        says it integrates the REPORTED charge and measures no current.
        """
        def consume(samples):
            m = FleetMonitor()
            for i in range(samples + 1):
                _push(m, 'scout_01', 0.0, 0.0, float(i),
                      battery=1.0 - 0.5 * i / samples)
            return m.get_total_energy_consumed()

        assert consume(2) == pytest.approx(consume(500), abs=1e-9)
        assert consume(500) == pytest.approx(25.0)   # 0.5 x 50 Wh fallback


class TestMotionAssessment:

    def test_the_expectation_clock_starts_once_and_does_not_restart(self):
        """REGRESSION test, and the one that matters most for C4.

        ``_motion_expected_since`` is written only when it is currently None. If
        it were written on every sample in a motion state, a robot would never
        accumulate stationary time at all and the stall detector would be dead
        -- and a burst of transition samples would make that failure MORE
        likely, not less.
        """
        m = FleetMonitor()
        _push(m, 'scout_01', 0.0, 0.0, 0.0)
        for i in range(1, 60):
            _push(m, 'scout_01', 0.0, 0.0, 0.5 * i)
            # A transition burst on top of every timer tick.
            _push(m, 'scout_01', 0.0, 0.0, 0.5 * i + 0.001)

        report = m.assess_motion(STALL_SEC, 0.5 * 59 + 0.002)
        assert report.stalled_ids == ['scout_01']
        assert report.stalled[0].stationary_sec == pytest.approx(
            0.5 * 59 + 0.002, abs=1e-6)

    def test_the_assessment_is_identical_at_two_sample_rates(self):
        """CHARACTERIZATION PIN over the whole report.

        Same 40 s of wall clock, same trajectory, one fed at the timer rate and
        one fed at four times it. Everything the report exposes must agree.
        """
        def run(period):
            m = FleetMonitor()
            ticks = int(40.0 / period)
            for i in range(ticks + 1):
                t = period * i
                # Drives for 10 s, then freezes with its wheels still turning.
                x = 0.3 * min(t, 10.0)
                _push(m, 'scout_01', x, 0.0, t, velocity=0.3)
                _push(m, 'hauler_01', x, 5.0, t, velocity=0.3)
            return m.assess_motion(STALL_SEC, period * ticks)

        slow, fast = run(0.5), run(0.125)
        assert slow.online == fast.online
        assert slow.movers == fast.movers
        assert slow.stalled_ids == fast.stalled_ids
        assert slow.no_fix == fast.no_fix
        assert slow.fleet_wide(2) is fast.fleet_wide(2) is True
        assert slow.longest_stationary_sec == pytest.approx(
            fast.longest_stationary_sec, abs=0.5)


class TestHeartbeats:

    def test_extra_samples_only_make_the_heartbeat_healthier(self):
        """A faster topic cannot cause a heartbeat timeout. Stated because a
        rate change is exactly the sort of thing that gets blamed for one."""
        m = FleetMonitor(heartbeat_timeout=5.0)
        _push(m, 'scout_01', 0.0, 0.0, 100.0)
        _push(m, 'scout_01', 0.0, 0.0, 100.001, fsm_state='WORKING')
        assert m.check_heartbeats(current_time=104.0) == []
        assert m.check_heartbeats(current_time=106.0) == ['scout_01']
