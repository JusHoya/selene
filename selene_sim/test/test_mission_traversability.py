"""Can the mission's robots physically get where the mission sends them?

WHY THIS EXISTS
---------------
Until 2026-07-31 nothing in SELENE asked. ``selene_agent/config/nav_params.yaml``
has declared ``navigation.max_traversable_slope_deg: 15.0`` since Phase 2 and
NOTHING HAS EVER READ IT -- ``AStarPlanner`` takes ``slope_penalty_weight`` and
multiplies it by an ``OccupancyGrid`` cost that no terrain ever writes to, so the
planner's slope term is identically zero and the limit is decoration. That is the
fourth instance of this repository's "wired but never called" pattern, and it is
the one that cost a mission.

WHAT HAPPENED WITHOUT IT. Every ice deposit in ``ice_deposits.yaml`` sits inside
the PSR crater, and until 2026-07-31 the configured depot sat outside it, so
every haul had to cross the rim. The rim, computed below from the shipped
generator, is 34-39 degrees on every azimuth. On 2026-07-31 a hauler was routed
straight at it, climbed to r=57.5 m, pitched to -35 degrees and pinned; for
320.7 s its wheels turned at the commanded 0.395 m/s while its body moved 6.6 cm,
and its dead-reckoned pose carried the phantom 126.7 m to within 0.4 m of the
depot, where it unloaded 19 kg -- 241.577 m from where it actually was. (Those
figures are from that run's analyser output. Everything this file prints is
computed here.)

WHAT THIS FILE IS, AND IS NOT
-----------------------------
It is an arithmetic gate on the SHIPPED, DETERMINISTIC height field
(``generate_heightmap.build_field()``, seed 42). It needs no Gazebo and runs on
every push, like ``test_heightmap_datum.py`` beside it and for the same reason:
the property is invisible from every file that depends on it.

It is NOT a measurement of what these vehicles can climb. The only slope on which
one has been observed to fail is ~35 degrees; nothing has swept the range, so
``max_traversable_slope_deg`` is a declared bound chosen to sit far under that,
not an estimate of the true limit.

It is also NOT a substitute for the planner reading the terrain. A green run here
says the mission's DESIGNED coordinates are mutually reachable; it says nothing
about a target an operator injects, or about an extraction site the orchestrator
picks off a resource-map cell that happens to lie on the wall. Both are still
unguarded. See the register.

WHY THE FINE FIELD AND A 3 m BASELINE
-------------------------------------
The 513-sample field is the terrain's true relief; the 129-sample collision map
gz-sim actually contacts is a decimation of it and can only be smoother, so
asserting against the fine field is the conservative direction. The gradient is
taken over a 3 m baseline because that is the scale a ~1 m wheelbase vehicle
integrates over -- a per-sample gradient at 0.98 m spacing reports noise the
chassis never feels.
"""

import math
import os
import re
import sys

import numpy as np
import pytest
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_REPO = os.path.dirname(_PKG)
sys.path.insert(0, os.path.join(_PKG, 'scripts'))

import generate_heightmap as G  # noqa: E402

WORLD_PARAMS = os.path.join(_PKG, 'config', 'world_params.yaml')
ICE_YAML = os.path.join(_PKG, 'config', 'ice_deposits.yaml')
WORLD_SDF = os.path.join(_PKG, 'worlds', 'lunar_psr.sdf')
ORCH_PARAMS = os.path.join(
    _REPO, 'selene_orchestrator', 'config', 'orchestrator_params.yaml')

#: Gradient baseline, metres. See the module docstring.
BASELINE_M = 3.0
#: Sampling step along a route, metres.
STEP_M = 0.5


# --------------------------------------------------------------------- field

@pytest.fixture(scope='module')
def field():
    """The generator's own metric field, ascending-y rows. No files written."""
    return G.build_field()


def _z_at(field, x, y):
    """Bilinear world z at (x, y). Rows ascend in +Y, matching build_field()."""
    n = field.shape[0]
    fx = (x + G.WORLD_SIZE / 2.0) / G.WORLD_SIZE * (n - 1)
    fy = (y + G.WORLD_SIZE / 2.0) / G.WORLD_SIZE * (n - 1)
    j0 = min(max(int(math.floor(fx)), 0), n - 2)
    i0 = min(max(int(math.floor(fy)), 0), n - 2)
    tx, ty = fx - j0, fy - i0
    v = (field[i0, j0] * (1 - tx) * (1 - ty)
         + field[i0, j0 + 1] * tx * (1 - ty)
         + field[i0 + 1, j0] * (1 - tx) * ty
         + field[i0 + 1, j0 + 1] * tx * ty)
    return float(v) - G.BASE_ELEVATION


