"""Autonomous navigation stack for SELENE lunar robots.

Provides A* path planning over an occupancy grid, pure-pursuit path
following, and a Navigator facade that ties them together through the
HAL.  Importable without rclpy -- ROS integration is optional.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Occupancy Grid
# ---------------------------------------------------------------------------

class CellState(IntEnum):
    FREE = 0
    OCCUPIED = 1
    UNKNOWN = 2


class OccupancyGrid:
    """2-D grid map used for path planning.

    Each cell stores an occupancy state and an optional traversal cost
    (e.g. slope penalty).  World coordinates are continuous (meters);
    grid coordinates are integer cell indices.
    """

    def __init__(
        self,
        width: int = 500,
        height: int = 500,
        resolution: float = 1.0,
        origin_x: float = -250.0,
        origin_y: float = -250.0,
    ):
        self._width = width
        self._height = height
        self._resolution = resolution
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._grid = np.zeros((height, width), dtype=np.int8)
        self._cost_grid = np.zeros((height, width), dtype=np.float32)

    # -- Coordinate transforms ------------------------------------------------

    def world_to_grid(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert world (meters) to grid cell indices."""
        gx = int((wx - self._origin_x) / self._resolution)
        gy = int((wy - self._origin_y) / self._resolution)
        return gx, gy

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        """Convert grid cell indices to the cell-centre world position."""
        wx = gx * self._resolution + self._origin_x + self._resolution / 2
        wy = gy * self._resolution + self._origin_y + self._resolution / 2
        return wx, wy

    # -- Cell access ----------------------------------------------------------

    def is_in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self._width and 0 <= gy < self._height

    def get_cell(self, gx: int, gy: int) -> CellState:
        if not self.is_in_bounds(gx, gy):
            return CellState.UNKNOWN
        return CellState(self._grid[gy, gx])

    def set_cell(self, gx: int, gy: int, state: CellState) -> None:
        if self.is_in_bounds(gx, gy):
            self._grid[gy, gx] = int(state)

    def get_cost(self, gx: int, gy: int) -> float:
        if not self.is_in_bounds(gx, gy):
            return float("inf")
        return float(self._cost_grid[gy, gx])

    def set_cost(self, gx: int, gy: int, cost: float) -> None:
        if self.is_in_bounds(gx, gy):
            self._cost_grid[gy, gx] = cost

    # -- Obstacle helpers -----------------------------------------------------

    def mark_obstacle_circle(self, wx: float, wy: float, radius: float) -> None:
        """Mark all cells whose centres are within *radius* of (*wx*, *wy*)
        as OCCUPIED."""
        cx, cy = self.world_to_grid(wx, wy)
        r_cells = int(math.ceil(radius / self._resolution))
        for dy in range(-r_cells, r_cells + 1):
            for dx in range(-r_cells, r_cells + 1):
                gx = cx + dx
                gy = cy + dy
                if not self.is_in_bounds(gx, gy):
                    continue
                cell_wx, cell_wy = self.grid_to_world(gx, gy)
                dist = math.hypot(cell_wx - wx, cell_wy - wy)
                if dist <= radius:
                    self._grid[gy, gx] = int(CellState.OCCUPIED)

    # -- Factory --------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict) -> "OccupancyGrid":
        """Build an OccupancyGrid from a nav-params config dict.

        Expected keys under ``config["navigation"]``:
            grid_width, grid_height, grid_resolution, origin_x, origin_y

        Optional ``config["static_obstacles"]["rocks"]`` list of
        ``{x, y, radius}`` dicts.  An inflation radius is added from
        ``config["navigation"]["obstacle_inflation_radius"]``.
        """
        nav = config.get("navigation", config)
        grid = cls(
            width=int(nav.get("grid_width", 500)),
            height=int(nav.get("grid_height", 500)),
            resolution=float(nav.get("grid_resolution", 1.0)),
            origin_x=float(nav.get("origin_x", -250.0)),
            origin_y=float(nav.get("origin_y", -250.0)),
        )
        inflation = float(nav.get("obstacle_inflation_radius", 0.5))

        rocks = config.get("static_obstacles", {}).get("rocks", [])
        for rock in rocks:
            grid.mark_obstacle_circle(
                rock["x"], rock["y"], rock["radius"] + inflation,
            )
        return grid

    # -- Properties -----------------------------------------------------------

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def resolution(self) -> float:
        return self._resolution

    @property
    def origin_x(self) -> float:
        return self._origin_x

    @property
    def origin_y(self) -> float:
        return self._origin_y


