#!/bin/bash
# Terrain acceptance check — asserts the simulated ground is where the software
# thinks it is, by asking Gazebo instead of reading the heightmap.
#
# WHY THIS EXISTS
# Every SELENE consumer places things in world coordinates: robot spawns
# (selene_sim/config/spawn_positions.yaml), 26 rocks and the depot
# (selene_sim/worlds/lunar_psr.sdf), the PSR zone (selene_sim/config/
# world_params.yaml), the ice deposits (selene_sim/config/ice_deposits.yaml) and
# the dashboard overlay (selene_dashboard/src/utils/worldConfig.js). None of them
# can see the terrain. Two defects hid there for months:
#
#   1. The heightmap was written with inverted row order, so the PSR crater
#      rendered at (-100, +150) instead of (-100, -150).
#   2. Nothing compensated for the generator's elevation datum, so every robot,
#      rock and the depot originated metres below the surface.
#
# AND THIS GATE ITSELF CERTIFIED A BURIED SPAWN. Until 2026-07-29 its probes were
# free spheres: they landed, ROLLED DOWNHILL, and were read at the bottom of the
# slope, under-reporting the surface by up to 5 m. On that evidence a spawn z of
# 1.5 m was passed as clear at (-45,-92)/(-45,-105)/(-45,-112), where the true
# surfaces are 2.49 / 4.01 / 5.27 m. Every robot began inside the terrain, wheels
# spinning, odometry advancing, world displacement exactly zero. Probes are now
# pinned to a prismatic Z slide so they cannot move laterally, and the reading is
# the joint position rather than a settled body pose.
#
# None of this is visible from the configs, and none of it produces an error
# message — robots simply sit inside solid geometry with their wheels turning. So
# the check lowers a laterally-pinned probe onto every coordinate the software
# cares about and reads the slide joint's position. Gazebo is the external
# authority; the heightmap PNG is not, and neither is a free-rolling probe.
#
# USAGE
#   bash scripts/check_terrain.sh            # uses ~/selene workspace install
#   SELENE_WS=/path/to/ws bash scripts/check_terrain.sh
#
# Exit 0 if every checked coordinate rests on a colliding surface below its
# placement height. Exit 1 on any burial, any fall-through, or a misplaced PSR.

set -uo pipefail

WS="${SELENE_WS:-$HOME/selene}"
# Probe dynamics are tuned so this gate measures the TERRAIN, not the probe.
# A small fast sphere on a large triangle mesh can pass straight through the
# surface: dropping 0.3 m spheres from 45 m at a 2 ms step produced convincing
# "no collision geometry" reports whose membership changed with unrelated
# parameters (heightmap bit depth, collision resolution, timestep). A lower drop
# (less impact speed), a bigger probe and a finer step make contact generation
# reliable. With the datum applied the terrain spans about -17 m (crater floor)
# to +6 m (eastern ridge), so 12 m clears everything at low impact speed.
PROBE_DROP_Z="${PROBE_DROP_Z:-12}"
PROBE_STEP="${PROBE_STEP:-0.0005}"
PROBE_RADIUS=0.5
SETTLE_SECONDS="${SETTLE_SECONDS:-30}"
FAIL=0

if [ ! -f "$WS/install/setup.bash" ]; then
    echo "ERROR: no built workspace at $WS/install/setup.bash" >&2
    echo "       run scripts/sync_and_build.sh first, or set SELENE_WS." >&2
    exit 1
fi

# ROS setup.bash references unset vars.
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash 2>/dev/null || source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source "$WS/install/setup.bash"
set -u

SHARE="$WS/install/selene_sim/share/selene_sim"
export GZ_SIM_RESOURCE_PATH="$SHARE/models:${GZ_SIM_RESOURCE_PATH:-}"
# CLI/short-lived DDS participants can exhaust /dev/shm on WSL2.
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

# ---------------------------------------------------------------- probe points
# name:x:y:placement_z
#   placement_z >= 0  -> something is really placed here; assert it clears the surface
#   placement_z = SURVEY -> only a coordinate the software reasons about (an ice
#                           deposit, a zone centre); assert only that collision exists
SURVEY=-999
POINTS=""
add() { POINTS="$POINTS $1:$2:$3:$4"; }

