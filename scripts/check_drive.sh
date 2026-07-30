#!/bin/bash
# Drive acceptance check — asserts a robot placed at its CONFIGURED spawn pose on
# the REAL lunar world actually translates when commanded, by comparing Gazebo's
# own model pose against the command.
#
# WHY THIS EXISTS
# For months every robot in this project reported healthy odometry while standing
# perfectly still. scripts/verify_drive.sh passed throughout, because it drives on
# a flat plane: on a plane the ground is at z=0, so a robot spawned at any z>0
# simply falls onto it, and no flat-ground test can ever catch a spawn height that
# is wrong relative to terrain. The real failure, MEASURED on lunar_psr.sdf with
# the shipped scout at the then-configured (-45,-92,1.5):
#
#     settle   x=-45.000000 y=-92.000000 z=1.507770 yaw=-2.340580
#     after 12 s at 0.4 m/s
#              x=-45.000000 y=-92.000000 z=1.523410 yaw=-2.410570
#     world displacement 0.0000 m   odometry 5.0820 m   ->  100% slip
#
# X and Y identical to six decimal places. The robot was ~1.0 m below the terrain
# collision surface, entombed, its horizontal DOFs held by contact while the wheels
# turned at exactly the commanded 4.0 rad/s inside solid rock. DiffDrive odometry
# integrates MEASURED wheel-joint position, so it is not lying — it simply cannot
# see slip, because an unloaded-torque wheel joint reaches its commanded speed
# whether it is rolling, free-spinning or buried (measured 4.00000 rad/s in all
# three). That is why odometry alone can never be the gate.
#
# THREE THINGS THIS CHECK ASSERTS, and why each is needed:
#   1. world displacement is within tolerance of the COMMAND (v * t). This is the
#      load-bearing assertion. Odometry is a cross-check, not the reference.
#   2. the robot SETTLED DOWNWARD from its spawn z. A robot created inside the
#      heightfield does not fall; it is extruded upward at ~1 mm/s, so its z rises
#      above the z it was created at. That is an unambiguous burial signature and
#      it is cheap to test.
#   3. commanding angular.z changes heading in the WORLD. Note this one is weak on
#      its own: the buried robot above still rotated +2.12 rad, because burial pins
#      translation, not yaw. A turn-only test would have passed the whole time.
#
# USAGE
#   bash scripts/check_drive.sh                       # scout_01, from spawn_positions.yaml
#   DRIVE_ROBOT=hauler_01 bash scripts/check_drive.sh
#   SELENE_WS=/path/to/ws bash scripts/check_drive.sh
#
# Exit 0 if the robot drives. Exit 1 on burial, on excessive slip, on no motion,
# on runaway motion, or if the heading does not change on command.

set -uo pipefail

WS="${SELENE_WS:-$HOME/selene}"
DRIVE_ROBOT="${DRIVE_ROBOT:-scout_01}"
DRIVE_SPEED="${DRIVE_SPEED:-0.4}"      # m/s, matches the nav layer's cruise speed
DRIVE_SECONDS="${DRIVE_SECONDS:-12}"
TURN_RATE="${TURN_RATE:-0.35}"         # rad/s
TURN_SECONDS="${TURN_SECONDS:-8}"
SETTLE_SECONDS="${SETTLE_SECONDS:-8}"
# The heightmap COLLISION mesh is built after the world topic appears. Spawning or
# stepping before it exists lets bodies fall through; 12 s was enough in every run
# on this machine at 129x129.
HEIGHTMAP_LOAD_SECONDS="${HEIGHTMAP_LOAD_SECONDS:-12}"

