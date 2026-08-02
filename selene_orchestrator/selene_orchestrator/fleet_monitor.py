"""Fleet state monitoring and heartbeat timeout detection."""

import math
import time
from dataclasses import dataclass


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
#
# It is also NOT SUFFICIENT on its own, and that is why the wheel-speed clause
# below exists. The FSM leaves NAVIGATING as soon as the haul skill's phase is
# no longer NAVIGATING_TO_PICKUP (selene_agent/agent_node.py:502-517,
# selene_agent/skills/haul.py:12-16), so HaulPhase.NAVIGATING_TO_DEPOT -- the
# leg the D-23/D-25 hauler pinned on for 320.7 s -- is reported as WORKING and
# is invisible to this tuple.
MOTION_STATES = ('NAVIGATING', 'RETURNING')

# How fast a robot's WHEELS must be turning for it to count as "being driven",
# metres per second of reported body speed. D-30.
#
# This is the honest substitute for "the orchestrator saw a non-zero velocity
# command". cmd_vel is published per robot by the HAL on /<robot_id>/cmd_vel
# (selene_hal/gazebo_hal.py:696) and the orchestrator subscribes to no such
# topic -- its only per-robot subscription is /<rid>/state. What IS on that
# topic is the ENCODER twist: RobotState.velocity, filled by the agent from the
# odometry sensor's linear/angular velocity, and copied unchanged from the
# wheel odometry by world_odometry_node in both pose_source modes. So one
# message carries the localisation pose and the wheel speed, which is exactly
# the pair "wheels turning, body not" needs.
#
# 0.05 m/s is bracketed, not chosen:
#   floor   0.02 m/s -- POSE_MOTION_EPSILON_M (0.01 m) over the nominal 0.5 s
#                       RobotState period is the slowest motion the pose test
#                       can resolve at all; anything below it would call a
#                       legitimately creeping robot stalled.
#   ceiling 0.30 m/s -- the slowest RCDL max_speed in the fleet
#                       (selene_hal/config/excavator.yaml). 0.05 is a sixth of
#                       it, so a robot crawling at a sixth of its top speed
#                       still counts as being driven.
# The margin above the floor (2.5x) is a judgement, not a measurement.
#
# CAVEAT, stated because a future mode switch would silently delete this
# coverage: under ``pose_source: dead_reckoning`` the pose is integrated from
# the same encoders that produce this twist, so a pinned robot's pose advances
# with its wheels and the clause adds nothing. The new coverage is a property
# of the LOCALISATION pose (D-24), not of this file. D-24 also records that
# dead_reckoning mode has never been run.
WHEEL_MOTION_EPSILON_MPS = 0.05

# Pose increments at or above this are refused by the distance accumulator,
# metres.
#
# READ THIS BEFORE TOUCHING IT. This gate is NOT the D-31 repair and must not
# be presented as one. It was sized for a respawn, and it admitted every single
# one of the fabricated-origin increments that caused D-31: two (0, 0) samples
# followed by the true spawn pose books 90.050 m (scout_03) to 127.224 m
# (hauler_02) per robot, 1096.580 m over the shipped ten-robot fleet
# (selene_sim/config/spawn_positions.yaml), and 500 m admits all of them. The
# repair is ``pose_valid``; this is an instrument that could not see the fault.
# ``test_fleet_distance.py::test_the_500_m_gate_admits_every_phantom_increment``
# holds that attribution executable.
#
# WHY IT WAS NOT REPLACED BY A KINEMATIC BOUND. The obvious improvement --
# max_speed x margin x dt -- needs a dt, and the only timestamp update_robot
# receives is ``time.monotonic()`` taken at ARRIVAL in the subscriber callback
# (orchestrator_node.py:_on_robot_state). After an executor stall, queued
# samples arrive back to back, dt collapses toward zero, the bound collapses
# with it and REAL increments are dropped silently -- a worse defect than the
# one being fixed, and the same shape. Using RobotState.stamp instead would put
# a second clock domain into a class whose heartbeat and stall logic are all on
# the monotonic clock, with ``use_sim_time`` set by nothing. Neither was worth
# it here, so the gate stays where it was and its rejections stopped being
# silent instead: see ``get_distance_rejections``.
MAX_PLAUSIBLE_POSE_JUMP_M = 500.0