# Robot spawns (selene_sim/config/spawn_positions.yaml) — really placed
# Placement heights are READ FROM THE CONFIG, not hard-coded. This gate used to
# assert a literal 1.5 for every robot; when spawn_positions.yaml moved to
# per-robot heights the gate went on testing a value the system no longer uses,
# and reported spurious burial.
# Resolve from the installed share dir first (works wherever the script is copied
# to), then the source tree next to this script.
if [ -z "${SPAWNS_YAML:-}" ]; then
    for cand in "$SHARE/config/spawn_positions.yaml"                 "$(dirname "$0")/../selene_sim/config/spawn_positions.yaml"; do
        [ -f "$cand" ] && { SPAWNS_YAML="$cand"; break; }
    done
fi
if [ -z "${SPAWNS_YAML:-}" ] || [ ! -f "$SPAWNS_YAML" ]; then
    echo "FAIL: cannot find spawn_positions.yaml; set SPAWNS_YAML." >&2
    exit 1
fi
eval "$(python3 - "$SPAWNS_YAML" <<'PYCFG'
import re, sys
rows = []
for line in open(sys.argv[1]):
    m = re.match(r'\s*-\s*\{x:\s*(-?[\d.]+),\s*y:\s*(-?[\d.]+),\s*z:\s*(-?[\d.]+)', line)
    if m:
        rows.append(m.groups())
names = ['scout_01', 'scout_02', 'excavator_01', 'hauler_01']
for n, (x, y, z) in zip(names, rows):
    print(f'add {n} {x} {y} {z}')
PYCFG
)"
for want in scout_01 scout_02 excavator_01 hauler_01; do
    case "$POINTS" in
        *"$want:"*) ;;
        *) echo "FAIL: $want was not read from $SPAWNS_YAML" >&2; exit 1 ;;
    esac
done
# Depot / recharge station (world_params.yaml, lunar_psr.sdf) — really placed
# depot marker z tracks lunar_psr.sdf (static, so it never settles)
add depot        -30 -100 1.86
# PSR centre, and two references well OUTSIDE the 60 m radius. Probes at exactly
# r=60 sit on the rim and read as crater floor, which makes the depth test lie.
add psr_centre  -100 -150 "$SURVEY"
add plain_north -100  -20 "$SURVEY"
add plain_east    10 -150 "$SURVEY"
# The four ice deposits (ice_deposits.yaml) — coordinates, not placed objects
add ice_alpha    -80 -140 "$SURVEY"
add ice_beta    -110 -170 "$SURVEY"
add ice_gamma    -90 -130 "$SURVEY"
add ice_delta   -120 -155 "$SURVEY"
# Mirror control: if the terrain is Y-flipped this is where the crater wrongly is
add mirror_check -100  150 "$SURVEY"
# Old spawn ring, kept as a reference point: it sat inside the PSR, which is why
# the fleet was moved. Should read as crater floor, well below the plain.
add old_spawn    -70 -110 "$SURVEY"

WORLD=$(mktemp /tmp/selene_check_terrain.XXXXXX.sdf)
# Clean up the temp world and any server we started, however we exit.
cleanup() {
    [ -n "${GZ_PID:-}" ] && kill -KILL "$GZ_PID" 2>/dev/null
    rm -f "$WORLD"
    return 0
}
trap cleanup EXIT INT TERM

