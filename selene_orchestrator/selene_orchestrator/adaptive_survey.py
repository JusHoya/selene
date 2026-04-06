"""Adaptive survey planner -- uncertainty-driven waypoint selection.

Replaces the static hexagonal grid with an information-theoretic approach
that directs scouts toward high-value areas (high uncertainty near known signals).

Scoring function per candidate cell:
    score = w_var * normalized_variance
          + w_sig * normalized_neighbor_signal
          - w_dist * normalized_distance

Candidates: grid cells within the PSR zone, filtered to min_spacing from
already-visited or queued waypoints.
"""

import math

import numpy as np


class AdaptiveSurveyPlanner:
    """Information-gain waypoint planner for ice prospecting surveys.

    Selects the next best waypoint by scoring candidate cells on three
    criteria: posterior variance (explore the unknown), neighbor signal
    strength (exploit near finds), and distance cost (prefer nearby).
    """

    def __init__(self, resource_map,
                 psr_center: tuple[float, float] = (-100.0, -150.0),
                 psr_radius: float = 60.0,
                 w_variance: float = 1.0,
                 w_signal: float = 0.5,
                 w_distance: float = 0.3,
                 min_spacing: float = 8.0,
                 candidate_resolution: float = 5.0):
        """
        Parameters:
            resource_map: ResourceMap instance to query for mean/variance.
            psr_center: Center of the PSR survey zone (x, y) in meters.
            psr_radius: Radius of the PSR survey zone in meters.
            w_variance: Weight for uncertainty term (explore unknown).
            w_signal: Weight for neighbor signal term (exploit near finds).
            w_distance: Weight for distance penalty (prefer nearby).
            min_spacing: Minimum distance between selected waypoints in meters.
            candidate_resolution: Spacing between candidate grid points in meters.
        """
        self._resource_map = resource_map
        self._psr_center = psr_center
        self._psr_radius = psr_radius
        self._w_variance = w_variance
        self._w_signal = w_signal
        self._w_distance = w_distance
        self._min_spacing = min_spacing
        self._candidate_resolution = candidate_resolution

    def select_next_waypoint(self,
                             robot_position: tuple[float, float],
                             visited: set[tuple[float, float]] | None = None,
                             queued: set[tuple[float, float]] | None = None
                             ) -> tuple[float, float] | None:
        """Select the highest-scoring candidate cell for the given robot.

        Returns (x, y) world coordinates of the best unvisited cell, or None
        if all candidates are exhausted.
        """
        visited = visited or set()
        queued = queued or set()

        candidates = self._generate_candidates(visited, queued)
        if not candidates:
            return None

        robot_x, robot_y = robot_position

        # Pre-compute raw values for normalization
        variances = np.array([
            self._resource_map.get_variance(wx, wy)
            for wx, wy in candidates
        ])
        signals = np.array([
            self._get_neighbor_signal(wx, wy)
            for wx, wy in candidates
        ])
        distances = np.array([
            math.sqrt((wx - robot_x) ** 2 + (wy - robot_y) ** 2)
            for wx, wy in candidates
        ])

        # Normalize each component to [0, 1]
        max_var = variances.max()
        norm_var = variances / max_var if max_var > 0 else np.zeros_like(variances)

        max_sig = signals.max()
        norm_sig = signals / max_sig if max_sig > 0 else np.zeros_like(signals)

        max_dist = distances.max()
        norm_dist = distances / max_dist if max_dist > 0 else np.zeros_like(distances)

        # Score: high variance + high signal - distance cost
        scores = (self._w_variance * norm_var
                  + self._w_signal * norm_sig
                  - self._w_distance * norm_dist)

        best_idx = int(np.argmax(scores))
        return candidates[best_idx]

    def _generate_candidates(self, visited, queued) -> list[tuple[float, float]]:
        """Generate candidate waypoints within PSR zone, filtered by spacing."""
        cx, cy = self._psr_center
        r = self._psr_radius
        res = self._candidate_resolution

        # Occupied positions: union of visited and queued
        occupied = list(visited | queued)

        # Build grid covering the bounding box of the PSR circle
        x_min = cx - r
        x_max = cx + r
        y_min = cy - r
        y_max = cy + r

        num_x = int((x_max - x_min) / res) + 1
        num_y = int((y_max - y_min) / res) + 1

        candidates = []
        for ix in range(num_x):
            wx = x_min + ix * res
            for iy in range(num_y):
                wy = y_min + iy * res

                # PSR boundary check
                dist_to_center = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist_to_center > r:
                    continue

                # Grid bounds check
                gx, gy = self._resource_map.world_to_grid(wx, wy)
                if not self._resource_map.is_in_bounds(gx, gy):
                    continue

                # Min spacing from occupied waypoints
                too_close = False
                for ox, oy in occupied:
                    if math.sqrt((wx - ox) ** 2 + (wy - oy) ** 2) < self._min_spacing:
                        too_close = True
                        break
                if too_close:
                    continue

                candidates.append((wx, wy))

        return candidates

    def _score_candidate(self, wx: float, wy: float,
                         robot_x: float, robot_y: float) -> float:
        """Compute information-gain score for a candidate position.

        Components:
        1. Variance: higher variance = more to learn = higher score
        2. Neighbor signal: neighboring cells with high mean ice concentration
           indicate this cell is worth investigating (follow the gradient)
        3. Distance: closer to robot = cheaper to reach = bonus

        All components normalized to [0, 1] before weighting.

        Note: this standalone method normalizes against single-point reference
        values. For batch selection, select_next_waypoint() uses cross-candidate
        normalization which produces better results.
        """
        variance = self._resource_map.get_variance(wx, wy)
        signal = self._get_neighbor_signal(wx, wy)
        distance = math.sqrt((wx - robot_x) ** 2 + (wy - robot_y) ** 2)

        # Use PSR diameter as normalization reference for distance
        max_dist = 2 * self._psr_radius
        norm_dist = min(distance / max_dist, 1.0) if max_dist > 0 else 0.0

        # Variance normalized by prior (100.0 is typical prior_variance)
        norm_var = min(variance / 100.0, 1.0)

        # Signal normalized by a reasonable peak concentration
        norm_sig = min(signal / 10.0, 1.0)

        return (self._w_variance * norm_var
                + self._w_signal * norm_sig
                - self._w_distance * norm_dist)

    def _get_neighbor_signal(self, wx: float, wy: float) -> float:
        """Average mean ice concentration of 8 neighboring grid cells."""
        res = self._resource_map._resolution
        offsets = [(-res, -res), (0, -res), (res, -res),
                   (-res, 0),               (res, 0),
                   (-res, res),  (0, res),  (res, res)]

        total = 0.0
        count = 0
        for dx, dy in offsets:
            nx, ny = wx + dx, wy + dy
            gx, gy = self._resource_map.world_to_grid(nx, ny)
            if self._resource_map.is_in_bounds(gx, gy):
                total += self._resource_map.get_mean(nx, ny)
                count += 1

        return total / count if count > 0 else 0.0

    def get_survey_stats(self) -> dict:
        """Return stats: total_candidates, visited_count, mean_variance.

        Computes statistics over all candidate cells in the PSR zone
        (without any spacing filter applied).
        """
        cx, cy = self._psr_center
        r = self._psr_radius
        res = self._candidate_resolution

        x_min = cx - r
        x_max = cx + r
        y_min = cy - r
        y_max = cy + r

        num_x = int((x_max - x_min) / res) + 1
        num_y = int((y_max - y_min) / res) + 1

        total_candidates = 0
        visited_count = 0
        variance_sum = 0.0

        for ix in range(num_x):
            wx = x_min + ix * res
            for iy in range(num_y):
                wy = y_min + iy * res

                dist_to_center = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist_to_center > r:
                    continue

                gx, gy = self._resource_map.world_to_grid(wx, wy)
                if not self._resource_map.is_in_bounds(gx, gy):
                    continue

                total_candidates += 1
                var = self._resource_map.get_variance(wx, wy)
                variance_sum += var

                count = self._resource_map.get_count(wx, wy)
                if count > 0:
                    visited_count += 1

        mean_variance = variance_sum / total_candidates if total_candidates > 0 else 0.0

        return {
            "total_candidates": total_candidates,
            "visited_count": visited_count,
            "mean_variance": mean_variance,
        }