# How many rejected increments to keep per robot. A COUNT IS NOT ENOUGH: eight
# rejections could be eight 2.6 m simulator hiccups or four 166 m localisation
# flips, and the second of those is an un-eliminated candidate mechanism for
# the rest of D-31's fleet-distance excess. So the magnitude and both poses are
# kept. Bounded because this is memory in a long-running node.
DISTANCE_REJECTION_HISTORY = 16


def _finite_abs(value) -> float:
    """``abs(float(value))``, or 0.0 for anything that is not a finite number.

    The twist arrives from a HAL read wrapped in the agent's ``try/except``, so
    a NaN or an inf is possible and would poison a comparison silently: NaN
    fails every ``>`` test, so a robot reporting NaN wheel speed would simply
    never count as being driven. Coerced here rather than at the call site so
    the ~40 existing positional callers cannot bypass it.
    """
    try:
        out = abs(float(value))
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


@dataclass(frozen=True)
class RobotStall:
    """One robot that was expected to be moving and was not.

    ``stationary_sec`` is time spent stationary WHILE EXPECTED TO MOVE, not
    time since the pose last changed -- see ``FleetMonitor.assess_motion``.
    """

    robot_id: str
    fsm_state: str
    stationary_sec: float
    wheel_speed_mps: float
    #: Yaw rate magnitude, rad/s. Carried because it separates two failures the
    #: linear speed alone cannot: a robot pushing into an obstacle reports
    #: forward speed with no yaw, while one pivoting against a wall reports
    #: yaw with little forward speed. It is NOT part of the expected-to-move
    #: test -- PathFollower never commands zero linear velocity while
    #: FOLLOWING, so a pure pivot does not occur in this system, and adding a
    #: yaw threshold would mean inventing a constant nothing here derives.
    wheel_yaw_rate: float