{
  echo '<?xml version="1.0" ?>'
  echo '<sdf version="1.9"><world name="terraincheck">'
  echo '  <gravity>0 0 -1.62</gravity>'
  echo '  <physics name="fast" type="ode">'
  echo "    <max_step_size>$PROBE_STEP</max_step_size><real_time_factor>0</real_time_factor>"
  echo '  </physics>'
  echo '  <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>'
  echo '  <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>'
  echo '  <include><uri>model://lunar_terrain</uri><name>terrain</name><pose>0 0 0 0 0 0</pose></include>'
  i=0
  for p in $POINTS; do
      IFS=: read -r _n px py _pz <<<"$p"
      i=$((i + 1))
      # Each probe is PINNED to a world-fixed anchor by a prismatic joint on Z so it
      # can only descend. Free spheres ROLLED DOWNHILL before being read, which is
      # how this gate certified a spawn z of 1.5 m as clear when the true surface
      # was up to 5 m higher. See the header.
      printf '  <model name="probe%d"><pose>%s %s 0 0 0 0</pose>' "$i" "$px" "$py"
      printf '<link name="anchor"><pose>0 0 %s 0 0 0</pose>' "$PROBE_DROP_Z"
      printf '<inertial><mass>1</mass><inertia><ixx>0.1</ixx><iyy>0.1</iyy><izz>0.1</izz>'
      printf '<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial></link>'
      printf '<joint name="fix" type="fixed"><parent>world</parent><child>anchor</child></joint>'
      printf '<link name="ball"><pose>0 0 %s 0 0 0</pose>' "$PROBE_DROP_Z"
      printf '<inertial><mass>5</mass><inertia><ixx>0.2</ixx><iyy>0.2</iyy><izz>0.2</izz>'
      printf '<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>'
      printf '<collision name="c"><geometry><sphere><radius>%s</radius></sphere></geometry>' "$PROBE_RADIUS"
      printf '<surface><friction><ode><mu>1</mu><mu2>1</mu2></ode></friction>'
      printf '<bounce><restitution_coefficient>0</restitution_coefficient></bounce></surface>'
      printf '</collision></link>'
      printf '<joint name="slide" type="prismatic"><parent>anchor</parent><child>ball</child>'
      printf '<axis><xyz>0 0 1</xyz><limit><lower>-60</lower><upper>0</upper></limit>'
      printf '<dynamics><damping>0</damping><friction>0</friction></dynamics></axis></joint>'
      printf '</model>\n'
  done
  echo '</world></sdf>'
} > "$WORLD"

echo "SELENE terrain acceptance check"
echo "  workspace: $WS"
echo "  probes:    $(echo "$POINTS" | wc -w) dropped from z=${PROBE_DROP_Z} m"
echo ""

# Start PAUSED, then unpause once the heightmap is loaded.
#
# With `gz sim -s -r` the server begins stepping physics while the heightmap
# collision is still being built, so probes fall freely for the first moments.
# Removing that race did NOT on its own eliminate the spurious "no collision"
# reports — the probe tuning above and the coarser collision heightmap did the
# real work — but it removes one confounder from a measurement whose whole job is
# to be trustworthy, and it costs a few seconds. Keep it.
gz sim -s -v 1 "$WORLD" > /tmp/selene_check_terrain.log 2>&1 &
GZ_PID=$!

# Wait for the world to be up, then let the heightmap finish loading.
for _ in $(seq 1 40); do
    if gz topic -l 2>/dev/null | grep -q "/world/terraincheck/"; then break; fi
    sleep 0.5
done
sleep "${HEIGHTMAP_LOAD_SECONDS:-10}"

gz service -s /world/terraincheck/control \
    --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean \
    --timeout 5000 --req 'pause: false' > /dev/null 2>&1 \
    || echo "  WARNING: could not unpause the world; results will be meaningless"

