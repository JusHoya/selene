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
# AND THAT REWIRE INITIALLY MEASURED NOTHING AT ALL — the gate's third
# measurement error in a row. The pinned probes are read from
# /world/terraincheck/model/probe<N>/joint_state, but the generated probe models
# did not carry gz-sim-joint-state-publisher-system, which is the plugin that
# advertises that topic and nothing else does. (It is the same plugin
# selene_sim/models/scout/model.sdf line ~323 carries, which is why the scout's
# joint_state topic existed while the probes' never did.) The topic name was
# right; the publisher was missing. Every read came back empty, every surface
# parsed as NaN, and all 14 coordinates printed MEASUREMENT FAILED with exit 1 —
# fail-closed, so it certified nothing false, but it also certified nothing true.
# Re-running the pre-fix script confirms exactly that: 14 of 14 NaN, no
# joint_state topic in the world. The plugin is now emitted with every probe, and
# the reading is parsed inside the slide joint's own axis1 block; both are
# documented at the point of use below.
#
# None of this is visible from the configs, and none of it produces an error
# message — robots simply sit inside solid geometry with their wheels turning. So
# the check lowers a laterally-pinned probe onto every coordinate the software
# cares about and reads the slide joint's position. Gazebo is the external
# authority; the heightmap PNG is not, and neither is a free-rolling probe.
#
# WHAT IS ACTUALLY VERIFIED, AND WHAT IS NOT
# Measured 2026-07-29 on gz-sim 8.11.0 / Gazebo Harmonic, Ubuntu 24.04 under
# WSL2, 30 s settle, against spawn_positions.yaml z = 2.8 / 2.7 / 4.3 / 5.6 and
# the lunar_psr.sdf depot marker at 1.86. The gate runs to completion and exits 0.
#
#   - Its surfaces were CROSS-CHECKED, not assumed. The six coordinates that an
#     independent pinned-probe harness also measured agree, in metres:
#         (-45, -92)    2.4928  vs   2.4925    +0.0003
#         (-45, -85)    2.3842  vs   2.3840    +0.0002
#         (-45,-105)    4.0200  vs   4.0114    +0.0086
#         (-45,-112)    5.2774  vs   5.2688    +0.0086
#         (-30,-100)    1.8065  vs   1.8051    +0.0014
#         (-100,-150) -16.6022  vs -16.6025    +0.0003
#     Worst disagreement 8.6 mm — small against the 0.30 m spawn margin and
#     against the ~0.05 m of relief a wheelbase sees across one 3.91 m collision
#     cell. Two separate runs reproduced every slide position to all 16 digits.
#     The two 8.6 mm rows are the two points on the steepest ground (0.12 and
#     0.18 m/m along x=-45, against 0.016 m/m at the two rows that agree to
#     0.3 mm), which is what a 0.5 m sphere resting tangent to a sloped collision
#     cell would do; that mechanism is a reading of the numbers, not a separate
#     measurement. Note also that the cross-check harness uses the SAME
#     pinned-probe method, so it confirms this gate's plumbing and parsing, not
#     the method — and nothing here confirms the heightmap's absolute datum,
#     which spawn_positions.yaml records as ~25% inflated upstream.
#   - IT STILL FAILS. Pointed at the same config with z forced back to 1.5 it
#     reports all four spawns BURIED (0.99 / 0.88 / 2.52 / 3.78 m) and exits 1.
#     The pass above is therefore a measurement, not a stuck green.
#
# NOT verified: the eight survey-only coordinates have no independent reference.
# For those this gate asserts only that collision geometry exists there, plus the
# PSR-depth and Y-mirror RELATIONS between them — it does not certify their
# absolute heights. And a pass means only "not inside the terrain at t=0";
# whether a robot can drive out of that pose is scripts/check_drive.sh's question.
#
# USAGE
#   bash scripts/check_terrain.sh            # uses ~/selene workspace install
#   SELENE_WS=/path/to/ws bash scripts/check_terrain.sh
#   SPAWNS_YAML=/path/to/spawns.yaml bash scripts/check_terrain.sh   # test a config
# It starts its own gz server on its own GZ_PARTITION, so it neither reads nor is
# read by another Gazebo on the same host (verified: a `gz topic -l` in another
# partition, and one with GZ_PARTITION unset, both see none of its topics).
#
# Exit 0 only if every probe made contact, and every PLACED coordinate's surface
# is below its placement height. Exit 1 on any burial, any coordinate with no
# collision beneath it, a misplaced PSR, or
# any probe that returned no reading.

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
# Travel limit of the probe's prismatic slide, in metres. The no-contact test below
# is DERIVED from this and PROBE_DROP_Z rather than hard-coded, because the two got
# out of step once already: with DROP=12 and LIMIT=60 a probe can never read below
# 12-60 = -48, while the fall-through test compared against -55. -48 <= -55 is
# always false, so the branch was dead and a coordinate over the void passed with
# "51.30 m of clearance". Keep these coupled.
SLIDE_LIMIT="${SLIDE_LIMIT:-60}"
# Exported so the analysis block below reads the REAL values rather than its own
# fallback defaults, which would silently diverge if any of these were overridden.
export PROBE_DROP_Z SLIDE_LIMIT PROBE_RADIUS
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
# Isolate this check's gz-transport traffic. The default partition is shared, so
# any other Gazebo on the host — including a server left behind by a crashed
# earlier run of THIS script, which advertises the same world name and the same
# probe<N>/joint_state topics — could be the thing answered below instead of the
# server started further down. Reading a stale server is exactly the class of
# measurement error this file exists to prevent. Honours a caller-set partition.
export GZ_PARTITION="${GZ_PARTITION:-selene_check_terrain_$$}"

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
      printf '<axis><xyz>0 0 1</xyz><limit><lower>-%s</lower><upper>0</upper></limit>' "$SLIDE_LIMIT"
      printf '<dynamics><damping>0</damping><friction>0</friction></dynamics></axis></joint>'
      # WITHOUT THIS LINE THE GATE MEASURES NOTHING. The descent is read from
      # /world/terraincheck/model/probe<N>/joint_state, and that topic is
      # advertised by this plugin and nothing else — it is the same one
      # selene_sim/models/scout/model.sdf carries to publish wheel states. When
      # the probes were rewired from free spheres to pinned slides the plugin was
      # not carried over, so the topic never existed, every read came back empty,
      # every surface parsed as NaN and all 14 coordinates printed MEASUREMENT
      # FAILED. The topic name was right; the publisher was missing.
      printf '<plugin filename="gz-sim-joint-state-publisher-system" name="gz::sim::systems::JointStatePublisher"/>'
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