@dataclass(frozen=True)
class FleetMotionReport:
    """What ``assess_motion`` observed. An OBSERVATION, not a diagnosis.

    Four disjoint-ish groups, and the distinction between them is the whole
    content of D-30:

    * ``online``     -- every non-OFFLINE robot.
    * ``movers``     -- those currently expected to move (motion FSM state, or
                        wheels turning). A parked robot is NOT a mover, so it
                        contributes no evidence either way; the old predicate
                        counted parked robots as "stalled" and they satisfied
                        its all-robots clause for free.
    * ``stalled``    -- movers that have not moved for longer than the
                        threshold. Always a subset of ``movers``.
    * ``no_fix``     -- online robots whose last RobotState said
                        ``pose_valid=False``. There is no position measurement
                        for them, so they are neither movers nor stalled. They
                        are listed rather than dropped because "the whole fleet
                        lost its position fix" must not look like "the whole
                        fleet is fine".
    """

    online: list[str]
    movers: list[str]
    stalled: list[RobotStall]
    no_fix: list[str]

    @property
    def longest_stationary_sec(self) -> float:
        return max((s.stationary_sec for s in self.stalled), default=0.0)

    @property
    def stalled_ids(self) -> list[str]:
        return [s.robot_id for s in self.stalled]

    def fleet_wide(self, min_movers: int) -> bool:
        """Is there enough evidence to make a claim about the whole fleet?

        Every mover stalled, AND at least ``min_movers`` of them. The floor of
        2 is not configurable downward: D-30 was opened because one wedged
        scout among nine parked robots produced output BIT-IDENTICAL to a dead
        simulator, so a single witness cannot support a fleet-level cause. Two
        can. This still is not proof -- two robots can wedge at once -- which
        is why the alert built on it reports the count and withholds the cause.
        """
        floor = max(2, int(min_movers))
        return len(self.movers) >= floor and len(self.stalled) == len(self.movers)


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
        # Robots whose bid was discarded because the auction they bid on was
        # ABORTED rather than resolved -- see ``note_stranded_bidders`` and the
        # BIDDING branch of ``_note_idle_arrival``. A set, not a count: the
        # question asked of it is "did THIS robot lose its auction to an abort?"
        # and it has to be answered once and then forgotten.
        self._stranded_bidders: set[str] = set()
        # D-21: when each robot's pose last actually changed. See
        # ``assess_motion``.
        self._last_pose_change: dict[str, float] = {}
        # D-30: when each robot most recently STARTED being expected to move,
        # or None while it is not expected to move at all. Started once and
        # never restarted while the expectation holds, so a robot that is
        # driving normally is measured from the moment it began driving.
        #
        # This is the state the old detector did not have. It compared "time
        # since this robot last moved 1 cm" against the threshold -- a clock
        # that RUNS WHILE A ROBOT IS PARKED -- so a robot that had sat in IDLE
        # for 60 s was already "stalled" at the instant its FSM flipped to
        # NAVIGATING, with zero seconds of actual failure.
        self._motion_expected_since: dict[str, float | None] = {}
        # D-31: pose increments the accumulator refused, per robot, with their
        # magnitudes. See ``MAX_PLAUSIBLE_POSE_JUMP_M`` and
        # ``get_distance_rejections``.
        self._distance_rejections: dict[str, list[dict]] = {}
        self._distance_rejection_count: int = 0

    def update_robot(self, robot_id: str, robot_type: str, fsm_state: str,
                     pose_x: float, pose_y: float, pose_theta: float,
                     battery_level: float, current_task_id: str,
                     capabilities: list[str] | None = None,
                     timestamp: float | None = None,
                     battery_capacity_wh: float = 0.0,
                     pose_valid: bool = True,
                     velocity_linear: float = 0.0,
                     velocity_angular: float = 0.0) -> None:
        """Update robot state from a RobotState message. Resets heartbeat.

        ``battery_capacity_wh``, ``pose_valid``, ``velocity_linear`` and
        ``velocity_angular`` are trailing and defaulted so every existing
        positional call site is unaffected. 0.0 (or a non-finite value) for the
        capacity means "this robot did not tell us", and the fallback capacity
        is used.

        ``pose_valid=False`` means the robot HAS NO POSITION FIX and the
        (pose_x, pose_y, pose_theta) it just sent is not a measurement -- see
        RobotState.msg and D-31. The default is True because ~40 existing test
        call sites predate the parameter and mean a real pose; the WIRE
        default, in the message, is False, which is the fail-safe direction.
        The two defaults disagree deliberately and for different reasons.

        SAMPLE RATE IS NOT ASSUMED ANYWHERE IN HERE. RobotState is published on
        a 0.5 s timer AND on every FSM transition, so samples arrive faster than
        2 Hz and at irregular spacing. Nothing in this method divides by a
        period or counts samples: distance integrates increments, the stall
        clocks are timestamps, and the energy sum takes positive battery deltas.
        Adding samples to a noiseless trajectory therefore changes no output --
        pinned by test_fleet_monitor_sample_rate.py, which also states what that
        pin does NOT cover (per-sample noise, which more samples DO integrate).
        """
        ts = timestamp if timestamp is not None else time.monotonic()

        capacity = self._resolve_capacity_wh(robot_id, battery_capacity_wh)
        wheel_speed = _finite_abs(velocity_linear)
        wheel_yaw_rate = _finite_abs(velocity_angular)
        has_fix = bool(pose_valid)

        # Mission start: first heartbeat from any robot anchors uptime.
        if self._mission_start_stamp is None:
            self._mission_start_stamp = ts

        self._note_idle_arrival(robot_id, fsm_state)

        if has_fix:
            # Distance traveled: integrate Euclidean increments between
            # samples. Only ever between two REAL poses -- see the else branch.
            prev_pose = self._last_pose.get(robot_id)
            if prev_pose is not None:
                dx = pose_x - prev_pose[0]
                dy = pose_y - prev_pose[1]
                increment = math.hypot(dx, dy)
                if increment < MAX_PLAUSIBLE_POSE_JUMP_M:
                    self._distance_traveled[robot_id] = (
                        self._distance_traveled.get(robot_id, 0.0) + increment
                    )
                else:
                    self._record_distance_rejection(
                        robot_id, increment, prev_pose, (pose_x, pose_y), ts)
                # D-21: remember WHEN it last moved, not only how far it has
                # been.
                if increment >= POSE_MOTION_EPSILON_M:
                    self._last_pose_change[robot_id] = ts
            else:
                self._distance_traveled.setdefault(robot_id, 0.0)
                # First sample, or the first after a gap in the fix: treat
                # arrival as motion, so a robot that has only ever been seen
                # once is not immediately reported as stalled.
                self._last_pose_change[robot_id] = ts
            self._last_pose[robot_id] = (pose_x, pose_y)
        else:
            # NO FIX. D-31, and the load-bearing branch of this whole change.
            #
            # Three things happen, and each has to.
            #
            # 1. The anchor is FORGOTTEN (`pop`, not "left alone"). The next
            #    valid pose then SEEDS the accumulator rather than incrementing
            #    against a pose from before the gap. At startup the anchor does
            #    not exist yet and this is what stops |spawn| being booked; in
            #    the middle of a run, after a fix outage, it is what stops the
            #    catch-up jump being booked. Both are the same statement: a
            #    path we could not observe is not a path we get to integrate.
            #    The cost is real and is the RIGHT direction -- distance travelled
            #    during a fix outage is lost, so the metric UNDER-reports rather
            #    than over-reporting, and this metric was over-reporting by 2.21x.
            # 2. The distance entry is still created, so a robot that has never
            #    had a fix reports 0.0 m rather than being absent.
            # 3. The stall clock is refreshed rather than left to run, because
            #    a sample with no position in it is not evidence that the robot
            #    failed to move. BE HONEST ABOUT THIS ONE: it is belt and
            #    braces. What actually stops a robot being branded stalled for
            #    an unobserved gap is `max(last_move, since)` in assess_motion
            #    together with the expectation reset below, and a mutation that
            #    deletes this line alone changes no test. It is kept so the
            #    dictionary never holds a stamp that predates a gap, which
            #    would be a trap for the next person to read it.
            self._last_pose.pop(robot_id, None)
            self._distance_traveled.setdefault(robot_id, 0.0)
            self._last_pose_change[robot_id] = ts

        # D-30: is this robot expected to be moving right now?
        #
        # The OR is deliberate and each half covers the other's blind spot: the
        # FSM clause catches a robot driving with its wheels stopped (planning,
        # or commanded to zero), and the wheel clause catches a robot driving
        # in a state the FSM reports as WORKING -- a hauler on
        # HaulPhase.NAVIGATING_TO_DEPOT, which is where D-23/D-25's hauler
        # spent 320.7 s with its wheels at 0.395 m/s and its body at 6.6 cm.
        #
        # Gated on the fix because an expectation we cannot check is not worth
        # holding: assess_motion has no position measurement for a no-fix robot
        # and reports it under `no_fix` instead. A fix outage therefore RESETS
        # the expectation, which under-alerts slightly; that is the safe
        # direction for a detector opened because of false positives.
        expected = has_fix and (
            fsm_state in MOTION_STATES
            or wheel_speed > WHEEL_MOTION_EPSILON_MPS
        )
        if expected:
            if self._motion_expected_since.get(robot_id) is None:
                self._motion_expected_since[robot_id] = ts
        else:
            self._motion_expected_since[robot_id] = None

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
            # D-31. `pose` above is STILL WRITTEN when this is False -- the
            # record has to stay well-formed for get_robot(), which is read on
            # the operator-command paths. Only the position ACCESSOR is gated.
            'pose_valid': has_fix,
            # D-30. Encoder twist magnitudes, so a consumer can tell "not being
            # driven" from "wheels turning, body not".
            'wheel_speed_mps': wheel_speed,
            'wheel_yaw_rate': wheel_yaw_rate,
        }

    def _record_distance_rejection(self, robot_id: str, increment: float,
                                   prev_pose: tuple[float, float],
                                   new_pose: tuple[float, float],
                                   ts: float) -> None:
        """Remember a refused pose increment, WITH ITS MAGNITUDE.

        A filter whose rejects are silent is how D-31 survived a full run: the
        500 m gate discarded whatever it discarded and told nobody, so there
        was no way to tell a 2.6 m simulator hiccup from a 166 m localisation
        flip. The orchestrator logs off this record; see
        ``OrchestratorNode._report_distance_rejections``.
        """
        self._distance_rejection_count += 1
        log = self._distance_rejections.setdefault(robot_id, [])
        log.append({
            # Fleet-wide sequence number, 1-based. It is what lets a consumer
            # log each rejection exactly once off a bounded ring: comparing
            # list lengths cannot, because the ring drops its oldest entry.
            'seq': self._distance_rejection_count,
            'robot_id': robot_id,
            'increment_m': float(increment),
            'prev_pose': (float(prev_pose[0]), float(prev_pose[1])),
            'new_pose': (float(new_pose[0]), float(new_pose[1])),
            'timestamp': float(ts),
        })
        del log[:-DISTANCE_REJECTION_HISTORY]

    @property
    def distance_rejections(self) -> int:
        """Total pose increments the accumulator has refused, fleet-wide."""
        return self._distance_rejection_count

    def get_distance_rejections(self, robot_id: str) -> list[dict]:
        """The last few refused increments for one robot, newest last."""
        return list(self._distance_rejections.get(robot_id, ()))

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

        THE BIDDING EXCLUSION HAS ONE EXCEPTION, ADDED 2026-08-01 WITH EMERGENCY
        PREEMPTION, and it is an exception because the justification above stops
        being true for exactly one transition. "An auction LOSS, the ordinary
        churn of a robot that bid and did not win" describes a round that
        RESOLVED. A preempted auction did not resolve: nothing was won, no task
        left the queue, and the robot's bid was thrown away by
        ``TaskAuction.reset()`` on the orchestrator's own initiative. That robot
        is genuinely new capacity, and it is capacity the preemption itself
        created -- so if it did not count here, the ONE thing that can release a
        backed-off or abandoned task (``wake_deferred_auctions``, driven only by
        ``idle_arrivals``) could never be reached by the capacity a preemption
        frees. ``note_stranded_bidders`` is how the orchestrator names those
        robots; the mark is consumed the first time the robot leaves BIDDING, so
        a robot that goes on to WIN the next auction (BIDDING -> ASSIGNED) does
        not carry a stale mark into some later ordinary loss.
        """
        previous = self._robots.get(robot_id, {}).get('fsm_state')
        stranded = False
        if previous == 'BIDDING' and fsm_state != 'BIDDING':
            # Consumed on ANY exit from BIDDING, not just the IDLE one, so the
            # mark cannot outlive the auction it was written for.
            stranded = robot_id in self._stranded_bidders
            self._stranded_bidders.discard(robot_id)
        if fsm_state != 'IDLE':
            return
        if previous == 'IDLE':
            return
        if previous == 'BIDDING' and not stranded:
            return
        self._idle_arrivals += 1

    def note_stranded_bidders(self, robot_ids) -> None:
        """Record robots whose auction was ABORTED rather than resolved.

        Called by ``orchestrator_node._preempt_for_emergency`` with the bidders
        on the auction it is about to discard. Nothing in this system tells a
        bidder its auction went away -- there is no such message -- so the robot
        sits in BIDDING until its own ``auction_timeout_sec`` (7.0 s,
        ``agent_node``) expires and then returns to IDLE. Without this mark that
        arrival is indistinguishable from an ordinary auction loss and
        ``_note_idle_arrival`` drops it.

        Idempotent, and marking a robot that never becomes idle costs nothing:
        the mark is consumed on the robot's next departure from BIDDING in any
        direction, and a robot that is not in BIDDING at all simply never
        matches.
        """
        self._stranded_bidders.update(str(rid) for rid in robot_ids)

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

    def assess_motion(self, stale_after_sec: float,
                      current_time: float | None = None) -> FleetMotionReport:
        """How long each robot has been EXPECTED TO MOVE and has not — D-30.

        This replaces ``is_fleet_frozen`` / ``get_stalled_robots`` /
        ``get_last_pose_change``, which are deleted rather than left beside it:
        the first had one production caller, the second was used only by the
        first, and the third had zero callers anywhere in the repository.

        WHAT WAS WRONG WITH THE OLD MEASUREMENT, and it was the measurement and
        not the threshold. ``_last_pose_change`` is "when this robot last moved
        1 cm", and that clock RUNS WHILE A ROBOT IS PARKED. Two false positives
        followed, both reproduced against the shipped module before this change:

        * A robot that had sat in IDLE for 60 s carried a 60 s-stale pose clock
          into NAVIGATING, so it was "stalled" at the first sample in the motion
          state -- with 0.0 s of actual failure -- and cleared one heartbeat
          later when it moved.
        * Parked robots are stalled by construction, so ``all online robots
          stalled`` was satisfied for free by the nine parked members of a ten
          robot fleet. One wedged scout among them produced output BIT-IDENTICAL
          to a dead simulator, and the alert built on it asserted "this is not a
          robot fault: the simulator has stopped".

        THE REPAIR is one line: ``stationary = now - max(last_move, since)``.
        History from before the expectation existed is no longer counted as
        evidence of failure. Everything else here is bookkeeping around it.

        WHAT COUNTS AS EXPECTED is set in ``update_robot``: a motion FSM state,
        or wheels turning above ``WHEEL_MOTION_EPSILON_MPS``. A robot with no
        position fix is never a mover -- there is nothing to compare -- and is
        listed under ``no_fix`` so that losing the fleet's position source does
        not read as a healthy fleet.

        OFFLINE robots are excluded: the heartbeat check has already reported
        them and their pose is stale by definition.

        This returns an OBSERVATION and takes no view of the cause. Whether the
        observation supports a fleet-level claim is
        ``FleetMotionReport.fleet_wide``; what to say about it is
        ``OrchestratorNode._check_motion_stalls``.
        """
        now = current_time if current_time is not None else time.monotonic()
        online: list[str] = []
        movers: list[str] = []
        stalled: list[RobotStall] = []
        no_fix: list[str] = []

        for rid, state in self._robots.items():
            if state['fsm_state'] == 'OFFLINE':
                continue
            online.append(rid)
            if not state.get('pose_valid', True):
                no_fix.append(rid)
                continue
            since = self._motion_expected_since.get(rid)
            if since is None:
                continue
            movers.append(rid)
            # Default to `since`, not to 0 or to now: a robot whose expectation
            # started before it ever reported a pose change has been stationary
            # for exactly as long as the expectation has existed.
            last_move = self._last_pose_change.get(rid, since)
            stationary = now - max(last_move, since)
            if stationary > stale_after_sec:
                stalled.append(RobotStall(
                    robot_id=rid,
                    fsm_state=state['fsm_state'],
                    stationary_sec=float(stationary),
                    wheel_speed_mps=float(state.get('wheel_speed_mps', 0.0)),
                    wheel_yaw_rate=float(state.get('wheel_yaw_rate', 0.0)),
                ))

        return FleetMotionReport(online=online, movers=movers,
                                 stalled=stalled, no_fix=no_fix)

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
            # D-30: a robot we have declared dead is not expected to move. It
            # is already excluded by fsm_state in assess_motion, so this is
            # belt and braces -- but leaving a live expectation on an OFFLINE
            # robot would mean a robot that comes back reports the whole
            # offline interval as stationary-while-expected.
            self._motion_expected_since[robot_id] = None

    def get_robot(self, robot_id: str) -> dict | None:
        """Get state dict for a robot, or None if unknown."""
        return self._robots.get(robot_id)

    def get_all_robots(self) -> dict[str, dict]:
        """Return all robot states."""
        return dict(self._robots)

    def get_idle_robots(self) -> list[str]:
        """Return robot_ids currently in IDLE state."""
        return [rid for rid, s in self._robots.items() if s['fsm_state'] == 'IDLE']

    def get_idle_robots_with_capabilities(self, capabilities) -> list[str]:
        """IDLE robots holding EVERY capability in *capabilities*.

        ALL of them, on ONE robot -- not the union across the idle set. A task
        requiring ['excavate', 'haul'] is served by a single vehicle that can do
        both, and a set-union test would report an idle scout plus an idle
        hauler as able to service it.

        An empty or missing requirement matches every idle robot, which is the
        pre-existing behaviour of every task the HTN planner emits without
        explicit capabilities.

        WHY THIS EXISTS. ``_auction_tick``'s idle gate was ``if not idle:
        return`` with no capability test, so a single idle excavator was enough
        to open -- and burn -- a whole auction round for a prospect-only task
        that no idle robot could ever bid on. Each burned round is charged to
        D-20's backoff, and a task inside its backoff is invisible to
        ``get_next_ready``; that is how an operator's EMERGENCY injection could
        put itself to sleep and then watch a priority-5.0 survey take the one
        capable robot. Announcing only what some idle robot could actually bid
        on is the fix, and it is a SKIP rather than a RETURN in the caller so a
        top-priority task nobody can serve does not starve the queue behind it.
        """
        required = set(capabilities or ())
        return [rid for rid, s in self._robots.items()
                if s['fsm_state'] == 'IDLE'
                and required.issubset(set(s['capabilities'] or ()))]

    def get_robots_with_capability(self, capability: str) -> list[str]:
        """Return robot_ids that have the given capability."""
        return [rid for rid, s in self._robots.items()
                if capability in s['capabilities'] and s['fsm_state'] != 'OFFLINE']

    def get_robot_position(self, robot_id: str) -> tuple[float, float] | None:
        """Return (x, y) for a robot, or None if it has no position fix.

        D-31: None for unknown AND for a robot whose last RobotState carried
        ``pose_valid=False``. Before this, a robot that had not yet received
        odometry reported a confident (0.0, 0.0), and the FR-MAP-3 adaptive
        survey centroid averages exactly this accessor over the prospect-capable
        robots -- so a startup fleet dragged the centroid ~100 m toward the
        world origin. The one production caller
        (``OrchestratorNode._survey_reference_position``) already filters None.

        ``get_robot()`` is deliberately NOT gated: it is read on the operator
        command paths and must keep returning a well-formed record. Its
        ``pose_valid`` key says the same thing to anyone who asks.
        """
        r = self._robots.get(robot_id)
        if r and r.get('pose_valid', True):
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
