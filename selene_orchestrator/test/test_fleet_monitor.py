"""Tests for FleetMonitor."""

import pytest

from selene_orchestrator.fleet_monitor import (
    DEFAULT_BATTERY_CAPACITY_WH,
    WHEEL_MOTION_EPSILON_MPS,
    FleetMonitor,
)


class TestFleetMonitor:

    def _make_monitor(self, timeout=10.0):
        return FleetMonitor(heartbeat_timeout=timeout)

    def test_update_stores_state(self):
        fm = self._make_monitor()
        fm.update_robot('scout_01', 'scout', 'IDLE', 10.0, 20.0, 0.5,
                        0.85, '', ['prospect'], timestamp=100.0)
        r = fm.get_robot('scout_01')
        assert r is not None
        assert r['robot_type'] == 'scout'
        assert r['fsm_state'] == 'IDLE'
        assert r['pose'] == (10.0, 20.0, 0.5)
        assert r['battery_level'] == 0.85
        assert r['capabilities'] == ['prospect']

    def test_heartbeat_timeout_detected(self):
        fm = self._make_monitor(timeout=5.0)
        fm.update_robot('scout_01', 'scout', 'NAVIGATING', 0, 0, 0,
                        0.9, 'task_1', timestamp=100.0)
        # Not timed out yet
        assert fm.check_heartbeats(current_time=104.0) == []
        # Timed out
        assert fm.check_heartbeats(current_time=106.0) == ['scout_01']

    def test_heartbeat_resets_on_update(self):
        fm = self._make_monitor(timeout=5.0)
        fm.update_robot('scout_01', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=100.0)
        fm.update_robot('scout_01', 'scout', 'IDLE', 1, 0, 0, 0.9, '', timestamp=104.0)
        # 6s after first update, but only 2s after second
        assert fm.check_heartbeats(current_time=106.0) == []

    def test_mark_offline(self):
        fm = self._make_monitor()
        fm.update_robot('scout_01', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=100.0)
        fm.mark_offline('scout_01')
        assert fm.get_robot('scout_01')['fsm_state'] == 'OFFLINE'

    def test_offline_not_checked_for_heartbeat(self):
        fm = self._make_monitor(timeout=5.0)
        fm.update_robot('scout_01', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=100.0)
        fm.mark_offline('scout_01')
        assert fm.check_heartbeats(current_time=200.0) == []

    def test_get_idle_robots(self):
        fm = self._make_monitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=0)
        fm.update_robot('s2', 'scout', 'NAVIGATING', 0, 0, 0, 0.9, '', timestamp=0)
        fm.update_robot('e1', 'excavator', 'IDLE', 0, 0, 0, 0.9, '', timestamp=0)
        idle = fm.get_idle_robots()
        assert 's1' in idle
        assert 'e1' in idle
        assert 's2' not in idle

    def test_get_robots_with_capability(self):
        fm = self._make_monitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.9, '', ['prospect'], timestamp=0)
        fm.update_robot('e1', 'excavator', 'IDLE', 0, 0, 0, 0.9, '', ['excavate'], timestamp=0)
        assert fm.get_robots_with_capability('prospect') == ['s1']
        assert fm.get_robots_with_capability('excavate') == ['e1']
        assert fm.get_robots_with_capability('haul') == []

    def test_unknown_robot_returns_none(self):
        fm = self._make_monitor()
        assert fm.get_robot('nonexistent') is None
        assert fm.get_robot_position('nonexistent') is None

    def test_get_robot_position(self):
        fm = self._make_monitor()
        fm.update_robot('s1', 'scout', 'IDLE', 55.0, 45.0, 1.0, 0.9, '', timestamp=0)
        assert fm.get_robot_position('s1') == (55.0, 45.0)

    def test_get_robot_battery(self):
        fm = self._make_monitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.73, '', timestamp=0)
        assert fm.get_robot_battery('s1') == 0.73
        assert fm.get_robot_battery('unknown') == 0.0

    def test_get_online_count(self):
        fm = self._make_monitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=0)
        fm.update_robot('s2', 'scout', 'NAVIGATING', 0, 0, 0, 0.9, '', timestamp=0)
        assert fm.get_online_count() == 2
        fm.mark_offline('s1')
        assert fm.get_online_count() == 1

    def test_multiple_timeouts(self):
        fm = self._make_monitor(timeout=5.0)
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=100.0)
        fm.update_robot('s2', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=102.0)
        timed_out = fm.check_heartbeats(current_time=106.0)
        assert 's1' in timed_out
        assert 's2' not in timed_out