# ---------------------------------------------------------------------------
# A* Planner
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    path: list[tuple[float, float]]
    cost: float
    success: bool
    failure_reason: str = ""


class AStarPlanner:
    """A* path planner on an 8-connected OccupancyGrid."""

    SQRT2 = 1.4142135623730951

    def __init__(
        self,
        grid: OccupancyGrid,
        slope_penalty_weight: float = 2.0,
        hazard_penalty_weight: float = 10.0,
    ):
        self._grid = grid
        self._slope_w = slope_penalty_weight
        self._hazard_w = hazard_penalty_weight

    # -- Public ---------------------------------------------------------------

    def plan(
        self,
        start_xy: tuple[float, float],
        goal_xy: tuple[float, float],
    ) -> PlanResult:
        """Compute a path from *start_xy* to *goal_xy* in world coords."""
        grid = self._grid
        sx, sy = grid.world_to_grid(*start_xy)
        gx, gy = grid.world_to_grid(*goal_xy)

        # Quick checks
        if not grid.is_in_bounds(sx, sy):
            return PlanResult([], 0.0, False, "start out of bounds")
        if not grid.is_in_bounds(gx, gy):
            return PlanResult([], 0.0, False, "goal out of bounds")
        if grid.get_cell(sx, sy) == CellState.OCCUPIED:
            return PlanResult([], 0.0, False, "start is occupied")
        if grid.get_cell(gx, gy) == CellState.OCCUPIED:
            return PlanResult([], 0.0, False, "goal is occupied")

        # Trivial case
        if sx == gx and sy == gy:
            wx, wy = grid.grid_to_world(sx, sy)
            return PlanResult([(wx, wy)], 0.0, True)

        # A* search
        # open_set entries: (f, counter, gx, gy)
        counter = 0
        open_set: list[tuple[float, int, int, int]] = []
        h0 = self._heuristic(sx, sy, gx, gy)
        heapq.heappush(open_set, (h0, counter, sx, sy))
        counter += 1

        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
        closed: set[tuple[int, int]] = set()

        while open_set:
            _f, _cnt, cx, cy = heapq.heappop(open_set)

            if (cx, cy) in closed:
                continue
            closed.add((cx, cy))

            if cx == gx and cy == gy:
                # Reconstruct
                grid_path = self._reconstruct_path(came_from, (cx, cy))
                world_path = [grid.grid_to_world(p[0], p[1]) for p in grid_path]
                world_path = self._simplify_path(world_path)
                return PlanResult(world_path, g_score[(cx, cy)], True)

            for nx, ny, move_cost in self._get_neighbors(cx, cy):
                if (nx, ny) in closed:
                    continue
                cost = g_score[(cx, cy)] + move_cost + grid.get_cost(nx, ny) * self._slope_w
                if cost < g_score.get((nx, ny), float("inf")):
                    g_score[(nx, ny)] = cost
                    came_from[(nx, ny)] = (cx, cy)
                    f = cost + self._heuristic(nx, ny, gx, gy)
                    heapq.heappush(open_set, (f, counter, nx, ny))
                    counter += 1

        return PlanResult([], 0.0, False, "no path found")

    # -- Internals ------------------------------------------------------------

    def _heuristic(self, gx1: int, gy1: int, gx2: int, gy2: int) -> float:
        return math.hypot(gx2 - gx1, gy2 - gy1)

    def _get_neighbors(self, gx: int, gy: int) -> list[tuple[int, int, float]]:
        """Return reachable 8-connected neighbours with move costs.

        Diagonal moves are allowed only when both adjacent cardinal
        cells are free (no corner-cutting through obstacles).
        """
        grid = self._grid
        neighbors: list[tuple[int, int, float]] = []

        cardinal = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        diagonal = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

        # Cardinal
        cardinal_free: dict[tuple[int, int], bool] = {}
        for dx, dy in cardinal:
            nx, ny = gx + dx, gy + dy
            free = (grid.is_in_bounds(nx, ny)
                    and grid.get_cell(nx, ny) != CellState.OCCUPIED)
            cardinal_free[(dx, dy)] = free
            if free:
                neighbors.append((nx, ny, 1.0))

        # Diagonal -- only if both adjacent cardinals are free
        for dx, dy in diagonal:
            nx, ny = gx + dx, gy + dy
            if not grid.is_in_bounds(nx, ny):
                continue
            if grid.get_cell(nx, ny) == CellState.OCCUPIED:
                continue
            if not cardinal_free.get((dx, 0), False):
                continue
            if not cardinal_free.get((0, dy), False):
                continue
            neighbors.append((nx, ny, self.SQRT2))

        return neighbors

    def _reconstruct_path(
        self,
        came_from: dict[tuple[int, int], tuple[int, int]],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _simplify_path(
        self, path: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Line-of-sight simplification using Bresenham cell checks."""
        if len(path) <= 2:
            return path

        simplified: list[tuple[float, float]] = [path[0]]
        anchor = 0

        while anchor < len(path) - 1:
            farthest = anchor + 1
            for probe in range(anchor + 2, len(path)):
                if self._line_of_sight(path[anchor], path[probe]):
                    farthest = probe
                else:
                    break
            simplified.append(path[farthest])
            anchor = farthest

        return simplified

    def _line_of_sight(
        self, p1: tuple[float, float], p2: tuple[float, float]
    ) -> bool:
        """Check whether a straight line between two world points
        crosses only FREE cells (Bresenham)."""
        grid = self._grid
        x0, y0 = grid.world_to_grid(*p1)
        x1, y1 = grid.world_to_grid(*p2)

        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            if grid.get_cell(x0, y0) == CellState.OCCUPIED:
                return False
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

        return True


# ---------------------------------------------------------------------------
# Path Follower  (pure-pursuit style)
# ---------------------------------------------------------------------------

class PathFollowerStatus:
    FOLLOWING = "following"
    GOAL_REACHED = "goal_reached"
    NO_PATH = "no_path"
    STALLED = "stalled"


class PathFollower:
    """Steers a robot along a waypoint list using pure-pursuit logic.

    Reads odometry and commands velocity through the HAL interfaces
    supplied at construction time.
    """

    def __init__(
        self,
        drive_actuator,
        odometry_sensor,
        kinematics,
        lookahead_distance: float = 2.0,
        waypoint_tolerance: float = 1.0,
        linear_kp: float = 0.5,
        angular_kp: float = 1.5,
        max_angular_speed: float = 1.0,
        stall_timeout: float = 5.0,
    ):
        self._drive = drive_actuator
        self._odom = odometry_sensor
        self._kinematics = kinematics
        self._lookahead = lookahead_distance
        self._wp_tol = waypoint_tolerance
        self._lin_kp = linear_kp
        self._ang_kp = angular_kp
        self._max_ang = max_angular_speed
        self._stall_timeout = stall_timeout

        self._path: list[tuple[float, float]] = []
        self._target_idx: int = 0
        self._stall_timer: float = 0.0
        self._velocity_threshold: float = 0.01  # m/s for stall detect

    # -- Public ---------------------------------------------------------------

    def set_path(self, path: list[tuple[float, float]]) -> None:
        self._path = list(path)
        self._target_idx = 0
        self._stall_timer = 0.0

    def update(self, dt: float) -> str:
        """Advance the follower by *dt* seconds.  Returns a status string."""
        if not self._path:
            return PathFollowerStatus.NO_PATH

        # Read current pose
        odom = self._odom.read()
        rx, ry, rtheta = odom.x, odom.y, odom.theta

        # Advance target index past waypoints already reached
        while self._target_idx < len(self._path) - 1:
            wx, wy = self._path[self._target_idx]
            if math.hypot(wx - rx, wy - ry) < self._wp_tol:
                self._target_idx += 1
            else:
                break

        # Find lookahead point
        tx, ty = self._find_lookahead(rx, ry)

        # Check if final goal is reached
        gx, gy = self._path[-1]
        dist_to_goal = math.hypot(gx - rx, gy - ry)
        if dist_to_goal < self._wp_tol:
            self._drive.command_velocity(0.0, 0.0)
            return PathFollowerStatus.GOAL_REACHED

        # Heading error
        desired_heading = math.atan2(ty - ry, tx - rx)
        heading_error = self._wrap_angle(desired_heading - rtheta)

        # Turn-in-place when heading error is large; otherwise drive forward
        # with speed scaled by alignment quality. The previous formulation
        # multiplied speed_scale BEFORE the max_speed cap, so a far-away goal
        # would saturate to max_speed and ignore the scale entirely — leaving
        # heavy 6-wheeled robots fighting between full forward motion and a
        # max-rate turn, generating massive wheel scrub and near-zero net
        # progress. Apply the scale AFTER capping, and stop forward motion
        # entirely when the robot is severely misaligned.
        abs_err = abs(heading_error)
        if abs_err > math.radians(45):
            speed_scale = 0.0  # turn in place
        elif abs_err > math.radians(22.5):
            speed_scale = 0.3
        elif abs_err > math.radians(10):
            speed_scale = 0.7
        else:
            speed_scale = 1.0

        max_speed = self._kinematics.get_max_speed()
        linear_vel = self._lin_kp * dist_to_goal
        linear_vel = min(linear_vel, max_speed) * speed_scale

        angular_vel = self._ang_kp * heading_error
        angular_vel = max(-self._max_ang, min(self._max_ang, angular_vel))

        self._drive.command_velocity(linear_vel, angular_vel)

        # Stall detection
        speed = math.hypot(odom.linear_velocity, 0.0)
        if speed < self._velocity_threshold and dist_to_goal > self._wp_tol:
            self._stall_timer += dt
            if self._stall_timer >= self._stall_timeout:
                self._drive.command_velocity(0.0, 0.0)
                return PathFollowerStatus.STALLED
        else:
            self._stall_timer = 0.0

        return PathFollowerStatus.FOLLOWING

    def get_distance_to_goal(self) -> float:
        if not self._path:
            return 0.0
        odom = self._odom.read()
        gx, gy = self._path[-1]
        return math.hypot(gx - odom.x, gy - odom.y)

    def is_goal_reached(self) -> bool:
        if not self._path:
            return False
        odom = self._odom.read()
        gx, gy = self._path[-1]
        return math.hypot(gx - odom.x, gy - odom.y) < self._wp_tol

    def stop(self) -> None:
        self._drive.command_velocity(0.0, 0.0)

    def get_current_target_index(self) -> int:
        return self._target_idx

    # -- Internals ------------------------------------------------------------

    def _find_lookahead(self, rx: float, ry: float) -> tuple[float, float]:
        """Return the lookahead point on the path ahead of the robot."""
        # Walk forward from current target to find a point at lookahead dist
        for i in range(self._target_idx, len(self._path)):
            wx, wy = self._path[i]
            if math.hypot(wx - rx, wy - ry) >= self._lookahead:
                return wx, wy
        # Fall back to the last waypoint
        return self._path[-1]

    @staticmethod
    def _wrap_angle(angle: float) -> float:
        """Wrap angle to [-pi, pi]."""
        while angle > math.pi:
            angle -= 2 * math.pi
        while angle < -math.pi:
            angle += 2 * math.pi
        return angle


# ---------------------------------------------------------------------------
# Navigator Facade
# ---------------------------------------------------------------------------

class NavigatorStatus:
    IDLE = "idle"
    NAVIGATING = "navigating"
    GOAL_REACHED = "goal_reached"
    REPLANNING = "replanning"
    BLOCKED = "blocked"


class Navigator:
    """High-level facade that ties planning and path-following together.

    Parameters
    ----------
    hal:
        A ``HalInterface`` instance for the robot.
    grid:
        The shared ``OccupancyGrid`` used for planning.
    ros_node:
        Optional ROS 2 node handle.  When ``None`` (test mode), ROS
        publishing is silently skipped.
    """

    MAX_REPLAN_ATTEMPTS = 3

    def __init__(self, hal, grid: OccupancyGrid, ros_node=None):
        self._hal = hal
        self._grid = grid
        self._ros_node = ros_node
        self._planner = AStarPlanner(grid)
        self._follower = PathFollower(
            hal.get_actuator("drive"),
            hal.get_sensor("odometry"),
            hal.get_kinematics(),
        )
        self._current_path: list[tuple[float, float]] = []
        self._goal: Optional[tuple[float, float]] = None
        self._status: str = NavigatorStatus.IDLE
        self._replan_count: int = 0

    # -- Planning -------------------------------------------------------------

    def plan_to(self, goal_xy: tuple[float, float]) -> PlanResult:
        """Plan a path from the current pose to *goal_xy*."""
        odom = self._hal.get_sensor("odometry").read()
        if not odom.is_valid:
            return PlanResult([], 0.0, False, "odometry not yet available")
        start = (odom.x, odom.y)
        return self._planner.plan(start, goal_xy)

    # -- Following ------------------------------------------------------------

    def start_following(self, path: list[tuple[float, float]]) -> None:
        """Begin following a pre-computed path."""
        self._current_path = list(path)
        self._follower.set_path(path)
        self._status = NavigatorStatus.NAVIGATING
        self._replan_count = 0
        if path:
            self._goal = path[-1]
        self.publish_path()

    def update(self, dt: float) -> str:
        """Tick the navigation loop.  Returns the navigator status."""
        if self._status not in (NavigatorStatus.NAVIGATING,
                                NavigatorStatus.REPLANNING):
            return self._status

        result = self._follower.update(dt)

        if result == PathFollowerStatus.GOAL_REACHED:
            self._status = NavigatorStatus.GOAL_REACHED
        elif result == PathFollowerStatus.STALLED:
            self._status = NavigatorStatus.REPLANNING
            replan = self.replan()
            if not replan.success:
                self._status = NavigatorStatus.BLOCKED
        elif result == PathFollowerStatus.NO_PATH:
            self._status = NavigatorStatus.IDLE

        return self._status

    def replan(self) -> PlanResult:
        """Attempt to find a new path to the current goal."""
        if self._goal is None:
            return PlanResult([], 0.0, False, "no goal set")

        self._replan_count += 1
        if self._replan_count > self.MAX_REPLAN_ATTEMPTS:
            return PlanResult([], 0.0, False, "max replan attempts exceeded")

        result = self.plan_to(self._goal)
        if result.success:
            self._current_path = result.path
            self._follower.set_path(result.path)
            self._status = NavigatorStatus.NAVIGATING
            self.publish_path()
        return result

    # -- Control --------------------------------------------------------------

    def stop(self) -> None:
        self._follower.stop()
        self._status = NavigatorStatus.IDLE
        self._goal = None
        self._current_path = []

    # -- Queries --------------------------------------------------------------

    def get_current_pose(self) -> tuple[float, float, float]:
        odom = self._hal.get_sensor("odometry").read()
        return (odom.x, odom.y, odom.theta)

    def get_distance_to_goal(self) -> float:
        return self._follower.get_distance_to_goal()

    def get_remaining_path(self) -> list[tuple[float, float]]:
        if not self._current_path:
            return []
        idx = self._follower.get_current_target_index()
        return self._current_path[idx:]

    @property
    def status(self) -> str:
        return self._status

    # -- Obstacle update ------------------------------------------------------

    def update_obstacle(self, wx: float, wy: float, radius: float) -> None:
        """Mark a newly-detected obstacle on the shared grid."""
        self._grid.mark_obstacle_circle(wx, wy, radius)

    # -- ROS publishing (optional) --------------------------------------------

    def publish_path(self) -> None:
        """Publish the current path as a ``nav_msgs/Path`` if a ROS node
        is available.  Silently skipped in test mode."""
        if self._ros_node is None or not self._current_path:
            return
        try:
            from nav_msgs.msg import Path
            from geometry_msgs.msg import PoseStamped

            if not hasattr(self, "_path_pub"):
                self._path_pub = self._ros_node.create_publisher(
                    Path, "planned_path", 10,
                )

            msg = Path()
            msg.header.frame_id = "map"
            now = self._ros_node.get_clock().now().to_msg()
            msg.header.stamp = now

            for wx, wy in self._current_path:
                ps = PoseStamped()
                ps.header.frame_id = "map"
                ps.header.stamp = now
                ps.pose.position.x = wx
                ps.pose.position.y = wy
                msg.poses.append(ps)

            self._path_pub.publish(msg)
        except ImportError:
            pass
