"""Fleet state monitoring and heartbeat timeout detection."""

import math
import time


# Fallback battery capacity (Wh) for converting normalised battery_level
# deltas (0..1) into energy. Used only when a robot reports no capacity of its
# own -- an agent built before RobotState carried battery_capacity_wh, or one
# whose HAL raised while reading it.
#
# 50 Wh is the SCOUT's RCDL capacity (selene_hal/config/scout.yaml). It was
# applied to every robot until 2026-07-30, which understated an excavator
# (80 Wh) by 37.5% and a hauler (65 Wh) by 23%. Keeping the scout's number as
# the fallback makes the degraded case plausible rather than zero.
DEFAULT_BATTERY_CAPACITY_WH = 50.0


# How far a robot must move between two RobotState samples for that to count as
# motion, metres. D-21: below this a pose difference is dead-reckoning noise
# rather than a robot going somewhere.
#
# 1 cm against DiffDrive odometry sampled at 2 Hz. A robot at the navigator's
# 0.3 m/s planning speed covers 15 cm per sample, so the margin is 15x; a robot
# creeping at a fifteenth of that still registers. The reason it cannot simply
# be "any change at all" is that a stationary Gazebo model's odometry jitters
# in the last float bits, so an exact comparison would report every parked
# robot as moving and the stall detector would never fire.
POSE_MOTION_EPSILON_M = 0.01

