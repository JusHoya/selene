#!/usr/bin/env python3
"""D-37 exposure campaign: hold a fleet DRIVING and measure fleet-metres.

WHAT THIS IS FOR
----------------
Register D-37 is three reproducible ODE aborts whose cause is unknown. The entry
names the next experiment -- hold a 4/3/3 fleet driving, with fleet-metres
instrumented as a first-class number, so a per-METRE hazard can be told apart
from a per-SECOND one -- and that experiment had never been run because the fleet
cannot drive long enough: a scout is flat in 43.8 minutes.

THE BLOCKER DISSOLVES AT THIS LAYER, and the reason is worth stating because it
is not obvious. **Nothing in the physics consumes BatteryState.** There is no
``<battery>`` element and no ``LinearBatteryPlugin`` in any
``selene_sim/models/*/model.sdf`` or in ``worlds/lunar_psr.sdf``;
``battery_node`` only publishes, its sole subscriber repo-wide is
``selene_hal/gazebo_hal.py``, and the only two things that ACT on the value live
in ``agent_node``. So a campaign that runs ``simulation.launch.py`` -- which
starts Gazebo, the bridges, ``world_odometry_node`` and the sim sensors, and NO
agent and NO orchestrator -- can drive the wheels directly and a flat battery
stops nothing. The abort is raised inside
``SimulationRunner::Step -> Physics::Update -> dartsim WorldForwardStep ->
ConstraintSolver::solve -> dxHashSpace::collide``; not one line of
``selene_agent`` is on that stack, so removing the agents removes nothing the
hazard depends on.

WHAT IT MEASURES, AND WHAT IT CANNOT
------------------------------------
Two hazard models are on the table (D-37):

    per robot-second   lambda = 1/5040     reject at p<0.05 with 15,098 robot-s
    per fleet-metre    lambda = 1/1274     reject at p<0.05 with  3,817 m

A single DRIVING arm accrues both together, so it can only ever REJECT BOTH --
it cannot distinguish them. Distinguishing needs either an abort, whose exposure
ratio then discriminates, or a second PARKED arm accruing robot-seconds at ~0 m.
This script implements the driving arm, which is the one that can reproduce the
abort, and prints both models' survival probabilities for whatever exposure it
actually achieves rather than for a planned one.

THE OPERATING POINT MATTERS. The clean runs the register already has ran at
0.053 m per robot-second; the three crash runs ran at 0.174, 0.201 and 0.368.
This campaign targets that band and REPORTS what it achieved, because a clean run
at the wrong operating point is what made the previous exposure argument weak.

WHAT IT RECORDS WHEN THE SIMULATOR DIES
---------------------------------------
Per-robot pose extremes, a rolling buffer of the last 20 s of every robot's pose
and twist, the achieved fleet-metres and robot-seconds, and the wall time of the
last message from each robot. D-37's own note is that the archived crash logs are
no longer on disk; this writes its state continuously so the next abort cannot
take its evidence with it.
"""

import argparse
import json
import math
import os
import time
from collections import deque

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from tf2_msgs.msg import TFMessage


#: Hazard fits from register D-37. Both are one-parameter maximum-likelihood
#: fits to the SAME three observed failures, so they are alternatives, not
#: independent estimates.
LAMBDA_PER_ROBOT_SECOND = 1.0 / 5040.0
LAMBDA_PER_FLEET_METRE = 1.0 / 1274.0

#: Seconds of per-robot history kept for the post-mortem dump.
RING_SECONDS = 20.0

#: The ODE heightfield half-extent, exactly 500/129 * 128 / 2. Any pose beyond
#: this is off the collision surface and is reported, though D-37 establishes
#: that leaving the heightfield is NOT what produces the assertion.
HEIGHTFIELD_HALF_EXTENT_M = 248.0620155