def _max_slope_deg(field, p, q):
    """Steepest gradient over a 3 m baseline along the straight line p -> q."""
    d = math.hypot(q[0] - p[0], q[1] - p[1])
    if d < BASELINE_M:
        return 0.0
    n = int(round(d / STEP_M))
    zs = np.array([
        _z_at(field, p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n)
        for k in range(n + 1)])
    xs = np.linspace(0.0, d, n + 1)
    w = max(1, int(round(BASELINE_M / (d / n))))
    grad = (zs[w:] - zs[:-w]) / (xs[w:] - xs[:-w])
    return math.degrees(math.atan(float(np.abs(grad).max())))


# -------------------------------------------------------------------- config

@pytest.fixture(scope='module')
def slope_limit_deg():
    """``world.max_traversable_slope_deg`` -- the declared bound."""
    with open(WORLD_PARAMS) as handle:
        world = (yaml.safe_load(handle) or {}).get('world') or {}
    limit = world.get('max_traversable_slope_deg')
    assert limit is not None, (
        f'{WORLD_PARAMS} has no world.max_traversable_slope_deg. This gate is '
        f'the only reader of a slope limit anywhere in the repository; without '
        f'it nothing checks that the mission is physically possible.')
    return float(limit)


@pytest.fixture(scope='module')
def configured_depot():
    """depot_x / depot_y from orchestrator_params.yaml.

    Read from the ORCHESTRATOR's file rather than from world_params.yaml,
    because this one is what actually reaches a hauler -- it is published on
    ``TaskAssignment.depot_location``. A copy in another file that disagreed
    would be exactly the defect the (50,50) / (-30,-100) split already was.
    """
    with open(ORCH_PARAMS) as handle:
        raw = yaml.safe_load(handle) or {}
    params = raw['orchestrator_node']['ros__parameters']
    return (float(params['depot_x']), float(params['depot_y']))


@pytest.fixture(scope='module')
def deposits():
    with open(ICE_YAML) as handle:
        return (yaml.safe_load(handle) or {})['deposits']


def _sdf_marker(name):
    """(x, y, z) of the <include> whose <name> is *name*, from lunar_psr.sdf."""
    text = open(WORLD_SDF).read()
    for block in re.findall(r'<include>(.*?)</include>', text, re.S):
        found = re.search(r'<name>\s*(\w+)\s*</name>', block)
        if not found or found.group(1) != name:
            continue
        pose = re.search(
            r'<pose>\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', block)
        assert pose, f'the {name} <include> has no parseable <pose>'
        return tuple(float(g) for g in pose.groups())
    return None


# --------------------------------------------------------------------- tests

def test_the_depot_has_a_physical_referent(configured_depot):
    """The configured depot and the world's depot marker are the same place.

    They were 234 m apart until 2026-07-31: orchestrator_params.yaml said
    (50, 50) and the only marker in lunar_psr.sdf was at (-30, -100). Every
    "delivery" in this project's history therefore landed on bare terrain, and
    the disagreement was recorded in a comment as deliberate rather than fixed.
    """
    marker = _sdf_marker('depot')
    assert marker is not None, (
        f'no <include> named "depot" in {WORLD_SDF}; a delivery would have '
        f'nowhere to arrive.')
    assert (marker[0], marker[1]) == pytest.approx(configured_depot, abs=1e-6), (
        f'the orchestrator delivers to {configured_depot} but the depot marker '
        f'is at ({marker[0]}, {marker[1]}). A haul would unload onto empty '
        f'terrain, and the ledger would balance while doing it.')


def test_the_recharge_pad_is_still_where_the_agent_expects_it():
    """The plain-side marker did not move when the depot did.

    ``selene_agent/agent_node.py`` defaults its recharge station to
    (-30, -100). The marker that used to be the depot now marks that, so the
    move did not silently delete the only object on the plain.
    """
    marker = _sdf_marker('recharge_pad')
    assert marker is not None, f'no <include> named "recharge_pad" in {WORLD_SDF}'
    assert (marker[0], marker[1]) == pytest.approx((-30.0, -100.0), abs=1e-6)


def test_every_deposit_can_reach_the_depot(field, deposits, configured_depot,
                                           slope_limit_deg):
    """THE ACCEPTANCE STATEMENT: the ISRU cycle is physically possible.

    A haul runs deposit -> depot. If the straight line between them crosses
    ground steeper than the declared limit, the mission cannot complete however
    good the software is -- and, worse, it will not FAIL: the hauler will pin,
    its wheel odometry will keep advancing, and it will report a delivery.
    """
    rows = []
    for deposit in deposits:
        centre = (float(deposit['center'][0]), float(deposit['center'][1]))
        rows.append((deposit['id'], centre,
                     _max_slope_deg(field, centre, configured_depot)))
    over = [r for r in rows if r[2] > slope_limit_deg]
    detail = '\n'.join(
        f'  {name:<16} {c[0]:8.1f} {c[1]:8.1f}  {s:6.2f} deg' for name, c, s in rows)
    assert not over, (
        f'ice deposits that cannot reach the depot at {configured_depot} '
        f'under a {slope_limit_deg:.1f} deg limit:\n{detail}')