# FSM states in which a robot holds a planned path and a velocity command, and
# is therefore expected to be moving. D-21: the fleet-freeze detector fires only
# when at least one robot is in one of these, so a fleet parked IDLE at the
# depot or RECHARGING at the station never trips it.
#
# WORKING is deliberately absent: an excavator drilling and a hauler waiting on
# a material transfer both legitimately hold still for tens of seconds, and
# calling that a dead simulator would make the alert untrustworthy.
MOTION_STATES = ('NAVIGATING', 'RETURNING')


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
        # Per-robot battery capacity in Wh, as reported by the robot itself in
        # RobotState.battery_capacity_wh (sourced from its RCDL).
        self._robot_capacity_wh: dict[str, float] = {}
        self._mission_start_stamp: float | None = None
        # D-20: monotonically increasing count of robots ARRIVING in IDLE.
        # See ``idle_arrivals``.
        self._idle_arrivals: int = 0
        # D-21: when each robot's pose last actually changed. See
        # ``get_stalled_robots``.
        self._last_pose_change: dict[str, float] = {}

    def update_robot(self, robot_id: str, robot_type: str, fsm_state: str,
                     pose_x: float, pose_y: float, pose_theta: float,
                     battery_level: float, current_task_id: str,
                     capabilities: list[str] | None = None,
                     timestamp: float | None = None,
                     battery_capacity_wh: float = 0.0) -> None:
        """Update robot state from a RobotState message. Resets heartbeat.

        ``battery_capacity_wh`` is trailing and defaulted so every existing
        positional call site is unaffected. 0.0 (or a non-finite value) means
        "this robot did not tell us", and the fallback capacity is used.
        """
        ts = timestamp if timestamp is not None else time.monotonic()

        capacity = self._resolve_capacity_wh(robot_id, battery_capacity_wh)

        # Mission start: first heartbeat from any robot anchors uptime.
        if self._mission_start_stamp is None:
            self._mission_start_stamp = ts

        self._note_idle_arrival(robot_id, fsm_state)

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
            # D-21: remember WHEN it last moved, not only how far it has been.
            if increment >= POSE_MOTION_EPSILON_M:
                self._last_pose_change[robot_id] = ts
        else:
            self._distance_traveled.setdefault(robot_id, 0.0)
            # First sample: treat arrival as motion, so a robot that has only
            # ever been seen once is not immediately reported as stalled.
            self._last_pose_change[robot_id] = ts
        self._last_pose[robot_id] = (pose_x, pose_y)

        # Energy consumed: running sum of positive battery_level decreases,
        # converted to Wh via THIS ROBOT's own capacity. Charging increments
        # (battery rising) are deliberately ignored so the metric represents
        # gross consumed energy, not net.
        prev_batt = self._last_battery.get(robot_id)
        if prev_batt is not None:
            drop = prev_batt - battery_level
            if drop > 0.0:
                self._energy_consumed[robot_id] = (
                    self._energy_consumed.get(robot_id, 0.0)
                    + drop * capacity
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
            'battery_capacity_wh': capacity,
            'last_heartbeat': ts,
        }

    def _note_idle_arrival(self, robot_id: str, fsm_state: str) -> None:
        """Count a robot ARRIVING in IDLE — the D-20 "fleet changed" signal.

        An abandoned auction has to become auctionable again when the fleet
        changes, or the mission deadlocks. "The fleet changed" has to be a
        TRANSITION and not a set membership, and the exclusions below are the
        whole reason this method exists rather than a call to
        ``get_idle_robots()``:

        * ``IDLE -> IDLE`` is not a change. A robot that declines to bid
          (capability mismatch, or ``can_afford_task`` says no) never leaves
          IDLE, which is precisely the fleet state the 261-round flood was
          measured in. Counting membership would reset the backoff on every
          tick and the mechanism would do nothing at all.
        * ``BIDDING -> IDLE`` is not a change either: it is an auction LOSS,
          the ordinary churn of a robot that bid and did not win. Counting it
          would reset the backoff every time some other task's auction ran.

        Everything else is real news -- a robot finishing work (RETURNING or
        WORKING -> IDLE), leaving the charger (RECHARGING -> IDLE), recovering
        from a fault (ERROR -> IDLE via an operator cancel), or appearing for
        the first time.
        """
        previous = self._robots.get(robot_id, {}).get('fsm_state')
        if fsm_state != 'IDLE':
            return
        if previous in ('IDLE', 'BIDDING'):
            return
        self._idle_arrivals += 1

    @property
    def idle_arrivals(self) -> int:
        """Monotonic count of robots arriving in IDLE since construction.

        A counter rather than an event or a callback so the consumer can be a
        timer that compares one int against the one it saw last tick. The
        auction tick already runs at 2 Hz; making it also carry a subscription
        into the task queue would mean mutating the queue from a DDS callback
        thread while a timer on another thread of the MultiThreadedExecutor
        walks it.
        """
        return self._idle_arrivals

    def get_stalled_robots(self, stale_after_sec: float,
                           current_time: float | None = None) -> list[str]:
        """Robot_ids whose pose has not changed for *stale_after_sec*.

        D-21. Frozen odometry is what a dead simulator looks like from inside
        the ROS graph: the agent processes survive, keep ticking and keep
        publishing RobotState at 2 Hz, so ``check_heartbeats`` sees a perfectly
        healthy fleet. What stops is the world.

        This reports staleness per robot and takes no view of what it means --
        a robot parked at the charger is legitimately stalled. Deciding that
        the FLEET is stalled is ``OrchestratorNode._check_simulation_stall``,
        which needs the fsm_state as well.

        OFFLINE robots are excluded: they have already been reported by the
        heartbeat check and their pose is stale by definition.
        """
        now = current_time if current_time is not None else time.monotonic()
        stalled = []
        for rid, state in self._robots.items():
            if state['fsm_state'] == 'OFFLINE':
                continue
            last = self._last_pose_change.get(rid)
            if last is None:
                continue
            if now - last > stale_after_sec:
                stalled.append(rid)
        return stalled

    def get_last_pose_change(self, robot_id: str) -> float | None:
        """Monotonic stamp of a robot's last real pose change, or None."""
        return self._last_pose_change.get(robot_id)

    def is_fleet_frozen(self, stale_after_sec: float,
                        current_time: float | None = None,
                        ) -> tuple[bool, list[str], list[str]]:
        """``(frozen, online_ids, robots_that_should_be_moving)`` — D-21.

        The predicate behind the CRITICAL "the simulator has died" alert. It
        lives here, on the pure-Python class, because it is the only part of
        that alert that can be wrong: the orchestrator's half is a latch and a
        message string.

        BOTH conditions are required, and each rules out a different false
        positive:

        * every online robot is stalled -- one robot wedged against a rock is
          a navigation fault, and it already surfaces as that robot's own
          ERROR. A simulator death is fleet-wide by construction.
        * at least one online robot is NAVIGATING or RETURNING -- those two
          states mean the robot holds a path and a velocity command and is
          EXPECTED to be moving. Without this a fleet that has finished its
          survey and is sitting IDLE at the depot would raise a CRITICAL alert
          on every mission, which is how an alert log becomes wallpaper.

        WORKING is deliberately not a motion state: an excavator drilling and
        a hauler waiting on a transfer both legitimately hold still for tens of
        seconds. RECHARGING and IDLE likewise. So the detector's window is the
        interval during which the fleet is still trying to drive -- which is
        what was observed on 2026-07-31, before the agents gave up and went to
        ERROR.
        """
        now = current_time if current_time is not None else time.monotonic()
        online = [rid for rid, s in self._robots.items()
                  if s['fsm_state'] != 'OFFLINE']
        expected_to_move = [rid for rid in online
                            if self._robots[rid]['fsm_state'] in MOTION_STATES]
        if not online or not expected_to_move:
            return False, online, expected_to_move
        stalled = set(self.get_stalled_robots(stale_after_sec, now))
        frozen = all(rid in stalled for rid in online)
        return frozen, online, expected_to_move

    def _resolve_capacity_wh(self, robot_id: str, reported: float) -> float:
        """Latch this robot's own capacity; fall back when it reports none.

        Latched rather than re-read each sample so a single malformed message
        (0.0 from a HAL exception in the agent's try/except) does not swing the
        energy integration between two capacities mid-mission.
        """
        try:
            value = float(reported)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0.0 and math.isfinite(value):
            self._robot_capacity_wh[robot_id] = value
            return value
        return self._robot_capacity_wh.get(robot_id, self._battery_capacity_wh)

    def get_robot_capacity_wh(self, robot_id: str) -> float:
        """Battery capacity (Wh) in force for a robot, fallback included."""
        return self._robot_capacity_wh.get(robot_id, self._battery_capacity_wh)

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

        WATT-HOURS, not kilowatt-hours: docs/PRD.md:685 (MSG-7) says kWh, the
        dashboard's ``formatWh`` formats Wh and promotes above 1000, and this
        computes Wh. Code and UI agree; the PRD is the outlier.

        Each robot's ``battery_level`` is a normalised state of charge (0..1);
        every positive drop between two samples is multiplied by THAT ROBOT's
        own capacity, reported in ``RobotState.battery_capacity_wh`` from its
        RCDL (scout 50 Wh, excavator 80 Wh, hauler 65 Wh). Until 2026-07-30 a
        single hardcoded 50 Wh was used for the whole fleet -- the previous
        version of this docstring promised "real RCDL-driven capacities will
        replace this in a future revision", and this is that revision.

        Still an approximation, and the part that is: it integrates the
        REPORTED state of charge, so it inherits whatever model
        ``selene_sim/battery_node.py`` uses and measures no current anywhere.
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
