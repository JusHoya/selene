"""The one place a robot's pose becomes a world pose, and the one place it is checked.

Subscribes ``/<robot_id>/odom`` -- Gazebo's DiffDrive output, dead-reckoned from
the robot's spawn pose -- and ``/<robot_id>/pose_truth``, the model's true world
pose from the simulator, and republishes ``/<robot_id>/odom_world``. Every
consumer of position in the system reads the republished topic; nothing else
transforms a pose.

WHY A REPUBLISHER, AND NOT THE ARITHMETIC IN EACH CONSUMER
----------------------------------------------------------
Five things read a robot's position: the agent's HAL (and through it navigation,
``prospect``, ``excavate`` and ``haul``), the neutron spectrometer, the hopper,
the extraction model and the battery's PSR test. They live in three packages.

The alternative design was to give each of them ``spawn_x`` / ``spawn_y`` /
``spawn_yaw`` parameters and let each apply the rotation itself. That is five
copies of one rotation, and a rotation is exactly the kind of arithmetic that is
wrong-but-plausible: drop the ``sin`` terms in one of the five and that consumer
still agrees with the others at the spawn point, still produces smooth
trajectories, and diverges only with distance -- which is the shape of the
defect this whole change exists to remove. One conversion means one place to be
wrong, and one place to test.

It is also the honest architecture rather than merely the convenient one.
CLAUDE.md's principle 5 is hardware-agnosticism through the HAL: an agent should
read the pose its localisation gives it and know nothing about how the pose was
obtained. On real hardware that pose comes from a localisation stack; here the
simulator stands in for it, on a topic shaped like the one a localisation stack
would publish. Teaching ``selene_agent`` about ``spawn_positions.yaml`` would
have put a simulation artefact inside the autonomy layer.

``pose_source``: WHICH ESTIMATE GOES OUT, AND WHY THE DEFAULT MOVED
-------------------------------------------------------------------
Until 2026-07-31 this node had exactly one input -- wheel odometry -- so
"stands in for a localisation stack" was true only in the shape of the topic,
never in its content. What went out was dead reckoning with a spawn transform
on it, and dead reckoning has no bound on its error.

The instrumented run of 2026-07-31 put a number on that. Over one 20-minute
mission the four robots ended 13.803 / 241.577 / 55.247 / 19.437 m from where
they physically were. The hauler climbed the PSR crater's inner rim wall,
pitched to -35 deg and pinned; for 320.7 s its wheels turned at the commanded
0.395 m/s cap while its body moved 6.6 cm, and the phantom 126.7 m that bought
carried its believed position to within 0.4 m of the depot. It unloaded 19.0 kg
there. The ledger balanced to float64 zero and the dashboard showed a delivery.
Ground truth had it 241.577 m away, on a crater wall. (Those figures are from
that run's analyser output; they are not re-measured by this file.)

So there are two settings, and both are honest about what they are:

* ``localisation`` (default) -- the pose published is the simulator's true
  world pose. This is the simulator standing in for a localisation stack that
  does not drift without bound: a star tracker, a sun sensor, visual odometry,
  terrain-relative navigation. It is NOT a claim that SELENE has solved
  localisation; it is a claim that the mission layer should be tested against a
  pose that means something, and that building the localisation stack is a
  separate job. The velocity still comes from the encoders (see below).
* ``dead_reckoning`` -- the previous behaviour exactly, spawn SE(2) composed
  onto wheel odometry. Kept so the defect above stays reproducible on demand,
  and so a run can be compared against the three that preceded this change.

IN BOTH SETTINGS THE DIVERGENCE IS MEASURED AND REPORTED. That is the part that
is not a choice. ``selene_sim/selene_sim/localisation.py`` compares the two
estimates continuously and this node raises a ``FleetAlert`` when they disagree
or when the wheels turn while the body does not. Selecting ``dead_reckoning``
therefore no longer hides the drift, it narrates it.

WHAT IS AND IS NOT TRANSFORMED
------------------------------
* ``pose.pose.position`` -- in ``dead_reckoning``, rotated by the spawn yaw and
  translated; z is ``spawn.z + odom.z`` and DiffDrive publishes odom z as
  identically 0, so that is the spawn HEIGHT carried forward, not a measured
  altitude. In ``localisation`` all three come from the simulator and z is a
  real altitude for the first time.
* ``pose.pose.orientation`` -- premultiplied by the spawn yaw quaternion in
  ``dead_reckoning``; taken whole from the truth pose in ``localisation``,
  which is also the first time roll and pitch are anything but zero.
* ``twist`` -- COPIED UNCHANGED FROM THE WHEEL ODOMETRY IN BOTH MODES, and this
  is deliberate, not an omission. ``nav_msgs/Odometry`` expresses twist in
  ``child_frame_id`` (``base_link``), i.e. the body frame, so re-parenting the
  pose frame does not touch it -- and more importantly a real vehicle reads its
  speed off its encoders whatever its localisation says. Keeping the encoder
  velocity is what leaves the slip signal intact: a pinned robot reports the
  commanded 0.4 m/s while its true position does not move, and that
  contradiction is precisely what the monitor below is looking for. Rotating it
  here would have been a real defect: ``navigator.PathFollower`` reads
  ``linear_velocity`` as forward speed.
* ``header.frame_id`` -- set to ``map`` (see ``world_frame.WORLD_FRAME_ID``).
  ``child_frame_id`` is passed through untouched.
* covariance -- copied. DiffDrive leaves it zero-filled; inventing one here
  would be a fabricated measurement.

FAILURE MODES, STATED
---------------------
If this node is not running, ``/<robot_id>/odom_world`` has no publisher and
every consumer holds its ``is_valid=False`` default: the agent waits in IDLE for
odometry rather than driving somewhere wrong (``agent_node.py:393-408``), the
spectrometer keeps sampling at (0, 0) and the battery reports no motion. That is
a fleet that visibly does nothing, which is the correct way for this to fail --
the alternative, falling back to raw odom, is the defect.

If ``pose_source`` is ``localisation`` and ``/<robot_id>/pose_truth`` never
arrives -- no PosePublisher in the model, no bridge entry, a world that predates
either -- this node publishes the dead-reckoned pose so the fleet still runs,
AND says so on every channel it has: an ERROR in the log every
``degraded_report_period_sec`` and a CRITICAL ``FleetAlert`` that names the
missing topic. A silent fallback would have reproduced the original defect with
a new name on it; a loud one is a degraded mode an operator can see.
"""

