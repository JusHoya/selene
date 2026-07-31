"""The odom -> world transform, and the terrain box a robot must stay inside.

WHY THIS FILE EXISTS
--------------------
Gazebo's DiffDrive plugin publishes ``/model/<robot>/odometry`` from
``gz::math::DiffDriveOdometry``, which integrates WHEEL ENCODER POSITIONS and
nothing else. ``Init()`` sets its pose to (0, 0, 0), so odom (0, 0) is wherever
that robot spawned and the odom x-axis points along the robot's SPAWN HEADING.
The plugin has no access to the model's world pose and cannot subtract it; see
``selene_sim/models/scout/model.sdf`` (``gz-sim-diff-drive-system``, with
``<frame_id>odom</frame_id>``).

Every consumer in SELENE then read that pose as if it were world coordinates.
It is not, and the consequence is not cosmetic:

  * the neutron spectrometer evaluated the ice field at the odom coordinate, so
    ``ResourceMapUpdate.location`` named a place the robot was not;
  * ``battery_node._is_in_psr()`` tested shadow at the odom coordinate, so solar
    recharge was decided for the wrong patch of ground;
  * navigation drove to targets expressed in world metres as though they were
    odom metres, which walks a robot off the finite 500 m heightfield. Past the
    edge there is no collision surface: the body falls, and the collision AABB
    leaves the integer range ODE's broadphase converts it into. The operator
    measured that abort three times on 2026-07-30/31 --
    ``ODE INTERNAL ERROR 1: assertion "aabbBound >= dMinIntExact && aabbBound <
    dMaxIntExact" failed in collide() [collision_space.cpp:460]`` -- taking
    Gazebo down mid-mission.

IT IS A FULL SE(2) TRANSFORM, NOT AN OFFSET. Every pose in
``selene_sim/config/spawn_positions.yaml`` carries ``yaw: -2.33``, which is the
world bearing from the spawn ring to the PSR centre
(``atan2(-150 - -92, -100 - -45) = -2.3300``). Dropping the rotation is the
seductive failure here: near the odom origin the error is small and the map
still looks plausible, and it grows without bound with range. At the 180 m the
survey leg actually covers it is a ~300 m error -- larger than the trip.

    world = spawn (+) odom
          = R(yaw_spawn) . p_odom + t_spawn ,   theta_w = yaw_spawn + theta_o

``test_world_frame.py`` pins that with a case that fails if the rotation is
dropped, and with a world -> odom -> world round trip.

WHERE THE CONVERSION HAPPENS: EXACTLY ONCE
------------------------------------------
``world_odometry_node`` applies it and republishes ``/<robot>/odom_world``.
Nothing else in the repository transforms a pose. The alternative -- each
consumer applying the same arithmetic from its own ``spawn_*`` parameters --
was rejected: it is five copies of a rotation in four packages, four of which
would look right for as long as nobody drove far from the origin.
See that node's docstring for the full argument.

THE TERRAIN BOX
---------------
``TerrainBounds`` is the second half. Fixing the frame stops the *planner* from
walking a robot off the map; it does not stop an operator injecting a task at
(400, 400), and FR-DASH-5 lets them click anywhere. The extent is read from
config -- never hardcoded here -- because four files already state the world
size independently and this module must not become a fifth:

    selene_sim/models/lunar_terrain/heightmaps/terrain_datum.json  world_size_m
    selene_sim/models/lunar_terrain/model.sdf                      <size>500 500 ...
    selene_sim/config/world_params.yaml                            world.bounds
    selene_agent/config/nav_params.yaml                            grid_* / origin_*

``selene_sim/test/test_world_extent_agrees.py`` fails the build if any of them
drifts from the others, which is the only reason the numbers below can be
trusted anywhere they are re-declared.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import yaml


#: Topic tail carrying the world-referenced pose. The RCDLs
#: (``selene_hal/config/*.yaml``) name this as the odometry sensor's topic, and
#: ``selene_sim/test/test_sensor_topic_coverage.py`` cross-checks the two
#: directions, so a rename here that is not mirrored there fails the build.
WORLD_ODOM_TOPIC: str = 'odom_world'

#: Topic tail Gazebo's own dead-reckoned odometry arrives on, after the
#: ``ros_gz_bridge`` remapping in ``simulation.launch.py``. Nothing but
#: ``world_odometry_node`` should subscribe to this.
RAW_ODOM_TOPIC: str = 'odom'

#: ``header.frame_id`` stamped on the world-referenced odometry. ``map``, not
#: ``odom``, and that is a statement rather than a label: the pose is no longer
#: expressed in a per-robot dead-reckoned frame. It also matches what the rest
#: of the system already publishes -- the navigator's ``nav_msgs/Path`` and the
#: FR-MAP-4 marker overlay are both stamped ``map`` (register D-08), and
#: ``selene_sim/rviz/selene_sim.rviz`` has ``Fixed Frame: map``. Nothing in this
#: repository publishes TF, so RViz resolves a frame only when it EQUALS the
#: fixed frame; a fourth spelling would render nothing.
WORLD_FRAME_ID: str = 'map'


@dataclass(frozen=True)
class SpawnPose:
    """Where a robot was placed, in world metres and radians.

    This is the same tuple ``simulation.launch.py`` hands to ``ros_gz_sim
    create`` as ``-x -y -z -Y``. It is passed to ``world_odometry_node`` from
    the same Python variable, not re-parsed, so the transform cannot describe a
    different placement from the one Gazebo performed.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0

    @classmethod
    def from_mapping(cls, mapping) -> "SpawnPose":
        """Build from one entry of ``spawn_positions.yaml``."""
        return cls(
            x=float(mapping['x']),
            y=float(mapping['y']),
            z=float(mapping.get('z', 0.0)),
            yaw=float(mapping.get('yaw', 0.0)),
        )


