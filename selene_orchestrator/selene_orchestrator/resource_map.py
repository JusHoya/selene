"""Probabilistic resource map with Bayesian sensor fusion."""

import numpy as np


class ResourceMap:
    """500x500 grid tracking ice concentration estimates with uncertainty.

    Each cell stores: mean (posterior estimate), variance (uncertainty),
    and observation count. Uses Bayesian Gaussian-Gaussian conjugate
    updates when new sensor readings arrive.
    """

    def __init__(self, width: int = 500, height: int = 500,
                 resolution: float = 1.0,
                 origin_x: float = -250.0, origin_y: float = -250.0,
                 prior_mean: float = 0.0, prior_variance: float = 100.0,
                 footprint_radius: float = 5.0, footprint_sigma: float = 3.0):
        self._width = width
        self._height = height
        self._resolution = resolution
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._footprint_radius = footprint_radius
        self._footprint_sigma = footprint_sigma

        # Initialize grids
        self._mean = np.full((height, width), prior_mean, dtype=np.float64)
        self._variance = np.full((height, width), prior_variance, dtype=np.float64)
        self._count = np.zeros((height, width), dtype=np.int32)

    def world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid indices."""
        gx = int((x - self._origin_x) / self._resolution)
        gy = int((y - self._origin_y) / self._resolution)
        return gx, gy

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        """Convert grid indices to world coordinates (cell center)."""
        wx = gx * self._resolution + self._origin_x + self._resolution / 2
        wy = gy * self._resolution + self._origin_y + self._resolution / 2
        return wx, wy

    def is_in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self._width and 0 <= gy < self._height

    def update(self, x: float, y: float, reading: float,
               sensor_uncertainty: float) -> None:
        """Apply Bayesian update at (x,y) and neighbors within footprint.

        For each cell within footprint_radius:
        - Compute distance-decayed observation weight
        - Apply Gaussian conjugate update:
          posterior_precision = prior_precision + observation_precision
          posterior_mean = (prior_precision * prior_mean + obs_precision * reading) / posterior_precision

        Args:
            x, y: World coordinates of measurement
            reading: Ice concentration value (wt%)
            sensor_uncertainty: Standard deviation of sensor noise
        """
        center_gx, center_gy = self.world_to_grid(x, y)
        radius_cells = int(self._footprint_radius / self._resolution) + 1
        sensor_var = max(sensor_uncertainty ** 2, 1e-6)

        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                gx = center_gx + dx
                gy = center_gy + dy
                if not self.is_in_bounds(gx, gy):
                    continue

                # Distance from measurement center
                wx, wy = self.grid_to_world(gx, gy)
                dist = np.sqrt((wx - x) ** 2 + (wy - y) ** 2)

                if dist > self._footprint_radius:
                    continue

                # Distance-decayed weight (Gaussian falloff)
                weight = np.exp(-(dist ** 2) / (2 * self._footprint_sigma ** 2))

                # Bayesian Gaussian conjugate update
                prior_precision = 1.0 / max(self._variance[gy, gx], 1e-10)
                obs_precision = weight / sensor_var

                posterior_precision = prior_precision + obs_precision
                posterior_variance = 1.0 / posterior_precision
                posterior_mean = posterior_variance * (
                    prior_precision * self._mean[gy, gx] + obs_precision * reading
                )

                self._mean[gy, gx] = posterior_mean
                self._variance[gy, gx] = posterior_variance
                self._count[gy, gx] += 1

    def get_mean(self, x: float, y: float) -> float:
        gx, gy = self.world_to_grid(x, y)
        if not self.is_in_bounds(gx, gy):
            return 0.0
        return float(self._mean[gy, gx])

    def get_variance(self, x: float, y: float) -> float:
        gx, gy = self.world_to_grid(x, y)
        if not self.is_in_bounds(gx, gy):
            return 0.0
        return float(self._variance[gy, gx])

    def get_count(self, x: float, y: float) -> int:
        gx, gy = self.world_to_grid(x, y)
        if not self.is_in_bounds(gx, gy):
            return 0
        return int(self._count[gy, gx])

    def get_total_readings(self) -> int:
        return int(np.sum(self._count))

    def get_mean_grid(self) -> np.ndarray:
        return self._mean.copy()

    def get_variance_grid(self) -> np.ndarray:
        return self._variance.copy()

    def get_best_extraction_sites(self, count: int = 5,
                                  min_concentration: float = 2.0
                                  ) -> list[tuple[float, float, float]]:
        """Return the top-K cells by mean ice concentration.

        Returns list of (world_x, world_y, mean_concentration) tuples,
        sorted by concentration descending.
        """
        mean_grid = self.get_mean_grid()
        candidates = []
        for gy in range(self._height):
            for gx in range(self._width):
                mean_val = float(mean_grid[gy, gx])
                if mean_val >= min_concentration:
                    wx, wy = self.grid_to_world(gx, gy)
                    candidates.append((wx, wy, mean_val))
        candidates.sort(key=lambda c: c[2], reverse=True)
        return candidates[:count]
