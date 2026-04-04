"""Reactive obstacle avoidance for SELENE lunar robots.

Processes depth-camera images into obstacle detections and computes
avoidance velocities using a potential-field approach.  Works through
the HAL so it is backend-agnostic.

Importable without rclpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ObstacleDetection:
    """A single obstacle in the robot's local frame."""
    local_x: float
    local_y: float
    distance: float


class ObstacleAvoidanceResult:
    CLEAR = "clear"
    OBSTACLE_DETECTED = "obstacle_detected"
    BLOCKED = "blocked"


class ObstacleAvoidance:
    """Reactive obstacle avoidance using depth-image processing.

    Reads the depth camera through the HAL, bins the image into angular
    sectors, and applies a repulsive potential-field to adjust the
    commanded velocity.

    Parameters
    ----------
    hal:
        ``HalInterface`` instance for the robot.
    detection_range:
        Maximum range (m) at which obstacles are considered.
    critical_range:
        Range (m) below which the robot is considered blocked.
    avoidance_gain:
        Strength of the repulsive angular push.
    slow_factor:
        Speed multiplier applied when an obstacle is inside
        *detection_range*.
    num_bins:
        Number of angular bins the depth image is divided into.
    """

    def __init__(
        self,
        hal,
        detection_range: float = 5.0,
        critical_range: float = 1.5,
        avoidance_gain: float = 0.8,
        slow_factor: float = 0.3,
        num_bins: int = 16,
    ):
        self._hal = hal
        self._detection_range = detection_range
        self._critical_range = critical_range
        self._avoidance_gain = avoidance_gain
        self._slow_factor = slow_factor
        self._num_bins = num_bins

    # -- Public API -----------------------------------------------------------

    def check_and_avoid(
        self,
        desired_linear: float,
        desired_angular: float,
    ) -> tuple[str, float, float]:
        """Read the depth camera and compute safe velocities.

        Returns
        -------
        (status, adjusted_linear, adjusted_angular)
            *status* is one of ``ObstacleAvoidanceResult`` constants.
        """
        depth_sensor = self._hal.get_sensor("stereo_camera")
        reading = depth_sensor.read()

        if reading.image is None:
            # No depth data available -- pass through desired velocities.
            return ObstacleAvoidanceResult.CLEAR, desired_linear, desired_angular

        fov_rad = math.radians(reading.fov_deg) if reading.fov_deg > 0 else math.radians(90.0)
        obstacles = self.process_depth_image(reading.image, fov_rad)

        return self.compute_avoidance_velocity(
            desired_linear, desired_angular, obstacles,
        )

    # -- Depth processing -----------------------------------------------------

    def process_depth_image(
        self,
        image: np.ndarray,
        fov_rad: float,
    ) -> list[ObstacleDetection]:
        """Convert a depth image into a list of ``ObstacleDetection``.

        The image is divided into ``num_bins`` vertical strips; the
        minimum depth in each strip becomes one detection.
        """
        if image.ndim == 1:
            row = image
        elif image.ndim >= 2:
            # Use the middle row for distance estimation.
            mid_row = image.shape[0] // 2
            row = image[mid_row]
            if row.ndim > 1:
                row = row.flatten()
        else:
            return []

        width = len(row)
        if width == 0:
            return []

        bin_width = max(1, width // self._num_bins)
        half_fov = fov_rad / 2.0
        detections: list[ObstacleDetection] = []

        for b in range(self._num_bins):
            start = b * bin_width
            end = min(start + bin_width, width)
            if start >= width:
                break
            segment = row[start:end]
            valid = segment[segment > 0]
            if len(valid) == 0:
                continue
            min_depth = float(np.min(valid))
            if min_depth > self._detection_range:
                continue

            # Angle of the bin centre relative to forward (0 rad).
            bin_centre_pixel = (start + end) / 2.0
            angle = -half_fov + (bin_centre_pixel / width) * fov_rad

            local_x = min_depth * math.cos(angle)
            local_y = min_depth * math.sin(angle)
            detections.append(ObstacleDetection(local_x, local_y, min_depth))

        return detections

    # -- Avoidance velocity ---------------------------------------------------

    def compute_avoidance_velocity(
        self,
        desired_linear: float,
        desired_angular: float,
        obstacles: list[ObstacleDetection],
    ) -> tuple[str, float, float]:
        """Compute adjusted velocity using a repulsive potential field.

        Returns ``(status, linear, angular)``.
        """
        if not obstacles:
            return ObstacleAvoidanceResult.CLEAR, desired_linear, desired_angular

        # Count obstacles in critical range in front of the robot.
        front_critical = 0
        total_repulsive_angular = 0.0
        min_distance = float("inf")
        critical_count = 0

        for obs in obstacles:
            min_distance = min(min_distance, obs.distance)
            if obs.distance < self._critical_range:
                critical_count += 1
                if obs.local_x > 0:
                    front_critical += 1

            # Repulsive angular push -- inverse-square, direction away
            if obs.distance > 0 and obs.distance < self._detection_range:
                strength = (1.0 / obs.distance - 1.0 / self._detection_range)
                # Push *away* from the obstacle: if obstacle is to the left
                # (local_y > 0) push right (negative angular).
                angle_to_obs = math.atan2(obs.local_y, obs.local_x)
                total_repulsive_angular -= self._avoidance_gain * strength * math.sin(angle_to_obs)

        # Blocked: critical obstacles on all sides
        blocked_threshold = max(1, self._num_bins // 4)
        if critical_count >= blocked_threshold:
            return ObstacleAvoidanceResult.BLOCKED, 0.0, 0.0

        # Speed reduction
        if min_distance < self._detection_range:
            ratio = max(0.0, min(1.0, (min_distance - self._critical_range)
                                 / (self._detection_range - self._critical_range)))
            speed_factor = self._slow_factor + (1.0 - self._slow_factor) * ratio
        else:
            speed_factor = 1.0

        adjusted_linear = desired_linear * speed_factor
        adjusted_angular = desired_angular + total_repulsive_angular

        return ObstacleAvoidanceResult.OBSTACLE_DETECTED, adjusted_linear, adjusted_angular

    # -- Coordinate conversion ------------------------------------------------

    def get_world_obstacle_positions(
        self,
        robot_pose: tuple[float, float, float],
        obstacles: list[ObstacleDetection],
    ) -> list[tuple[float, float]]:
        """Convert local-frame obstacles to world coordinates.

        Parameters
        ----------
        robot_pose:
            ``(x, y, theta)`` of the robot in the world frame.
        obstacles:
            List of detections in the robot's local frame.

        Returns
        -------
        list of (world_x, world_y)
        """
        rx, ry, rtheta = robot_pose
        cos_t = math.cos(rtheta)
        sin_t = math.sin(rtheta)
        positions: list[tuple[float, float]] = []
        for obs in obstacles:
            wx = rx + cos_t * obs.local_x - sin_t * obs.local_y
            wy = ry + sin_t * obs.local_x + cos_t * obs.local_y
            positions.append((wx, wy))
        return positions
