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
# Measured 2026-07-30 on gz-sim 8.14.0 / Gazebo Harmonic, ROS 2 Jazzy, Ubuntu
# 24.04.3 under WSL2, 30 s settle, against spawn_positions.yaml
# z = 1.75 / 1.65 / 2.94 / 3.93 and the lunar_psr.sdf depot marker at 0.94. The
# gate runs to completion and exits 0.
#
#   - Surfaces on the AFTER-FIX terrain, in metres:
#         (-45, -92)    1.446014      (-45, -85)    1.340096
#         (-45,-105)    2.633854      (-45,-112)    3.621368
#         (-30,-100)    0.886175      (-100,-150) -13.914932
#     These are ~0.94-1.66 m lower than every earlier number in this file's
#     history, because the heightmap normalisation bug was fixed in
#     selene_sim/scripts/generate_heightmap.py: gz-sim maps an image's OWN
#     brightest pixel to <size> z, the generator had assumed the format maximum,
#     and the -18 m datum on terrain_link was cancelling the resulting 1.25x
#     inflation. terrain_link now carries -15.0 and world z is exactly
#     (metric height - 15.0). Do not compare these against the pre-fix figures.
#   - They are NOT a bilinear read of the PNG, and must not be replaced by one.
#     A bilinear read predicts 1.4199 / 1.3108 / 2.4540 / 3.4121 — low by 26 mm
#     on the flattest of the four and by 209 mm on the steepest. A 0.5 m probe
#     sphere rests TANGENT to a sloped collision cell, so it reads high exactly
#     where the ground is steep, and a wheel does the same. The probe is the
#     reference; the image is not.
#   - IT STILL FAILS, three ways, all measured on this exact script:
#         spawn z forced back to 1.5   -> 4x BURIED (0.99/0.88/2.52/3.78), exit 1
#         a survey coordinate at (300,300), off the 500x500 terrain
#                                      -> FELL THROUGH (no collision),  exit 1
#         probes that return no reading -> 14x MEASUREMENT FAILED,       exit 1
#     The pass above is therefore a measurement, not a stuck green.
#
# THE EXIT STATUS IS FINE, AND WAS NEVER BROKEN. Commit c08d5bc's message says
# "STILL BROKEN, DO NOT WIRE THIS INTO CI YET: exit-code propagation ... prints
# RESULT: FAIL and then exits 0 (measured: void_run_exit=0, normal_run_exit=0)".
# That measurement was wrong. The harness that produced it did:
#     bash ct_void.sh >/dev/null 2>&1
#     echo "void_run_exit=0" > ec.txt     # a LITERAL 0, not $?
# It never captured $? at all, so its file said 0 because the string said 0.
# Re-measured 2026-07-30 on this byte-identical script with $? captured properly:
# normal run 0, void injection 1, buried spawns 1. There is no swallow, the tail
# is unchanged since the file was created, and this gate is wired into CI by
# .github/workflows/sim-gates.yaml.
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
#   WORLD_SDF=/path/to/lunar_psr.sdf bash scripts/check_terrain.sh   # depot z source
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

# THE FILES THAT CARRY THE MEASUREMENT ARE PID-SCOPED, for the same reason the
# partition above is. GZ_PARTITION was made per-PID precisely so a second Gazebo
# could not answer this run's queries; the file that carries the readings into the
# verdict got no such treatment, and it was the wider hole of the two.
#
# The truncate/append checks further down close the STALE-file case (a leftover
# unwritable file). They do NOT close the CONCURRENT case: run A truncates and
# writes its 14 lines, run B truncates — wiping A's data — and writes its own 14,
# and A's "must be exactly NPROBES lines" check then passes on B's measurements.
# Measured: an A with a burial injected reported "ok (+0.31 m)" and RESULT: PASS,
# exit 0, off an overlapping clean B's readings. Two developers, or a dev box and a
# CI container sharing /tmp, or a scheduled run overlapping a push run, are all
# enough. Per-PID names make the collision impossible rather than unlikely.
#
# The gz log and the joint-state dump are NOT removed on exit: they are the raw
# payload every one of the last three measurement bugs was diagnosed from. The
# paths are echoed below so an operator can find them, and
# .github/workflows/sim-gates.yaml globs them as artifacts.
RUN_ID=$$
GZLOG="/tmp/selene_check_terrain.$RUN_ID.log"
POSES="/tmp/selene_check_terrain_poses.$RUN_ID.txt"
JOINT_DUMP="/tmp/selene_check_terrain_joint_state.$RUN_ID.txt"

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
# Keyed on the GROUP HEADER, not on file order. This used to collect every
# `- {x:, y:, z:}` line in the file and zip() it against a fixed name list, so a
# reordered group, an added scout_03, or any other list of x/y/z mappings shifted
# every name onto the wrong coordinate — silently, because the names still all
# appeared. check_drive.sh:119 does the keyed thing with yaml.safe_load; this
# stays on the regex so the terrain gate keeps needing no third-party module.
eval "$(python3 - "$SPAWNS_YAML" <<'PYCFG'
import re, sys