# --- tolerances, and why they are these numbers -----------------------------
# Ideal distance is DRIVE_SPEED * DRIVE_SECONDS = 4.80 m at the defaults. Known
# systematic losses: DiffDrive's own <max_linear_acceleration>0.5</...> costs a
# 0.8 s ramp = 0.16 m (3.3%); wheel slip on regolith friction measured 0.5-4%;
# climbing terrain shortens the HORIZONTAL projection (the scout gained 0.47 m of
# height over its 4.70 m run). MEASURED on the fixed config: scout 4.6958 m
# (97.8% of command), hauler 4.4197 m (92.1%). 0.70 leaves ample headroom while
# still failing hard on the 0.0000 m burial case.
MIN_FRACTION="${MIN_FRACTION:-0.70}"
# Upper bound catches the opposite failure, which looks like success in a
# distance-only test: a robot that has lost traction and is sliding downhill, or
# one being ejected sideways out of the terrain. Both were observed at 6.6 m and
# 15.9 m against the same ~4.2 m of odometry.
MAX_FRACTION="${MAX_FRACTION:-1.15}"
# |world - odom| / odom. Honest driving measured 0.5-4.1%; total burial is 100%.
MAX_SLIP_PCT="${MAX_SLIP_PCT:-25}"
# Commanded yaw change is TURN_RATE * TURN_SECONDS = 2.80 rad at the defaults, but
# a skid-steer with no steered wheels scrubs badly, and the 6-wheelers are worse
# because their mid wheels sit on the turn axis: MEASURED scout +1.3074 rad (47%
# of command), hauler +0.3158 rad (11%). So this threshold only asks "did the
# heading actually move in the world" — a stalled or high-centred robot measures
# exactly 0.0000. Do NOT treat it as a burial test: the buried scout in the note
# above still rotated +2.12 rad, because burial pins translation, not yaw.
MIN_TURN_RAD="${MIN_TURN_RAD:-0.20}"

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
WORLD="$SHARE/worlds/lunar_psr.sdf"
SPAWN_YAML="$SHARE/config/spawn_positions.yaml"
export GZ_SIM_RESOURCE_PATH="$SHARE/models:${GZ_SIM_RESOURCE_PATH:-}"
# CLI/short-lived DDS participants can exhaust /dev/shm on WSL2.
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
# Isolate gz transport so a developer's own running simulation, or a parallel CI
# job, cannot answer our `gz model` queries. The world name inside lunar_psr.sdf
# is fixed, so without this the two would collide.
export GZ_PARTITION="${GZ_PARTITION:-selene_check_drive_$$}"

WORLD_NAME=lunar_psr

for f in "$WORLD" "$SPAWN_YAML"; do
    [ -f "$f" ] || { echo "ERROR: missing $f" >&2; exit 1; }
done

# The spawn pose comes from the SAME file simulation.launch.py reads. Hard-coding
# it here is how scripts/check_terrain.sh ended up gating a z that the config no
# longer used.
read -r SX SY SZ SYAW QZ QW MODEL_DIR < <(python3 - "$SPAWN_YAML" "$DRIVE_ROBOT" <<'PY'
import math, sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
want = sys.argv[2]
groups = (('scouts', 'scout'), ('excavators', 'excavator'), ('haulers', 'hauler'))
for key, model in groups:
    for i, pos in enumerate(cfg.get(key) or [], start=1):
        if f'{model}_{i:02d}' == want:
            yaw = float(pos.get('yaw', 0.0))
            print(pos['x'], pos['y'], pos['z'], yaw,
                  math.sin(yaw / 2.0), math.cos(yaw / 2.0), model)
            raise SystemExit(0)
raise SystemExit(f'ERROR: {want} not found in {sys.argv[1]}')
PY
)
if [ -z "${SX:-}" ] || [ -z "${MODEL_DIR:-}" ]; then
    echo "ERROR: could not read a spawn pose for '$DRIVE_ROBOT' from $SPAWN_YAML" >&2
    echo "       expected one of scout_01, scout_02, excavator_01, hauler_01" >&2
    exit 1
fi

MODEL_SDF="$SHARE/models/$MODEL_DIR/model.sdf"
[ -f "$MODEL_SDF" ] || { echo "ERROR: missing $MODEL_SDF" >&2; exit 1; }

# Per-robot, so a four-robot sweep keeps four server logs instead of overwriting
# one. Deterministic rather than PID-scoped on purpose: CI globs
# /tmp/selene_check_drive*.log to collect them, and a predictable name is what
# makes "which robot produced this log" answerable afterwards.
LOG="/tmp/selene_check_drive_${DRIVE_ROBOT}.log"
GZ_PID=""
# Kill ONLY the server this script started. Never pattern-match on "gz sim" or on
# the world file name — lunar_psr.sdf is the world everyone else runs too, and a
# broad pkill here would take down a developer's session (and, because the pattern
# matches its own command line, this script).
stop_gz() {
    [ -n "$GZ_PID" ] || return 0
    kill -TERM "$GZ_PID" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "$GZ_PID" 2>/dev/null || return 0
        sleep 0.5
    done
    kill -KILL "$GZ_PID" 2>/dev/null
    return 0
}
# The signal traps EXIT EXPLICITLY. `trap stop_gz EXIT INT TERM` with a handler
# that ends in `return 0` does NOT stop the script — the handler runs and execution
# RESUMES. Measured on the identical structure in check_terrain.sh: a SIGTERM tore
# down the Gazebo server and then the script carried on and printed RESULT: PASS
# and exited 0. This script has the same window: stop_gz is called before the
# verdict is computed, and the verdict comes from poses already captured, so a
# cancelled run can still print PASS. .github/workflows/sim-gates.yaml sets
# concurrency.cancel-in-progress, which makes that path reachable in CI today.
# stop_gz is idempotent, so running it twice is harmless.
trap stop_gz EXIT
trap 'stop_gz; exit 130' INT
trap 'stop_gz; exit 143' TERM