class DriveCampaign(Node):
    """Drives every robot on an independent circuit and integrates true metres."""

    def __init__(self, robot_ids, out_dir, speed, radius, report_every):
        super().__init__('d37_drive_campaign')
        self._out_dir = out_dir
        self._speed = speed
        self._radius = radius
        self._report_every = report_every
        self._t0 = time.time()
        self._last_report = 0.0

        self._pubs = {}
        self._truth = {}          # rid -> (x, y, z)
        self._metres = {}         # rid -> integrated true path length
        self._extremes = {}       # rid -> dict of min/max per axis
        self._rings = {}          # rid -> deque of samples
        self._last_msg = {}       # rid -> wall time
        self._driving_since = {}  # rid -> wall time of first pose

        for rid in robot_ids:
            self._pubs[rid] = self.create_publisher(Twist, f'/{rid}/cmd_vel', 10)
            self._metres[rid] = 0.0
            self._rings[rid] = deque(maxlen=int(RING_SECONDS * 20) + 10)
            self._extremes[rid] = {'min_x': math.inf, 'max_x': -math.inf,
                                   'min_y': math.inf, 'max_y': -math.inf,
                                   'min_z': math.inf, 'max_z': -math.inf}
            self.create_subscription(
                TFMessage, f'/{rid}/pose_truth', self._truth_cb(rid), 10)

        self._robot_ids = list(robot_ids)
        self.create_timer(0.1, self._drive)
        self.create_timer(1.0, self._tick)
        self.get_logger().info(
            f'D-37 campaign driving {len(robot_ids)} robots at {speed} m/s on '
            f'{radius} m circuits; artefacts -> {out_dir}')

    # -- inputs --------------------------------------------------------------

    def _truth_cb(self, rid):
        def cb(msg):
            for tf in msg.transforms:
                if tf.child_frame_id and tf.child_frame_id != rid:
                    continue
                t = tf.transform.translation
                now = time.time()
                prev = self._truth.get(rid)
                if prev is not None:
                    d = math.dist((t.x, t.y, t.z), prev)
                    # Reject the one-off spawn settle and any teleport: a robot
                    # cannot move more than speed*dt between two 20 Hz samples.
                    if d < 1.0:
                        self._metres[rid] += d
                self._truth[rid] = (t.x, t.y, t.z)
                self._last_msg[rid] = now
                self._driving_since.setdefault(rid, now)
                e = self._extremes[rid]
                e['min_x'] = min(e['min_x'], t.x)
                e['max_x'] = max(e['max_x'], t.x)
                e['min_y'] = min(e['min_y'], t.y)
                e['max_y'] = max(e['max_y'], t.y)
                e['min_z'] = min(e['min_z'], t.z)
                e['max_z'] = max(e['max_z'], t.z)
                self._rings[rid].append(
                    (round(now - self._t0, 3), round(t.x, 4), round(t.y, 4),
                     round(t.z, 4)))
                if not all(map(math.isfinite, (t.x, t.y, t.z))):
                    self.get_logger().error(
                        f'*** NON-FINITE POSE *** {rid} ({t.x}, {t.y}, {t.z}) -- '
                        f'this is what D-37 predicts precedes the abort')
                    self.dump('non_finite_pose')
                elif max(abs(t.x), abs(t.y)) > HEIGHTFIELD_HALF_EXTENT_M:
                    self.get_logger().warn(
                        f'{rid} is off the heightfield at ({t.x:.1f}, {t.y:.1f})')
                break
        return cb

    # -- outputs -------------------------------------------------------------

    def _drive(self):
        """Every robot on its own circle, so nobody converges on anybody."""
        for i, rid in enumerate(self._robot_ids):
            msg = Twist()
            msg.linear.x = self._speed
            # Alternate turn direction so the fleet spreads rather than convoys.
            sign = 1.0 if i % 2 == 0 else -1.0
            msg.angular.z = sign * self._speed / max(self._radius, 1e-6)
            self._pubs[rid].publish(msg)

    def fleet_metres(self):
        return sum(self._metres.values())

    def robot_seconds(self):
        now = time.time()
        return sum(max(0.0, now - t) for t in self._driving_since.values())

    def _tick(self):
        now = time.time() - self._t0
        if now - self._last_report < self._report_every:
            return
        self._last_report = now
        m = self.fleet_metres()
        rs = self.robot_seconds()
        rate = m / rs if rs > 0 else 0.0
        p_sec = math.exp(-rs * LAMBDA_PER_ROBOT_SECOND)
        p_met = math.exp(-m * LAMBDA_PER_FLEET_METRE)
        self.get_logger().info(
            f'[{now:6.0f}s] fleet-metres {m:8.1f}  robot-seconds {rs:8.0f}  '
            f'rate {rate:.3f} m/robot-s  |  survival: per-second {p_sec:.3f}, '
            f'per-metre {p_met:.3f}')
        self.dump('progress', quiet=True)

    def dump(self, reason, quiet=False):
        m = self.fleet_metres()
        rs = self.robot_seconds()
        rec = {
            'reason': reason,
            'elapsed_s': round(time.time() - self._t0, 2),
            'fleet_metres': round(m, 3),
            'robot_seconds': round(rs, 1),
            'metres_per_robot_second': round(m / rs, 4) if rs > 0 else None,
            'per_robot_second_survival': math.exp(-rs * LAMBDA_PER_ROBOT_SECOND),
            'per_fleet_metre_survival': math.exp(-m * LAMBDA_PER_FLEET_METRE),
            'per_robot_metres': {k: round(v, 2) for k, v in self._metres.items()},
            'extremes': self._extremes,
            'last_message_age_s': {
                k: round(time.time() - v, 2) for k, v in self._last_msg.items()},
        }
        with open(os.path.join(self._out_dir, 'campaign_state.json'), 'w') as fh:
            json.dump(rec, fh, indent=2)
        if reason != 'progress':
            rec['rings'] = {k: list(v) for k, v in self._rings.items()}
            with open(os.path.join(self._out_dir, f'dump_{reason}.json'), 'w') as fh:
                json.dump(rec, fh, indent=2)
        if not quiet:
            self.get_logger().warn(f'state dumped ({reason})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--robots', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--seconds', type=float, default=2700.0)
    ap.add_argument('--speed', type=float, default=0.35,
                    help='m/s; 0.35 over 10 robots lands inside the crash runs 0.17-0.37 band')
    ap.add_argument('--radius', type=float, default=25.0)
    ap.add_argument('--report-every', type=float, default=60.0)
    ap.add_argument('--stall-timeout', type=float, default=15.0,
                    help='seconds with no pose from ANY robot before declaring the simulator dead')
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    rclpy.init()
    node = DriveCampaign([r.strip() for r in args.robots.split(',') if r.strip()],
                         args.out_dir, args.speed, args.radius, args.report_every)
    deadline = time.time() + args.seconds
    try:
        while rclpy.ok() and time.time() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            if node._last_msg:
                quiet_for = time.time() - max(node._last_msg.values())
                if quiet_for > args.stall_timeout:
                    node.get_logger().error(
                        f'*** NO POSE FROM ANY ROBOT FOR {quiet_for:.1f}s *** '
                        f'the simulator has stopped. Dumping and exiting.')
                    node.dump('simulator_stopped')
                    break
    except KeyboardInterrupt:
        node.dump('interrupted')
    else:
        node.dump('completed')
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