# The whole measurement rides on one topic per probe. If it is not advertised
# there is nothing to read, and the run would otherwise spend its settle time and
# then print a wall of MEASUREMENT FAILED without naming the cause. Name it here.
if ! gz topic -l 2>/dev/null | grep -qx "/world/terraincheck/model/probe1/joint_state"; then
    echo "  WARNING: /world/terraincheck/model/probe1/joint_state is not advertised."
    echo "           Either the probe models lost gz-sim-joint-state-publisher-system"
    echo "           or the world did not load. Every reading will be NaN."
fi

sleep "$SETTLE_SECONDS"
# A pinned probe's descent IS the slide joint position, which is exact and needs
# no pose bookkeeping:  surface = PROBE_DROP_Z + joint_position - PROBE_RADIUS
#
# The parser below is written against a message that was actually captured from
# this world, not against an assumed layout. gz-sim 8.11.0 publishes a
# gz.msgs.Model in protobuf text format, and each probe has TWO joints:
#
#   name: "probe2"
#   id: 14
#   pose { position { x: -45 y: -92 } orientation { w: 1 } }
#   joint {
#     name: "fix"
#     id: 18
#     parent: "world"
#     child: "anchor"
#     pose { position { } orientation { w: 1 } }     <- no axis1 at all
#   }
#   joint {
#     name: "slide"
#     id: 19
#     parent: "anchor"
#     child: "ball"
#     pose { position { } orientation { w: 1 } }     <- NOT the reading
#     axis1 {
#       xyz { z: 1 }
#       limit_lower: -60
#       position: -9.0072210705977973                <- the reading
#       velocity: 1.7391765111396396e-12
#     }
#   }
#
# (shown flattened; the wire text puts every field on its own line.) Three traps
# are visible in that message and the parser has to survive all of them:
#
#   1. TWO joints. A lazy `name:"slide".*?position:` across the whole payload can
#      pair one joint's name with another joint's position. So the match is scoped
#      to the slide joint's own brace block, and then to that block's own axis1.
#   2. Every joint carries `pose { position { } }`. That is a nested message —
#      `position` followed by `{`, never by a number — so requiring the
#      colon-then-number form keeps the joint pose out of the reading.
#   3. proto3 text format omits fields that equal their default, which is why
#      `limit_upper: 0` and `velocity: 0` simply are not printed. An axis1 with no
#      `position:` line therefore means position is exactly 0.0 (the probe never
#      moved) — a real reading of 0, not a missing one, and one that then fails
#      the clearance test rather than being mistaken for a measurement error.
#
# `gz topic -e -n 1` prints more than one message in practice; the first complete
# slide/axis1 block wins.
PARSE_SLIDE=$(cat <<'PYSLIDE'
import re, sys

NUM = r'[-+]?(?:[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)'
t = sys.stdin.read()
out = 'nan'


def block_after(text, start):
    """Return the text inside the brace group whose '{' precedes `start`."""
    i, depth = start, 1
    while i < len(text) and depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return None if depth else text[start:i - 1]


for m in re.finditer(r'\bjoint\s*\{', t):
    body = block_after(t, m.end())
    if body is None:
        continue                          # truncated trailing message
    if not re.search(r'\bname:\s*"slide"', body):
        continue                          # some other joint, e.g. "fix"
    a = re.search(r'\baxis1\s*\{', body)
    if a is None:
        continue                          # slide seen but no axis state yet
    axis = block_after(body, a.end())
    if axis is None:
        continue
    p = re.search(r'\bposition:\s*(' + NUM + r')\s*$', axis, re.M)
    out = p.group(1) if p else '0'         # absent field == proto3 default 0.0
    break
print(out)
PYSLIDE
)
: > /tmp/selene_check_terrain_poses.txt
# Keep the raw payloads. When this gate next misreports, the first question is
# "what did Gazebo actually send", and guessing at that is how the previous three
# measurement errors survived.
: > /tmp/selene_check_terrain_joint_state.txt
NPROBES=$(echo "$POINTS" | wc -w)
for j in $(seq 1 "$NPROBES"); do
    raw=$(timeout 15 gz topic -e -t "/world/terraincheck/model/probe${j}/joint_state" -n 1 2>&1)
    printf '========== probe%s ==========\n%s\n' "$j" "$raw" \
        >> /tmp/selene_check_terrain_joint_state.txt
    jp=$(printf '%s\n' "$raw" | python3 -c "$PARSE_SLIDE")
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
LIMIT = float(os.environ.get('SLIDE_LIMIT', '60'))
RADIUS = float(os.environ.get('PROBE_RADIUS', '0.5'))
# A probe that ran to the end of its slide never touched anything. Derived, not
# guessed. NOTE THE FRAME: z here is the BALL CENTRE (DROP + joint_position), not
# the surface, so the radius must NOT appear. Bottom-out centre = DROP - LIMIT,
# plus 0.2 m of tolerance. Getting this wrong by one radius made the check silently
# unreachable once already, which is the same defect this threshold exists to catch.
NO_CONTACT_Z = DROP - LIMIT + 0.2
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
    if z <= NO_CONTACT_Z:
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {pz:>9.2f} {'none':>10}   FELL THROUGH (no collision)")
        failures.append(f"{name} ({x:.0f},{y:.0f}): no collision geometry")
        continue
    surf = z - radius
    surfaces[name] = surf
    if pz < -900:
        tag = '(control)' if name == 'mirror_check' else '(survey coord)'
        # Survey coordinates carry no clearance test, but they DO assert that
        # collision geometry exists here; the no-contact case was caught above.
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
