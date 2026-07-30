"""The terrain datum, checked without Gazebo.

WHY THIS EXISTS
The relationship between a heightmap pixel and a world z is invisible from every
file that depends on it. It has now been wrong twice, both times silently:

  1. Row order. The generator built its field with rows ascending in +Y and wrote
     it straight out, but the image convention is row 0 = +Y, so the whole
     terrain rendered mirrored about the equator: the PSR crater configured for
     (-100, -150) physically appeared at (-100, +150).
  2. Vertical scale. gz-sim maps the maximum pixel value PRESENT IN THE IMAGE to
     <size> z, not the format maximum. The generator emitted (H/30)*65535 on a
     field whose true maximum is 24.2528 m, so its brightest pixel was 0.8084 of
     full range, gz-sim stretched it back over 30 m, and every elevation came out
     1.2370x (visual) / 1.2500x (collision) too high. The -18 m datum on
     terrain_link existed to cancel that, which is why it sat ~3 m away from the
     +15 m base the generator adds.

Both were found by dropping probes in Gazebo (scripts/check_terrain.sh), which
needs WSL2, ROS 2 and a built workspace and takes about a minute. This file
checks the same invariants in pure Python in well under a second, so the
arithmetic half is gated on every push. It cannot tell you whether a robot can
drive; that is check_drive.sh's job.

WHAT IT ASSERTS
  * the generator's field is the one the constants were derived from
  * each emitted PNG's brightest pixel is EXACTLY the format maximum — the single
    property the whole datum rests on
  * models/lunar_terrain/model.sdf's three magic literals (the link pose z and
    the two <size> z values) match heightmaps/terrain_datum.json
  * the collision and visual <size> z values are DIFFERENT, and that sharing one
    would be wrong
  * decoding a PNG the way gz-sim does reproduces world z = height - 15.0
  * row order: the crater is at (-100, -150) and NOT at (-100, +150)
"""

import json
import os
import sys

import numpy as np
import pytest

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PKG, 'scripts'))

import generate_heightmap as G  # noqa: E402

HEIGHTMAPS = os.path.join(_PKG, 'models', 'lunar_terrain', 'heightmaps')
MODEL_SDF = os.path.join(_PKG, 'models', 'lunar_terrain', 'model.sdf')

# Coordinates that matter to something: the four spawns, the depot, the PSR
# centre, two off-crater references and the Y-mirror control.
SAMPLES = [
    (-45, -92), (-45, -85), (-45, -105), (-45, -112),
    (-30, -100), (-100, -150), (-100, -20), (10, -150), (-100, 150), (0, 0),
]


@pytest.fixture(scope='module')
def datum():
    path = os.path.join(HEIGHTMAPS, 'terrain_datum.json')
    assert os.path.isfile(path), (
        f'{path} is missing. Run: python3 selene_sim/scripts/generate_heightmap.py')
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def field():
    """The generator's own metric field, ascending-y rows. No files written."""
    return G.build_field()


@pytest.fixture(scope='module')
def sdf_numbers():
    """The three literals model.sdf carries, pulled out by a deliberately dumb parse."""
    import re
    text = open(MODEL_SDF).read()
    pose = re.search(r'<link\s+name="terrain_link">\s*<pose>\s*0\s+0\s+(-?[\d.]+)', text)
    assert pose, 'could not find terrain_link <pose> in model.sdf'
    sizes = re.findall(r'<size>\s*500\s+500\s+([\d.]+)\s*</size>', text)
    assert len(sizes) == 2, f'expected 2 <size> elements in model.sdf, found {len(sizes)}'
    # Document order in model.sdf is collision first, then visual.
    return {'pose_z': float(pose.group(1)),
            'collision_size_z': float(sizes[0]),
            'visual_size_z': float(sizes[1])}


