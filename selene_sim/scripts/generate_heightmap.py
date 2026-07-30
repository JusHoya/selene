#!/usr/bin/env python3
"""Generate the heightmap PNGs for the SELENE lunar simulation.

Terrain features:
  - Base terrain with gentle undulation (2-5m amplitude, 50-100m wavelength)
  - Large PSR crater centered at (-100, -150), diameter ~120m, depth ~15m, flat bottom
  - 3-4 small secondary craters scattered across the area
  - Slope ridge on the eastern edge (10-25 degree slopes)

Uses seed 42, so the field is deterministic and the constants written to
heightmaps/terrain_datum.json are reproducible.

HOW A PIXEL BECOMES A METRE, AND WHY THIS FILE CARES
gz-sim does NOT map the format maximum to <size> z. It maps THE MAXIMUM PIXEL
VALUE PRESENT IN THE IMAGE to <size> z, and it does not subtract the image
minimum:

    z_render = size_z * pixel_value / max(pixel_value in image)

MEASURED, not inferred (2026-07-30, gz-sim 8.14.0, three synthetic 65x65 8-bit
heightmaps at <size>100 100 30</size>, read with a probe pinned to a prismatic
Z joint so it cannot roll):

    image                       measured   this rule   format-max rule
    uniform 128                  30.0000     30.0000           15.0588
    102 flat, 204 in a corner    15.0000     15.0000           12.0000
    153 flat, min 51, max 255    18.0000     18.0000           18.0000
                                            (a (max-min) rule predicts 15.0000)

Exact to four decimals in all three cases.

WHAT THAT DID TO THIS PROJECT
This generator used to emit `(H / 30.0) * 65535`, i.e. it assumed the second
rule. The field's true maximum is 24.2528 m, not 30 m, so the brightest pixel
came out at 52980/65535 = 0.8084 of full range and gz-sim stretched the image
back out to fill 30 m. Every elevation was inflated by 30/24.2528 = 1.2370 for
the visual, and by 1.2500 for the 8-bit collision map whose decimated maximum
landed on 204/255 = 0.8000. The -18 m datum on terrain_link was compensating for
that inflation, which is why it was ~3 m away from the +15 m base this file adds.
The two images disagreeing (0.8084 vs 0.8000) also put the collision surface up
to 0.24 m ABOVE the visual one, so robots drove on an invisible floor.

THE FIX, AND WHY IT LOOKS LIKE THIS
Each image is normalised by ITS OWN maximum height, so its brightest pixel is
exactly the format maximum, and each heightmap declares a <size> z equal to that
same maximum in metres. Then z_render == H for both images, and

    world z = H - BASE_ELEVATION

with terrain_link's pose carrying -BASE_ELEVATION. The datum is now the number
this file actually adds, not a fudge factor for a normalisation bug.

The two images necessarily carry DIFFERENT <size> z values, because decimating
the field to 129x129 does not preserve its maximum (24.2528 -> 24.0537). Sharing
one <size> would reintroduce the bug: normalising the coarse map against the fine
maximum makes its brightest pixel 253, not 255, and gz-sim would then renormalise
by 253 and put the coarse surface 0.199 m too high.

Nothing here can be verified from the configs, so the numbers are written to
heightmaps/terrain_datum.json and asserted against
models/lunar_terrain/model.sdf by selene_sim/test/test_heightmap_datum.py, which
needs no Gazebo and runs on every push. scripts/check_terrain.sh is the physical
check.
"""

import json
import math
import os

import numpy as np
from PIL import Image