import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from selene_msgs.msg import FleetAlert
from tf2_msgs.msg import TFMessage

from selene_sim.localisation import (
    DEFAULT_ERROR_M,
    DEFAULT_SLIP_FRACTION,
    DEFAULT_TRUTH_TIMEOUT_S,
    DEFAULT_WINDOW_S,
    LocalisationMonitor,
)
from selene_sim.world_frame import (
    RAW_ODOM_TOPIC,
    WORLD_FRAME_ID,
    WORLD_ODOM_TOPIC,
    SpawnPose,
    odom_to_world,
    quaternion_multiply,
    yaw_to_quaternion,
)

# QOS: THE PLAIN DEPTH-10 DEFAULT, RELIABLE, ON BOTH ENDS. Not a detail, and
# not an oversight -- this node sits between subscribers that do not agree.
#
# An incompatible pair is INVISIBLE in ROS 2: DDS simply never connects them and
# the topic shows a publisher, a subscriber and no messages, which looks exactly
# like a node that failed to start. It is the same silent-failure class as the
# load-cell topic mismatch that made every haul deliver 0.0 kg for two phases
# (register D-11).
#
# Downstream this node has two kinds of subscriber:
#   * the four selene_sim consumer nodes, which subscribe with the int
#     shorthand 10 -> RELIABLE. A RELIABLE subscriber does NOT match a
#     BEST_EFFORT publisher, so publishing best-effort here would disconnect
#     the spectrometer, the hopper, the extraction model and the battery at
#     once, with no error anywhere.
#   * ``selene_hal.gazebo_hal._SENSOR_QOS``, which is BEST_EFFORT. A
#     best-effort subscriber DOES match a reliable publisher.
# RELIABLE is therefore the only choice that serves both.
#
# Upstream, subscribing with the same shorthand reproduces exactly what those
# four nodes already do against ``/{robot_id}/odom`` from ``ros_gz_bridge``, on
# this system, today -- so it is proven compatible rather than reasoned to be.
_ODOM_QOS = 10

#: ``pose_source`` values. Anything else is a launch error rather than a
#: silently-assumed default -- picking one of these decides whether the pose
#: every mission decision rests on is bounded or not.
POSE_SOURCE_LOCALISATION = 'localisation'
POSE_SOURCE_DEAD_RECKONING = 'dead_reckoning'
_POSE_SOURCES = (POSE_SOURCE_LOCALISATION, POSE_SOURCE_DEAD_RECKONING)