def wrap_angle(theta: float) -> float:
    """Fold an angle into (-pi, pi].

    ``yaw_spawn + theta_odom`` leaves the principal range for any robot that has
    turned more than about 50 degrees from its spawn heading, which on the
    shipped -2.33 rad spawns is the first navigation leg. Consumers compare
    headings by subtraction (``navigator.PathFollower``), so an unwrapped value
    produces a robot that believes it must spin a full turn to face a bearing it
    is already on.
    """
    return math.atan2(math.sin(theta), math.cos(theta))


def odom_to_world(
    x: float, y: float, theta: float, spawn: SpawnPose,
) -> tuple[float, float, float]:
    """Dead-reckoned odom pose -> world pose. THE conversion.

    ``world = spawn (+) odom``: rotate the odom vector into the world frame by
    the spawn heading, then translate by the spawn position.

    THE ROTATION IS NOT OPTIONAL and dropping it is the likely mistake, because
    the result stays plausible near the origin. At the spawn itself both forms
    agree exactly; at 10 m they differ by up to 20 m; at the 180 m of the first
    survey leg, by up to 360 m -- which is off a 500 m world.
    """
    cos_y = math.cos(spawn.yaw)
    sin_y = math.sin(spawn.yaw)
    return (
        spawn.x + cos_y * x - sin_y * y,
        spawn.y + sin_y * x + cos_y * y,
        wrap_angle(spawn.yaw + theta),
    )


def world_to_odom(
    x: float, y: float, theta: float, spawn: SpawnPose,
) -> tuple[float, float, float]:
    """World pose -> the odom frame of a robot spawned at *spawn*.

    The exact inverse of :func:`odom_to_world`. Nothing in the running system
    calls it -- the point of the fix is that world coordinates flow one way --
    but it is what makes the round trip testable, and it is the function to
    reach for if a diagnostic ever has to express a world point in a particular
    robot's odom frame (for example to compare against a raw ``/<robot>/odom``
    reading while debugging).
    """
    cos_y = math.cos(spawn.yaw)
    sin_y = math.sin(spawn.yaw)
    dx = x - spawn.x
    dy = y - spawn.y
    return (
        cos_y * dx + sin_y * dy,
        -sin_y * dx + cos_y * dy,
        wrap_angle(theta - spawn.yaw),
    )


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """``(x, y, z, w)`` for a rotation of *yaw* about +Z."""
    return (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))