GROUPS = {'scouts': 'scout', 'excavators': 'excavator', 'haulers': 'hauler'}
current = None
counts = {}
for line in open(sys.argv[1]):
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    head = re.match(r'([A-Za-z_][A-Za-z0-9_]*):\s*$', line)
    if head:
        current = GROUPS.get(head.group(1))
        continue
    row = re.match(r'\s*-\s*\{x:\s*(-?[\d.]+),\s*y:\s*(-?[\d.]+),\s*z:\s*(-?[\d.]+)',
                   line)
    if row and current:
        counts[current] = counts.get(current, 0) + 1
        print(f'add {current}_{counts[current]:02d} '
              f'{row.group(1)} {row.group(2)} {row.group(3)}')
PYCFG
)"
for want in scout_01 scout_02 excavator_01 hauler_01; do
    case "$POINTS" in
        *"$want:"*) ;;
        *) echo "FAIL: $want was not read from $SPAWNS_YAML" >&2; exit 1 ;;
    esac
done
# Depot / recharge station — really placed, and READ FROM lunar_psr.sdf.
# The depot marker is static, so whatever z the world file carries is where it
# stays. This used to hard-code 1.86, and it went stale the moment the datum fix
# moved the marker to 0.94: the gate went on certifying a height the world no
# longer used — the identical mistake it already documents for the robot spawns
# ("This gate used to assert a literal 1.5 for every robot"). Resolve it the same
# way, from the installed share dir first, then the source tree.
if [ -z "${WORLD_SDF:-}" ]; then
    for cand in "$SHARE/worlds/lunar_psr.sdf" \
                "$(dirname "$0")/../selene_sim/worlds/lunar_psr.sdf"; do
        [ -f "$cand" ] && { WORLD_SDF="$cand"; break; }
    done
fi
if [ -z "${WORLD_SDF:-}" ] || [ ! -f "$WORLD_SDF" ]; then
    echo "FAIL: cannot find lunar_psr.sdf; set WORLD_SDF." >&2
    exit 1
fi
DEPOT_Z=$(python3 - "$WORLD_SDF" <<'PYDEPOT'
import re
import sys

text = open(sys.argv[1]).read()
# The <include> whose <name> is 'depot'; take that block's <pose> z.
for block in re.findall(r'<include>(.*?)</include>', text, re.S):
    if re.search(r'<name>\s*depot\s*</name>', block):
        pose = re.search(r'<pose>\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', block)
        if pose:
            print(pose.group(3))
            break
PYDEPOT
)
if [ -z "$DEPOT_Z" ]; then
    echo "FAIL: could not read the depot marker's pose z from $WORLD_SDF" >&2
    exit 1
fi
add depot        -30 -100 "$DEPOT_Z"
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

WORLD=$(mktemp /tmp/selene_check_terrain.XXXXXX.sdf) || {
    echo "FAIL: mktemp could not create the temp world file" >&2; exit 1; }
# Clean up the temp world and any server we started, however we exit.
cleanup() {
    [ -n "${GZ_PID:-}" ] && kill -KILL "$GZ_PID" 2>/dev/null
    rm -f "$WORLD"
    return 0
}
# The signal traps EXIT EXPLICITLY. `trap cleanup EXIT INT TERM` with a cleanup
# that ends in `return 0` does NOT stop the script: on SIGTERM it tore down the
# Gazebo server and the world file and then CARRIED ON to the analysis block,
# which read whatever the probes had managed to report and could print
# "RESULT: PASS" and exit 0. Measured: SIGTERM at t=4 s of a 10 s settle gave
# RESULT: PASS, exit 0, with cleanup having run twice. It also made the script
# effectively uninterruptible, so a CI `timeout` overruns its budget by minutes.
# 130/143 are the conventional 128+SIGINT / 128+SIGTERM statuses.
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

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
gz sim -s -v 1 "$WORLD" > "$GZLOG" 2>&1 &
GZ_PID=$!

