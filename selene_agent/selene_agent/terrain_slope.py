"""Terrain elevation and slope, decoded from the committed heightmap.

WHY THIS EXISTS
---------------
``selene_agent/config/nav_params.yaml:21`` has declared
``navigation.max_traversable_slope_deg: 15.0`` since Phase 2 and NOTHING IN
PRODUCTION HAS EVER READ IT (deviation D-28,
``docs/phase5_deviation_register.md``). The reason nothing read it is that
nothing could: no module in this repository knew the ground's shape. The
planner's ``slope_penalty_weight`` multiplies an ``OccupancyGrid`` cost that no
terrain ever writes to, so the planner's slope term is identically zero. This
module is the missing half -- it turns the shipped heightmap into an elevation
and slope field that a planner, a guard, or a startup audit can read.

It deliberately does NOT enforce anything and does not know what the limit is.
Enforcement, and the constant to enforce, belong to the caller.

WHAT IS AND IS NOT MEASURED
---------------------------
Everything here is ARITHMETIC on the committed PNG. It is not a measurement of
what a vehicle can climb. The declared 15.0 is contradicted by observation --
on 2026-07-31 a ten-robot fleet delivered 94.85 kg to a depot on the floor of a
crater whose gentlest measured rim exit is 34.09 deg -- and the campaign that
measures the real capability is ``scripts/measure_slope_capability.sh``, which
uses this module to choose where to drive.

TWO SAMPLING METHODS, AND THEY ARE NOT INTERCHANGEABLE
------------------------------------------------------
This is the trap this API is shaped to prevent. The same point reads a
different slope depending on how it is sampled, by up to ~0.6 deg on the crater
wall, so EVERY entry point names its method and every number this module
produces can be traced to one of them:

``SAMPLING_NATIVE`` -- :meth:`TerrainSlopeField.slope_deg_native`
    Bilinear interpolation of a slope grid precomputed on the heightmap's own
    513-sample lattice. The finest thing the committed data supports.

``SAMPLING_RESAMPLED`` -- :meth:`SlopeLattice.slope_deg_at`
    The native slope grid bilinearly resampled onto a coarser planning lattice
    (500 x 500 at 1.0 m, matching ``OccupancyGrid``), then read at the CELL
    CENTRE containing the query point. A planner can only act per cell, so this
    is what a planner will really see.

MEASURED difference between them (this module, 2026-07-31, seed-42 terrain):

    point            native    resampled   (resampled cell centre)
    (-60, -120)      36.80        37.36     (-59.5, -119.5)
    (-75, -100)      37.26        37.08     (-74.5,  -99.5)
    (-100, -150)      1.80         1.76     (-99.5, -149.5)

The resampled reading is not "wrong" and is not merely smoothed -- it is the
slope at a DIFFERENT PLACE, up to half a cell diagonal (0.707 m) away. On a
37 deg wall that is worth half a degree. ``test_terrain_slope_field.py`` pins
the difference so it stays a documented property.

THE BASELINE
------------
Slope is the gradient over a ~3 m baseline, because that is the scale a ~1 m
wheelbase vehicle integrates over and because
``selene_sim/test/test_mission_traversability.py:75`` uses ``BASELINE_M = 3.0``
and a second opinion that disagreed with the existing gate would be worse than
none. The 513 lattice's spacing is 500/512 = 0.9766 m, so the requested 3.0 m
is realised as a 3-cell central difference = 2.9297 m; see
:attr:`TerrainSlopeField.effective_baseline_m`. Against the gate's exact-3.0 m
radial profile, over the crater exit azimuths the gate samples:

    24 azimuths   gate 34.26 deg   this module 34.28 deg
    72 azimuths   gate 34.09 deg   this module 34.03 deg

so 0.5 deg is the justified agreement tolerance between the two.

DEPENDENCIES
------------
numpy, and the standard library. Pillow is used when importable because it
decodes the 513 image in ~21 ms against ~430 ms for the bundled decoder, but it
is NOT required: :func:`decode_png_greyscale` is a complete PNG reader for the
greyscale images this project ships. ``selene_agent/package.xml`` does not
declare Pillow, and this module does not make it start.
"""

from __future__ import annotations

import json
import math
import os
import struct
import zlib
from collections import deque
from typing import Optional, Sequence

import numpy as np


#: Sampling method identifiers. Every slope number this module produces is
#: tagged with one of these, and callers should carry the tag with the number.
SAMPLING_NATIVE = 'native'
SAMPLING_RESAMPLED = 'resampled'

#: Requested gradient baseline, metres. Matches ``BASELINE_M`` in
#: ``selene_sim/test/test_mission_traversability.py``.
DEFAULT_BASELINE_M = 3.0

