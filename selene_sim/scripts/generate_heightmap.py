#!/usr/bin/env python3
"""Generate a 513x513 16-bit grayscale PNG heightmap for the SELENE lunar simulation.

Terrain features:
  - Base terrain with gentle undulation (2-5m amplitude, 50-100m wavelength)
  - Large PSR crater centered at (-100, -150), diameter ~120m, depth ~15m, flat bottom
  - 3-4 small secondary craters scattered across the area
  - Slope ridge on the eastern edge (10-25 degree slopes)

The height range 0-30m is mapped to 16-bit PNG values 0-65535.
Uses seed 42 for reproducibility.
"""

import os

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Simple Perlin noise implementation (no external packages)
# ---------------------------------------------------------------------------

def _fade(t):
    """Perlin fade function: 6t^5 - 15t^4 + 10t^3."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(a, b, t):
    """Linear interpolation."""
    return a + t * (b - a)


def _gradient(h, x, y):
    """Compute gradient dot product for 2D Perlin noise."""
    vectors = np.array([
        [1, 1], [-1, 1], [1, -1], [-1, -1],
        [1, 0], [-1, 0], [0, 1], [0, -1],
    ])
    g = vectors[h % 8]
    return g[..., 0] * x + g[..., 1] * y


class PerlinNoise2D:
    """Simple 2D Perlin noise generator."""

    def __init__(self, seed=42):
        rng = np.random.default_rng(seed)
        self.perm = np.arange(256, dtype=np.int32)
        rng.shuffle(self.perm)
        self.perm = np.tile(self.perm, 2)

    def __call__(self, x, y):
        """Evaluate noise at arrays *x*, *y* (same shape)."""
        xi = np.floor(x).astype(np.int32) & 255
        yi = np.floor(y).astype(np.int32) & 255
        xf = x - np.floor(x)
        yf = y - np.floor(y)

        u = _fade(xf)
        v = _fade(yf)

        aa = self.perm[self.perm[xi] + yi]
        ab = self.perm[self.perm[xi] + yi + 1]
        ba = self.perm[self.perm[xi + 1] + yi]
        bb = self.perm[self.perm[xi + 1] + yi + 1]

        x1 = _lerp(_gradient(aa, xf, yf), _gradient(ba, xf - 1, yf), u)
        x2 = _lerp(_gradient(ab, xf, yf - 1), _gradient(bb, xf - 1, yf - 1), u)

        return _lerp(x1, x2, v)

    def octave(self, x, y, octaves=4, persistence=0.5):
        """Fractal Brownian Motion — sum of multiple octaves."""
        total = np.zeros_like(x, dtype=np.float64)
        amplitude = 1.0
        frequency = 1.0
        max_val = 0.0
        for _ in range(octaves):
            total += self.__call__(x * frequency, y * frequency) * amplitude
            max_val += amplitude
            amplitude *= persistence
            frequency *= 2.0
        return total / max_val


# ---------------------------------------------------------------------------
# Terrain generation helpers
# ---------------------------------------------------------------------------

def _make_base_grid(size=513, world_size=500.0):
    """Return (height, wx, wy) arrays. wx/wy are world-space coords in meters."""
    coords = np.linspace(-world_size / 2, world_size / 2, size)
    wx, wy = np.meshgrid(coords, coords)
    height = np.zeros((size, size), dtype=np.float64)
    return height, wx, wy


def _add_undulation(height, wx, wy, noise):
    """Gentle terrain undulation, 2-5m amplitude, 50-100m wavelength."""
    # Large-scale undulation
    h1 = noise.octave(wx / 80.0, wy / 80.0, octaves=3, persistence=0.5)
    height += h1 * 3.5  # ~2-5m amplitude

    # Finer-scale bumps
    h2 = noise.octave(wx / 25.0, wy / 25.0, octaves=2, persistence=0.4)
    height += h2 * 0.8
    return height


def _add_crater(height, wx, wy, cx, cy, diameter, depth, flat_fraction=0.3):
    """Carve a crater with raised rim and flat bottom.

    Parameters
    ----------
    cx, cy : float  — center in world coords (meters)
    diameter : float — outer diameter
    depth : float — depth below surrounding terrain at center
    flat_fraction : float — fraction of radius that is flat bottom
    """
    radius = diameter / 2.0
    dist = np.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)

    # Rim raise (Gaussian bump just outside the edge)
    rim_width = radius * 0.15
    rim_height = depth * 0.2
    rim_mask = np.exp(-0.5 * ((dist - radius) / rim_width) ** 2)
    height += rim_height * rim_mask

    # Interior bowl
    inside = dist < radius
    normalized = dist[inside] / radius  # 0 at center, 1 at rim

    flat_r = flat_fraction
    bowl = np.zeros_like(normalized)

    # Flat bottom region
    flat_mask = normalized <= flat_r
    bowl[flat_mask] = -depth

    # Parabolic transition from flat bottom to rim
    trans_mask = ~flat_mask
    t = (normalized[trans_mask] - flat_r) / (1.0 - flat_r)  # 0..1
    bowl[trans_mask] = -depth * (1.0 - t ** 2)

    height[inside] += bowl
    return height


def _add_ridge(height, wx, wy):
    """Add a slope ridge on the eastern edge (10-25 degree slopes)."""
    # Ridge runs roughly N-S at x ~ 180-220m
    ridge_center_x = 200.0
    ridge_width = 40.0

    # Distance from ridge axis
    dx = wx - ridge_center_x
    mask = dx > -ridge_width
    ridge = np.zeros_like(height)

    # East of ridge center: rises sharply
    east = dx >= 0
    ridge[east & mask] = 8.0 * np.exp(-0.5 * (dx[east & mask] / 15.0) ** 2)

    # Approach ramp from west
    west = (dx < 0) & mask
    t = (dx[west] + ridge_width) / ridge_width  # 0..1
    ridge[west] = 8.0 * np.exp(-0.5 * (0.0 / 15.0) ** 2) * (t ** 1.5)

    height += ridge
    return height


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_heightmap():
    """Generate the heightmap and save it as a 16-bit PNG."""
    size = 513
    world_size = 500.0

    print("SELENE Heightmap Generator")
    print("=" * 50)
    print(f"Grid size:   {size} x {size}")
    print(f"World size:  {world_size} x {world_size} m")
    print("Random seed: 42")
    print()

    noise = PerlinNoise2D(seed=42)
    height, wx, wy = _make_base_grid(size, world_size)

    # Base elevation offset so terrain sits around 15m (mid-range)
    height += 15.0

    # 1. Gentle undulation
    print("  [1/5] Adding base terrain undulation...")
    height = _add_undulation(height, wx, wy, noise)

    # 2. Primary PSR crater: center (-100, -150), diameter 120m, depth 15m
    print("  [2/5] Carving PSR crater (120m diameter, 15m depth)...")
    height = _add_crater(height, wx, wy,
                         cx=-100.0, cy=-150.0,
                         diameter=120.0, depth=15.0,
                         flat_fraction=0.25)

    # 3. Secondary craters
    print("  [3/5] Carving secondary craters...")
    secondaries = [
        # (cx, cy, diameter, depth)
        (80.0, 60.0, 35.0, 6.0),
        (-170.0, 100.0, 25.0, 4.0),
        (150.0, -120.0, 30.0, 5.0),
        (-50.0, 180.0, 22.0, 3.5),
    ]
    for cx, cy, diam, dep in secondaries:
        height = _add_crater(height, wx, wy, cx, cy, diam, dep,
                             flat_fraction=0.2)

    # 4. Eastern ridge
    print("  [4/5] Adding eastern slope ridge...")
    height = _add_ridge(height, wx, wy)

    # 5. Clamp and map to 16-bit
    print("  [5/5] Mapping to 16-bit PNG...")
    height = np.clip(height, 0.0, 30.0)

    # Map [0, 30] -> [0, 65535]
    img_data = ((height / 30.0) * 65535.0).astype(np.uint16)

    # Save
    script_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.dirname(script_dir)
    output_dir = os.path.join(package_dir, "models", "lunar_terrain", "heightmaps")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "lunar_surface_513.png")

    img = Image.fromarray(img_data, mode='I;16')
    img.save(output_path)

    # Summary
    print()
    print("Terrain Summary")
    print("-" * 50)
    print(f"  Height range:  {height.min():.2f} - {height.max():.2f} m")
    print(f"  Mean height:   {height.mean():.2f} m")
    print(f"  Output file:   {output_path}")
    print()
    print("Features:")
    print("  PSR crater:       center=(-100, -150), diameter=120m, depth=15m")
    for i, (cx, cy, diam, dep) in enumerate(secondaries):
        print(f"  Secondary #{i + 1}:     center=({cx}, {cy}), "
              f"diameter={diam}m, depth={dep}m")
    print("  Eastern ridge:    x~200m, height~8m, slope 10-25 deg")
    print("  Base undulation:  2-5m amplitude, 50-100m wavelength")
    print()
    print("Done.")

    return output_path


if __name__ == "__main__":
    generate_heightmap()