# THESE THREE ARE HARD FAILURES, and were warnings until 2026-07-30. Every
# infrastructure failure between here and the analysis block used to be a
# warning, so the gate failed closed only by accident — via the PSR-depth
# RELATION between two survey points, which is not a check that the world
# stepped. check_drive.sh exits 1 on exactly these conditions; match it.
#
# CARRY THE POLL'S RESULT; DO NOT RE-QUERY. The loop used to break on a match and
# then a SECOND, independent `gz topic -l | grep -q` decided the verdict — so a
# transient failure of that one query turned a healthy world into
# "world never appeared". Under CPU contention that is a real false FAIL, and
# promoting this from a warning to exit 1 is what made it fatal. The evidence was
# already in hand at the break; use it.
WORLD_UP=0
for _ in $(seq 1 40); do
    if gz topic -l 2>/dev/null | grep -q "/world/terraincheck/"; then
        WORLD_UP=1
        break
    fi
    sleep 0.5
done
if [ "$WORLD_UP" -ne 1 ]; then
    echo "FAIL: world 'terraincheck' never appeared. See $GZLOG"
    exit 1
fi
sleep "${HEIGHTMAP_LOAD_SECONDS:-10}"

gz service -s /world/terraincheck/control \
    --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean \
    --timeout 5000 --req 'pause: false' > /dev/null 2>&1 \
    || { echo "FAIL: could not unpause the world; results would be meaningless"
         exit 1; }

# The whole measurement rides on one topic per probe. If it is not advertised
# there is nothing to read, and the run would otherwise spend its settle time and
# then print a wall of MEASUREMENT FAILED without naming the cause.
#
# RETRIED, not sampled once. The topic is advertised asynchronously after the
# world unpauses, so a single query here races the publisher and — now that this
# is exit 1 rather than a warning — a lost race is a red gate on a healthy world.
# 10 x 0.5 s is generous against the ~0 s it normally takes, and still fails fast
# relative to the settle that follows.
TOPIC_UP=0
for _ in $(seq 1 10); do
    if gz topic -l 2>/dev/null | grep -qx "/world/terraincheck/model/probe1/joint_state"; then
        TOPIC_UP=1
        break
    fi
    sleep 0.5
done
if [ "$TOPIC_UP" -ne 1 ]; then
    echo "FAIL: /world/terraincheck/model/probe1/joint_state is not advertised."
    echo "      Either the probe models lost gz-sim-joint-state-publisher-system"
    echo "      or the world did not load. Every reading would be NaN."
    echo "      See $GZLOG"
    exit 1
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
# THE WRITE IS CHECKED, AND SO IS THE LINE COUNT. These are fixed names so CI can
# collect them as artifacts, which means a previous run's file can already be
# sitting there — and under `set -uo pipefail` with no -e, a redirection that
# fails is silent. Measured consequence before this check existed: seed a passing
# run, `chmod 444` the pose file, then run a VOIDED config — all 14 appends fail
# with "Permission denied", the analysis block reads the PREVIOUS run's readings,
# and the gate prints "RESULT: PASS" and exits 0. That is the exact class of
# false green this file exists to prevent, and it was in the file doing the
# preventing. A root-owned leftover from a sudo/CI run is all it takes.
# POSES / JOINT_DUMP / GZLOG are defined near GZ_PARTITION and are PID-scoped; see
# the note there for why the checks below are not sufficient on their own.
: > "$POSES" || { echo "FAIL: cannot write $POSES (stale root-owned file? full /tmp?)" >&2
                  exit 1; }
