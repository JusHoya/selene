#!/bin/bash
# Slope capability campaign — MEASURES the grade each vehicle can actually
# drive, up and down, on the shipped lunar terrain, and writes the measurement
# out as a self-describing artefact fit to be a committed constant's provenance.
#
# WHY THIS EXISTS
# selene_agent/config/nav_params.yaml:21 has declared
# `navigation.max_traversable_slope_deg: 15.0` since Phase 2 and NOTHING IN
# PRODUCTION READS IT (deviation D-28, docs/phase5_deviation_register.md). That
# is the fifth instance of this repository's "wired but never called" pattern.
# But wiring the declared value in would be worse than leaving it dangling,
# because the value is CONTRADICTED BY OBSERVATION:
#
#   * on 2026-07-31 a ten-robot fleet delivered 94.85 kg to a depot at
#     (-100,-150) on the floor of the PSR crater, hauler ground truth 1.539 m
#     from the depot marker. The gentlest measured exit from that crater is
#     34.09 deg. The robots crossed a ~34 deg rim while the config said 15.
#   * under a hard 15 deg cut the world splits into two DISCONNECTED navigable
#     components — a plain of 227,185 cells holding all ten spawns and the
#     recharge pad, and a crater basin of 3,531 cells holding the depot and all
#     four ice deposits. Enforcing 15 would refuse every spawn-to-depot route
#     and break a mission that works. (Reproduced twice; see
#     selene_agent/test/test_terrain_slope_field.py.)
#
# So the operator's decision is: measure the real capability, enforce the
# measured value, and commit this campaign's log as the constant's provenance.
# This script is the measuring apparatus. It decides nothing.
#
# WHAT IT DOES
# For each robot type, each target grade and BOTH directions:
#   1. finds a site on the committed heightmap whose local grade is closest to
#      the target AND whose grade is SUSTAINED over the length of a drive,
#      using selene_agent.terrain_slope (the same module a planner will read);
#   2. faces the robot directly up- or down-gradient there;
#   3. spawns it at the collision surface plus the clearance the shipped spawn
#      poses use;
#   4. drives linear.x for a fixed number of SIMULATION seconds and measures
#      WORLD displacement, its component along the commanded heading, the
#      achieved fraction of command, the slip, and the elevation change;
#   5. reports every trial as pass / fail / apparatus-failure / never-tested,
#      and prints the steepest grade that still met the acceptance floor for
#      ASCENT and for DESCENT separately.
#
# IT IS MODELLED ON scripts/check_drive.sh AND INHERITS ITS HARD-WON METHOD:
#   * the verdict compares WORLD displacement against the COMMAND, never
#     against odometry. A robot buried in terrain satisfies odometry perfectly
#     while not moving — DiffDrive integrates measured wheel-joint position and
#     an unloaded wheel reaches its commanded speed whether it is rolling, free
#     spinning or turning inside solid rock (measured 4.00000 rad/s in all
#     three). See check_drive.sh:17-32.
#   * it drives for SIMULATION seconds and computes the verdict from the sim
#     duration actually achieved, because timing a sim-time target with wall
#     clock made check_drive.sh's gate fail for reasons unrelated to terrain.
#     DRIVE_WALL_CAP bounds a stalled server, not a slow one.
#   * it reports the real-time factor read from /world/lunar_psr/stats.
#   * MIN_FRACTION 0.70 and MAX_SLIP_PCT 25 are check_drive.sh's, with its
#     reasoning at :85-99. Its FLAT-GROUND baselines are 94.7-98.2% of command
#     at -1.07% to +1.04% slip, so a trial that only just clears 0.70 is
#     already losing 30% of its command and is nowhere near flat behaviour.
#
# WHAT IT DOES NOT MEASURE — read this before quoting a number from it.
# Printed again at the end of every run, because a limitation that only lives
# in a comment is a limitation nobody reads.
#   * ONE STRAIGHT RUN FROM REST, ~4.8 m, EMPTY. Not sustained climbing over a
#     hundred metres, not climbing with a loaded hopper (mass changes with
#     cargo and every trial here drives empty), not stopping and restarting on
#     the grade.
#   * STRAIGHT UP OR STRAIGHT DOWN THE GRADIENT. A real route crosses a slope
#     at an angle. The side-slope rollover limit is NOT measured here and is
#     usually the binding one on a real vehicle.
#   * NO TURNING ON THE SLOPE. check_drive.sh's turn check is deliberately not
#     reproduced: a skid-steer scrubs badly and its yaw response says nothing
#     about whether it can climb.
#   * SIM PHYSICS, NOT HARDWARE. gz-sim/ODE with whatever <surface> friction
#     the shipped models declare. The number transfers to this simulation and
#     to nothing else.
#   * THE VISUAL HEIGHTMAP CHOOSES THE SITE; THE COLLISION HEIGHTMAP CARRIES
#     THE ROBOT. The 513-sample visual map is the terrain's true relief; the
#     129-sample collision mesh gz-sim actually contacts is a decimation of it
#     and can only be smoother. The grade a robot really feels is therefore at
#     most the grade reported, which makes every result here CONSERVATIVE in
#     the direction that matters.
#
# USAGE
#   bash scripts/measure_slope_capability.sh                 # all three types
#   SLOPE_ROBOTS=scout bash scripts/measure_slope_capability.sh
#   SLOPE_GRADES="10 20 30 34 36 40" bash scripts/measure_slope_capability.sh
#   SLOPE_JSON=/tmp/run7.json SELENE_WS=$HOME/selene_ws bash scripts/...
#
# EXIT CODES
#   0  the campaign ran and produced a verdict for every requested direction
#   1  the campaign ran but at least one requested (robot, grade, direction)
#      could not be measured — no site, spawn failure, burial or tumble. The
#      JSON still contains everything that WAS measured; a missing measurement
#      is not a pass and this script will not imply one.
#   3  the campaign could not start (no workspace, no ROS, world never came up)
#
# EXPECTED WALL CLOCK: about 40 s per trial at real-time factor ~0.5, plus ~35 s
# per robot type to bring a world up. The default sweep is 3 types x 9 grades x
# 2 directions = 54 trials, so budget roughly 40 minutes. It is printed before
# anything is spawned so you can cut the sweep instead of discovering the cost.

set -uo pipefail

WS="${SELENE_WS:-$HOME/selene}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# THE DEFAULT SWEEPS ALL THREE TYPES. The excavator and hauler are heavier than
# the scout and check_drive.sh's own flat baselines already show them behaving
# differently (excavator +1.04% slip, scout -0.80%), so a single-type campaign
# would produce a fleet-wide constant from one vehicle. Narrowing this is
# allowed and is reported loudly in the output.
SLOPE_ROBOTS="${SLOPE_ROBOTS:-scout excavator hauler}"
SLOPE_GRADES="${SLOPE_GRADES:-5 10 15 20 25 30 35 40 45}"
SLOPE_DIRECTIONS="${SLOPE_DIRECTIONS:-ascent descent}"

DRIVE_SPEED="${DRIVE_SPEED:-0.4}"        # m/s, the nav layer's cruise speed
DRIVE_SECONDS="${DRIVE_SECONDS:-12}"     # SIMULATION seconds, not wall seconds
DRIVE_WALL_CAP="${DRIVE_WALL_CAP:-8}"    # wall-clock safety multiple; see drive()
SETTLE_SECONDS="${SETTLE_SECONDS:-8}"
HEIGHTMAP_LOAD_SECONDS="${HEIGHTMAP_LOAD_SECONDS:-12}"