#: Label used by :class:`ComponentLabels` for cells that are not passable.
IMPASSABLE_LABEL = 0

#: Environment variable naming the directory that holds the heightmap PNGs and
#: ``terrain_datum.json``. Set it and no search is performed.
HEIGHTMAP_DIR_ENV = 'SELENE_TERRAIN_HEIGHTMAPS'

_DATUM_NAME = 'terrain_datum.json'
_MODEL_RELPATH = os.path.join('models', 'lunar_terrain', 'heightmaps')


class TerrainDataUnavailable(RuntimeError):
    """The committed heightmap could not be located or decoded.

    Raised loudly and never swallowed. A silent fallback to flat ground would
    reproduce exactly the defect this module exists to remove: a system that
    believes the terrain is traversable because it cannot see it.
    """


# ---------------------------------------------------------------------------
# PNG decoding
# ---------------------------------------------------------------------------

def decode_png_greyscale(path: str) -> np.ndarray:
    """Decode a non-interlaced greyscale PNG to a ``uint16`` array.

    Standard library only. Handles bit depths 8 and 16 and all five PNG filter
    types, which is everything ``selene_sim/scripts/generate_heightmap.py``
    emits through Pillow (measured: the shipped images use filter 1 on their
    first scanline and filter 4 on every other).

    Rows come back in IMAGE order -- row 0 is the +Y edge -- exactly as Pillow
    would return them. ``test_terrain_slope_field.py`` asserts equality with
    Pillow on both shipped images, so this path is exercised on every push
    rather than being a fallback nobody ever runs.
    """
    with open(path, 'rb') as handle:
        raw = handle.read()
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise TerrainDataUnavailable(f'{path} is not a PNG')

    header = None
    idat = []
    offset = 8
    while offset + 8 <= len(raw):
        (length,) = struct.unpack('>I', raw[offset:offset + 4])
        kind = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:offset + 8 + length]
        if kind == b'IHDR':
            header = payload
        elif kind == b'IDAT':
            idat.append(payload)
        elif kind == b'IEND':
            break
        offset += 12 + length

    if header is None or not idat:
        raise TerrainDataUnavailable(f'{path} has no IHDR/IDAT chunk')
    width, height, depth, colour, _comp, _filt, interlace = struct.unpack(
        '>IIBBBBB', header)
    if colour != 0 or interlace != 0 or depth not in (8, 16):
        raise TerrainDataUnavailable(
            f'{path}: only non-interlaced greyscale 8/16-bit PNGs are '
            f'supported (colour type {colour}, depth {depth}, '
            f'interlace {interlace})')

    data = zlib.decompress(b''.join(idat))
    bpp = depth // 8
    stride = width * bpp
    expected = height * (stride + 1)
    if len(data) != expected:
        raise TerrainDataUnavailable(
            f'{path}: decompressed to {len(data)} bytes, expected {expected}')

    scanlines = np.frombuffer(data, dtype=np.uint8).reshape(height, stride + 1)
    rows = np.empty((height, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    for row in range(height):
        kind = int(scanlines[row, 0])
        cur = scanlines[row, 1:].copy()
        if kind == 0:
            pass
        elif kind == 2:
            cur += prev                     # uint8 wraparound is the PNG rule
        elif kind in (1, 3, 4):
            _unfilter_serial(cur, prev, bpp, kind)
        else:
            raise TerrainDataUnavailable(
                f'{path}: unknown PNG filter type {kind} on row {row}')
        rows[row] = cur
        prev = cur

    if bpp == 2:
        return ((rows[:, 0::2].astype(np.uint16) << 8)
                | rows[:, 1::2].astype(np.uint16))
    return rows.astype(np.uint16)


def _unfilter_serial(cur, prev, bpp, kind):
    """Undo PNG filter 1/3/4 in place. Serial by construction: each byte
    depends on the reconstructed byte *bpp* to its left."""
    buf = cur                                # uint8 view, modified in place
    for i in range(len(buf)):
        left = int(buf[i - bpp]) if i >= bpp else 0
        up = int(prev[i])
        upleft = int(prev[i - bpp]) if i >= bpp else 0
        if kind == 1:
            add = left
        elif kind == 3:
            add = (left + up) >> 1
        else:
            estimate = left + up - upleft
            da, db, dc = (abs(estimate - left), abs(estimate - up),
                          abs(estimate - upleft))
            add = left if (da <= db and da <= dc) else (up if db <= dc else upleft)
        buf[i] = (int(buf[i]) + add) & 0xFF


def _read_png(path: str) -> np.ndarray:
    """Decode via Pillow when it is importable, else via the bundled decoder."""
    try:
        from PIL import Image
    except ImportError:
        return decode_png_greyscale(path)
    with Image.open(path) as img:
        return np.asarray(img).astype(np.uint16)


# ---------------------------------------------------------------------------
# Locating the committed data
# ---------------------------------------------------------------------------

def find_heightmap_dir(explicit: Optional[str] = None) -> str:
    """Return the directory holding the heightmap PNGs and the datum record.

    Resolution order, most explicit first. Every candidate tried is named in
    the exception when none exists, because "terrain not found" with no path in
    it is the kind of error that gets worked around instead of fixed.

      1. *explicit*, if given.
      2. ``$SELENE_TERRAIN_HEIGHTMAPS``.
      3. ``share/selene_sim/models/lunar_terrain/heightmaps`` from the ament
         index, when ``ament_index_python`` is importable. Both PNGs and the
         datum ARE installed there -- ``selene_sim/setup.py`` walks ``models/``
         recursively -- so this is the runtime path on a built workspace.
      4. A source checkout found by walking up from this file.

    THE FIRST TWO DO NOT FALL THROUGH. A caller that named a directory, or an
    operator who exported one, has asserted which terrain is under test; if it
    is not there the answer is an error, never a different terrain found by
    searching. A campaign that silently measured another checkout's world and
    reported it under this one's git commit would be worse than one that did
    not run.
    """
    tried = []

    def candidate(path):
        tried.append(path)
        return path if path and os.path.isfile(
            os.path.join(path, _DATUM_NAME)) else None

    if explicit:
        found = candidate(explicit)
        if found is None:
            raise TerrainDataUnavailable(
                f'{explicit} was named explicitly but holds no {_DATUM_NAME}')
        return found
    env = os.environ.get(HEIGHTMAP_DIR_ENV)
    if env:
        found = candidate(env)
        if found is None:
            raise TerrainDataUnavailable(
                f'${HEIGHTMAP_DIR_ENV} is set to {env}, which holds no '
                f'{_DATUM_NAME}')
        return found
    found = None
    if found is None:
        try:
            from ament_index_python.packages import get_package_share_directory
            share = get_package_share_directory('selene_sim')
        except Exception:                        # noqa: BLE001 - optional dep
            share = None
        if share:
            found = candidate(os.path.join(share, _MODEL_RELPATH))
    if found is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for _ in range(6):
            here = os.path.dirname(here)
            found = candidate(os.path.join(here, 'selene_sim', _MODEL_RELPATH))
            if found:
                break
    if found is None:
        raise TerrainDataUnavailable(
            'could not find the committed heightmap. Looked for '
            + _DATUM_NAME + ' in:\n  ' + '\n  '.join(tried or ['(nowhere)'])
            + f'\nSet ${HEIGHTMAP_DIR_ENV} to the directory that holds it.')
    return found


# ---------------------------------------------------------------------------
# The native field
# ---------------------------------------------------------------------------

class TerrainSlopeField:
    """Elevation and slope on the heightmap's OWN lattice (``SAMPLING_NATIVE``).

    Construct with :meth:`load`. The array is the decoded PNG in ASCENDING-Y
    row order -- row 0 is world y = -250 -- which is the orientation
    ``generate_heightmap.build_field()`` works in and the OPPOSITE of the image
    convention; the flip happens once, here, at the I/O boundary.

    Elevations are WORLD z, i.e. the decoded metric height minus the datum's
    ``base_elevation_m``, so they are directly comparable with a robot's pose.
    """

    def __init__(self, elevation_m, world_size_m, base_elevation_m,
                 baseline_m=DEFAULT_BASELINE_M, source=None):
        self._z = np.asarray(elevation_m, dtype=np.float64)
        if self._z.ndim != 2 or self._z.shape[0] != self._z.shape[1]:
            raise TerrainDataUnavailable(
                f'elevation field must be square, got {self._z.shape}')
        self._n = int(self._z.shape[0])
        self._world_size = float(world_size_m)
        self._base_elevation = float(base_elevation_m)
        self._spacing = self._world_size / (self._n - 1)
        self._requested_baseline = float(baseline_m)
        self._source = dict(source or {})

        # Cells per half-difference. round(), not ceil(): the point is to land
        # as close to the requested baseline as the lattice allows, and the
        # realised value is published rather than assumed.
        self._w = max(1, int(round(self._requested_baseline / self._spacing)))
        self._dzdx, self._dzdy = _gradient_components(self._z, self._w,
                                                      self._spacing)
        self._slope = np.degrees(np.arctan(np.hypot(self._dzdx, self._dzdy)))

    # -- construction --------------------------------------------------------

    @classmethod
    def load(cls, heightmap_dir=None, layer='visual',
             baseline_m=DEFAULT_BASELINE_M):
        """Decode a committed heightmap into a field.

        *layer* selects which of the two shipped images to read:

        ``'visual'``
            the 513-sample 16-bit image. THE DEFAULT, and the conservative
            choice for a traversability question: it is the terrain's true
            relief, and the collision map gz-sim actually contacts is a
            decimation of it and can only be smoother. Reproduces
            ``build_field()`` to max|err| 1.85e-4 m, rms 1.07e-4 m.
        ``'collision'``
            the 129-sample 8-bit image, i.e. the surface a robot's wheels
            really touch, quantised at 0.094 m and reproducing its own
            decimation to max|err| 4.72e-2 m. Read this when the question is
            "what will the contact solver do", not "how steep is the ground".

        The two are different surfaces and the choice is never implicit.
        """
        directory = find_heightmap_dir(heightmap_dir)
        datum_path = os.path.join(directory, _DATUM_NAME)
        with open(datum_path) as handle:
            datum = json.load(handle)
        if layer not in ('visual', 'collision'):
            raise ValueError(f"layer must be 'visual' or 'collision', got {layer!r}")
        spec = datum[layer]

        image_path = os.path.join(directory, spec['image'])
        pixels = _read_png(image_path).astype(np.float64)
        if pixels.shape != (spec['grid'], spec['grid']):
            raise TerrainDataUnavailable(
                f"{image_path} is {pixels.shape}, datum says "
                f"{spec['grid']}x{spec['grid']}")

        # gz-sim normalises a heightmap by the image's OWN maximum pixel, and
        # the generator guarantees that maximum IS full scale; dividing by
        # full_scale rather than by pixels.max() therefore reproduces gz-sim
        # while ALSO going wrong loudly, instead of silently rescaling, if a
        # future image ever stops peaking at full scale.
        metric = spec['size_z_m'] * pixels / float(spec['full_scale'])
        world_z = np.flipud(metric) - float(datum['base_elevation_m'])

        return cls(world_z,
                   world_size_m=datum['world_size_m'],
                   base_elevation_m=datum['base_elevation_m'],
                   baseline_m=baseline_m,
                   source={'directory': directory,
                           'datum': datum_path,
                           'layer': layer,
                           'image': image_path,
                           'grid': int(spec['grid']),
                           'bit_depth': int(spec['bit_depth']),
                           'size_z_m': float(spec['size_z_m']),
                           'full_scale': int(spec['full_scale']),
                           'base_elevation_m': float(datum['base_elevation_m']),
                           'seed': datum.get('seed')})

    # -- geometry ------------------------------------------------------------

    @property
    def grid_size(self) -> int:
        """Samples per side of the native lattice."""
        return self._n

    @property
    def world_size_m(self) -> float:
        return self._world_size

    @property
    def spacing_m(self) -> float:
        """Metres between adjacent native samples."""
        return self._spacing

    @property
    def requested_baseline_m(self) -> float:
        return self._requested_baseline

    @property
    def effective_baseline_m(self) -> float:
        """The baseline actually used: ``round(requested/spacing)`` cells.

        3.0 m requested on the 513 lattice becomes 2.9297 m. Published rather
        than hidden, because a gate that compares against an exact-3.0 m
        reference needs to know the difference is 2.3%, not zero.
        """
        return self._w * self._spacing

    @property
    def source(self) -> dict:
        """Provenance of the decoded data: paths, layer, datum constants."""
        return dict(self._source)

    def contains(self, x: float, y: float) -> bool:
        """True when (*x*, *y*) is inside the terrain footprint."""
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        half = self._world_size / 2.0
        return -half <= x <= half and -half <= y <= half

    # -- native sampling -----------------------------------------------------

    def elevation_native_m(self, x: float, y: float) -> float:
        """World z at (*x*, *y*), bilinear on the native lattice."""
        return _bilinear(self._z, x, y, self._world_size)

    def slope_deg_native(self, x: float, y: float) -> float:
        """Slope in degrees at (*x*, *y*) -- ``SAMPLING_NATIVE``.

        Bilinear interpolation of the slope grid precomputed over
        :attr:`effective_baseline_m`. This is NOT the same as differencing
        elevations at x +/- baseline/2 about the query point: that reads
        36.86 deg at (-60, -120) where this reads 36.80, because it re-centres
        the stencil on the query point instead of interpolating between
        lattice-centred stencils. This one is the pinned method, because it is
        the one whose figures the register and the campaign quote.
        """
        return _bilinear(self._slope, x, y, self._world_size)

    def gradient_native(self, x: float, y: float) -> tuple:
        """``(dz/dx, dz/dy)`` at (*x*, *y*) -- ``SAMPLING_NATIVE``."""
        return (_bilinear(self._dzdx, x, y, self._world_size),
                _bilinear(self._dzdy, x, y, self._world_size))

    def uphill_azimuth_rad_native(self, x: float, y: float) -> float:
        """Heading of steepest ASCENT at (*x*, *y*), radians, world frame.

        Downhill is this plus pi. On ground flat enough that the gradient is
        numerically zero the direction is meaningless and 0.0 is returned;
        callers driving a slope experiment should check
        :meth:`slope_deg_native` first rather than trusting this.
        """
        dzdx, dzdy = self.gradient_native(x, y)
        if math.hypot(dzdx, dzdy) < 1e-12:
            return 0.0
        return math.atan2(dzdy, dzdx)

    @property
    def slope_grid_native(self) -> np.ndarray:
        """Read-only native slope grid in degrees, rows ascending in +Y."""
        view = self._slope.view()
        view.flags.writeable = False
        return view

    @property
    def elevation_grid_m(self) -> np.ndarray:
        """Read-only native world-z grid, rows ascending in +Y."""
        view = self._z.view()
        view.flags.writeable = False
        return view

    def profile_along(self, x: float, y: float, azimuth_rad: float,
                      length_m: float, step_m: float = 0.5) -> dict:
        """Sample a straight corridor -- ``SAMPLING_NATIVE`` throughout.

        Returns arrays ``s`` (metres from the start), ``x``, ``y``,
        ``elevation_m`` and ``slope_deg``. Used by
        ``scripts/measure_slope_capability.sh`` to check that a candidate site's
        grade is SUSTAINED over the length of a drive, rather than being a
        one-cell feature that a 4.8 m run would leave in the first second.
        """
        if step_m <= 0.0:
            raise ValueError('step_m must be positive')
        count = max(1, int(round(length_m / step_m)))
        s = np.linspace(0.0, length_m, count + 1)
        xs = x + s * math.cos(azimuth_rad)
        ys = y + s * math.sin(azimuth_rad)
        return {
            's': s,
            'x': xs,
            'y': ys,
            'elevation_m': np.array([self.elevation_native_m(a, b)
                                     for a, b in zip(xs, ys)]),
            'slope_deg': np.array([self.slope_deg_native(a, b)
                                   for a, b in zip(xs, ys)]),
            'sampling': SAMPLING_NATIVE,
        }

    # -- resampling ----------------------------------------------------------

    def resample(self, width: int, height: int, resolution: float,
                 origin_x: float, origin_y: float) -> 'SlopeLattice':
        """Bilinearly resample onto a planning lattice -- ``SAMPLING_RESAMPLED``.

        Cell (gx, gy) takes the native slope and elevation at its CENTRE,
        ``(origin + (g + 0.5) * resolution)``, which is the convention
        ``OccupancyGrid.grid_to_world`` uses. Cost on the shipped geometry
        (500 x 500 at 1.0 m): ~12 ms and 977 KiB of float32 per array.
        """
        cxs = origin_x + (np.arange(width) + 0.5) * resolution
        cys = origin_y + (np.arange(height) + 0.5) * resolution
        slope = _bilinear_lattice(self._slope, cxs, cys, self._world_size)
        elevation = _bilinear_lattice(self._z, cxs, cys, self._world_size)
        return SlopeLattice(slope, elevation, width, height, resolution,
                            origin_x, origin_y, field=self)

    def resample_to_grid(self, occupancy_grid) -> 'SlopeLattice':
        """Resample onto an existing ``OccupancyGrid``'s exact geometry.

        Duck-typed on ``width`` / ``height`` / ``resolution`` / ``origin_x`` /
        ``origin_y`` so this module keeps no import of the navigation stack and
        stays usable by anything with the same five numbers.
        """
        return self.resample(int(occupancy_grid.width),
                             int(occupancy_grid.height),
                             float(occupancy_grid.resolution),
                             float(occupancy_grid.origin_x),
                             float(occupancy_grid.origin_y))


# ---------------------------------------------------------------------------
# The resampled lattice
# ---------------------------------------------------------------------------

class SlopeLattice:
    """A slope field on a planning lattice -- every read is ``SAMPLING_RESAMPLED``.

    This is what a planner sees: it can only act per cell, so a world query
    returns the value of the cell that CONTAINS the point, not an interpolation
    at the point. The consequence is that a reading here can differ from
    :meth:`TerrainSlopeField.slope_deg_native` at the same coordinates by the
    relief across half a cell diagonal -- measured at up to 0.6 deg on the
    crater wall, which is why the two methods are named separately everywhere.
    """

    def __init__(self, slope_deg, elevation_m, width, height, resolution,
                 origin_x, origin_y, field=None):
        self._slope = np.asarray(slope_deg, dtype=np.float32)
        self._elevation = np.asarray(elevation_m, dtype=np.float32)
        self._width = int(width)
        self._height = int(height)
        self._resolution = float(resolution)
        self._origin_x = float(origin_x)
        self._origin_y = float(origin_y)
        self._field = field

    # -- geometry, matching OccupancyGrid ------------------------------------

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

    @property
    def sampling(self) -> str:
        return SAMPLING_RESAMPLED

    def world_to_grid(self, wx: float, wy: float) -> tuple:
        """Cell indices containing a world point.

        Uses ``floor``, so it agrees with ``OccupancyGrid.world_to_grid``
        everywhere inside the lattice. The two differ only for points below the
        origin, where ``int()`` truncation toward zero maps -0.5 cells onto
        cell 0; :meth:`is_in_bounds` rejects those here.
        """
        gx = int(math.floor((wx - self._origin_x) / self._resolution))
        gy = int(math.floor((wy - self._origin_y) / self._resolution))
        return gx, gy

    def grid_to_world(self, gx: int, gy: int) -> tuple:
        """Cell-centre world position, matching ``OccupancyGrid.grid_to_world``."""
        return (gx * self._resolution + self._origin_x + self._resolution / 2.0,
                gy * self._resolution + self._origin_y + self._resolution / 2.0)

    def is_in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self._width and 0 <= gy < self._height

    # -- reads ---------------------------------------------------------------

    @property
    def slope_deg(self) -> np.ndarray:
        """Read-only ``[gy, gx]`` slope array in degrees -- planner cost input."""
        view = self._slope.view()
        view.flags.writeable = False
        return view

    @property
    def elevation_m(self) -> np.ndarray:
        """Read-only ``[gy, gx]`` world-z array in metres."""
        view = self._elevation.view()
        view.flags.writeable = False
        return view

    def slope_deg_cell(self, gx: int, gy: int) -> float:
        """Slope of one cell. ``inf`` off the lattice -- there is no ground there."""
        if not self.is_in_bounds(gx, gy):
            return float('inf')
        return float(self._slope[gy, gx])

    def slope_deg_at(self, wx: float, wy: float) -> float:
        """Slope at a world point -- ``SAMPLING_RESAMPLED``.

        ``inf`` off the lattice, so an unguarded comparison against a limit
        REFUSES rather than admits. A NaN coordinate is off the lattice too,
        and is rejected explicitly rather than by accident: NaN compares false
        against everything, so the right answer would otherwise be reached for
        the wrong reason.
        """
        if not (math.isfinite(wx) and math.isfinite(wy)):
            return float('inf')
        gx, gy = self.world_to_grid(wx, wy)
        return self.slope_deg_cell(gx, gy)

    def elevation_at_m(self, wx: float, wy: float) -> float:
        """World z at a world point -- ``SAMPLING_RESAMPLED``. NaN off the lattice."""
        if not (math.isfinite(wx) and math.isfinite(wy)):
            return float('nan')
        gx, gy = self.world_to_grid(wx, wy)
        if not self.is_in_bounds(gx, gy):
            return float('nan')
        return float(self._elevation[gy, gx])

    # -- the two consumers ---------------------------------------------------

    def is_traversable(self, wx: float, wy: float, limit_deg: float) -> bool:
        """Goal check: is the cell containing this point inside *limit_deg*?

        The comparison is ``<=``, and off-lattice is False.
        """
        return self.slope_deg_at(wx, wy) <= float(limit_deg)

    def passable_mask(self, limit_deg: float) -> np.ndarray:
        """Boolean ``[gy, gx]`` mask of cells at or under *limit_deg*."""
        return self._slope <= np.float32(limit_deg)

    def cost_grid(self, limit_deg: float, weight: float = 1.0,
                  impassable_cost: float = float('inf')) -> np.ndarray:
        """Per-cell traversal cost for a planner.

        ``weight * slope / limit`` where passable -- 0 on the flat, *weight* at
        the limit -- and *impassable_cost* above it. The default ``inf`` makes
        an over-limit cell unreachable; a large finite value instead makes it
        merely expensive, which is the right choice when refusing to plan is
        worse than planning a bad route. The caller decides, because that is a
        mission question and not a terrain question.
        """
        limit = float(limit_deg)
        if limit <= 0.0:
            raise ValueError('limit_deg must be positive')
        cost = (float(weight) / limit) * self._slope.astype(np.float64)
        return np.where(self._slope <= np.float32(limit), cost,
                        float(impassable_cost))

    def components(self, limit_deg: float, connectivity: int = 4
                   ) -> 'ComponentLabels':
        """Connected components of the passable set -- for a startup audit.

        4-connected by default: a robot cannot squeeze through a diagonal
        contact between two cells any more than a wheel can. 8-connectivity is
        available because a coarse lattice can pinch a real corridor into a
        diagonal, and knowing whether that changed the answer is worth a second
        run rather than an assumption.

        Costs ~0.3 s on the shipped 500 x 500 lattice.
        """
        return ComponentLabels(self, float(limit_deg), int(connectivity))


# ---------------------------------------------------------------------------
# Connected components
# ---------------------------------------------------------------------------

_NEIGHBOURS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_NEIGHBOURS_8 = _NEIGHBOURS_4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


class ComponentLabels:
    """Connected components of ``slope <= limit``, over a :class:`SlopeLattice`.

    WHAT THIS IS FOR. Enforcing a slope limit that splits the world into
    mutually unreachable pieces breaks a mission that works -- under a 15 deg
    cut the shipped terrain splits into a plain holding every spawn and the
    recharge pad, and a crater basin holding the depot and the ice, with no
    route between them. A startup audit that labels components can say that
    BEFORE a hauler is dispatched at a wall, instead of after.

    Label ``IMPASSABLE_LABEL`` (0) means "over the limit", not "component 0".
    """

    def __init__(self, lattice: SlopeLattice, limit_deg: float,
                 connectivity: int = 4):
        if connectivity not in (4, 8):
            raise ValueError('connectivity must be 4 or 8')
        self._lattice = lattice
        self._limit_deg = float(limit_deg)
        self._connectivity = connectivity

        passable = lattice.passable_mask(limit_deg)
        height, width = passable.shape
        labels = np.zeros((height, width), dtype=np.int32)
        neighbours = _NEIGHBOURS_4 if connectivity == 4 else _NEIGHBOURS_8
        sizes = {}
        nlabel = 0
        for sy in range(height):
            for sx in range(width):
                if not passable[sy, sx] or labels[sy, sx]:
                    continue
                nlabel += 1
                labels[sy, sx] = nlabel
                queue = deque(((sy, sx),))
                count = 0
                while queue:
                    yy, xx = queue.popleft()
                    count += 1
                    for dy, dx in neighbours:
                        ny, nx = yy + dy, xx + dx
                        if (0 <= ny < height and 0 <= nx < width
                                and passable[ny, nx] and not labels[ny, nx]):
                            labels[ny, nx] = nlabel
                            queue.append((ny, nx))
                sizes[nlabel] = count
        self._labels = labels
        self._sizes = sizes

    @property
    def limit_deg(self) -> float:
        return self._limit_deg

    @property
    def connectivity(self) -> int:
        return self._connectivity

    @property
    def count(self) -> int:
        """Number of passable components. Zero if nothing is passable."""
        return len(self._sizes)

    @property
    def labels(self) -> np.ndarray:
        """Read-only ``[gy, gx]`` label array; 0 is impassable."""
        view = self._labels.view()
        view.flags.writeable = False
        return view

    @property
    def sizes(self) -> dict:
        """``{label: cell count}``."""
        return dict(self._sizes)

    def sizes_sorted(self) -> list:
        """``[(label, size), ...]`` largest first."""
        return sorted(self._sizes.items(), key=lambda kv: (-kv[1], kv[0]))

    def passable_cells(self) -> int:
        return int(sum(self._sizes.values()))

    def label_at(self, wx: float, wy: float) -> int:
        """Component label of the cell containing a world point.

        ``IMPASSABLE_LABEL`` both for over-limit ground and for points off the
        lattice, which are equally unreachable.
        """
        if not (math.isfinite(wx) and math.isfinite(wy)):
            return IMPASSABLE_LABEL
        gx, gy = self._lattice.world_to_grid(wx, wy)
        if not self._lattice.is_in_bounds(gx, gy):
            return IMPASSABLE_LABEL
        return int(self._labels[gy, gx])

    def same_component(self, a: Sequence[float], b: Sequence[float]) -> bool:
        """True when two world points are mutually reachable under the limit.

        False when either is impassable -- an unreachable point is not in the
        same component as anything, including another unreachable point.
        """
        la = self.label_at(a[0], a[1])
        lb = self.label_at(b[0], b[1])
        return la != IMPASSABLE_LABEL and la == lb

    def membership(self, points: dict) -> dict:
        """``{name: label}`` for a dict of ``{name: (x, y)}`` -- audit input."""
        return {name: self.label_at(p[0], p[1]) for name, p in points.items()}

    def unreachable_pairs(self, points: dict) -> list:
        """``[(name_a, name_b, label_a, label_b), ...]`` for pairs that cannot
        reach each other. The whole point of an audit: name the pairs."""
        names = sorted(points)
        member = self.membership(points)
        out = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if member[a] == IMPASSABLE_LABEL or member[a] != member[b]:
                    out.append((a, b, member[a], member[b]))
        return out


# ---------------------------------------------------------------------------
# Numerics
# ---------------------------------------------------------------------------

def _gradient_components(z, w, spacing):
    """Central differences over *w* cells, one-sided within *w* of the edge.

    The stencil width is what makes this a 3 m baseline rather than a
    per-sample one: a 0.98 m gradient reports relief a ~1 m wheelbase never
    feels. Edge rows use a one-sided difference over the same *w* cells, so the
    baseline is constant across the whole array and only the centring changes.
    """
    dzdx = np.zeros_like(z)
    dzdy = np.zeros_like(z)
    span = 2 * w * spacing
    edge = w * spacing
    dzdx[:, w:-w] = (z[:, 2 * w:] - z[:, :-2 * w]) / span
    dzdx[:, :w] = (z[:, w:2 * w] - z[:, :w]) / edge
    dzdx[:, -w:] = (z[:, -w:] - z[:, -2 * w:-w]) / edge
    dzdy[w:-w, :] = (z[2 * w:, :] - z[:-2 * w, :]) / span
    dzdy[:w, :] = (z[w:2 * w, :] - z[:w, :]) / edge
    dzdy[-w:, :] = (z[-w:, :] - z[-2 * w:-w, :]) / edge
    return dzdx, dzdy


def _uv(coord, world_size, n):
    """World metres -> fractional lattice index, ascending-y rows."""
    return (np.asarray(coord, dtype=np.float64) + world_size / 2.0) \
        / world_size * (n - 1)


def _bilinear(arr, x, y, world_size):
    """Bilinear sample of an ascending-y array at world (*x*, *y*).

    Coordinates outside the lattice clamp to the edge cell rather than
    extrapolating. Callers that must not silently read off-terrain values check
    :meth:`TerrainSlopeField.contains` first -- clamping is the right default
    for a numeric helper and the wrong default for a navigation decision.
    """
    n = arr.shape[0]
    fx = float(_uv(x, world_size, n))
    fy = float(_uv(y, world_size, n))
    j0 = min(max(int(math.floor(fx)), 0), n - 2)
    i0 = min(max(int(math.floor(fy)), 0), n - 2)
    tx = min(max(fx - j0, 0.0), 1.0)
    ty = min(max(fy - i0, 0.0), 1.0)
    return float(arr[i0, j0] * (1.0 - tx) * (1.0 - ty)
                 + arr[i0, j0 + 1] * tx * (1.0 - ty)
                 + arr[i0 + 1, j0] * (1.0 - tx) * ty
                 + arr[i0 + 1, j0 + 1] * tx * ty)


def _bilinear_lattice(arr, xs, ys, world_size):
    """Vectorised :func:`_bilinear` over an outer product of xs and ys."""
    n = arr.shape[0]
    fx = _uv(xs, world_size, n)
    fy = _uv(ys, world_size, n)
    j0 = np.clip(np.floor(fx).astype(np.intp), 0, n - 2)
    i0 = np.clip(np.floor(fy).astype(np.intp), 0, n - 2)
    tx = np.clip(fx - j0, 0.0, 1.0)[None, :]
    ty = np.clip(fy - i0, 0.0, 1.0)[:, None]
    return (arr[np.ix_(i0, j0)] * (1.0 - tx) * (1.0 - ty)
            + arr[np.ix_(i0, j0 + 1)] * tx * (1.0 - ty)
            + arr[np.ix_(i0 + 1, j0)] * (1.0 - tx) * ty
            + arr[np.ix_(i0 + 1, j0 + 1)] * tx * ty).astype(np.float32)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def load_default_lattice(heightmap_dir=None, layer='visual',
                         baseline_m=DEFAULT_BASELINE_M,
                         width=500, height=500, resolution=1.0,
                         origin_x=-250.0, origin_y=-250.0):
    """``(field, lattice)`` on the shipped navigation geometry.

    The defaults are the numbers in ``selene_agent/config/nav_params.yaml``
    (``grid_width`` / ``grid_height`` / ``grid_resolution`` / ``origin_x`` /
    ``origin_y``). They are REPEATED here rather than read, because this module
    must stay importable with no config file present; a caller that has the
    config should pass ``OccupancyGrid.from_config(...)`` to
    :meth:`TerrainSlopeField.resample_to_grid` instead and get the geometry
    from the one source.
    """
    field = TerrainSlopeField.load(heightmap_dir=heightmap_dir, layer=layer,
                                   baseline_m=baseline_m)
    return field, field.resample(width, height, resolution, origin_x, origin_y)


def describe_sampling(method: str) -> str:
    """One-line description of a sampling method, for reports and logs."""
    if method == SAMPLING_NATIVE:
        return ('native: bilinear on the heightmap\'s own lattice, gradient '
                'over the effective baseline')
    if method == SAMPLING_RESAMPLED:
        return ('resampled: native slope bilinearly resampled onto the '
                'planning lattice, read at the containing cell centre')
    raise ValueError(f'unknown sampling method {method!r}')