def _decode(png_name, full_scale, size_z, base):
    """Decode a heightmap the way gz-sim does, into world z, in image row order."""
    px = np.asarray(Image.open(os.path.join(HEIGHTMAPS, png_name))).astype(np.float64)
    # z_render = size_z * pixel / max(pixel in image);  world z = z_render - base
    return size_z * px / px.max() - base


def _bilinear(img, x, y):
    """Sample an image-convention array (row 0 = +Y) at world (x, y) metres."""
    n = img.shape[0]
    w = G.WORLD_SIZE
    fx = (x + w / 2.0) / w * (n - 1)
    fy = (w / 2.0 - y) / w * (n - 1)
    x0, y0 = int(np.floor(fx)), int(np.floor(fy))
    x1, y1 = min(x0 + 1, n - 1), min(y0 + 1, n - 1)
    tx, ty = fx - x0, fy - y0
    top = img[y0, x0] * (1 - tx) + img[y0, x1] * tx
    bot = img[y1, x0] * (1 - tx) + img[y1, x1] * tx
    return top * (1 - ty) + bot * ty


# --------------------------------------------------------------------- field

def test_field_matches_the_datum_record(field, datum):
    """The constants must have been derived from THIS field, not an older one."""
    assert field.min() == pytest.approx(datum['field']['min_m'], abs=1e-9)
    assert field.max() == pytest.approx(datum['field']['max_m'], abs=1e-9)
    assert field.mean() == pytest.approx(datum['field']['mean_m'], abs=1e-9)


def test_field_is_not_clipped_at_zero(field):
    """A clipped floor silently flattens the crater instead of erroring."""
    assert field.min() > 0.0, (
        f'field minimum {field.min():.6f} is at the clip floor; raise '
        f'BASE_ELEVATION in generate_heightmap.py')


def test_base_elevation_is_the_single_source_of_truth(datum, sdf_numbers):
    assert datum['base_elevation_m'] == G.BASE_ELEVATION
    assert datum['link_pose_z'] == -G.BASE_ELEVATION
    assert sdf_numbers['pose_z'] == pytest.approx(-G.BASE_ELEVATION, abs=1e-9), (
        f"model.sdf terrain_link pose z is {sdf_numbers['pose_z']}, but the "
        f"generator's BASE_ELEVATION is {G.BASE_ELEVATION}. Every elevation in "
        f"the world is offset by the difference.")


# ---------------------------------------------------------------- the images

@pytest.mark.parametrize('which', ['visual', 'collision'])
def test_brightest_pixel_is_exactly_full_scale(datum, which):
    """The one property the whole datum rests on.

    gz-sim normalises by the image's own maximum, so if the brightest pixel is
    even one level short of full scale, every elevation is scaled by
    full_scale/actual_max. One level short of 255 is a 0.4% error = 0.094 m.
    """
    spec = datum[which]
    px = np.asarray(Image.open(os.path.join(HEIGHTMAPS, spec['image'])))
    assert int(px.max()) == spec['full_scale'], (
        f"{spec['image']} peaks at {px.max()}/{spec['full_scale']}. gz-sim would "
        f"renormalise and inflate every elevation by "
        f"{spec['full_scale'] / max(int(px.max()), 1):.6f}x. Re-run "
        f"generate_heightmap.py.")


@pytest.mark.parametrize('which', ['visual', 'collision'])
def test_sdf_size_z_matches_the_generated_datum(datum, sdf_numbers, which):
    generated = datum[which]['size_z_m']
    carried = sdf_numbers[f'{which}_size_z']
    assert carried == pytest.approx(generated, abs=1e-6), (
        f'model.sdf {which} <size> z is {carried}, generator says {generated}. '
        f'The terrain renders at {generated / carried:.6f}x the intended scale.')


def test_the_two_size_z_values_must_differ(datum):
    """Sharing one <size> would reintroduce the scaling bug.

    Decimating the field to 129x129 does not preserve its maximum, so the coarse
    map's brightest pixel represents a lower elevation than the fine map's.
    """
    vis = datum['visual']['size_z_m']
    col = datum['collision']['size_z_m']
    assert col < vis, 'the decimated field cannot exceed the full field maximum'
    assert vis - col > 1e-4, (
        'the two maxima have converged; if they are ever genuinely equal this '
        'test should be relaxed, but check first that the coarse map was '
        'decimated from the float field and normalised by its own maximum')