MIN_FRACTION="${MIN_FRACTION:-0.70}"
MAX_FRACTION="${MAX_FRACTION:-1.15}"
MAX_SLIP_PCT="${MAX_SLIP_PCT:-25}"

# How far a site's own grade may sit from the requested target before the
# target is reported as UNAVAILABLE rather than quietly substituted.
GRADE_TOLERANCE_DEG="${GRADE_TOLERANCE_DEG:-1.0}"
# How far the grade may wander along the drive corridor. A 40 deg reading on a
# single cell that flattens after 2 m would measure nothing; this is what makes
# a site a slope rather than a lip.
CORRIDOR_TOLERANCE_DEG="${CORRIDOR_TOLERANCE_DEG:-6.0}"
# Minimum separation between the sites chosen for successive trials of one
# robot type, so a leftover entity from a failed removal cannot sit in the next
# trial's path.
SITE_SEPARATION_M="${SITE_SEPARATION_M:-25.0}"
# Metres inside the terrain edge a site and its whole corridor must stay.
# navigation.terrain_margin_m / world.safety_margin_m both carry 10.0.
TERRAIN_MARGIN_M="${TERRAIN_MARGIN_M:-10.0}"
# DERIVED, NOT GUESSED. selene_sim/config/spawn_positions.yaml:26-27 states the
# rule every shipped spawn z follows: "(collision surface MEASURED at that
# exact XY by scripts/check_terrain.sh) + 0.30 m, rounded UP to 10 mm". 0.30 is
# that clearance. This campaign cannot re-measure a surface with a probe, so it
# reads the collision heightmap instead and adds a slope allowance on top; see
# the plan generator.
SPAWN_CLEARANCE_M="${SPAWN_CLEARANCE_M:-0.30}"

SLOPE_JSON="${SLOPE_JSON:-/tmp/selene_slope_capability.json}"
WORKDIR="${SLOPE_WORKDIR:-/tmp/selene_slope_campaign.$$}"
WORLD_NAME="${SELENE_WORLD_NAME:-lunar_psr}"

# --------------------------------------------------------------------- setup

if [ ! -f "$WS/install/setup.bash" ]; then
    echo "ERROR: no built workspace at $WS/install/setup.bash" >&2
    echo "       run scripts/sync_and_build.sh first, or set SELENE_WS." >&2
    echo "       NOTE \$HOME/selene may be a stale tree; \$HOME/selene_ws is" >&2
    echo "       the built one on the development machine." >&2
    exit 3
fi

# ROS setup.bash references unset vars.
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash 2>/dev/null || source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source "$WS/install/setup.bash"
set -u

SHARE="$WS/install/selene_sim/share/selene_sim"
WORLD="$SHARE/worlds/lunar_psr.sdf"
MODELS="$SHARE/models"
HEIGHTMAPS="$MODELS/lunar_terrain/heightmaps"
export GZ_SIM_RESOURCE_PATH="$MODELS:${GZ_SIM_RESOURCE_PATH:-}"
# CLI/short-lived DDS participants can exhaust /dev/shm on WSL2.
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
# Isolate gz transport so a developer's own simulation, or a parallel CI job,
# cannot answer our `gz model` queries. The world name inside lunar_psr.sdf is
# fixed, so without this the two would collide.
export GZ_PARTITION="${GZ_PARTITION:-selene_slope_$$}"
# EXPLICIT, NOT SEARCHED. terrain_slope.find_heightmap_dir refuses to fall
# through when this is set and wrong, so the campaign cannot silently measure a
# different checkout's terrain and report it under this one's git commit.
export SELENE_TERRAIN_HEIGHTMAPS="$HEIGHTMAPS"

for f in "$WORLD" "$HEIGHTMAPS/terrain_datum.json"; do
    [ -f "$f" ] || { echo "ERROR: missing $f" >&2; exit 3; }
done

mkdir -p "$WORKDIR" || { echo "ERROR: cannot create $WORKDIR" >&2; exit 3; }
PLAN_JSON="$WORKDIR/plan.json"
PLAN_TSV="$WORKDIR/plan.tsv"
RECORDS="$WORKDIR/records.tsv"
: > "$RECORDS"

# ---------------------------------------------------------------------------
# SENSOR-STRIPPED SPAWN MODELS, and why this campaign needs them.
#
# MEASURED on this host, 2026-08-01, ROS 2 Jazzy / gz-sim 8.11.0 on WSL2: a
# server-only `gz sim -s` segfaulted partway through the first robot's trials,
# every trial after it recording "no pose after spawn". The stack is entirely in
# the RENDERING path and has nothing to do with locomotion or terrain:
#
#   Sensors::CreateSensor -> DepthCameraSensor::SetScene
#     -> Ogre2DepthCamera::CreateDepthTexture -> CompositorManager2::addWorkspace
#     -> Ogre2DepthCamera::CreateWorkspaceInstance
#     -> Ogre::HlmsDatablock::_unlinkRenderable -> SIGSEGV
#
# `gz sim -s` still loads the sensors system, and each robot model declares a
# `depth_camera` (models/<type>/model.sdf:46). Creating its depth texture needs a
# real GL context; under WSL2's software rasteriser Ogre2 dies. This is NOT the
# D-37 ODE abort -- that one aborts in dxHashSpace::collide with an assertion,
# and this one segfaults in Ogre with no physics on the stack at all. Do not
# conflate them in the register.
#
# So spawn a copy with every <sensor> element removed. This is safe for what this
# campaign measures and the reasoning is worth stating rather than assuming:
# the sensors are massless, they declare no <collision>, and neither is consumed
# by anything -- `sensors/depth` and `sensors/imu` are bridged by
# selene_sim/launch/spawn_robot.launch.py:58-59 and have ZERO subscribers
# repo-wide, which is the register's own "Open items carried forward" item 11.
# Removing them cannot change wheel-terrain contact, mass, inertia or friction,
# which are the only things a slope measurement depends on.
#
# It is DISCLOSED in the limitations block and in the JSON artefact, because a
# campaign that quietly measures a different model than the one the mission flies
# is exactly the kind of undisclosed substitution this repository exists to
# refuse. The stripped SDFs are kept in the work directory so the substitution
# can be diffed after the fact.
SPAWN_MODELS="$WORKDIR/models_nosensors"
mkdir -p "$SPAWN_MODELS"
strip_sensors() {
    # $1 = model directory name (scout / excavator / hauler)
    local src="$MODELS/$1/model.sdf"
    local dst="$SPAWN_MODELS/$1.sdf"
    python3 - "$src" "$dst" <<'PYSTRIP'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding='utf-8') as fh:
    text = fh.read()
stripped, n = re.subn(r'[ \t]*<sensor\b.*?</sensor>\s*', '', text, flags=re.S)
with open(dst, 'w', encoding='utf-8', newline='') as fh:
    fh.write(stripped)
print(n)
PYSTRIP
}
SENSORS_STRIPPED=0
for _md in scout excavator hauler; do
    if [ -f "$MODELS/$_md/model.sdf" ]; then
        _n="$(strip_sensors "$_md")"
        SENSORS_STRIPPED=$(( SENSORS_STRIPPED + _n ))
    fi