# --------------------------------------------------------------------------
# The datum. This is the single source of truth for the terrain's vertical
# reference: the field is built around BASE_ELEVATION so a 15 m crater can be
# carved without clipping at 0, and terrain_link's pose is -BASE_ELEVATION so
# that world z == (metric height) - BASE_ELEVATION. selene_sim/models/
# lunar_terrain/model.sdf MUST carry -BASE_ELEVATION as its link pose z;
# test_heightmap_datum.py fails if the two ever drift apart.
# --------------------------------------------------------------------------
BASE_ELEVATION = 15.0
WORLD_SIZE = 500.0
VISUAL_SIZE = 513
COLLISION_SIZE = 129
CRATER = dict(cx=-100.0, cy=-150.0, diameter=120.0, depth=15.0, flat_fraction=0.25)
SECONDARY_CRATERS = [
    # (cx, cy, diameter, depth)
    (80.0, 60.0, 35.0, 6.0),
    (-170.0, 100.0, 25.0, 4.0),
    (150.0, -120.0, 30.0, 5.0),
    (-50.0, 180.0, 22.0, 3.5),
]


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

def _make_base_grid(size=VISUAL_SIZE, world_size=WORLD_SIZE):
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
# The field, and the image encoding
# ---------------------------------------------------------------------------

def build_field(size=VISUAL_SIZE, world_size=WORLD_SIZE):
    """Return the metric height field in metres, ROWS ASCENDING IN Y.

    Row 0 is world y = -world_size/2. That is the natural orientation for the
    terrain maths below and the OPPOSITE of the image convention; see
    to_image_rows().

    Split out of generate_heightmap() so tests can obtain the field without
    triggering any file writes: test_heightmap_datum.py asserts the
    world-z identity against this, and it must check the generator rather than
    re-implement it.
    """
    noise = PerlinNoise2D(seed=42)
    height, wx, wy = _make_base_grid(size, world_size)

    # Base elevation offset, so a 15 m crater can be carved without clipping at 0.
    height += BASE_ELEVATION

    height = _add_undulation(height, wx, wy, noise)
    height = _add_crater(height, wx, wy, **CRATER)
    for cx, cy, diam, dep in SECONDARY_CRATERS:
        height = _add_crater(height, wx, wy, cx, cy, diam, dep, flat_fraction=0.2)
    height = _add_ridge(height, wx, wy)

    # A negative height cannot be encoded (pixel values are unsigned, and
    # gz-sim maps pixel 0 to z 0), so clamp the floor. This is currently a
    # no-op — the field minimum is +0.2181 m — and the assertion in
    # generate_heightmap() will say so loudly if a terrain edit ever changes
    # that, because clipping here silently flattens the crater floor.
    return np.clip(height, 0.0, None)


def decimate(field, size):
    """Sample *field* onto a coarser (2^k)+1 lattice, preserving the extent.

    Decimating on this lattice keeps the corner heights and the 500 m extent
    exactly, so the coarse and fine surfaces cannot disagree at the edges.
    """
    step = (field.shape[0] - 1) // (size - 1)
    coarse = field[::step, ::step]
    assert coarse.shape == (size, size), coarse.shape
    return coarse


def to_image_rows(field):
    """Convert an ascending-y field to image row order (row 0 = +Y).

    Row-order conversion at the I/O boundary — do not remove.

    build_field() uses np.meshgrid(coords, coords), so its rows ASCEND with
    world y: row 0 is y = -250 and row 512 is y = +250. Image and heightmap
    convention is the opposite — row 0 is the NORTH (+Y) edge — and Gazebo's
    heightmap loader follows the image convention. Writing the array rows
    straight out therefore mirrored the whole terrain about the equator.

    MEASURED before this was added (2026-07-29, Gazebo Harmonic, falling-probe
    test — see scripts/check_terrain.sh): the PSR crater carved for
    (-100, -150) physically rendered at (-100, +150). A probe dropped at
    (-100, +150) came to rest on the crater floor, while the whole region around
    the configured (-100, -150) had no collision at all and probes fell out of
    the world. Every consumer — the PSR zone in world_params.yaml, the four ice
    deposits, the battery shadow model and the dashboard overlay — assumes
    (-100, -150), so the terrain was mirrored relative to all of them.

    Keep the terrain maths in intuitive ascending-y world coordinates and
    convert once, here, where the array becomes an image.

    scripts/check_terrain.sh's mirror_check probe at (-100, +150) is the
    regression test: it must NOT read as a crater.
    """
    return np.flipud(field)