class TestPositionFix:
    """D-31. A robot without odometry has no position, not (0, 0).

    ``get_robot_position`` returned a confident origin for a robot that had
    never received an odometry message, and ``_survey_reference_position`` (FR-MAP-3)
    averages exactly this accessor over the prospect-capable robots -- so a
    fleet still waiting for odometry dragged the adaptive survey target ~100 m
    toward the world origin. Only the ACCESSOR is gated; the record itself
    stays well-formed for ``get_robot``, which the operator-command paths read.
    """

    def test_get_robot_position_is_none_without_a_fix(self):
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0.0, 0.0, 0.0, 0.9, '',
                        timestamp=0.0, pose_valid=False)
        assert fm.get_robot_position('s1') is None

    def test_a_fix_restores_the_position(self):
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0.0, 0.0, 0.0, 0.9, '',
                        timestamp=0.0, pose_valid=False)
        fm.update_robot('s1', 'scout', 'IDLE', -45.0, -92.0, 0.0, 0.9, '',
                        timestamp=0.5, pose_valid=True)
        assert fm.get_robot_position('s1') == (-45.0, -92.0)

    def test_losing_the_fix_hides_the_stale_position(self):
        """A pose from ten seconds ago is not a position fix now."""
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', -45.0, -92.0, 0.0, 0.9, '',
                        timestamp=0.0, pose_valid=True)
        fm.update_robot('s1', 'scout', 'IDLE', -45.0, -92.0, 0.0, 0.9, '',
                        timestamp=10.0, pose_valid=False)
        assert fm.get_robot_position('s1') is None
        # get_robot still answers, with the flag and the last pose it saw.
        record = fm.get_robot('s1')
        assert record['pose_valid'] is False
        assert record['pose'] == (-45.0, -92.0, 0.0)

    def test_the_default_is_a_fix_so_existing_callers_are_unchanged(self):
        """~40 positional call sites predate the parameter and mean a pose.

        The WIRE default is the opposite (ROS 2 default-initialises bool to
        false, which is the fail-safe direction for a publisher that has not
        been updated). The two defaults disagree deliberately.
        """
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', 1.0, 2.0, 0.0, 0.9, '',
                        timestamp=0.0)
        assert fm.get_robot_position('s1') == (1.0, 2.0)
        assert fm.get_robot('s1')['pose_valid'] is True


class TestWheelTwistOnTheRecord:
    """D-30. The orchestrator dropped ``RobotState.velocity`` entirely."""

    def test_the_twist_magnitudes_are_stored(self):
        fm = FleetMonitor()
        fm.update_robot('h1', 'hauler', 'WORKING', 0, 0, 0, 0.8, '',
                        timestamp=0.0,
                        velocity_linear=-0.395, velocity_angular=1.0)
        record = fm.get_robot('h1')
        assert record['wheel_speed_mps'] == pytest.approx(0.395)
        assert record['wheel_yaw_rate'] == pytest.approx(1.0)

    def test_the_default_is_stopped(self):
        """Every existing call site omits the twist and means "not driven"."""
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.9, '', timestamp=0.0)
        assert fm.get_robot('s1')['wheel_speed_mps'] == 0.0
        assert fm.get_robot('s1')['wheel_speed_mps'] < WHEEL_MOTION_EPSILON_MPS