done
echo "  spawn models: $SENSORS_STRIPPED <sensor> element(s) removed -> $SPAWN_MODELS"
echo "                (rendering-only; see the SENSOR-STRIPPED note in this script)"

GIT_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY="clean"
if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    GIT_DIRTY="dirty"
fi
WS_COMMIT="$(git -C "$WS/src/selene" rev-parse HEAD 2>/dev/null || echo unknown)"
GZ_VERSION="$(gz sim --version 2>/dev/null | head -1 || echo unknown)"

# --------------------------------------------------------------- the plan
#
# Site selection is arithmetic on the committed heightmap and needs no
# simulator, so it happens once, up front, and is written out before anything
# is spawned. A campaign whose plan is only visible in its own stdout cannot be
# audited afterwards.

python3 - "$PLAN_JSON" "$PLAN_TSV" "$MODELS" "$SLOPE_ROBOTS" "$SLOPE_GRADES" \
         "$SLOPE_DIRECTIONS" "$DRIVE_SPEED" "$DRIVE_SECONDS" \
         "$GRADE_TOLERANCE_DEG" "$CORRIDOR_TOLERANCE_DEG" "$SITE_SEPARATION_M" \
         "$TERRAIN_MARGIN_M" "$SPAWN_CLEARANCE_M" <<'PY'
import json
import math
import os
import re
import sys

import numpy as np

from selene_agent.terrain_slope import SAMPLING_NATIVE, TerrainSlopeField

(plan_path, tsv_path, models_dir, robots_s, grades_s, directions_s, speed_s,
 secs_s, grade_tol_s, corridor_tol_s, separation_s, margin_s,
 clearance_s) = sys.argv[1:14]

robots = robots_s.split()
grades = [float(g) for g in grades_s.split()]
directions = directions_s.split()
speed, secs = float(speed_s), float(secs_s)
grade_tol, corridor_tol = float(grade_tol_s), float(corridor_tol_s)
separation, margin, clearance = (float(separation_s), float(margin_s),
                                 float(clearance_s))
drive_m = speed * secs

# The site is chosen on the VISUAL layer -- the terrain's true relief -- and the
# spawn height comes from the COLLISION layer, which is the surface gz-sim
# actually contacts. Two different questions, two explicit loads.
relief = TerrainSlopeField.load(layer='visual')
contact = TerrainSlopeField.load(layer='collision')

half = relief.world_size_m / 2.0 - margin
lattice = relief.resample(500, 500, 1.0, -250.0, -250.0)
slope_grid = np.asarray(lattice.slope_deg)


def chassis_length_m(model_dir):
    """First <box><size> in the model, which is base_link's collision box.

    scout 0.6 x 0.4 x 0.15, excavator 0.8 x 0.6 x 0.2, hauler 0.9 x 0.6 x 0.2.
    Half of the x extent is how far the chassis reaches ahead of its own
    origin, which is the term the spawn height needs on a slope.
    """
    path = os.path.join(models_dir, model_dir, 'model.sdf')
    with open(path) as handle:
        text = handle.read()
    found = re.search(r'<box>\s*<size>\s*([\d.]+)', text)
    if not found:
        raise SystemExit(f'ERROR: no <box><size> in {path}')
    return float(found.group(1))


def corridor(x, y, azimuth):
    """Grade statistics along the drive, and whether it stays on the terrain."""
    profile = relief.profile_along(x, y, azimuth, drive_m, step_m=0.5)
    on_terrain = bool(np.all(np.abs(profile['x']) <= half)
                      and np.all(np.abs(profile['y']) <= half))
    return profile, on_terrain


# ONE SITE PER (grade, direction), SHARED BY EVERY ROBOT TYPE. The site is a
# property of the ground, not of the vehicle, and sharing it makes the three
# vehicles a controlled comparison on identical terrain instead of three
# separate experiments. Only the spawn height differs, because only the chassis
# does. The server is restarted between robot types, so one entity is ever in
# the world at a time and a shared site cannot collide with anything.
#: Hard cap on corridor evaluations per (grade, direction), so a target with
#: thousands of near-miss cells cannot make planning unbounded.
MAX_CANDIDATES = 1200
#: Stop looking once this many acceptable sites have been scored; the best of
#: them is taken. More than this buys nothing measurable.
ENOUGH_CANDIDATES = 40