sleep "$SETTLE_SECONDS"
# A pinned probe's descent IS the slide joint position, which is exact and needs
# no pose bookkeeping:  surface = PROBE_DROP_Z + joint_position - PROBE_RADIUS
: > /tmp/selene_check_terrain_poses.txt
NPROBES=$(echo "$POINTS" | wc -w)
for j in $(seq 1 "$NPROBES"); do
    jp=$(timeout 15 gz topic -e -t "/world/terraincheck/model/probe${j}/joint_state" -n 1 2>/dev/null \
         | python3 -c "
import re, sys
t = sys.stdin.read()
m = re.search(r'name:\s*\"slide\".*?position:\s*(-?[0-9eE.+-]+)', t, re.S)
print(m.group(1) if m else 'nan')")
    echo "probe${j} ${jp}" >> /tmp/selene_check_terrain_poses.txt
done

# Bounded teardown. `gz sim` does not always die on SIGTERM, and a bare `wait`
# after a kill that the child survived blocks this script forever — which would
# hang CI rather than fail it. Escalate to SIGKILL and never wait unbounded.
stop_gz() {
    kill -TERM "$GZ_PID" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "$GZ_PID" 2>/dev/null || return 0
        sleep 0.5
    done
    kill -KILL "$GZ_PID" 2>/dev/null
    pkill -KILL -f "gz sim .*$(basename "$WORLD")" 2>/dev/null
    return 0
}
stop_gz

python3 - "$POINTS" "$PROBE_RADIUS" <<'PY'
import re
import sys

points = sys.argv[1].split()
radius = float(sys.argv[2])

import os
DROP = float(os.environ.get('PROBE_DROP_Z', '12'))
z_by_probe = {}
for line in open('/tmp/selene_check_terrain_poses.txt'):
    parts = line.split()
    if len(parts) != 2:
        continue
    name, jp = parts
    try:
        # jp is the prismatic slide position: negative descent from DROP.
        z_by_probe[name] = DROP + float(jp)
    except ValueError:
        pass          # 'nan' -> no reading; reported as missing below

if not z_by_probe:
    print("FAIL: no probe poses were read from Gazebo. Is the world loading?")
    print("      see /tmp/selene_check_terrain.log")
    raise SystemExit(1)

failures = []
surfaces = {}
print(f"{'coordinate':<14} {'x':>6} {'y':>6} {'placed_z':>9} {'surface_z':>10}   verdict")
for idx, spec in enumerate(points, start=1):
    name, x, y, pz = spec.split(':')
    x, y, pz = float(x), float(y), float(pz)
    z = z_by_probe.get(f'probe{idx}')
    if z is not None and z != z:          # NaN: no joint reading came back
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {'NO DATA':>10}   MEASUREMENT FAILED")
        failures.append(f"{name}: probe returned no reading (NaN) - measurement failed, "
                        f"NOT a pass")
        continue
    if z is None:
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {'--':>10}   NO POSE")
        failures.append(f"{name}: no pose reported")
        continue
    if z <= -55:
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {'none':>10}   FELL THROUGH (no collision)")
        failures.append(f"{name} ({x:.0f},{y:.0f}): no collision geometry")
        continue
    surf = z - radius
    surfaces[name] = surf
    if pz < -900:
        tag = '(control)' if name == 'mirror_check' else '(survey coord)'
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {'n/a':>9} {surf:>10.2f}   {tag}")
        continue
    clearance = pz - surf
    if clearance < 0:
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {surf:>10.2f}   "
              f"BURIED by {-clearance:.2f} m")
        failures.append(f"{name} ({x:.0f},{y:.0f}): buried {-clearance:.2f} m")
    else:
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {surf:>10.2f}   ok (+{clearance:.2f} m)")

# The PSR must be a depression relative to its own rim, and the mirror control
# must NOT be one. This catches a re-introduced row-order flip.
print()
centre = surfaces.get('psr_centre')
rim = [surfaces[k] for k in ('plain_north', 'plain_east') if k in surfaces]
mirror = surfaces.get('mirror_check')
if centre is not None and centre == centre and rim and all(r == r for r in rim):
    rim_mean = sum(rim) / len(rim)
    depth = rim_mean - centre
    print(f"PSR depth at (-100,-150): outside {rim_mean:.2f} m - centre {centre:.2f} m "
          f"= {depth:.2f} m")
    if depth < 5.0:
        print("  FAIL: the configured PSR centre is not a depression.")
        failures.append(f"PSR at (-100,-150) is not a crater (depth {depth:.2f} m)")
    else:
        print("  ok: the crater is where world_params.yaml says it is.")
else:
    print("PSR depth: could not evaluate (missing probe results)")
    failures.append("PSR depth not evaluable")

if mirror is not None and mirror == mirror and centre is not None and centre == centre:
    if mirror < centre:
        print(f"  FAIL: (-100,+150) at {mirror:.2f} m is LOWER than the configured "
              f"centre at {centre:.2f} m — terrain looks mirrored in Y.")
        failures.append("terrain appears mirrored in Y")
    else:
        print(f"  ok: mirror control at (-100,+150) is {mirror:.2f} m, not a crater.")

print()
if failures:
    print(f"RESULT: FAIL — {len(failures)} problem(s)")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: PASS — every placed entity clears a colliding surface, and the "
      "PSR crater is at the configured location.")
PY
RC=$?

if [ "$RC" -ne 0 ]; then
    FAIL=1
fi
echo ""
echo "Gazebo log: /tmp/selene_check_terrain.log"
exit "$FAIL"