#: Gazebo topic tail bridged into ``/<robot_id>/pose_truth`` by
#: ``simulation.launch.py``. See the PosePublisher block in each robot's
#: ``models/<type>/model.sdf``.
TRUTH_POSE_TOPIC: str = 'pose_truth'


def _yaw_of(qx: float, qy: float, qz: float, qw: float) -> float:
    return math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))


class WorldOdometryNode(Node):
    """Republish one robot's pose in world coordinates, and audit it."""

    def __init__(self):
        super().__init__('world_odometry_node')

        self.declare_parameter('robot_id', 'robot_01')
        # Set by simulation.launch.py from the same pose dict it spawns with.
        # Defaulting them to 0 makes an UNPARAMETERISED node the identity
        # transform, which is deliberate: a launch that forgets to pass them
        # reproduces exactly the old (broken) behaviour rather than an
        # arbitrary new one, so the symptom is the familiar one.
        self.declare_parameter('spawn_x', 0.0)
        self.declare_parameter('spawn_y', 0.0)
        self.declare_parameter('spawn_z', 0.0)
        self.declare_parameter('spawn_yaw', 0.0)
        self.declare_parameter('frame_id', WORLD_FRAME_ID)
        self.declare_parameter('pose_source', POSE_SOURCE_LOCALISATION)
        # Monitor thresholds. Their derivations are on the constants in
        # selene_sim/selene_sim/localisation.py; they are parameters here only
        # so a run can widen them without a rebuild.
        self.declare_parameter('divergence_window_sec', DEFAULT_WINDOW_S)
        self.declare_parameter('divergence_error_m', DEFAULT_ERROR_M)
        self.declare_parameter('slip_fraction_threshold', DEFAULT_SLIP_FRACTION)
        self.declare_parameter('truth_timeout_sec', DEFAULT_TRUTH_TIMEOUT_S)
        # How often a PERSISTING condition is re-stated. An alert that repeats
        # at the tick rate is how an alert log becomes wallpaper; one that is
        # stated once and never again dates the failure without tracking it.
        self.declare_parameter('degraded_report_period_sec', 60.0)
        # How long the truth stream may be silent at STARTUP before its absence
        # is reported. MEASURED on 2026-07-31: this node reaches its first
        # /<robot>/odom message before the first /<robot>/pose_truth (the
        # PosePublisher plugin comes up with the spawned model and the bridge
        # has to discover it), so without a grace period every launch opens
        # with a CRITICAL alert that is true for about a second. 20 s covers
        # the staggered 2 s-per-robot spawn plus DDS discovery on this system
        # with room to spare, and a truth stream that is really absent is still
        # reported 20 s in and every degraded_report_period_sec after that.
        self.declare_parameter('truth_grace_sec', 20.0)

        self.robot_id = self.get_parameter('robot_id').value
        self.spawn = SpawnPose(
            x=float(self.get_parameter('spawn_x').value),
            y=float(self.get_parameter('spawn_y').value),
            z=float(self.get_parameter('spawn_z').value),
            yaw=float(self.get_parameter('spawn_yaw').value),
        )
        self.frame_id = str(self.get_parameter('frame_id').value)
        self.pose_source = str(self.get_parameter('pose_source').value)
        if self.pose_source not in _POSE_SOURCES:
            raise RuntimeError(
                f'pose_source must be one of {_POSE_SOURCES}, got '
                f'{self.pose_source!r}. There is no default worth guessing '
                f'here: the choice decides whether the pose every mission '
                f'decision rests on is bounded or unbounded.')
        self._report_period = max(1.0, float(
            self.get_parameter('degraded_report_period_sec').value))
        self._truth_grace = max(0.0, float(
            self.get_parameter('truth_grace_sec').value))
        self._start_time = None
        self._ever_had_truth = False

        self._spawn_quat = yaw_to_quaternion(self.spawn.yaw)
        self._published = 0
        self._alerts = 0
        #: Latest truth pose as (x, y, z, qx, qy, qz, qw), or None.
        self._truth = None
        #: Latest dead-reckoned (x, y), and the latest comparison of the two.
        #: Both are latched by the odometry callback so the 1 Hz audit only
        #: READS -- feeding the monitor from two places would double-count the
        #: window and make every path length twice what the robot travelled.
        self._dead_reckoned = (self.spawn.x, self.spawn.y)
        self._divergence = None
        self._last_degraded_report = None
        self._last_divergence_report = None
        self._slip_active = False

        self._monitor = LocalisationMonitor(
            window_s=float(self.get_parameter('divergence_window_sec').value),
            slip_fraction=float(
                self.get_parameter('slip_fraction_threshold').value),
            error_m=float(self.get_parameter('divergence_error_m').value),
            truth_timeout_s=float(self.get_parameter('truth_timeout_sec').value),
        )

        prefix = f'/{self.robot_id}'
        in_topic = f'{prefix}/{RAW_ODOM_TOPIC}'
        out_topic = f'{prefix}/{WORLD_ODOM_TOPIC}'
        truth_topic = f'{prefix}/{TRUTH_POSE_TOPIC}'

        # THE TOPIC TAILS BELOW ARE WRITTEN OUT AS LITERALS, and that repetition
        # is deliberate. selene_sim/test/test_sensor_topic_coverage.py AST-parses
        # every create_publisher in this package and can only resolve a constant
        # or an f-string; a topic passed as a bare variable is invisible to it,
        # and this publisher is exactly the one that must be checked against the
        # RCDLs' `topic: odom_world`. The same test asserts these literals equal
        # RAW_ODOM_TOPIC and WORLD_ODOM_TOPIC, so the two spellings cannot drift.
        self.world_pub = self.create_publisher(
            Odometry, f'{prefix}/odom_world', _ODOM_QOS)
        self.odom_sub = self.create_subscription(
            Odometry, f'{prefix}/odom', self._odom_callback, _ODOM_QOS)
        self.truth_sub = self.create_subscription(
            TFMessage, f'{prefix}/pose_truth', self._truth_callback, _ODOM_QOS)

        # The operator's channel. This is a selene_sim node publishing onto the
        # orchestrator's alert topic, which is a deliberate small impurity:
        # /orchestrator/alerts is the ONE path that reaches the dashboard
        # (FR-DASH-4) and the probe, a localisation divergence is exactly the
        # kind of thing an operator must be told about, and the alternative --
        # a private topic plus an orchestrator subscription -- would put a
        # simulator concept inside the fleet layer. Multiple publishers on one
        # topic is ordinary ROS. source_robot_id names the robot, so the alert
        # is attributable whatever published it.
        self.alert_pub = self.create_publisher(
            FleetAlert, '/orchestrator/alerts', 10)

        self.create_timer(1.0, self._audit)

        self.get_logger().info(
            f'World odometry for {self.robot_id}: {in_topic} + {truth_topic} '
            f'-> {out_topic} (frame {self.frame_id}, pose_source '
            f'{self.pose_source}), spawn '
            f'({self.spawn.x:.3f}, {self.spawn.y:.3f}, {self.spawn.z:.3f}) '
            f'yaw {self.spawn.yaw:.4f} rad')
        if self.spawn.x == 0.0 and self.spawn.y == 0.0 and self.spawn.yaw == 0.0:
            # Not an error -- a robot really can spawn at the origin facing +X --
            # but on the shipped spawn_positions.yaml it means the parameters
            # did not arrive, and a silent identity transform is the exact
            # defect this node was written to remove.
            self.get_logger().warn(
                f'{self.robot_id}: spawn pose is the identity, so the '
                f'dead-reckoned estimate carries the raw pose. If this robot '
                f'was not spawned at (0, 0) facing +X, the spawn_x / spawn_y / '
                f'spawn_yaw parameters did not reach this node.')

    # ------------------------------------------------------------- plumbing

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _publish_alert(self, severity: str, message: str) -> None:
        self._alerts += 1
        msg = FleetAlert()
        msg.alert_id = f'loc_{self.robot_id}_{self._alerts:04d}'
        msg.severity = severity
        msg.source_robot_id = self.robot_id
        msg.message = message
        msg.stamp = self.get_clock().now().to_msg()
        self.alert_pub.publish(msg)

    def _due(self, last: float | None, now: float) -> bool:
        return last is None or (now - last) >= self._report_period

    # -------------------------------------------------------------- inputs

    def _truth_callback(self, msg: TFMessage) -> None:
        """Latch the model's true world pose.

        The bridge turns one ``gz.msgs.Pose_V`` into a ``TFMessage``; the
        PosePublisher in the robot's model.sdf is configured to publish the
        MODEL pose only, so there is exactly one transform and its
        ``child_frame_id`` is the robot's name. Indexing [0] is therefore not
        a guess -- but it is checked, because a future SDF edit that turns link
        poses back on would otherwise silently start reporting a wheel.
        """
        for tf in msg.transforms:
            if tf.child_frame_id and tf.child_frame_id != self.robot_id:
                continue
            t = tf.transform.translation
            r = tf.transform.rotation
            self._truth = (t.x, t.y, t.z, r.x, r.y, r.z, r.w)
            self._ever_had_truth = True
            self._monitor.note_truth(self._now())
            return

    def _odom_callback(self, msg: Odometry) -> None:
        now = self._now()
        position = msg.pose.pose.position
        orientation = msg.pose.pose.orientation

        # The dead-reckoned estimate is computed on EVERY message regardless of
        # pose_source, because it is half of the comparison below. Publishing it
        # is a separate decision from computing it.
        dx, dy, _ = odom_to_world(position.x, position.y, 0.0, self.spawn)
        dz = self.spawn.z + position.z
        dq = quaternion_multiply(
            self._spawn_quat,
            (orientation.x, orientation.y, orientation.z, orientation.w),
        )

        truth_fresh = self._truth is not None and self._monitor.truth_is_fresh(now)
        use_truth = (self.pose_source == POSE_SOURCE_LOCALISATION and truth_fresh)

        if use_truth:
            tx, ty, tz, qx, qy, qz, qw = self._truth
        else:
            tx, ty, tz = dx, dy, dz
            qx, qy, qz, qw = dq
            if self.pose_source == POSE_SOURCE_LOCALISATION:
                self._report_degraded(now)

        world = Odometry()
        world.header.stamp = msg.header.stamp
        world.header.frame_id = self.frame_id
        world.child_frame_id = msg.child_frame_id
        world.pose.pose.position.x = tx
        world.pose.pose.position.y = ty
        world.pose.pose.position.z = tz
        world.pose.pose.orientation.x = qx
        world.pose.pose.orientation.y = qy
        world.pose.pose.orientation.z = qz
        world.pose.pose.orientation.w = qw
        world.pose.covariance = msg.pose.covariance
        # Body frame, and from the ENCODERS in both modes; see the module
        # docstring. Not rotated, on purpose, and not taken from truth.
        world.twist = msg.twist
        self.world_pub.publish(world)

        self._dead_reckoned = (dx, dy)
        if truth_fresh:
            self._divergence = self._monitor.update(
                now, (dx, dy), (self._truth[0], self._truth[1]))

        # ONE line, on the first message only. It is the cheapest live proof
        # that the transform is doing what this file claims: at t=0 the robot
        # has not moved, odom is (0, 0, 0), and the DEAD-RECKONED world pose
        # printed here must equal the spawn pose in spawn_positions.yaml to the
        # millimetre. If it does not, nothing downstream is worth reading. The
        # truth column beside it is the same assertion made by the simulator
        # rather than by this file's arithmetic, so the two must also agree.
        if self._published == 0:
            truth_str = (
                f'truth ({self._truth[0]:.3f}, {self._truth[1]:.3f})'
                if self._truth is not None else 'truth <none yet>')
            self.get_logger().info(
                f'{self.robot_id}: first world pose ({dx:.3f}, {dy:.3f}) '
                f'yaw {_yaw_of(*dq):.4f} rad from odom '
                f'({position.x:.3f}, {position.y:.3f}); {truth_str}; '
                f'publishing {self.pose_source}')
        self._published += 1

    # --------------------------------------------------------------- audits

    def _report_degraded(self, now: float) -> None:
        """Say, repeatedly and on both channels, that truth is missing."""
        if self._start_time is None:
            self._start_time = now
        if (not self._ever_had_truth
                and (now - self._start_time) < self._truth_grace):
            # Startup, not a fault. See truth_grace_sec.
            #
            # THE GRACE APPLIES ONLY BEFORE THE FIRST TRUTH SAMPLE. A stream
            # that arrived and then stopped is not a slow start -- it is the
            # simulator, the PosePublisher or the bridge dying mid-mission,
            # which is the case this file exists to make loud. Report that on
            # the next odometry message, not 20 s later.
            return
        if not self._due(self._last_degraded_report, now):
            return
        self._last_degraded_report = now
        topic = f'/{self.robot_id}/{TRUTH_POSE_TOPIC}'
        self.get_logger().error(
            f'{self.robot_id}: pose_source is {POSE_SOURCE_LOCALISATION} but '
            f'no pose has arrived on {topic} inside the freshness timeout. '
            f'Publishing the DEAD-RECKONED pose instead. Its error is '
            f'unbounded and nothing downstream can tell. Check the '
            f'PosePublisher plugin in the robot model.sdf and the pose_truth '
            f'bridge in simulation.launch.py.')
        self._publish_alert(
            'CRITICAL',
            f'{self.robot_id} has no localisation source: {topic} is silent, '
            f'so /{self.robot_id}/odom_world is carrying dead-reckoned wheel '
            f'odometry whose error is unbounded. Every position this robot '
            f'reports -- task targets, resource-map cells, the depot it '
            f'unloads at -- is a belief with no reference behind it.')

    def _audit(self) -> None:
        """1 Hz: compare the two estimates and report what they say.

        Runs in BOTH pose_source modes. In ``localisation`` it is the only
        thing that will ever tell an operator the wheels are lying, because the
        published pose no longer carries the lie.
        """
        now = self._now()
        if self._truth is None or not self._monitor.truth_is_fresh(now):
            return
        divergence = self._divergence
        if divergence is None:
            return

        slipping = self._monitor.is_slipping(divergence)
        if slipping and not self._slip_active:
            self._slip_active = True
            self.get_logger().error(
                '%s: WHEELS TURNING, BODY NOT MOVING. %.1f m of wheel travel '
                'over %.0fs, %.2f m covered (%.0f%% slip).'
                % (self.robot_id, divergence.odom_path_m, divergence.window_s,
                   divergence.truth_path_m, 100.0 * divergence.slip_fraction))
            self._publish_alert(
                'CRITICAL',
                f'{self.robot_id} is not moving under power: its wheels '
                f'reported {divergence.odom_path_m:.1f} m over the last '
                f'{divergence.window_s:.0f}s while its body covered '
                f'{divergence.truth_path_m:.2f} m ('
                f'{100.0 * divergence.slip_fraction:.0f}% slip). It is pinned, '
                f'buried or on ground it cannot climb. Its odometry is '
                f'advancing normally, so no heartbeat, fleet-freeze or '
                f'progress check will see this, and it will report arrival at '
                f'a place it never reached.')
        elif self._slip_active and not slipping:
            self._slip_active = False
            self.get_logger().info(
                f'{self.robot_id}: motion restored, {divergence.truth_path_m:.2f} m '
                f'covered against {divergence.odom_path_m:.1f} m of wheel travel.')
            self._publish_alert(
                'INFO',
                f'{self.robot_id} is moving again ('
                f'{100.0 * divergence.slip_fraction:.0f}% slip).')

        if (self._monitor.is_diverged(divergence)
                and self._due(self._last_divergence_report, now)):
            self._last_divergence_report = now
            carried = ('published' if self.pose_source == POSE_SOURCE_DEAD_RECKONING
                       else 'suppressed')
            self._publish_alert(
                'WARNING',
                f'{self.robot_id} dead reckoning has drifted '
                f'{divergence.error_m:.1f} m from its true position '
                f'(threshold {self._monitor.error_threshold_m:.1f} m). That '
                f'error is currently {carried}: pose_source is '
                f'{self.pose_source}. Dead reckoning says '
                f'({self._dead_reckoned[0]:.1f}, {self._dead_reckoned[1]:.1f}), '
                f'the simulator says ({self._truth[0]:.1f}, {self._truth[1]:.1f}).')


def main(args=None):
    rclpy.init(args=args)
    node = WorldOdometryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # GUARDED, because a launch-level shutdown gets there first. When the
        # simulator dies, simulation.launch.py brings the whole system down and
        # every node is SIGINT-ed; rclpy has already shut the context down by
        # the time this runs, and calling it again raises
        #   RCLError: failed to shutdown: rcl_shutdown already called
        # out of `finally`, so the process exits 1 and the launch reports
        # "process has died [exit code 1]". Eight of those buried the actual
        # diagnosis in the 2026-07-31 smoke test. A clean teardown must not
        # look like eight crashes, least of all on the one code path whose
        # whole purpose is to be legible after a crash.
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