sites = {}
chosen = []
for target in grades:
    for direction in directions:
        deviation = np.abs(slope_grid - target)
        flat_order = np.argsort(deviation, axis=None)[:MAX_CANDIDATES]
        best = None
        seen = 0
        within_tolerance = 0
        rejected_corridor = 0
        rejected_edge = 0
        rejected_separation = 0
        tightest_rejected = None
        for flat in flat_order:
            gy, gx = int(flat // 500), int(flat % 500)
            if float(deviation[gy, gx]) > grade_tol:
                break
            within_tolerance += 1
            wx, wy = lattice.grid_to_world(gx, gy)
            if abs(wx) > half or abs(wy) > half:
                rejected_edge += 1
                continue
            if any(math.hypot(wx - px, wy - py) < separation
                   for px, py in chosen):
                rejected_separation += 1
                continue
            uphill = relief.uphill_azimuth_rad_native(wx, wy)
            azimuth = uphill if direction == 'ascent' else uphill + math.pi
            profile, on_terrain = corridor(wx, wy, azimuth)
            if not on_terrain:
                rejected_edge += 1
                continue
            # Scored on the WHOLE corridor, not on the cell. A cell that reads
            # the target exactly and flattens two metres later measures
            # nothing, and ranking by the cell alone picked exactly those.
            spread = float(np.max(np.abs(profile['slope_deg'] - target)))
            if spread > corridor_tol:
                rejected_corridor += 1
                if tightest_rejected is None or spread < tightest_rejected:
                    tightest_rejected = spread
                continue
            if best is None or spread < best['spread']:
                best = dict(x=wx, y=wy, azimuth=azimuth, uphill=uphill,
                            spread=spread,
                            site_grade=float(relief.slope_deg_native(wx, wy)),
                            corridor_mean=float(np.mean(profile['slope_deg'])),
                            corridor_min=float(np.min(profile['slope_deg'])),
                            corridor_max=float(np.max(profile['slope_deg'])),
                            rise=float(profile['elevation_m'][-1]
                                       - profile['elevation_m'][0]))
            seen += 1
            if seen >= ENOUGH_CANDIDATES:
                break
        if best is not None:
            chosen.append((best['x'], best['y']))
        nearest_flat = int(np.argmin(deviation))
        sites[(target, direction)] = dict(
            best=best,
            nearest_available_grade_deg=float(
                slope_grid[nearest_flat // 500, nearest_flat % 500]),
            candidates_within_grade_tolerance=within_tolerance,
            rejected_by_corridor=rejected_corridor,
            rejected_by_terrain_edge=rejected_edge,
            rejected_by_site_separation=rejected_separation,
            tightest_rejected_corridor_spread_deg=tightest_rejected,
            candidate_scan_capped=(within_tolerance >= MAX_CANDIDATES))

trials = []
rows = []
for robot in robots:
    length = chassis_length_m(robot)
    for target in grades:
        for direction in directions:
            info = sites[(target, direction)]
            best = info['best']
            tag = f'{robot}_g{int(round(target)):02d}_' \
                  f'{"up" if direction == "ascent" else "dn"}'
            if best is None:
                # SAID, NOT SUBSTITUTED, AND WITH THE REASON. A target with no
                # site is reported as having no site. The counts below say
                # WHICH rule refused it -- "no ground near 40 deg" and "plenty
                # of 40 deg ground, none of it 4.8 m long" are different facts
                # about the world and only one of them is about the grade.
                trials.append(dict(
                    trial_id=tag, robot=robot, target_grade_deg=target,
                    direction=direction, status='no_site',
                    nearest_available_grade_deg=info[
                        'nearest_available_grade_deg'],
                    candidates_within_grade_tolerance=info[
                        'candidates_within_grade_tolerance'],
                    rejected_by_corridor=info['rejected_by_corridor'],
                    rejected_by_terrain_edge=info['rejected_by_terrain_edge'],
                    rejected_by_site_separation=info[
                        'rejected_by_site_separation'],
                    tightest_rejected_corridor_spread_deg=info[
                        'tightest_rejected_corridor_spread_deg'],
                    candidate_scan_capped=info['candidate_scan_capped'],
                    note=(
                        f"{info['candidates_within_grade_tolerance']} cells lie "
                        f"within {grade_tol} deg of {target} deg (nearest grade "
                        f"on the map {info['nearest_available_grade_deg']:.2f} "
                        f"deg), but none gave a usable site: "
                        f"{info['rejected_by_corridor']} did not hold the grade "
                        f"to {corridor_tol} deg over the {drive_m:.2f} m "
                        f"corridor"
                        + (f" (tightest was "
                           f"{info['tightest_rejected_corridor_spread_deg']:.2f}"
                           f" deg)"
                           if info['tightest_rejected_corridor_spread_deg']
                           is not None else "")
                        + f", {info['rejected_by_terrain_edge']} ran outside "
                        f"the {margin} m terrain margin, "
                        f"{info['rejected_by_site_separation']} were within "
                        f"{separation} m of another site")))
                rows.append('\t'.join([tag, robot, robot, f'{target}',
                                       direction, 'no_site'] + ['0'] * 10))
                continue

            # SPAWN HEIGHT, term by term:
            #   collision-map elevation at the site  -- the surface gz contacts
            # + 0.30 m                               -- spawn_positions.yaml:26
            # + (chassis half-length) * tan(grade)   -- an axis-aligned body is
            #   created level, so the ground under its leading edge is this
            #   much higher than the ground under its origin. Without it a
            #   40 deg trial spawns its own nose inside the hill.
            # A KNOWN SHORTFALL, disclosed rather than tuned away:
            # spawn_positions.yaml:78-84 records that a bilinear read of the
            # collision PNG under-predicts the probe-MEASURED surface by
            # 0.026 m on flat ground and 0.209 m on the steepest surveyed
            # point, because a body rests tangent to a sloped cell. This
            # campaign cannot run a probe, so it does not pretend to correct
            # for that; a burial is detected and reported as an APPARATUS
            # failure rather than scored as a slope the robot could not climb.
            terrain_z = contact.elevation_native_m(best['x'], best['y'])
            allowance = (length / 2.0) * math.tan(math.radians(
                min(best['corridor_max'], 60.0)))
            spawn_z = terrain_z + clearance + allowance
            yaw = math.atan2(math.sin(best['azimuth']), math.cos(best['azimuth']))
            trials.append(dict(
                trial_id=tag, robot=robot, target_grade_deg=target,
                direction=direction, status='planned',
                site_x=best['x'], site_y=best['y'],
                site_grade_deg=best['site_grade'],
                site_grade_sampling=SAMPLING_NATIVE,
                corridor_mean_deg=best['corridor_mean'],
                corridor_min_deg=best['corridor_min'],
                corridor_max_deg=best['corridor_max'],
                corridor_rise_m=best['rise'],
                uphill_azimuth_rad=best['uphill'],
                commanded_yaw_rad=yaw,
                terrain_z_m=terrain_z,
                spawn_z_m=spawn_z,
                spawn_clearance_m=clearance,
                spawn_slope_allowance_m=allowance,
                chassis_length_m=length))
            rows.append('\t'.join([
                tag, robot, robot, f'{target}', direction, 'planned',
                f'{best["x"]:.6f}', f'{best["y"]:.6f}', f'{spawn_z:.6f}',
                f'{yaw:.9f}', f'{math.sin(yaw / 2.0):.12f}',
                f'{math.cos(yaw / 2.0):.12f}', f'{best["site_grade"]:.4f}',
                f'{best["corridor_mean"]:.4f}', f'{best["corridor_min"]:.4f}',
                f'{best["corridor_max"]:.4f}']))

# The crater exit, recomputed here so the verdict can be read against the wall
# the mission actually has to cross. NAME THE METHOD: this is the 2-D native
# gradient magnitude, minimised over 72 azimuths, and it gives 34.03 deg.
# selene_sim/test/test_mission_traversability.py's radial 1-D derivative over
# the same azimuths gives 34.09, which is the figure the register quotes. The
# two are different measures of one wall and agree to 0.06 deg; see
# selene_agent/test/test_terrain_slope_field.py, which pins both.
cx, cy = -100.0, -150.0
radii = np.arange(0.0, 95.0, 0.5)
gentlest = 90.0
for k in range(72):
    az = 2.0 * math.pi * k / 72.0
    gentlest = min(gentlest, max(
        relief.slope_deg_native(cx + r * math.cos(az), cy + r * math.sin(az))
        for r in radii))

plan = dict(
    params=dict(robots=robots, grades_deg=grades, directions=directions,
                drive_speed_mps=speed, drive_sim_seconds=secs,
                commanded_distance_m=drive_m,
                grade_tolerance_deg=grade_tol,
                corridor_tolerance_deg=corridor_tol,
                site_separation_m=separation, terrain_margin_m=margin,
                spawn_clearance_m=clearance,
                site_sampling=SAMPLING_NATIVE),
    terrain=dict(relief=relief.source, contact=contact.source,
                 effective_baseline_m=relief.effective_baseline_m,
                 requested_baseline_m=relief.requested_baseline_m,
                 gentlest_crater_exit_deg=gentlest,
                 gentlest_crater_exit_azimuths=72,
                 gentlest_crater_exit_sampling=SAMPLING_NATIVE,
                 gentlest_crater_exit_method=(
                     '2-D native gradient magnitude, max over each azimuth, '
                     'min over 72 azimuths. The radial 1-D derivative used by '
                     'selene_sim/test/test_mission_traversability.py gives '
                     '34.09 deg on the same terrain.')),
    trials=trials)
with open(plan_path, 'w') as handle:
    json.dump(plan, handle, indent=2)
    handle.write('\n')
with open(tsv_path, 'w') as handle:
    handle.write('\n'.join(rows) + ('\n' if rows else ''))

planned = sum(1 for t in trials if t['status'] == 'planned')
print(f'  planned {planned} of {len(trials)} trials '
      f'({len(trials) - planned} with no suitable site)')
print(f'  terrain: {os.path.basename(relief.source["image"])} for site choice, '
      f'{os.path.basename(contact.source["image"])} for spawn height')
print(f'  gentlest crater exit over 72 azimuths: {gentlest:.2f} deg '
      f'(2-D native; the gate\'s radial method gives 34.09)')
for (target, direction), info in sorted(sites.items()):
    if info['best'] is None:
        print(f'  NO SITE for {target:.0f} deg {direction}: '
              f"{info['candidates_within_grade_tolerance']} candidate cells, "
              f"{info['rejected_by_corridor']} rejected on corridor spread")
PY
PLAN_RC=$?
if [ "$PLAN_RC" -ne 0 ] || [ ! -f "$PLAN_TSV" ]; then
    echo "ERROR: site planning failed (rc $PLAN_RC). Is selene_agent built into" >&2
    echo "       $WS and is numpy available to python3?" >&2
    exit 3
fi

TRIAL_TOTAL=$(grep -c . "$PLAN_TSV" 2>/dev/null || echo 0)

echo ""
echo "SELENE slope capability campaign"
echo "  workspace:  $WS"
echo "  world:      $WORLD"
echo "  robots:     $SLOPE_ROBOTS"
echo "  grades:     $SLOPE_GRADES  (degrees)"
echo "  directions: $SLOPE_DIRECTIONS"
echo "  command:    linear.x=$DRIVE_SPEED for ${DRIVE_SECONDS}s of SIM time"
echo "  artefact:   $SLOPE_JSON"
echo "  trials:     $TRIAL_TOTAL  (budget ~40 s each plus ~35 s per robot type)"
if [ "$(printf '%s\n' "$SLOPE_ROBOTS" | wc -w)" -lt 3 ]; then
    echo ""
    echo "  *** ONE-VEHICLE-SUBSET CAMPAIGN: '$SLOPE_ROBOTS'. Any limit derived"
    echo "  *** from this run applies to the type(s) measured and to nothing"
    echo "  *** else. The excavator and hauler are heavier than the scout and"
    echo "  *** already slip differently on FLAT ground (check_drive.sh"
    echo "  *** baselines: excavator +1.04%, scout -0.80%). Re-run with"
    echo "  *** SLOPE_ROBOTS='scout excavator hauler' before committing a"
    echo "  *** fleet-wide constant."
fi
echo ""

# ------------------------------------------------------------ gz plumbing

GZ_PID=""
GZ_LOG="$WORKDIR/gz_server.log"

# Kill ONLY the server this script started. Never pattern-match on "gz sim" or
# on the world file name — lunar_psr.sdf is the world everyone else runs too,
# and a broad pkill here would take down a developer's session (and, because
# the pattern matches its own command line, this script).
stop_gz() {
    [ -n "$GZ_PID" ] || return 0
    kill -TERM "$GZ_PID" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "$GZ_PID" 2>/dev/null || { GZ_PID=""; return 0; }
        sleep 0.5
    done
    kill -KILL "$GZ_PID" 2>/dev/null
    GZ_PID=""
    return 0
}
# The signal traps EXIT EXPLICITLY, and INT/TERM exit rather than resuming.
# `trap stop_gz EXIT INT TERM` with a handler that ends in `return 0` does NOT
# stop the script: the handler runs and execution RESUMES, which is how
# check_terrain.sh once printed PASS after a SIGTERM tore its server down.
trap stop_gz EXIT
trap 'stop_gz; exit 130' INT
trap 'stop_gz; exit 143' TERM

start_gz() {
    # Start PAUSED so the heightmap collision mesh is complete before anything
    # is spawned or stepped, then unpause and spawn into a running world —
    # which is what simulation.launch.py's `create` nodes do.
    gz sim -s -v 1 "$WORLD" >> "$GZ_LOG" 2>&1 &
    GZ_PID=$!
    # CARRY THE POLL'S RESULT; DO NOT RE-QUERY. A second independent `gz topic
    # -l | grep -q` deciding the verdict reported "world never appeared" about
    # a world the loop had just matched (check_drive.sh:288-295).
    local up=0
    for _ in $(seq 1 60); do
        if gz topic -l 2>/dev/null | grep -q "/world/$WORLD_NAME/"; then
            up=1
            break
        fi
        sleep 0.5
    done
    if [ "$up" -ne 1 ]; then
        echo "FAIL: world $WORLD_NAME never appeared. See $GZ_LOG" >&2
        return 1
    fi
    sleep "$HEIGHTMAP_LOAD_SECONDS"
    gz service -s "/world/$WORLD_NAME/control" --reqtype gz.msgs.WorldControl \
        --reptype gz.msgs.Boolean --timeout 5000 --req 'pause: false' \
        >/dev/null 2>&1 || {
            echo "FAIL: could not unpause $WORLD_NAME" >&2
            return 1
        }
    sleep 2
    return 0
}

pose() {   # authoritative model pose: x y z roll pitch yaw, one number per line
    gz model -m "$1" -p 2>/dev/null \
        | tr -d '[]' | tr -s ' ' | awk '/^ *-?[0-9]/{print}'
}
odom() {   # DiffDrive odometry position, as "x y"
    timeout 8 gz topic -e -t "/model/$1/odometry" -n 1 2>/dev/null | python3 -c '
import re, sys
m = re.search(r"pose\s*\{.*?position\s*\{(.*?)\}", sys.stdin.read(), re.S)
f = dict(re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", m.group(1))) if m else {}
print(f.get("x", "nan"), f.get("y", "nan"))'
}
sim_ms() {  # simulation time in integer milliseconds; empty if unreadable
    timeout 8 gz topic -e -t "/world/$WORLD_NAME/stats" -n 1 2>/dev/null | python3 -c '
import re, sys
m = re.search(r"sim_time\s*\{(.*?)\}", sys.stdin.read(), re.S)
if m:
    d = dict(re.findall(r"(sec|nsec):\s*(\d+)", m.group(1)))
    print(int(d.get("sec", 0)) * 1000 + int(d.get("nsec", 0)) // 1000000)'
}
rtf() {     # real-time factor the server is actually achieving
    timeout 8 gz topic -e -t "/world/$WORLD_NAME/stats" -n 1 2>/dev/null | python3 -c '
import re, sys
m = re.search(r"real_time_factor:\s*([\d.eE+-]+)", sys.stdin.read())
print(round(float(m.group(1)), 4) if m else "nan")'
}

# DRIVE FOR A DURATION IN *SIMULATION* TIME AND REPORT WHAT IT GOT.
# Bounding a sim-time target with wall clock is check_drive.sh's single most
# likely way to go red for a reason unrelated to terrain: lunar_psr.sdf caps the
# server at real_time_factor 1.0, so at factor r a 12 s wall drive covers 12*r
# seconds of sim time and r times the distance while the acceptance floor stays
# at 70% of the full command. So: loop until the requested SIM seconds elapse
# and echo the sim seconds actually covered, and let the caller judge against
# that. The wall cap only stops a stalled server hanging the campaign, and
# hitting it warns rather than being silently tolerated.
drive() {  # $1 entity, $2 twist, $3 sim seconds; echoes sim seconds covered
    local entity="$1" twist="$2" secs="$3" t0 now wall_end i=0 s
    t0=$(sim_ms)
    if [ -z "$t0" ]; then
        echo "0.0"
        return 1
    fi
    wall_end=$(( $(date +%s) + secs * DRIVE_WALL_CAP + 15 ))
    now=$t0
    while [ $(( now - t0 )) -lt $(( secs * 1000 )) ]; do
        gz topic -t "/model/$entity/cmd_vel" -m gz.msgs.Twist -p "$twist" \
            >/dev/null 2>&1
        i=$(( i + 1 ))
        # One stats read costs ~88 ms, about the same as one publish, so
        # sampling every 5th iteration keeps the cmd_vel stream dense without
        # doubling the loop cost.
        if [ $(( i % 5 )) -eq 0 ]; then
            s=$(sim_ms)
            [ -n "$s" ] && now=$s
            if [ "$(date +%s)" -ge "$wall_end" ]; then
                echo "  WARNING: wall-clock cap reached after $(( now - t0 )) ms" >&2
                echo "           of sim time (wanted $(( secs * 1000 )) ms)." >&2
                break
            fi
        fi
    done
    python3 -c "print(($now - $t0) / 1000.0)"
}

record() {  # trial_id outcome sim_secs rtf p0 p1 o0 o1
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" >> "$RECORDS"
}

# ------------------------------------------------------------ the campaign

CURRENT_ROBOT=""
TRIAL_N=0
while IFS=$'\t' read -r TID ROBOT MODEL_DIR TARGET DIRECTION STATUS SX SY SZ \
                        YAW QZ QW SGRADE CMEAN CMIN CMAX; do
    TRIAL_N=$(( TRIAL_N + 1 ))
    if [ "$STATUS" != "planned" ]; then
        printf '[%s/%s] %s: NO SITE - target %s deg is not available on this ' \
            "$TRIAL_N" "$TRIAL_TOTAL" "$TID" "$TARGET"
        printf 'terrain under the corridor and separation rules. NOT TESTED.\n'
        record "$TID" no_site 0 nan "" "" "" ""
        continue
    fi
    if [ "$ROBOT" != "$CURRENT_ROBOT" ]; then
        stop_gz
        echo ""
        echo "--- bringing up $WORLD_NAME for '$ROBOT' ---"
        if ! start_gz; then
            echo "ERROR: could not start a world for '$ROBOT'; abandoning the" >&2
            echo "       campaign. Everything measured so far is in $RECORDS." >&2
            exit 3
        fi
        CURRENT_ROBOT="$ROBOT"
    fi

    # The sensor-stripped copy, not models/<type>/model.sdf -- see the
    # SENSOR-STRIPPED note near the top. Falls back to the real model if the
    # strip did not produce a file, so a stripping failure is loud (the Ogre
    # segfault returns) rather than silently measuring nothing.
    MODEL_SDF="$SPAWN_MODELS/$MODEL_DIR.sdf"
    [ -f "$MODEL_SDF" ] || MODEL_SDF="$MODELS/$MODEL_DIR/model.sdf"
    ENTITY="probe_$TID"
    printf '[%s/%s] %s: target %s deg %s at (%s, %s) yaw %s\n' \
        "$TRIAL_N" "$TRIAL_TOTAL" "$TID" "$TARGET" "$DIRECTION" "$SX" "$SY" "$YAW"
    printf '    site %s deg, corridor %s..%s deg (mean %s), spawn z %s\n' \
        "$SGRADE" "$CMIN" "$CMAX" "$CMEAN" "$SZ"

    if ! gz service -s "/world/$WORLD_NAME/create" --reqtype gz.msgs.EntityFactory \
        --reptype gz.msgs.Boolean --timeout 10000 \
        --req "sdf_filename: \"$MODEL_SDF\", name: \"$ENTITY\", pose: {position: {x: $SX, y: $SY, z: $SZ}, orientation: {x: 0, y: 0, z: $QZ, w: $QW}}" \
        >/dev/null 2>&1; then
        echo "    spawn service call FAILED — recorded as apparatus failure"
        record "$TID" spawn_failed 0 nan "" "" "" ""
        continue
    fi
    sleep "$SETTLE_SECONDS"

    P0=$(pose "$ENTITY" | tr '\n' ' ')
    if [ -z "${P0// /}" ]; then
        echo "    no pose after spawn — recorded as apparatus failure"
        record "$TID" no_pose 0 nan "" "" "" ""
        continue
    fi
    O0=$(odom "$ENTITY")
    TRIAL_RTF=$(rtf)
    SIM_SECS=$(drive "$ENTITY" "linear: {x: $DRIVE_SPEED}" "$DRIVE_SECONDS")
    gz topic -t "/model/$ENTITY/cmd_vel" -m gz.msgs.Twist \
        -p 'linear: {x: 0.0}, angular: {z: 0.0}' >/dev/null 2>&1
    sleep 1
    P1=$(pose "$ENTITY" | tr '\n' ' ')
    O1=$(odom "$ENTITY")
    record "$TID" measured "$SIM_SECS" "$TRIAL_RTF" "$P0" "$P1" "$O0" "$O1"

    # Remove the entity so the next trial starts from a world with one robot in
    # it. Sites for successive trials are at least SITE_SEPARATION_M apart, so
    # a removal that silently fails cannot put a leftover in the next path.
    gz service -s "/world/$WORLD_NAME/remove" --reqtype gz.msgs.Entity \
        --reptype gz.msgs.Boolean --timeout 5000 \
        --req "name: \"$ENTITY\", type: MODEL" >/dev/null 2>&1
    sleep 1
done < "$PLAN_TSV"

stop_gz

# ------------------------------------------------------------- the verdict

echo ""
python3 - "$PLAN_JSON" "$RECORDS" "$SLOPE_JSON" "$MIN_FRACTION" \
         "$MAX_FRACTION" "$MAX_SLIP_PCT" "$GIT_COMMIT" "$GIT_DIRTY" \
         "$WS_COMMIT" "$GZ_VERSION" "$WORLD" "${ROS_DISTRO:-unknown}" <<'PY'
import hashlib
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone

(plan_path, records_path, out_path, min_frac_s, max_frac_s, max_slip_s,
 git_commit, git_dirty, ws_commit, gz_version, world_path,
 ros_distro) = sys.argv[1:13]

min_frac, max_frac, max_slip = (float(min_frac_s), float(max_frac_s),
                                float(max_slip_s))
with open(plan_path) as handle:
    plan = json.load(handle)
params = plan['params']
commanded_speed = params['drive_speed_mps']

records = {}
with open(records_path) as handle:
    for line in handle:
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 8:
            continue
        records[parts[0]] = parts


def numbers(text):
    out = []
    for token in text.split():
        try:
            out.append(float(token))
        except ValueError:
            return None
    return out


def sha256(path):
    try:
        with open(path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


results = []
for trial in plan['trials']:
    row = dict(trial)
    record = records.get(trial['trial_id'])
    if trial['status'] == 'no_site':
        row['outcome'] = 'no_site'
        results.append(row)
        continue
    if record is None:
        # NEVER TESTED is its own outcome and is never folded into a failure.
        row['outcome'] = 'not_tested'
        row['note'] = ('the campaign did not reach this trial; no measurement '
                       'was taken and none is implied')
        results.append(row)
        continue

    outcome = record[1]
    row['sim_seconds'] = float(record[2]) if numbers(record[2]) else 0.0
    row['real_time_factor'] = (float(record[3])
                               if numbers(record[3]) else float('nan'))
    if outcome != 'measured':
        row['outcome'] = outcome
        row['note'] = 'apparatus failure, not a slope result'
        results.append(row)
        continue

    p0, p1 = numbers(record[4]), numbers(record[5])
    o0, o1 = numbers(record[6]), numbers(record[7])
    if not p0 or not p1 or len(p0) < 6 or len(p1) < 6:
        row['outcome'] = 'no_pose'
        row['note'] = 'apparatus failure, not a slope result'
        results.append(row)
        continue

    commanded = commanded_speed * row['sim_seconds']
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    world = math.hypot(dx, dy)
    yaw = trial['commanded_yaw_rad']
    # THE COMPONENT ALONG THE COMMANDED HEADING is the governing quantity here,
    # where check_drive.sh uses total displacement. On flat ground the two are
    # the same to within a degree of heading error; on a 40 deg wall a robot
    # that slides sideways travels distance without climbing, and the
    # projection refuses to call that progress. It is strictly the more
    # conservative of the two and both are reported.
    along = dx * math.cos(yaw) + dy * math.sin(yaw)
    odo = math.hypot(o1[0] - o0[0], o1[1] - o0[1]) if o0 and o1 else float('nan')
    slip = (100.0 * (1.0 - world / odo)
            if odo == odo and odo > 1e-6 else float('nan'))
    fraction = along / commanded if commanded > 1e-9 else 0.0
    total_fraction = world / commanded if commanded > 1e-9 else 0.0

    row.update(dict(
        commanded_distance_m=commanded,
        world_displacement_m=world,
        along_heading_m=along,
        fraction_of_command=fraction,
        total_fraction_of_command=total_fraction,
        odometry_m=odo,
        slip_pct=slip,
        elevation_change_m=dz,
        achieved_grade_deg=(math.degrees(math.atan2(dz, world))
                            if world > 1e-6 else float('nan')),
        settled_z_m=p0[2], spawn_z_m=trial['spawn_z_m'],
        settle_delta_m=p0[2] - trial['spawn_z_m'],
        roll_rad=p1[3], pitch_rad=p1[4], final_yaw_rad=p1[5]))

    reasons = []
    # A robot created inside the heightfield does not fall; it is extruded
    # upward at ~1 mm/s, so its settled z rises ABOVE the z it was created at.
    # That is an unambiguous burial signature (check_drive.sh:27-33) and it is
    # an APPARATUS failure: it says the spawn height was wrong, not that the
    # vehicle could not climb.
    if p0[2] > trial['spawn_z_m']:
        row['outcome'] = 'buried'
        row['note'] = (f"settled z {p0[2]:.4f} is above spawn z "
                       f"{trial['spawn_z_m']:.4f}; the body was created inside "
                       f"the collision surface. Apparatus failure -- raise "
                       f"SPAWN_CLEARANCE_M and re-run this trial.")
        results.append(row)
        continue
    if abs(p1[3]) > 1.2:
        row['outcome'] = 'tumbled'
        row['note'] = (f'final roll {p1[3]:+.3f} rad; the vehicle turned over. '
                       f'Recorded separately from a traction failure because it '
                       f'is a different limit and this campaign does not '
                       f'measure the side-slope one.')
        results.append(row)
        continue

    if fraction < min_frac:
        reasons.append(f'along-heading {along:.3f} m is under {min_frac:.0%} of '
                       f'the commanded {commanded:.3f} m')
    if total_fraction > max_frac:
        reasons.append(f'world displacement {world:.3f} m exceeds '
                       f'{max_frac:.0%} of command -- sliding, not driving')
    if slip == slip and abs(slip) > max_slip:
        reasons.append(f'slip {slip:.1f}% exceeds {max_slip:.0f}%')
    row['outcome'] = 'fail' if reasons else 'pass'
    row['failure_reasons'] = reasons
    results.append(row)

# ------------------------------------------------------------------- table
# EVERY OUTCOME APPEARS, and the four kinds are visibly different words: PASS
# and FAIL are measurements, NO_SITE and NOT_TESTED are absences, BURIED and
# TUMBLED are the apparatus failing rather than the vehicle. A table that
# printed only the grades that produced a number would read as a clean sweep.
header = (f"{'trial':<20}{'tgt':>5}{'site':>7}{'corridor':>14}{'cmd':>7}"
          f"{'along':>8}{'frac':>7}{'slip%':>8}{'dz':>8}  outcome")
print(header)
print('-' * len(header))
notes = []
for row in results:
    site = row.get('site_grade_deg')
    corridor = (f"{row['corridor_min_deg']:.1f}-{row['corridor_max_deg']:.1f}"
                if 'corridor_min_deg' in row else '')
    print(f"{row['trial_id']:<20}"
          f"{row['target_grade_deg']:>5.0f}"
          f"{(f'{site:.1f}' if site is not None else '-'):>7}"
          f"{corridor:>14}"
          f"{row.get('commanded_distance_m', float('nan')):>7.2f}"
          f"{row.get('along_heading_m', float('nan')):>8.3f}"
          f"{row.get('fraction_of_command', float('nan')):>7.2f}"
          f"{row.get('slip_pct', float('nan')):>8.1f}"
          f"{row.get('elevation_change_m', float('nan')):>8.3f}"
          f"  {row['outcome'].upper()}")
    if row.get('note'):
        notes.append((row['trial_id'], row['outcome'], row['note']))
    if row.get('failure_reasons'):
        notes.append((row['trial_id'], row['outcome'],
                      '; '.join(row['failure_reasons'])))

if notes:
    print('')
    print('WHY, for every trial that did not simply pass:')
    seen_notes = set()
    for trial_id, outcome, note in notes:
        key = (outcome, note)
        if key in seen_notes:
            print(f'  {trial_id:<20} {outcome.upper()}: as above')
            continue
        seen_notes.add(key)
        print(f'  {trial_id:<20} {outcome.upper()}: {note}')

# ----------------------------------------------------------------- verdict
verdict = {}
for robot in params['robots']:
    for direction in params['directions']:
        subset = [r for r in results
                  if r['robot'] == robot and r['direction'] == direction]
        passed = sorted(r['target_grade_deg'] for r in subset
                        if r['outcome'] == 'pass')
        failed = sorted(r['target_grade_deg'] for r in subset
                        if r['outcome'] == 'fail')
        unmeasured = sorted(r['target_grade_deg'] for r in subset
                            if r['outcome'] not in ('pass', 'fail'))
        entry = dict(
            steepest_passing_deg=(passed[-1] if passed else None),
            gentlest_failing_deg=(failed[0] if failed else None),
            passed_deg=passed, failed_deg=failed, unmeasured_deg=unmeasured,
            monotonic=(not (passed and failed and passed[-1] > failed[0])))
        verdict[f'{robot}/{direction}'] = entry

print('')
print('=' * 78)
print('VERDICT -- steepest grade still achieving '
      f'{min_frac:.0%} of command at under {max_slip:.0f}% slip')
print('=' * 78)
for key in sorted(verdict):
    entry = verdict[key]
    steepest = entry['steepest_passing_deg']
    gentlest = entry['gentlest_failing_deg']
    print(f"  {key:<22} passed up to "
          f"{('%.0f deg' % steepest) if steepest is not None else 'NOTHING':>10}"
          f"   first failure at "
          f"{('%.0f deg' % gentlest) if gentlest is not None else 'none seen':>10}")
    if entry['unmeasured_deg']:
        print(f"  {'':<22} NOT MEASURED at: "
              f"{', '.join('%.0f' % g for g in entry['unmeasured_deg'])} deg -- "
              f"absent from the sweep, not passed")
    if not entry['monotonic']:
        print(f"  {'':<22} *** NON-MONOTONIC: a steeper grade passed than one "
              f"that failed. Treat the FIRST failure as the limit.")

directional = {}
for direction in params['directions']:
    values = [verdict[k]['steepest_passing_deg'] for k in verdict
              if k.endswith('/' + direction)
              and verdict[k]['steepest_passing_deg'] is not None]
    directional[direction] = min(values) if values else None

print('')
governing = [v for v in directional.values() if v is not None]
for direction, value in sorted(directional.items()):
    print(f"  worst case across the measured vehicles, {direction}: "
          + (f'{value:.0f} deg' if value is not None else 'NOTHING PASSED'))
print('')
if len(directional) > 1 and governing:
    limit = min(governing)
    print("  A MISSION THAT NEEDS ROUND TRIPS IS GOVERNED BY THE MORE")
    print(f"  RESTRICTIVE OF THE TWO DIRECTIONS: {limit:.0f} deg.")
    print( "  Ascent and descent are not the same experiment -- a vehicle that")
    print( "  climbs a grade under power can still lose it coming down, and the")
    print( "  crater the mission has to enter must also be left.")
else:
    print("  ONLY ONE DIRECTION WAS SWEPT, so no round-trip limit can be")
    print("  stated. Run with SLOPE_DIRECTIONS='ascent descent'.")

exit_grade = plan['terrain']['gentlest_crater_exit_deg']
print('')
print(f"  The gentlest exit from the PSR crater is {exit_grade:.2f} deg "
      f"(72 azimuths).")
if governing and min(governing) < exit_grade:
    print(f"  THE MEASURED CAPABILITY IS BELOW THAT. A limit of "
          f"{min(governing):.0f} deg refuses every route between the plain and")
    print( "  the crater basin, which is where the depot and all four ice")
    print( "  deposits are. Enforcing this measurement would break the mission:")
    print( "  the fix is the terrain or the depot, NOT a larger constant.")
elif governing:
    print( "  The measured capability covers it, so enforcing the measurement")
    print( "  leaves the mission connected.")

# ------------------------------------------------------------ disclosures
limitations = [
    'The spawned model is a SENSOR-STRIPPED copy: every <sensor> element is '
    'removed before spawning, because gz sim -s segfaults in '
    'Ogre2DepthCamera::CreateDepthTexture on a host without a real GL context '
    '(MEASURED on WSL2 / gz-sim 8.11.0, 2026-08-01). The sensors are massless, '
    'declare no <collision>, and have zero subscribers repo-wide, so this '
    'cannot affect wheel-terrain contact -- but the vehicle measured is not '
    'byte-identical to the vehicle the mission flies, and the stripped SDFs '
    'are kept in the work directory so the substitution can be diffed.',
    'One straight run from rest of about '
    f'{params["commanded_distance_m"]:.1f} m, with an EMPTY vehicle. Sustained '
    'climbing, restarting on the grade and climbing under load are not '
    'measured.',
    'Straight up or straight down the local gradient only. The side-slope '
    'rollover limit -- usually the binding one on a real vehicle -- is NOT '
    'measured.',
    'No turning on the slope. check_drive.sh\'s turn assertion is deliberately '
    'not reproduced: a skid-steer scrubs badly and its yaw response says '
    'nothing about climbing.',
    'gz-sim/ODE physics with the shipped models\' own <surface> friction. The '
    'result transfers to this simulation and to nothing else.',
    'Sites are chosen on the 513-sample VISUAL heightmap; the robot contacts '
    'the 129-sample COLLISION decimation, which can only be smoother. The '
    'grade actually felt is therefore at most the grade reported.',
    'Spawn height is computed from the collision PNG plus a 0.30 m clearance '
    'and a chassis-length slope allowance. selene_sim/config/'
    'spawn_positions.yaml:78-84 records that a bilinear PNG read '
    'under-predicts the probe-measured surface by 0.026 m on flat ground and '
    '0.209 m on the steepest surveyed point; this campaign cannot run a probe '
    'and does not correct for it. A burial is reported as an APPARATUS '
    'failure, never as a grade the vehicle could not climb.',
    'Slope figures for site selection use terrain_slope\'s NATIVE sampling. '
    'The same points read up to 0.6 deg differently through the planning '
    'lattice, and up to 8.8 deg differently at the worst point on the map. A '
    'planner enforcing a limit acts on the lattice, not on these numbers.',
    'One trial per (robot, grade, direction). No repeats, so run-to-run spread '
    'is unmeasured and no confidence interval can be quoted.',
    'use_sim_time is set by nothing in SELENE. This script reads gz sim_time '
    'directly from /world/<world>/stats and does not depend on it.',
]
print('')
print('WHAT THIS CAMPAIGN DID NOT MEASURE')
for item in limitations:
    print(f'  - {item}')
if len(params['robots']) < 3:
    print('')
    print(f"  *** ONLY {', '.join(params['robots'])} WAS MEASURED. Any "
          f"fleet-wide constant taken from this run is an extrapolation.")

# ----------------------------------------------------------------- artefact
terrain = plan['terrain']
artefact = dict(
    schema='selene.slope_capability.v1',
    generated_utc=datetime.now(timezone.utc).isoformat(),
    provenance=dict(
        git_commit=git_commit, git_worktree=git_dirty,
        workspace_source_commit=ws_commit,
        gz_version=gz_version, ros_distro=ros_distro,
        host=platform.node(), platform=platform.platform(),
        world_file=world_path, world_sha256=sha256(world_path),
        relief_image=terrain['relief']['image'],
        relief_sha256=sha256(terrain['relief']['image']),
        contact_image=terrain['contact']['image'],
        contact_sha256=sha256(terrain['contact']['image']),
        terrain_datum=terrain['relief']['datum'],
        terrain_datum_sha256=sha256(terrain['relief']['datum']),
        terrain_seed=terrain['relief'].get('seed')),
    parameters=dict(params, min_fraction=min_frac, max_fraction=max_frac,
                    max_slip_pct=max_slip),
    terrain=terrain,
    real_time_factor=dict(
        observed=[r['real_time_factor'] for r in results
                  if isinstance(r.get('real_time_factor'), float)
                  and r['real_time_factor'] == r['real_time_factor']]),
    trials=results,
    verdict=dict(per_robot_direction=verdict,
                 worst_case_by_direction=directional,
                 governing_limit_deg=(min(governing) if governing else None),
                 governing_rule=('the more restrictive of ascent and descent, '
                                 'across every vehicle measured'),
                 gentlest_crater_exit_deg=exit_grade),
    limitations=limitations,
    counts=dict((outcome, sum(1 for r in results if r['outcome'] == outcome))
                for outcome in sorted({r['outcome'] for r in results})))

with open(out_path, 'w') as handle:
    json.dump(artefact, handle, indent=2, sort_keys=False)
    handle.write('\n')
print('')
print(f'  artefact: {out_path}  ({os.path.getsize(out_path)} bytes)')
print(f'  counts:   {artefact["counts"]}')

unmeasured = sum(count for outcome, count in artefact['counts'].items()
                 if outcome not in ('pass', 'fail'))
raise SystemExit(1 if unmeasured else 0)
PY
ANALYSIS_RC=$?

echo ""
echo "Gazebo log:  $GZ_LOG"
echo "Plan:        $PLAN_JSON"
echo "Raw records: $RECORDS"
if [ "$ANALYSIS_RC" -ne 0 ]; then
    echo ""
    echo "EXIT 1: at least one requested (robot, grade, direction) was NOT"
    echo "        measured. A measurement that was not taken is not a pass."
fi
exit "$ANALYSIS_RC"
