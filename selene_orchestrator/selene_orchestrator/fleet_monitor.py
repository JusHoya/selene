"""Fleet state monitoring and heartbeat timeout detection."""

import time


class FleetMonitor:
    """Tracks robot fleet state and detects heartbeat timeouts."""

    def __init__(self, heartbeat_timeout: float = 10.0):
        self._timeout = heartbeat_timeout
        self._robots: dict[str, dict] = {}

    def update_robot(self, robot_id: str, robot_type: str, fsm_state: str,
                     pose_x: float, pose_y: float, pose_theta: float,
                     battery_level: float, current_task_id: str,
                     capabilities: list[str] | None = None,
                     timestamp: float | None = None) -> None:
        """Update robot state from a RobotState message. Resets heartbeat."""
        self._robots[robot_id] = {
            'robot_id': robot_id,
            'robot_type': robot_type,
            'fsm_state': fsm_state,
            'pose': (pose_x, pose_y, pose_theta),
            'battery_level': battery_level,
            'current_task_id': current_task_id,
            'capabilities': capabilities or [],
            'last_heartbeat': timestamp or time.monotonic(),
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