# --------------------------------------------------- the world-z identity

@pytest.mark.parametrize('which,tol', [('visual', 0.01), ('collision', 0.10)])
def test_world_z_equals_height_minus_base(datum, field, which, tol):
    """Decode the PNG as gz-sim does; it must reproduce height - BASE_ELEVATION.

    Tolerance is quantisation, not slack: the collision map is 8-bit over
    ~24 m, i.e. 0.094 m per level, and it is a 129x129 decimation of a 513x513
    field, so a bilinear read between lattice points differs from the fine field
    by real terrain relief as well.
    """
    spec = datum[which]
    world = _decode(spec['image'], spec['full_scale'], spec['size_z_m'],
                    datum['base_elevation_m'])
    fine = G.to_image_rows(field)
    for x, y in SAMPLES:
        want = _bilinear(fine, x, y) - datum['base_elevation_m']
        got = _bilinear(world, x, y)
        assert got == pytest.approx(want, abs=tol), (
            f'{which} at ({x},{y}): decoded world z {got:.4f} vs field-derived '
            f'{want:.4f}')


def test_collision_and_visual_agree(datum):
    """They disagreed by up to 0.24 m, so robots drove on an invisible floor."""
    surfaces = {}
    for which in ('visual', 'collision'):
        spec = datum[which]
        surfaces[which] = _decode(spec['image'], spec['full_scale'],
                                  spec['size_z_m'], datum['base_elevation_m'])
    worst = 0.0
    for x, y in SAMPLES:
        d = abs(_bilinear(surfaces['collision'], x, y)
                - _bilinear(surfaces['visual'], x, y))
        worst = max(worst, d)
    # 8-bit quantisation of the coarse map is 0.094 m; allow ~1 level of it.
    assert worst < 0.10, (
        f'collision and visual disagree by {worst:.4f} m. Before the '
        f'normalisation fix this was 0.24 m.')


# ------------------------------------------------------------------ row order

def test_crater_is_south_not_north(datum, field):
    """The Y-mirror regression. This is what check_terrain.sh's mirror_check probes.

    The PSR crater is carved at (-100, -150) with depth 15 m. If the flipud at
    the I/O boundary is ever dropped, it renders at (-100, +150) instead and
    every consumer — the PSR zone, the ice deposits, the battery shadow model,
    the dashboard overlay — is pointing at the wrong place.
    """
    spec = datum['collision']
    world = _decode(spec['image'], spec['full_scale'], spec['size_z_m'],
                    datum['base_elevation_m'])
    south = _bilinear(world, -100, -150)
    north = _bilinear(world, -100, 150)
    assert south < north - 10.0, (
        f'(-100,-150) reads {south:.2f} m and (-100,+150) reads {north:.2f} m. '
        f'The crater must be the SOUTHERN one; the terrain looks mirrored in Y.')
    assert south < -10.0, f'the PSR crater floor should be well below 0, got {south:.2f}'
    assert north > -1.0, f'(-100,+150) should be plain, got {north:.2f}'


def test_psr_is_a_depression_relative_to_its_surroundings(datum):
    """Mirrors the PSR-depth relation check_terrain.sh asserts in Gazebo."""
    spec = datum['collision']
    world = _decode(spec['image'], spec['full_scale'], spec['size_z_m'],
                    datum['base_elevation_m'])
    centre = _bilinear(world, -100, -150)
    rim = (_bilinear(world, -100, -20) + _bilinear(world, 10, -150)) / 2.0
    assert rim - centre > 5.0, (
        f'PSR depth is {rim - centre:.2f} m (outside {rim:.2f}, centre '
        f'{centre:.2f}); check_terrain.sh uses the same 5.0 m threshold')
