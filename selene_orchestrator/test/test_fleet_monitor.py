"""Tests for FleetMonitor."""

import pytest
from selene_orchestrator.fleet_monitor import FleetMonitor


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