def test_the_depot_sits_on_the_crater_floor(field, configured_depot):
    """It is inside the PSR, not merely reachable from it.

    Stated as its own assertion because the reason the depot moved was the
    crater wall: a depot that drifted back outside would restore the defect
    while every route test above still passed for whichever deposits happened
    to be on its side.
    """
    cx, cy = G.CRATER['cx'], G.CRATER['cy']
    r = math.hypot(configured_depot[0] - cx, configured_depot[1] - cy)
    flat_r = (G.CRATER['diameter'] / 2.0) * G.CRATER['flat_fraction']
    assert r <= flat_r, (
        f'the depot is {r:.1f} m from the crater centre; the flat bottom ends '
        f'at {flat_r:.1f} m. Beyond it the floor tilts, and beyond r=15 m the '
        f'parabolic wall begins.')


def test_the_crater_is_a_one_way_trip(field, slope_limit_deg):
    """PINNED, NOT ASSERTED AS DESIRABLE. This is a recorded world defect.

    Every azimuth out of the PSR crater is steeper than the declared limit, so
    a robot that descends to the ice cannot climb back to the recharge pad on
    the plain. No run has hit it -- batteries end a 20-minute mission at 73-86%
    -- and nothing in the system would detect it if one did.

    The test asserts the defect is STILL THERE so that regenerating the terrain
    with a gentler crater, or adding a graded ramp, cannot happen without
    someone landing here and updating docs/phase5_deviation_register.md. If this
    fails with "the crater is now climbable", that is good news and the fix is
    to delete this test and the register entry together.
    """
    cx, cy = G.CRATER['cx'], G.CRATER['cy']
    radii = np.arange(0.0, 95.0, 0.5)
    w = int(round(BASELINE_M / 0.5))
    gentlest = 90.0
    for az_deg in range(0, 360, 5):
        az = math.radians(az_deg)
        zs = np.array([_z_at(field, cx + r * math.cos(az), cy + r * math.sin(az))
                       for r in radii])
        grad = (zs[w:] - zs[:-w]) / (radii[w:] - radii[:-w])
        gentlest = min(gentlest, math.degrees(math.atan(float(grad.max()))))
    assert gentlest > slope_limit_deg, (
        f'the gentlest way out of the PSR crater is now {gentlest:.2f} deg, '
        f'inside the {slope_limit_deg:.1f} deg limit. The crater is no longer '
        f'one-way. Delete this test and the matching register entry.')
    # Printed, not asserted: the register quotes this number.
    print(f'\ngentlest crater exit over 72 azimuths: {gentlest:.2f} deg '
          f'(limit {slope_limit_deg:.1f} deg)')


def test_deposit_edges_are_reported_even_where_they_are_unreachable(
        field, deposits, configured_depot, slope_limit_deg):
    """The half of the picture the acceptance test above does not cover.

    An extraction site is not the deposit centre: the orchestrator picks the
    hottest cell of the fused resource map, and a gaussian deposit puts warm
    cells up to several sigma out. Some of those lie on the crater wall.
    Nothing in the planner knows, because nothing reads a slope limit.

    This test does not fail on that -- it cannot, without either moving the
    deposits or building the terrain-aware planner that is the real fix. It
    fails only if the SHAPE of the problem changes, i.e. if the worst 1-sigma
    route stops exceeding the limit, so the register's claim stays true or
    somebody is told.
    """
    worst = 0.0
    worst_at = None
    for deposit in deposits:
        cx, cy = float(deposit['center'][0]), float(deposit['center'][1])
        sigma = float(deposit['sigma'])
        for k in range(36):
            az = 2.0 * math.pi * k / 36.0
            for rr in np.linspace(0.0, sigma, 6):
                point = (cx + rr * math.cos(az), cy + rr * math.sin(az))
                slope = _max_slope_deg(field, point, configured_depot)
                if slope > worst:
                    worst, worst_at = slope, point
    print(f'\nworst 1-sigma route to the depot: {worst:.2f} deg at '
          f'({worst_at[0]:.1f}, {worst_at[1]:.1f}), limit {slope_limit_deg:.1f} deg')
    assert worst > slope_limit_deg, (
        f'the worst 1-sigma route is now {worst:.2f} deg, inside the limit. '
        f'Every plausible extraction site is reachable, which is better than '
        f'the register currently says. Update it and delete this test.')