class TestPerRobotBatteryCapacity:
    """D-06, FR-DASH-7's energy clause.

    A single hardcoded 50 Wh was applied to every robot until 2026-07-30 --
    the scout's RCDL capacity, which understates an excavator (80 Wh) by 37.5%
    and a hauler (65 Wh) by 23%. The capacity is now reported by the robot in
    RobotState.battery_capacity_wh, sourced from its own RCDL.
    """

    def test_a_drop_is_costed_at_the_robots_own_capacity(self):
        fm = FleetMonitor()
        fm.update_robot('excavator_01', 'excavator', 'IDLE', 0, 0, 0,
                        1.0, '', timestamp=0.0, battery_capacity_wh=80.0)
        fm.update_robot('excavator_01', 'excavator', 'WORKING', 0, 0, 0,
                        0.5, '', timestamp=1.0, battery_capacity_wh=80.0)
        # 0.5 of an 80 Wh battery is 40 Wh, not the 25 Wh a fixed 50 would give.
        assert fm.get_robot_energy_consumed('excavator_01') == pytest.approx(40.0)
        assert fm.get_total_energy_consumed() == pytest.approx(40.0)

    def test_robots_are_costed_independently(self):
        fm = FleetMonitor()
        for rid, rtype, cap in (('scout_01', 'scout', 50.0),
                                ('hauler_01', 'hauler', 65.0)):
            fm.update_robot(rid, rtype, 'IDLE', 0, 0, 0, 1.0, '',
                            timestamp=0.0, battery_capacity_wh=cap)
            fm.update_robot(rid, rtype, 'NAVIGATING', 0, 0, 0, 0.8, '',
                            timestamp=1.0, battery_capacity_wh=cap)
        assert fm.get_robot_energy_consumed('scout_01') == pytest.approx(10.0)
        assert fm.get_robot_energy_consumed('hauler_01') == pytest.approx(13.0)
        assert fm.get_total_energy_consumed() == pytest.approx(23.0)

    def test_zero_capacity_falls_back_rather_than_reporting_no_energy(self):
        """An agent built before the field exists, or one whose HAL raised
        while reading it, must still report plausible energy."""
        fm = FleetMonitor()
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 1.0, '', timestamp=0.0)
        fm.update_robot('s1', 'scout', 'IDLE', 0, 0, 0, 0.5, '', timestamp=1.0)
        assert fm.get_robot_energy_consumed('s1') == pytest.approx(
            0.5 * DEFAULT_BATTERY_CAPACITY_WH)
        assert fm.get_robot_capacity_wh('s1') == DEFAULT_BATTERY_CAPACITY_WH

    def test_a_non_finite_capacity_is_ignored(self):
        fm = FleetMonitor()
        fm.update_robot('h1', 'hauler', 'IDLE', 0, 0, 0, 1.0, '',
                        timestamp=0.0, battery_capacity_wh=float('nan'))
        fm.update_robot('h1', 'hauler', 'IDLE', 0, 0, 0, 0.5, '',
                        timestamp=1.0, battery_capacity_wh=float('inf'))
        assert fm.get_robot_energy_consumed('h1') == pytest.approx(
            0.5 * DEFAULT_BATTERY_CAPACITY_WH)

    def test_a_reported_capacity_is_latched_against_a_single_bad_sample(self):
        """One malformed message must not swing the integration between two
        capacities mid-mission."""
        fm = FleetMonitor()
        fm.update_robot('e1', 'excavator', 'IDLE', 0, 0, 0, 1.0, '',
                        timestamp=0.0, battery_capacity_wh=80.0)
        fm.update_robot('e1', 'excavator', 'WORKING', 0, 0, 0, 0.5, '',
                        timestamp=1.0, battery_capacity_wh=0.0)
        assert fm.get_robot_capacity_wh('e1') == 80.0
        assert fm.get_robot_energy_consumed('e1') == pytest.approx(40.0)

    def test_charging_is_still_ignored(self):
        fm = FleetMonitor()
        fm.update_robot('e1', 'excavator', 'RECHARGING', 0, 0, 0, 0.2, '',
                        timestamp=0.0, battery_capacity_wh=80.0)
        fm.update_robot('e1', 'excavator', 'IDLE', 0, 0, 0, 0.9, '',
                        timestamp=1.0, battery_capacity_wh=80.0)
        assert fm.get_total_energy_consumed() == pytest.approx(0.0)

    def test_capacity_is_exposed_on_the_robot_record(self):
        fm = FleetMonitor()
        fm.update_robot('h1', 'hauler', 'IDLE', 0, 0, 0, 1.0, '',
                        timestamp=0.0, battery_capacity_wh=65.0)
        assert fm.get_robot('h1')['battery_capacity_wh'] == 65.0
