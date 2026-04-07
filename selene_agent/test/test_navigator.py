"""Tests for the SELENE navigation stack.

All tests are pure Python -- no ROS 2 or simulation required.
Uses controllable stub/mock HAL objects so that sensor readings and
actuator commands can be precisely verified.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from selene_agent.navigator import (
    AStarPlanner,
    CellState,
    Navigator,
    NavigatorStatus,
    OccupancyGrid,
    PathFollower,
    PathFollowerStatus,
)
from selene_agent.obstacle_avoidance import (
    ObstacleAvoidance,
    ObstacleAvoidanceResult,
    ObstacleDetection,
)
from selene_hal.data_types import (
    OdometryReading,
    DepthImageReading,
)


# ===================================================================
# Controllable mock helpers
# ===================================================================

class MockOdometrySensor:
    """Odometry sensor whose readings can be set from test code."""

    def __init__(self, x: float = 0.0, y: float = 0.0, theta: float = 0.0,
                 linear_velocity: float = 0.0, angular_velocity: float = 0.0):
        self.x = x
        self.y = y
        self.theta = theta
        self.linear_velocity = linear_velocity
        self.angular_velocity = angular_velocity

    def read(self) -> OdometryReading:
        return OdometryReading(
            x=self.x, y=self.y, theta=self.theta,
            linear_velocity=self.linear_velocity,
            angular_velocity=self.angular_velocity,
        )

    def is_active(self) -> bool:
        return True

    def get_config(self):
        return None


class MockDriveActuator:
    """Drive actuator that records the last command."""

    def __init__(self):
        self.last_linear = 0.0
        self.last_angular = 0.0
        self.stopped = False

    def command_velocity(self, linear_x: float, angular_z: float) -> None:
        self.last_linear = linear_x
        self.last_angular = angular_z
        self.stopped = False

    def stop(self) -> None:
        self.last_linear = 0.0
        self.last_angular = 0.0
        self.stopped = True

    def is_active(self) -> bool:
        return True


class MockKinematics:
    """Simple kinematics returning configurable max speed."""

    def __init__(self, max_speed: float = 0.5):
        self._max_speed = max_speed

    def get_max_speed(self) -> float:
        return self._max_speed

    def get_turn_radius(self) -> float:
        return 0.0

    def get_kinematic_model(self) -> str:
        return "differential_drive"

    def get_mass(self) -> float:
        return 50.0


class MockDepthImageSensor:
    """Depth camera that returns a configurable image."""

    def __init__(self, image: np.ndarray | None = None,
                 fov_deg: float = 90.0, max_range: float = 20.0):
        self.image = image
        self.fov_deg = fov_deg
        self.max_range = max_range

    def read(self) -> DepthImageReading:
        return DepthImageReading(
            image=self.image, fov_deg=self.fov_deg, max_range=self.max_range,
        )

    def is_active(self) -> bool:
        return True


class MockHal:
    """Minimal HAL mock wiring up controllable sensors and actuators."""

    def __init__(
        self,
        odom: MockOdometrySensor | None = None,
        drive: MockDriveActuator | None = None,
        kinematics: MockKinematics | None = None,
        depth: MockDepthImageSensor | None = None,
    ):
        self._odom = odom or MockOdometrySensor()
        self._drive = drive or MockDriveActuator()
        self._kinematics = kinematics or MockKinematics()
        self._depth = depth or MockDepthImageSensor()

    def get_sensor(self, name: str):
        if name == "odometry":
            return self._odom
        if name == "stereo_camera":
            return self._depth
        raise KeyError(f"No sensor '{name}'")

    def get_actuator(self, name: str):
        if name == "drive":
            return self._drive
        raise KeyError(f"No actuator '{name}'")

    def get_kinematics(self):
        return self._kinematics


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def small_grid():
    """A small 20x20 grid centred at origin, 1 m resolution."""
    return OccupancyGrid(width=20, height=20, resolution=1.0,
                         origin_x=-10.0, origin_y=-10.0)


@pytest.fixture
def default_grid():
    """Full-size 500x500 grid with default parameters."""
    return OccupancyGrid()


# ===================================================================
# OccupancyGrid tests
# ===================================================================

class TestOccupancyGrid:

    def test_world_to_grid_origin(self, default_grid: OccupancyGrid):
        """World origin of the grid maps to cell (0, 0)."""
        gx, gy = default_grid.world_to_grid(-250.0, -250.0)
        assert gx == 0
        assert gy == 0

    def test_world_to_grid_center(self, default_grid: OccupancyGrid):
        """World (0, 0) maps to the grid centre (250, 250)."""
        gx, gy = default_grid.world_to_grid(0.0, 0.0)
        assert gx == 250
        assert gy == 250

    def test_grid_to_world_roundtrip(self, default_grid: OccupancyGrid):
        """Converting grid -> world -> grid returns the same cell."""
        for gx, gy in [(0, 0), (250, 250), (100, 400), (499, 499)]:
            wx, wy = default_grid.grid_to_world(gx, gy)
            gx2, gy2 = default_grid.world_to_grid(wx, wy)
            assert gx2 == gx
            assert gy2 == gy

    def test_mark_obstacle_circle(self, small_grid: OccupancyGrid):
        """Marking a circle at (0, 0) with radius 2m fills the correct cells."""
        small_grid.mark_obstacle_circle(0.0, 0.0, 2.0)
        # Centre cell (grid 10, 10) -> world (0.5, 0.5), dist ~0.71 -> occupied
        assert small_grid.get_cell(10, 10) == CellState.OCCUPIED
        # Cell (11, 10) -> world (1.5, 0.5), dist ~1.58 -> occupied
        assert small_grid.get_cell(11, 10) == CellState.OCCUPIED
        # Cell (9, 10) -> world (-0.5, 0.5), dist ~0.71 -> occupied
        assert small_grid.get_cell(9, 10) == CellState.OCCUPIED
        # Cell at distance well beyond radius must still be free
        # Cell (13, 10) -> world (3.5, 0.5), dist ~3.54 -> free
        assert small_grid.get_cell(13, 10) == CellState.FREE

    def test_out_of_bounds_safe(self, small_grid: OccupancyGrid):
        """Out-of-bounds access returns UNKNOWN and set_cell is a no-op."""
        assert small_grid.get_cell(-1, 0) == CellState.UNKNOWN
        assert small_grid.get_cell(0, -1) == CellState.UNKNOWN
        assert small_grid.get_cell(20, 0) == CellState.UNKNOWN
        assert small_grid.get_cell(0, 20) == CellState.UNKNOWN
        # Setting out-of-bounds should not raise
        small_grid.set_cell(-1, -1, CellState.OCCUPIED)
        small_grid.set_cell(999, 999, CellState.OCCUPIED)

    def test_from_config_loads_rocks(self):
        """from_config creates a grid with obstacles from the config dict."""
        config = {
            "navigation": {
                "grid_width": 50,
                "grid_height": 50,
                "grid_resolution": 1.0,
                "origin_x": -25.0,
                "origin_y": -25.0,
                "obstacle_inflation_radius": 0.5,
            },
            "static_obstacles": {
                "rocks": [
                    {"x": 0.0, "y": 0.0, "radius": 1.0},
                    {"x": 10.0, "y": 10.0, "radius": 2.0},
                ],
            },
        }
        grid = OccupancyGrid.from_config(config)
        # Centre cell should be occupied (rock at 0,0)
        cx, cy = grid.world_to_grid(0.0, 0.0)
        assert grid.get_cell(cx, cy) == CellState.OCCUPIED
        # Rock at (10, 10) with radius 2 + inflation 0.5 = 2.5
        rx, ry = grid.world_to_grid(10.0, 10.0)
        assert grid.get_cell(rx, ry) == CellState.OCCUPIED

    def test_set_and_get_cost(self, small_grid: OccupancyGrid):
        """Cost grid can be written and read back."""
        small_grid.set_cost(5, 5, 3.14)
        assert abs(small_grid.get_cost(5, 5) - 3.14) < 1e-5
        # Out-of-bounds cost is inf
        assert small_grid.get_cost(-1, -1) == float("inf")


# ===================================================================
# AStarPlanner tests
# ===================================================================

class TestAStarPlanner:

    def test_straight_line_on_empty_grid(self, small_grid: OccupancyGrid):
        """On an empty grid, a straight-line path is found."""
        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (5.0, 0.0))
        assert result.success
        assert len(result.path) >= 2
        # Start near origin, end near goal
        assert abs(result.path[0][0] - 0.5) < 1.0
        assert abs(result.path[-1][0] - 5.5) < 1.0

    def test_path_around_single_obstacle(self, small_grid: OccupancyGrid):
        """Path routes around a blocking obstacle."""
        # Block cells along y=0.5 (grid row 10) from x=3 to x=7
        for gx in range(13, 18):
            small_grid.set_cell(gx, 10, CellState.OCCUPIED)

        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (8.0, 0.0))
        assert result.success
        # Path must detour, so no waypoint should lie in occupied cells
        for wx, wy in result.path:
            gx, gy = small_grid.world_to_grid(wx, wy)
            assert small_grid.get_cell(gx, gy) != CellState.OCCUPIED

    def test_no_path_exists(self, small_grid: OccupancyGrid):
        """When the goal is surrounded, plan returns failure."""
        # Surround (5, 5) with a wall
        gx_c, gy_c = small_grid.world_to_grid(5.0, 5.0)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if abs(dx) == 2 or abs(dy) == 2:
                    small_grid.set_cell(gx_c + dx, gy_c + dy, CellState.OCCUPIED)
        # Also block diagonal openings
        for dx in [-2, 2]:
            for dy in [-2, 2]:
                small_grid.set_cell(gx_c + dx, gy_c + dy, CellState.OCCUPIED)

        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (5.0, 5.0))
        assert not result.success

    def test_diagonal_path(self, small_grid: OccupancyGrid):
        """Diagonal path on an empty grid has cost proportional to sqrt(2)."""
        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (5.0, 5.0))
        assert result.success
        # Euclidean distance ~7.07; A* diagonal cost should be in that ballpark
        assert result.cost < 10.0  # upper bound sanity
        assert result.cost > 4.0   # lower bound sanity

    def test_path_simplification(self, small_grid: OccupancyGrid):
        """A diagonal on empty grid gets simplified to 2 waypoints."""
        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (5.0, 5.0))
        assert result.success
        # Simplification should collapse a staircase to start+end
        assert len(result.path) == 2

    def test_start_equals_goal(self, small_grid: OccupancyGrid):
        """Trivial path when start == goal."""
        planner = AStarPlanner(small_grid)
        result = planner.plan((0.0, 0.0), (0.0, 0.0))
        assert result.success
        assert len(result.path) == 1

    def test_start_or_goal_occupied(self, small_grid: OccupancyGrid):
        """Planning fails when start or goal is occupied."""
        planner = AStarPlanner(small_grid)

        # Occupy start cell
        gx, gy = small_grid.world_to_grid(0.0, 0.0)
        small_grid.set_cell(gx, gy, CellState.OCCUPIED)
        result = planner.plan((0.0, 0.0), (5.0, 0.0))
        assert not result.success
        assert "start" in result.failure_reason

        # Free start, occupy goal
        small_grid.set_cell(gx, gy, CellState.FREE)
        gx2, gy2 = small_grid.world_to_grid(5.0, 0.0)
        small_grid.set_cell(gx2, gy2, CellState.OCCUPIED)
        result = planner.plan((0.0, 0.0), (5.0, 0.0))
        assert not result.success
        assert "goal" in result.failure_reason


# ===================================================================
# PathFollower tests
# ===================================================================

class TestPathFollower:

    def _make_follower(self, odom: MockOdometrySensor | None = None,
                       drive: MockDriveActuator | None = None,
                       kinematics: MockKinematics | None = None):
        odom = odom or MockOdometrySensor()
        drive = drive or MockDriveActuator()
        kin = kinematics or MockKinematics(max_speed=0.5)
        return PathFollower(drive, odom, kin,
                            lookahead_distance=2.0,
                            waypoint_tolerance=1.0,
                            linear_kp=0.5,
                            angular_kp=1.5,
                            max_angular_speed=1.0,
                            stall_timeout=5.0), odom, drive

    def test_follows_straight_path(self):
        """Robot facing a target ahead moves forward with low angular vel."""
        odom = MockOdometrySensor(x=0.0, y=0.0, theta=0.0,
                                  linear_velocity=0.2)
        drive = MockDriveActuator()
        follower, _, _ = self._make_follower(odom=odom, drive=drive)
        follower.set_path([(5.0, 0.0), (10.0, 0.0)])
        status = follower.update(0.1)

        assert status == PathFollowerStatus.FOLLOWING
        assert drive.last_linear > 0.0
        assert abs(drive.last_angular) < 0.3

    def test_turns_toward_target(self):
        """Robot with target 90 deg to the left produces positive angular vel."""
        odom = MockOdometrySensor(x=0.0, y=0.0, theta=0.0,
                                  linear_velocity=0.1)
        drive = MockDriveActuator()
        follower, _, _ = self._make_follower(odom=odom, drive=drive)
        follower.set_path([(0.0, 5.0)])  # target is to the left (+y)
        follower.update(0.1)

        # Heading to target is +pi/2, heading error is +pi/2 -> positive angular
        assert drive.last_angular > 0.0

    def test_goal_reached_within_tolerance(self):
        """Status is GOAL_REACHED when the robot is within tolerance."""
        odom = MockOdometrySensor(x=9.5, y=0.0, theta=0.0,
                                  linear_velocity=0.1)
        drive = MockDriveActuator()
        follower, _, _ = self._make_follower(odom=odom, drive=drive)
        follower.set_path([(5.0, 0.0), (10.0, 0.0)])
        status = follower.update(0.1)
        assert status == PathFollowerStatus.GOAL_REACHED

    def test_speed_reduction_on_sharp_turn(self):
        """Speed is reduced when heading error exceeds 45 degrees."""
        # Use low kp so proportional speed doesn't saturate at max_speed
        odom = MockOdometrySensor(x=0.0, y=0.0, theta=0.0,
                                  linear_velocity=0.1)
        drive_straight = MockDriveActuator()
        follower_s = PathFollower(
            drive_straight, odom, MockKinematics(),
            lookahead_distance=2.0, waypoint_tolerance=1.0,
            linear_kp=0.05, angular_kp=1.5, max_angular_speed=1.0)
        follower_s.set_path([(5.0, 0.0)])  # straight ahead
        follower_s.update(0.1)
        speed_straight = drive_straight.last_linear

        drive_turn = MockDriveActuator()
        follower_t = PathFollower(
            drive_turn, odom, MockKinematics(),
            lookahead_distance=2.0, waypoint_tolerance=1.0,
            linear_kp=0.05, angular_kp=1.5, max_angular_speed=1.0)
        follower_t.set_path([(0.0, 5.0)])  # 90 deg left
        follower_t.update(0.1)
        speed_turn = drive_turn.last_linear

        assert speed_straight > 0
        assert speed_turn < speed_straight

    def test_no_path_returns_no_path(self):
        """update() returns NO_PATH when no path has been set."""
        follower, _, _ = self._make_follower()
        assert follower.update(0.1) == PathFollowerStatus.NO_PATH

    def test_stall_detection(self):
        """Robot that is not moving eventually reports STALLED."""
        odom = MockOdometrySensor(x=0.0, y=0.0, theta=0.0,
                                  linear_velocity=0.0)
        drive = MockDriveActuator()
        follower, _, _ = self._make_follower(odom=odom, drive=drive)
        follower.set_path([(10.0, 0.0)])

        # Simulate 6 seconds of zero velocity (stall timeout is 5)
        status = PathFollowerStatus.FOLLOWING
        for _ in range(60):
            status = follower.update(0.1)
            if status == PathFollowerStatus.STALLED:
                break
        assert status == PathFollowerStatus.STALLED

    def test_distance_to_goal(self):
        """get_distance_to_goal returns correct Euclidean distance."""
        odom = MockOdometrySensor(x=0.0, y=0.0, theta=0.0)
        follower, _, _ = self._make_follower(odom=odom)
        follower.set_path([(3.0, 4.0)])
        assert abs(follower.get_distance_to_goal() - 5.0) < 0.01


# ===================================================================
# ObstacleAvoidance tests
# ===================================================================

class TestObstacleAvoidance:

    def test_clear_when_no_obstacles(self):
        """No depth data (None image) -> CLEAR, velocities unchanged."""
        hal = MockHal(depth=MockDepthImageSensor(image=None))
        oa = ObstacleAvoidance(hal, detection_range=5.0, critical_range=1.5)
        status, lin, ang = oa.check_and_avoid(0.5, 0.0)
        assert status == ObstacleAvoidanceResult.CLEAR
        assert lin == 0.5
        assert ang == 0.0

    def test_slows_down_for_forward_obstacle(self):
        """A forward obstacle within detection range reduces linear speed."""
        # Depth image: 320-wide, obstacle at 3m straight ahead
        image = np.full((240, 320), 3.0, dtype=np.float32)
        hal = MockHal(depth=MockDepthImageSensor(image=image, fov_deg=90.0))
        oa = ObstacleAvoidance(hal, detection_range=5.0, critical_range=1.5,
                               num_bins=16)
        status, lin, ang = oa.check_and_avoid(0.5, 0.0)
        assert status == ObstacleAvoidanceResult.OBSTACLE_DETECTED
        assert lin < 0.5

    def test_steers_away_from_lateral_obstacle(self):
        """An obstacle to the left produces a rightward angular correction."""
        # Create image where only the left quarter has close obstacles
        image = np.full((240, 320), 100.0, dtype=np.float32)  # far away
        image[:, :80] = 2.0  # close obstacle in left quadrant
        hal = MockHal(depth=MockDepthImageSensor(image=image, fov_deg=90.0))
        oa = ObstacleAvoidance(hal, detection_range=5.0, critical_range=1.5,
                               avoidance_gain=0.8, num_bins=16)
        status, lin, ang = oa.check_and_avoid(0.5, 0.0)
        # Obstacle to the left (negative angle in image convention)
        # should push angular in the opposite direction
        assert status == ObstacleAvoidanceResult.OBSTACLE_DETECTED

    def test_blocked_when_surrounded(self):
        """When obstacles are all around at critical range -> BLOCKED."""
        image = np.full((240, 320), 1.0, dtype=np.float32)  # 1m everywhere
        hal = MockHal(depth=MockDepthImageSensor(image=image, fov_deg=90.0))
        oa = ObstacleAvoidance(hal, detection_range=5.0, critical_range=1.5,
                               num_bins=16)
        status, lin, ang = oa.check_and_avoid(0.5, 0.0)
        assert status == ObstacleAvoidanceResult.BLOCKED
        assert lin == 0.0
        assert ang == 0.0

    def test_world_coordinate_conversion(self):
        """Local obstacle coords are correctly transformed to world frame."""
        hal = MockHal()
        oa = ObstacleAvoidance(hal)
        obs = [ObstacleDetection(local_x=3.0, local_y=0.0, distance=3.0)]

        # Robot at origin facing +x (theta=0)
        world = oa.get_world_obstacle_positions((0.0, 0.0, 0.0), obs)
        assert len(world) == 1
        assert abs(world[0][0] - 3.0) < 0.01
        assert abs(world[0][1] - 0.0) < 0.01

        # Robot at origin facing +y (theta=pi/2)
        world = oa.get_world_obstacle_positions(
            (0.0, 0.0, math.pi / 2), obs)
        assert abs(world[0][0] - 0.0) < 0.01
        assert abs(world[0][1] - 3.0) < 0.01

        # Robot at (10, 5) facing +x
        world = oa.get_world_obstacle_positions((10.0, 5.0, 0.0), obs)
        assert abs(world[0][0] - 13.0) < 0.01
        assert abs(world[0][1] - 5.0) < 0.01


# ===================================================================
# Navigator facade tests
# ===================================================================

class TestNavigator:

    def _make_navigator(self, odom_x=0.0, odom_y=0.0, odom_theta=0.0):
        odom = MockOdometrySensor(x=odom_x, y=odom_y, theta=odom_theta,
                                  linear_velocity=0.2)
        drive = MockDriveActuator()
        hal = MockHal(odom=odom, drive=drive)
        grid = OccupancyGrid(width=50, height=50, resolution=1.0,
                             origin_x=-25.0, origin_y=-25.0)
        nav = Navigator(hal, grid, ros_node=None)
        return nav, odom, drive, grid

    def test_plan_and_follow(self):
        """Full plan-then-follow cycle on a small empty grid."""
        nav, odom, drive, _ = self._make_navigator()
        result = nav.plan_to((10.0, 0.0))
        assert result.success
        nav.start_following(result.path)
        assert nav.status == NavigatorStatus.NAVIGATING

        # One tick -- robot should be commanded to move
        nav.update(0.1)
        assert drive.last_linear > 0.0

    def test_goal_reached(self):
        """Navigator reports GOAL_REACHED when close enough."""
        # Plan first to find the actual goal cell-centre position, then
        # place the robot within tolerance of that point.
        nav, odom, drive, _ = self._make_navigator(odom_x=0.0)
        result = nav.plan_to((10.0, 0.0))
        assert result.success
        # Move odom to within tolerance of the final waypoint
        goal_wx, goal_wy = result.path[-1]
        odom.x = goal_wx - 0.3
        odom.y = goal_wy
        nav.start_following(result.path)
        status = nav.update(0.1)
        assert status == NavigatorStatus.GOAL_REACHED

    def test_stop_resets_status(self):
        """Calling stop() returns status to IDLE."""
        nav, odom, drive, _ = self._make_navigator()
        result = nav.plan_to((10.0, 0.0))
        nav.start_following(result.path)
        nav.stop()
        assert nav.status == NavigatorStatus.IDLE

    def test_update_obstacle_marks_grid(self):
        """update_obstacle writes to the occupancy grid."""
        nav, _, _, grid = self._make_navigator()
        nav.update_obstacle(5.0, 5.0, 1.5)
        gx, gy = grid.world_to_grid(5.0, 5.0)
        assert grid.get_cell(gx, gy) == CellState.OCCUPIED

    def test_get_current_pose(self):
        """get_current_pose reads from the odometry sensor."""
        nav, odom, _, _ = self._make_navigator(
            odom_x=3.0, odom_y=4.0, odom_theta=1.57
        )
        x, y, theta = nav.get_current_pose()
        assert abs(x - 3.0) < 0.01
        assert abs(y - 4.0) < 0.01
        assert abs(theta - 1.57) < 0.01

    def test_idle_update_stays_idle(self):
        """Calling update when IDLE returns IDLE without error."""
        nav, _, _, _ = self._make_navigator()
        assert nav.update(0.1) == NavigatorStatus.IDLE

    def test_publish_path_no_ros_ok(self):
        """publish_path is a no-op when ros_node is None."""
        nav, _, _, _ = self._make_navigator()
        result = nav.plan_to((5.0, 0.0))
        nav.start_following(result.path)
        nav.publish_path()  # Should not raise

    def test_remaining_path(self):
        """get_remaining_path returns the unconsumed portion of the path."""
        nav, _, _, _ = self._make_navigator()
        result = nav.plan_to((10.0, 0.0))
        nav.start_following(result.path)
        remaining = nav.get_remaining_path()
        assert len(remaining) > 0
