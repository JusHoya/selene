"""Fleet state monitoring and heartbeat timeout detection."""

import math
import time


# Battery capacity (Wh) used to convert normalised battery_level deltas
# (0..1) into approximate energy consumption. Project default is 50 Wh.
DEFAULT_BATTERY_CAPACITY_WH = 50.0


class FleetMonitor:
    """Tracks robot fleet state and detects heartbeat timeouts."""

    def __init__(self, heartbeat_timeout: float = 10.0,
                 battery_capacity_wh: float = DEFAULT_BATTERY_CAPACITY_WH):
        self._timeout = heartbeat_timeout
        self._battery_capacity_wh = battery_capacity_wh
        self._robots: dict[str, dict] = {}
        # Mission progress accounting (FR-DASH-7 backend support)
        self._last_pose: dict[str, tuple[float, float]] = {}
        self._distance_traveled: dict[str, float] = {}
        self._last_battery: dict[str, float] = {}
        self._energy_consumed: dict[str, float] = {}
        self._mission_start_stamp: float | None = None

    def update_robot(self, robot_id: str, robot_type: str, fsm_state: str,
                     pose_x: float, pose_y: float, pose_theta: float,
                     battery_level: float, current_task_id: str,
                     capabilities: list[str] | None = None,
                     timestamp: float | None = None) -> None:
        """Update robot state from a RobotState message. Resets heartbeat."""
        ts = timestamp if timestamp is not None else time.monotonic()

        # Mission start: first heartbeat from any robot anchors uptime.
        if self._mission_start_stamp is None:
            self._mission_start_stamp = ts

        # Distance traveled: integrate Euclidean increments between samples.
        prev_pose = self._last_pose.get(robot_id)
        if prev_pose is not None:
            dx = pose_x - prev_pose[0]
            dy = pose_y - prev_pose[1]
            increment = math.hypot(dx, dy)
            # Defensive: skip absurd jumps (>500 m) which indicate a respawn
            # rather than legitimate motion.
            if increment < 500.0:
                self._distance_traveled[robot_id] = (
                    self._distance_traveled.get(robot_id, 0.0) + increment
                )
        else:
            self._distance_traveled.setdefault(robot_id, 0.0)
        self._last_pose[robot_id] = (pose_x, pose_y)

        # Energy consumed: running sum of positive battery_level decreases,
        # converted to Wh via the configured battery capacity. Charging
        # increments (battery rising) are deliberately ignored so the metric
        # represents gross consumed energy, not net.
        prev_batt = self._last_battery.get(robot_id)
        if prev_batt is not None:
            drop = prev_batt - battery_level
            if drop > 0.0:
                self._energy_consumed[robot_id] = (
                    self._energy_consumed.get(robot_id, 0.0)
                    + drop * self._battery_capacity_wh
                )
        else:
            self._energy_consumed.setdefault(robot_id, 0.0)
        self._last_battery[robot_id] = battery_level

        self._robots[robot_id] = {
            'robot_id': robot_id,
            'robot_type': robot_type,
            'fsm_state': fsm_state,
            'pose': (pose_x, pose_y, pose_theta),
            'battery_level': battery_level,
            'current_task_id': current_task_id,
            'capabilities': capabilities or [],
            'last_heartbeat': ts,
        }

    def check_heartbeats(self, current_time: float | None = None) -> list[str]:
        """Return robot_ids whose heartbeat has timed out."""
        now = current_time if current_time is not None else time.monotonic()
        timed_out = []
        for rid, state in self._robots.items():
            if state['fsm_state'] == 'OFFLINE':
                continue
            if now - state['last_heartbeat'] > self._timeout:
                timed_out.append(rid)
        return timed_out

    def mark_offline(self, robot_id: str) -> None:
        """Set robot to OFFLINE state."""
        if robot_id in self._robots:
            self._robots[robot_id]['fsm_state'] = 'OFFLINE'

    def get_robot(self, robot_id: str) -> dict | None:
        """Get state dict for a robot, or None if unknown."""
        return self._robots.get(robot_id)

    def get_all_robots(self) -> dict[str, dict]:
        """Return all robot states."""
        return dict(self._robots)

    def get_idle_robots(self) -> list[str]:
        """Return robot_ids currently in IDLE state."""
        return [rid for rid, s in self._robots.items() if s['fsm_state'] == 'IDLE']

    def get_robots_with_capability(self, capability: str) -> list[str]:
        """Return robot_ids that have the given capability."""
        return [rid for rid, s in self._robots.items()
                if capability in s['capabilities'] and s['fsm_state'] != 'OFFLINE']

    def get_robot_position(self, robot_id: str) -> tuple[float, float] | None:
        """Return (x, y) for a robot, or None."""
        r = self._robots.get(robot_id)
        if r:
            return (r['pose'][0], r['pose'][1])
        return None

    def get_robot_task(self, robot_id: str) -> str:
        """Return current_task_id for a robot."""
        r = self._robots.get(robot_id)
        return r['current_task_id'] if r else ''

    def get_robot_battery(self, robot_id: str) -> float:
        """Return battery_level for a robot."""
        r = self._robots.get(robot_id)
        return r['battery_level'] if r else 0.0

    def get_online_count(self) -> int:
        """Count robots not OFFLINE."""
        return sum(1 for s in self._robots.values() if s['fsm_state'] != 'OFFLINE')

    # ------------------------------------------------------------------ #
    #  Mission progress accessors (FR-DASH-7)                              #
    # ------------------------------------------------------------------ #

    def get_total_distance(self) -> float:
        """Return total distance traveled by the entire fleet, in metres."""
        return float(sum(self._distance_traveled.values()))

    def get_total_energy_consumed(self) -> float:
        """Return total energy consumed by the entire fleet, in Wh.

        Approximation: each robot's battery_level is interpreted as a
        normalised state-of-charge (0..1) and multiplied by a fixed
        ``DEFAULT_BATTERY_CAPACITY_WH`` (50 Wh) capacity. Real RCDL-driven
        capacities will replace this in a future revision.
        """
        return float(sum(self._energy_consumed.values()))

    def get_uptime_sec(self, current_time: float | None = None) -> float:
        """Return mission uptime in seconds since the first robot heartbeat."""
        if self._mission_start_stamp is None:
            return 0.0
        now = current_time if current_time is not None else time.monotonic()
        return float(max(0.0, now - self._mission_start_stamp))

    def get_robot_distance(self, robot_id: str) -> float:
        """Return distance traveled (m) for a single robot."""
        return float(self._distance_traveled.get(robot_id, 0.0))

    def get_robot_energy_consumed(self, robot_id: str) -> float:
        """Return energy consumed (Wh) for a single robot."""
        return float(self._energy_consumed.get(robot_id, 0.0))