def encode(field, full_scale):
    """Encode a metric field as heightmap pixels. Returns (pixels, size_z).

    The contract, which the whole datum rests on:

      * the returned array's MAXIMUM pixel is exactly *full_scale*, because
        gz-sim normalises by the image's own maximum. If it were even one level
        short, gz-sim would stretch the image and every elevation would be
        wrong by that ratio (1/255 = 0.4% = 0.094 m for the collision map).
      * size_z is the metric height that maximum represents, so
        z_render = size_z * pixel / full_scale == the metric height.

    size_z is floored to 6 decimals so it can be written into model.sdf as a
    literal. Flooring (never rounding up) keeps size_z <= the true maximum, so
    dividing by it can only push the brightest pixels slightly OVER full_scale,
    where the clip pins them to exactly full_scale — which is what the contract
    needs. Rounding up would leave the maximum one level short and silently
    reintroduce the scaling bug. The cost is bounded by 1e-6 m on the single
    highest cell.
    """
    size_z = math.floor(field.max() * 1e6) / 1e6
    pixels = np.clip(np.round(field / size_z * full_scale), 0, full_scale)
    assert pixels.max() == full_scale, (
        f'brightest pixel is {pixels.max()}, not {full_scale}; gz-sim would '
        f'renormalise and every elevation would be scaled by '
        f'{full_scale / pixels.max():.6f}')
    return pixels, size_z


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_heightmap():
    """Generate the heightmaps and the datum record. Returns the datum dict."""
    print("SELENE Heightmap Generator")
    print("=" * 60)
    print(f"Grid size:      {VISUAL_SIZE} x {VISUAL_SIZE}")
    print(f"World size:     {WORLD_SIZE} x {WORLD_SIZE} m")
    print(f"Base elevation: {BASE_ELEVATION} m  (world z = height - "
          f"{BASE_ELEVATION})")
    print("Random seed:    42")
    print()

    print("  [1/4] Building the height field...")
    field = build_field()
    assert field.min() > 0.0, (
        f'field minimum {field.min():.6f} was clipped at 0; the crater floor is '
        f'being flattened. Raise BASE_ELEVATION.')

    print("  [2/4] Encoding the 513x513 16-bit visual heightmap...")
    vis_px, vis_size_z = encode(to_image_rows(field), 65535)

    # The COLLISION map is coarser, and is decimated from the FLOAT field rather
    # than from the already-quantised visual image — quantising once is strictly
    # better than quantising twice, and it keeps the two encodings independent
    # so each can carry its own honest maximum.
    #
    # gz-sim's heightmap collision is not reliable at 513x513 (~525k triangles).
    # MEASURED with the falling-probe gate (scripts/check_terrain.sh) on Gazebo
    # Harmonic: at 513/16-bit, probes at some coordinates pass straight through
    # the surface, and *which* coordinates changes when unrelated parameters
    # change (bit depth, collision resolution, timestep). Sweeping the collision
    # resolution with the visual held constant:
    #   513 (16-bit) -> 3 fall-throughs
    #   257 ( 8-bit) -> 3
    #   129 ( 8-bit) -> 1     <- best
    #    65 ( 8-bit) -> 1
    # 129x129 gives 3.91 m cells, finer than any robot footprint here and far
    # coarser than the visual, so the crater and the plain still read correctly
    # to the gate while contact generation becomes much more robust.
    #
    # This does NOT provably eliminate the holes. If the gate reports a
    # fall-through again, the next step is a collision MESH generated from the
    # same field, since mesh collision in gz-physics is better tested than
    # heightmap collision.
    print(f"  [3/4] Encoding the {COLLISION_SIZE}x{COLLISION_SIZE} 8-bit "
          f"collision heightmap...")
    coarse = decimate(field, COLLISION_SIZE)
    col_px, col_size_z = encode(to_image_rows(coarse), 255)

    print("  [4/4] Writing images and the datum record...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.dirname(script_dir)
    out_dir = os.path.join(package_dir, "models", "lunar_terrain", "heightmaps")
    os.makedirs(out_dir, exist_ok=True)

    vis_name = f"lunar_surface_{VISUAL_SIZE}.png"
    col_name = f"lunar_collision_{COLLISION_SIZE}.png"
    Image.fromarray(vis_px.astype(np.uint16), mode='I;16').save(
        os.path.join(out_dir, vis_name))
    Image.fromarray(col_px.astype(np.uint8), mode='L').save(
        os.path.join(out_dir, col_name))

    datum = {
        "_comment": [
            "GENERATED by selene_sim/scripts/generate_heightmap.py. Do not edit.",
            "gz-sim maps a heightmap's OWN maximum pixel to <size> z, so each",
            "image carries its own size_z in metres. world z = height - "
            "base_elevation_m.",
            "models/lunar_terrain/model.sdf must match these numbers; "
            "test_heightmap_datum.py enforces it.",
        ],
        "base_elevation_m": BASE_ELEVATION,
        "link_pose_z": -BASE_ELEVATION,
        "world_size_m": WORLD_SIZE,
        "seed": 42,
        "field": {
            "min_m": float(field.min()),
            "max_m": float(field.max()),
            "mean_m": float(field.mean()),
        },
        "visual": {
            "image": vis_name,
            "grid": VISUAL_SIZE,
            "bit_depth": 16,
            "full_scale": 65535,
            "size_z_m": vis_size_z,
        },
        "collision": {
            "image": col_name,
            "grid": COLLISION_SIZE,
            "bit_depth": 8,
            "full_scale": 255,
            "size_z_m": col_size_z,
        },
    }
    datum_path = os.path.join(out_dir, "terrain_datum.json")
    with open(datum_path, "w") as f:
        json.dump(datum, f, indent=2)
        f.write("\n")

    # ------------------------------------------------------------- summary
    cell = WORLD_SIZE / (COLLISION_SIZE - 1)
    print()
    print("Terrain Summary")
    print("-" * 60)
    print(f"  metric height range   {field.min():.6f} .. {field.max():.6f} m "
          f"(mean {field.mean():.6f})")
    print(f"  world z range         {field.min() - BASE_ELEVATION:+.6f} .. "
          f"{field.max() - BASE_ELEVATION:+.6f} m")
    print(f"  visual    {vis_name}  max {int(vis_px.max())}/65535  "
          f"size_z {vis_size_z:.6f} m  "
          f"({vis_size_z / 65535:.8f} m/level)")
    print(f"  collision {col_name}  max {int(col_px.max())}/255    "
          f"size_z {col_size_z:.6f} m  "
          f"({col_size_z / 255:.6f} m/level, {cell:.2f} m cells)")
    print(f"  datum record          {datum_path}")
    print()
    print("  model.sdf MUST carry exactly:")
    print(f"    terrain_link  <pose>0 0 {-BASE_ELEVATION:g} 0 0 0</pose>")
    print(f"    collision     <size>{WORLD_SIZE:g} {WORLD_SIZE:g} "
          f"{col_size_z:.6f}</size>")
    print(f"    visual        <size>{WORLD_SIZE:g} {WORLD_SIZE:g} "
          f"{vis_size_z:.6f}</size>")
    print("  (selene_sim/test/test_heightmap_datum.py fails if it does not.)")
    print()
    print("Features:")
    print(f"  PSR crater:       center=({CRATER['cx']:g}, {CRATER['cy']:g}), "
          f"diameter={CRATER['diameter']:g}m, depth={CRATER['depth']:g}m")
    for i, (cx, cy, diam, dep) in enumerate(SECONDARY_CRATERS):
        print(f"  Secondary #{i + 1}:     center=({cx}, {cy}), "
              f"diameter={diam}m, depth={dep}m")
    print("  Eastern ridge:    x~200m, height~8m, slope 10-25 deg")
    print("  Base undulation:  2-5m amplitude, 50-100m wavelength")
    print()
    print("Done. Re-run scripts/check_terrain.sh to re-measure the surfaces, and")
    print("update selene_sim/config/spawn_positions.yaml from what it reports.")

    return datum


if __name__ == "__main__":
    generate_heightmap()