# Keep the raw payloads. When this gate next misreports, the first question is
# "what did Gazebo actually send", and guessing at that is how the previous three
# measurement errors survived.
: > "$JOINT_DUMP" || { echo "FAIL: cannot write $JOINT_DUMP" >&2; exit 1; }
NPROBES=$(echo "$POINTS" | wc -w)
for j in $(seq 1 "$NPROBES"); do
    raw=$(timeout 15 gz topic -e -t "/world/terraincheck/model/probe${j}/joint_state" -n 1 2>&1)
    printf '========== probe%s ==========\n%s\n' "$j" "$raw" >> "$JOINT_DUMP"
    jp=$(printf '%s\n' "$raw" | python3 -c "$PARSE_SLIDE")
    echo "probe${j} ${jp}" >> "$POSES" || {
        echo "FAIL: could not append probe${j} to $POSES" >&2; exit 1; }
done
# One line per probe, or the analysis below is reading something other than this
# run. A short file means appends were lost; a long one means it was not truncated.
GOT=$(wc -l < "$POSES")
if [ "$GOT" -ne "$NPROBES" ]; then
    echo "FAIL: $POSES has $GOT lines, expected $NPROBES — refusing to analyse a"
    echo "      pose file this run did not fully write."
    exit 1
fi

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
    # NO pkill HERE. It used to run
    #     pkill -KILL -f "gz sim .*$(basename "$WORLD")"
    # which is the pattern check_drive.sh:145-148 and verify_drive.sh explicitly
    # forbid. It could not match this script's own command line (the basename is
    # generated by mktemp after the script starts), but if mktemp had failed
    # `basename ""` prints nothing and returns 0, degenerating the pattern to
    # `gz sim .*` — a SIGKILL to every Gazebo on the host, including a
    # developer's session. The mktemp is now checked, and the line above already
    # SIGKILLs the one server this script started; GZ_PARTITION is what keeps any
    # other server out of the measurement.
    return 0
}
stop_gz

python3 - "$POINTS" "$PROBE_RADIUS" "$POSES" "$GZLOG" <<'PY'
import os
import sys

points = sys.argv[1].split()
radius = float(sys.argv[2])
poses_path = sys.argv[3]        # passed in, not hardcoded, so the shell owns the path
gz_log = sys.argv[4]            # ditto; both are PID-scoped by the shell

DROP = float(os.environ.get('PROBE_DROP_Z', '12'))
LIMIT = float(os.environ.get('SLIDE_LIMIT', '60'))
# A probe that ran to the end of its slide never touched anything. Derived, not
# guessed. NOTE THE FRAME: z here is the BALL CENTRE (DROP + joint_position), not
# the surface, so the radius must NOT appear. Bottom-out centre = DROP - LIMIT.
# Getting this wrong by one radius made the check silently unreachable once
# already, which is the same defect this threshold exists to catch.
#
# The tolerance is 1.0 m, not the 0.2 m it was until 2026-07-30. The slide carries
# <damping>0</damping><friction>0</friction> and the zero-restitution surface is on
# the BALL, not on the joint stop, so a probe over the void arrives at the stop at
# sqrt(2 * 1.62 * 60) = 13.9 m/s and rings against ODE's default stop ERP/CFM.
# At 0.2 m a reading only 0.3 m off the stop was accepted as a real surface at
# -48.2 m. 1.0 m still leaves 47 m of daylight to the lowest real terrain
# (-14.8 m world, i.e. a ball centre near -14.3).
NO_CONTACT_Z = DROP - LIMIT + 1.0
z_by_probe = {}
for line in open(poses_path):
    parts = line.split()
    if len(parts) != 2:
        continue
    name, jp = parts
    try:
        # jp is the prismatic slide position: negative descent from DROP.
        # NOTE: float('nan') SUCCEEDS — it does not raise — so a NaN reading lands
        # in this dict and is caught by the `z != z` test further down, not here.
        # The ValueError branch only catches a genuinely malformed token.
        z_by_probe[name] = DROP + float(jp)
    except ValueError:
        pass          # malformed token; reported as missing below

if not z_by_probe:
    print("FAIL: no probe poses were read from Gazebo. Is the world loading?")
    print(f"      see {gz_log}")
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
        # Survey rows print 'n/a' everywhere else; don't leak the -999 sentinel here.
        shown = 'n/a' if pz < -900 else f'{pz:.2f}'
        print(f"{name:<14} {x:>6.0f} {y:>6.0f} {shown:>9} {'none':>10}   FELL THROUGH (no collision)")
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
echo "Gazebo log:      $GZLOG"
echo "Probe readings:  $POSES"
echo "Raw joint_state: $JOINT_DUMP"
exit "$FAIL"