pose() {   # authoritative model pose: x y z roll pitch yaw, one number per line
    gz model -m "$DRIVE_ROBOT" -p 2>/dev/null \
        | tr -d '[]' | tr -s ' ' | awk '/^ *-?[0-9]/{print}'
}
odom() {   # DiffDrive odometry position, as "x y"
    timeout 8 gz topic -e -t "/model/$DRIVE_ROBOT/odometry" -n 1 2>/dev/null | python3 -c '
import re, sys
m = re.search(r"pose\s*\{.*?position\s*\{(.*?)\}", sys.stdin.read(), re.S)
f = dict(re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", m.group(1))) if m else {}
print(f.get("x", "nan"), f.get("y", "nan"))'
}
drive() {  # publish $1 repeatedly for $2 seconds
    local twist="$1" secs="$2" end
    end=$(( $(date +%s) + secs ))
    while [ "$(date +%s)" -lt "$end" ]; do
        gz topic -t "/model/$DRIVE_ROBOT/cmd_vel" -m gz.msgs.Twist -p "$twist" >/dev/null 2>&1
    done
}

echo "SELENE drive acceptance check"
echo "  workspace: $WS"
echo "  world:     $WORLD"
echo "  robot:     $DRIVE_ROBOT ($MODEL_DIR) at configured ($SX, $SY, $SZ) yaw $SYAW"
echo "  command:   linear.x=$DRIVE_SPEED for ${DRIVE_SECONDS}s, then angular.z=$TURN_RATE for ${TURN_SECONDS}s"
echo ""

# Start PAUSED so the heightmap collision mesh is complete before anything is
# spawned or stepped, then unpause and spawn into a running world — which is what
# simulation.launch.py's `create` nodes do.
gz sim -s -v 1 "$WORLD" > "$LOG" 2>&1 &
GZ_PID=$!
# CARRY THE POLL'S RESULT; DO NOT RE-QUERY. This loop used to break on a match and
# then a SECOND, independent `gz topic -l | grep -q` decided the verdict, so a
# transient failure of that one query reported "world never appeared" about a world
# that was demonstrably up — the loop had just matched it. Measured pinned to one
# CPU: the loop matched and broke on its first iteration and the re-check then did
# not match, failing in 5.2 s with a 0-byte server log. That is a false FAIL, and
# on a 2-4 vCPU hosted runner it is the likeliest way this gate goes red for a
# reason that has nothing to do with driving.
WORLD_UP=0
for _ in $(seq 1 60); do
    if gz topic -l 2>/dev/null | grep -q "/world/$WORLD_NAME/"; then
        WORLD_UP=1
        break
    fi
    sleep 0.5
done
if [ "$WORLD_UP" -ne 1 ]; then
    echo "FAIL: world $WORLD_NAME never appeared. See $LOG"
    exit 1
fi
sleep "$HEIGHTMAP_LOAD_SECONDS"
gz service -s "/world/$WORLD_NAME/control" --reqtype gz.msgs.WorldControl \
    --reptype gz.msgs.Boolean --timeout 5000 --req 'pause: false' >/dev/null 2>&1 \
    || { echo "FAIL: could not unpause $WORLD_NAME; results would be meaningless"; exit 1; }
sleep 2

gz service -s "/world/$WORLD_NAME/create" --reqtype gz.msgs.EntityFactory \
    --reptype gz.msgs.Boolean --timeout 10000 \
    --req "sdf_filename: \"$MODEL_SDF\", name: \"$DRIVE_ROBOT\", pose: {position: {x: $SX, y: $SY, z: $SZ}, orientation: {x: 0, y: 0, z: $QZ, w: $QW}}" \
    >/dev/null 2>&1 || { echo "FAIL: spawn service call failed. See $LOG"; exit 1; }
sleep "$SETTLE_SECONDS"

P0=$(pose)
[ -n "$P0" ] || { echo "FAIL: $DRIVE_ROBOT has no pose — did it spawn? See $LOG"; exit 1; }
O0=$(odom)
drive "linear: {x: $DRIVE_SPEED}" "$DRIVE_SECONDS"
gz topic -t "/model/$DRIVE_ROBOT/cmd_vel" -m gz.msgs.Twist -p 'linear: {x: 0.0}' >/dev/null 2>&1
sleep 1
P1=$(pose)
O1=$(odom)
drive "angular: {z: $TURN_RATE}" "$TURN_SECONDS"
gz topic -t "/model/$DRIVE_ROBOT/cmd_vel" -m gz.msgs.Twist \
    -p 'linear: {x: 0.0}, angular: {z: 0.0}' >/dev/null 2>&1
sleep 1
P2=$(pose)

stop_gz

python3 - "$SZ" "$DRIVE_SPEED" "$DRIVE_SECONDS" "$TURN_RATE" "$TURN_SECONDS" \
         "$MIN_FRACTION" "$MAX_FRACTION" "$MAX_SLIP_PCT" "$MIN_TURN_RAD" \
         "$P0" "$P1" "$P2" "$O0" "$O1" <<'PY'
import math
import sys

a = sys.argv[1:]
spawn_z, speed, secs, turn_rate, turn_secs = (float(a[0]), float(a[1]),
                                              float(a[2]), float(a[3]), float(a[4]))
min_frac, max_frac, max_slip, min_turn = (float(a[5]), float(a[6]),
                                          float(a[7]), float(a[8]))
nums = [float(v) for v in ' '.join(a[9:]).split()]
if len(nums) != 22:                       # 3 poses x 6 + 2 odom x 2
    print(f"FAIL: expected 22 numbers from Gazebo, got {len(nums)}: {nums}")
    raise SystemExit(1)
p0, p1, p2 = nums[0:6], nums[6:12], nums[12:18]
o0, o1 = nums[18:20], nums[20:22]

commanded = speed * secs
world = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
odo = math.hypot(o1[0] - o0[0], o1[1] - o0[1])
slip = 100.0 * (1.0 - world / odo) if odo > 1e-6 else float('nan')
turn = p2[5] - p1[5]
# unwrap to (-pi, pi]
turn = (turn + math.pi) % (2 * math.pi) - math.pi

print(f"{'':14}{'x':>12} {'y':>12} {'z':>10} {'yaw':>10}")
print(f"{'settled':14}{p0[0]:>12.6f} {p0[1]:>12.6f} {p0[2]:>10.6f} {p0[5]:>10.6f}")
print(f"{'after drive':14}{p1[0]:>12.6f} {p1[1]:>12.6f} {p1[2]:>10.6f} {p1[5]:>10.6f}")
print(f"{'after turn':14}{p2[0]:>12.6f} {p2[1]:>12.6f} {p2[2]:>10.6f} {p2[5]:>10.6f}")
print()
print(f"  spawned at z          {spawn_z:.6f}   settled at z {p0[2]:.6f} "
      f"({p0[2] - spawn_z:+.6f})")
print(f"  commanded distance    {commanded:.4f} m")
print(f"  WORLD  displacement   {world:.4f} m   ({100 * world / commanded:.1f}% of command)")
print(f"  ODOM   displacement   {odo:.4f} m")
print(f"  slip                  {slip:.2f} %")
print(f"  height gained         {p1[2] - p0[2]:+.4f} m")
print(f"  yaw change on turn    {turn:+.4f} rad  (commanded {turn_rate * turn_secs:.2f})")
print()

failures = []
if p0[2] > spawn_z:
    failures.append(
        f"BURIED: settled z {p0[2]:.6f} is ABOVE spawn z {spawn_z:.6f}. A robot on "
        f"the surface falls; one created inside the heightfield is extruded upward "
        f"at ~1 mm/s. Survey the collision surface at ({p0[0]:.0f},{p0[1]:.0f}) and "
        f"raise z in selene_sim/config/spawn_positions.yaml.")
if world < min_frac * commanded:
    failures.append(
        f"NOT DRIVING: world displacement {world:.4f} m is under {min_frac:.0%} of "
        f"the commanded {commanded:.4f} m. Odometry read {odo:.4f} m, which proves "
        f"only that the wheel joints turned.")
if world > max_frac * commanded:
    failures.append(
        f"RUNAWAY: world displacement {world:.4f} m exceeds {max_frac:.0%} of the "
        f"commanded {commanded:.4f} m — sliding or being ejected, not driving.")
if not math.isnan(slip) and abs(slip) > max_slip:
    failures.append(
        f"SLIP {slip:.1f}% exceeds {max_slip:.0f}%: world {world:.4f} m vs odometry "
        f"{odo:.4f} m.")
if abs(turn) < min_turn:
    failures.append(
        f"NO TURN: heading changed {turn:+.4f} rad, under {min_turn:.2f} rad, on a "
        f"commanded {turn_rate * turn_secs:.2f} rad.")

if failures:
    print(f"RESULT: FAIL — {len(failures)} problem(s)")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: PASS — the robot translates in the world consistently with the "
      "command, settled onto the surface rather than inside it, and turns.")
PY
RC=$?

echo ""
echo "Gazebo log: $LOG"
exit "$RC"