def quaternion_multiply(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Hamilton product ``a * b``, both ``(x, y, z, w)``.

    Used instead of yaw-composition so the node stays correct if a future
    odometry source reports roll or pitch. DiffDrive reports yaw only today, and
    for that case this reduces exactly to ``yaw_a + yaw_b``.
    """
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


# ---------------------------------------------------------------------------
# The terrain box
# ---------------------------------------------------------------------------

#: Fallback margin, metres, if ``world_params.yaml`` does not name one. See
#: ``TerrainBounds.margin`` for where the number comes from.
DEFAULT_SAFETY_MARGIN_M: float = 10.0


@dataclass(frozen=True)
class TerrainBounds:
    """The axis-aligned world box a commanded position must lie inside.

    ``x_min``/``x_max``/``y_min``/``y_max`` are the nominal terrain extent --
    the heightfield's own footprint, +/-250 m for the shipped 500 m world.

    ``margin`` is what a target must additionally keep clear of that edge, and
    it is a sum of four measured or configured terms rather than a round number
    someone liked:

      * 1.95 m -- half a collision cell. The collision heightmap is 129x129 over
        500 m, so its outermost SAMPLE sits at +/-248.05 m, not +/-250: there is
        no surface beyond it. The operator's ODE abort log names the broadphase
        AABB as +/-248.062, which is that inset to within the quantisation of an
        8-bit map.
      * 0.59 m -- the largest robot's collision half-extent, from
        ``htn_planner.FOOTPRINT_CLEARANCE_M`` (1.1694 m, the sum of two body
        radii derived from the shipped ``model.sdf`` files).
      * 3.0 m -- arrival slop. ``PathFollower`` declares a waypoint reached
        inside ``waypoint_tolerance`` (1.0 m) while steering toward a point
        ``lookahead_distance`` (2.0 m) beyond it, so the body can sit up to
        about 3 m past a commanded coordinate.
      * the remainder is slack, because falling off is unrecoverable (it takes
        the simulator down) while stopping 10 m short of an edge nothing is at
        costs the mission nothing. Every coordinate this mission uses -- the
        four ``ice_deposits.yaml`` centres, the PSR disc, the depot, the
        recharge station, all ten spawns, all 26 rocks -- is at least 45 m
        inside the bound.

    NOT SAMPLED FROM THE HEIGHTMAP, deliberately: this is a box test, not a
    traversability test. Whether the ground inside it is drivable is
    ``check_terrain.sh``'s and ``check_drive.sh``'s question.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    margin: float = DEFAULT_SAFETY_MARGIN_M

    @classmethod
    def from_world_params(cls, path: str) -> "TerrainBounds":
        """Read ``world.bounds`` (and ``world.safety_margin_m``) from YAML.

        Raises rather than defaulting on a missing file or missing bounds: a
        guard that silently falls back to a guessed extent is a guard that
        certifies nothing, which is how this project spent two phases with a
        parameter that was declared and never read (register D-09).
        """
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(
                f'world params file not found: {path!r}. TerrainBounds must be '
                f'read from selene_sim/config/world_params.yaml; it is not '
                f'safe to guess the terrain extent.'
            )
        with open(path, 'r') as handle:
            config = yaml.safe_load(handle) or {}
        world = config.get('world') or {}
        bounds = world.get('bounds')
        if not bounds:
            raise KeyError(
                f'{path} has no world.bounds; the terrain extent cannot be '
                f'derived and must not be assumed.'
            )
        return cls(
            x_min=float(bounds['x_min']),
            x_max=float(bounds['x_max']),
            y_min=float(bounds['y_min']),
            y_max=float(bounds['y_max']),
            margin=float(world.get('safety_margin_m', DEFAULT_SAFETY_MARGIN_M)),
        )

    @property
    def safe_x(self) -> tuple[float, float]:
        return (self.x_min + self.margin, self.x_max - self.margin)

    @property
    def safe_y(self) -> tuple[float, float]:
        return (self.y_min + self.margin, self.y_max - self.margin)

    def contains(self, x: float, y: float) -> bool:
        """True when ``(x, y)`` is inside the safe area, margin included.

        A non-finite coordinate is OUTSIDE. NaN fails every comparison, so a
        naive ``lo <= x <= hi`` would reject it too, but only by accident; it is
        checked explicitly because a NaN target is exactly what produces the
        unbounded AABB this guard exists to prevent.
        """
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        lo_x, hi_x = self.safe_x
        lo_y, hi_y = self.safe_y
        return lo_x <= x <= hi_x and lo_y <= y <= hi_y

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        """Nearest point inside the safe area. Non-finite input -> the centre.

        Offered beside :meth:`contains` because the two callers want different
        things: an operator-injected target is REFUSED (the operator is present
        and can be told why), while a target the system generated for itself is
        better clamped and logged than dropped.
        """
        lo_x, hi_x = self.safe_x
        lo_y, hi_y = self.safe_y
        cx = (lo_x + hi_x) / 2.0
        cy = (lo_y + hi_y) / 2.0
        sx = cx if not math.isfinite(x) else min(max(x, lo_x), hi_x)
        sy = cy if not math.isfinite(y) else min(max(y, lo_y), hi_y)
        return (sx, sy)

    def describe(self) -> str:
        """One line naming the safe area, for a rejection message or a log."""
        lo_x, hi_x = self.safe_x
        lo_y, hi_y = self.safe_y
        return (
            f'x [{lo_x:.1f}, {hi_x:.1f}] y [{lo_y:.1f}, {hi_y:.1f}] '
            f'({self.margin:.1f} m inside the terrain edge)'
        )
