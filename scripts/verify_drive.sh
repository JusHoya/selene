#!/bin/bash
# PLANE-ONLY DRIVE SMOKE TEST — NOT terrain validation.
#
# WHAT THIS DOES: spawns one scout on a bare, flat, infinite plane under LUNAR
# gravity and checks that commanding cmd_vel moves it. That is all. It exists so
# you can tell "the model, the DiffDrive plugin and the Gazebo install are wired
# up at all" from "the world is wrong", without waiting for a heightmap to load.
#
# WHAT THIS CANNOT DO — read this before trusting a green result. On a plane the
# ground is at z=0, so a robot spawned at any z>0 simply falls onto it. No
# flat-ground test can ever detect a spawn height that is wrong relative to
# TERRAIN, and that is precisely the defect that immobilised the entire fleet:
# every robot was spawned ~1.0-3.8 m below the lunar heightmap's collision
# surface, reported healthy odometry, and moved 0.0000 m. This script passed
# throughout. Two further reasons it gave false assurance, both now fixed:
#   * <gravity> was nested inside <physics>, which SDF 1.9 ignores, so it silently
#     ran at Earth gravity (-9.81) — the opposite of the target environment.
#   * it published to /cmd_vel, but gz-sim's DiffDrive subscribes to
#     /model/<name>/cmd_vel by default, so nothing was ever commanded; and the
#     script had no assertion of any kind, so it exited 0 unconditionally.
#
# FOR REAL VALIDATION USE scripts/check_drive.sh — it drives on lunar_psr.sdf at
# the poses in selene_sim/config/spawn_positions.yaml and fails on burial and slip.
# Use scripts/check_terrain.sh for placement of static objects.
#
# USAGE
#   bash scripts/verify_drive.sh          # uses the repo checkout this file is in
#   SELENE_WS=$HOME/selene bash scripts/verify_drive.sh
#
# Exit 0 if the scout translates; exit 1 if it does not.

set -uo pipefail

# Workspace root is derived from this script's location; override with SELENE_WS
# (e.g. SELENE_WS=$HOME/selene to test the synced ext4 copy). Note this points at
# the SOURCE tree, not install/ — the point is to be runnable before a colcon build.
SELENE_WS="${SELENE_WS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SPEED="${SPEED:-0.4}"
SECONDS_DRIVE="${SECONDS_DRIVE:-10}"
# Plane, lunar gravity, no slope, no slip to speak of: MEASURED 4.87 m of the
# 4.80 m commanded at 0.4 m/s for 12 s, minus DiffDrive's 0.8 s acceleration ramp.
# 0.60 is a smoke-test threshold, not a precision one.
MIN_FRACTION="${MIN_FRACTION:-0.60}"

set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash 2>/dev/null || source /opt/ros/humble/setup.bash
set -u

export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
# Isolate gz transport so a simulation already running on this machine cannot
# answer our queries; the world name below is fixed.
export GZ_PARTITION="${GZ_PARTITION:-selene_verify_drive_$$}"

WORLD=/tmp/selene_verify_drive.sdf
cat > "$WORLD" << 'EOFWORLD'
<?xml version="1.0"?>
<sdf version="1.9">
  <world name="flat">
    <!-- Lunar gravity, at WORLD scope. SDF 1.9 defines <gravity> as a child of
         <world> only; nesting it inside <physics> - which this file used to do -
         is silently ignored and leaves the world at Earth's -9.81. -->
    <gravity>0 0 -1.62</gravity>
    <physics name="fast" type="ode">
      <max_step_size>0.002</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <model name="ground">
      <static>true</static>
      <link name="l">
        <collision name="c">
          <geometry><plane><normal>0 0 1</normal><size>600 600</size></plane></geometry>
          <!-- Same friction as lunar_terrain, so a pass here is not bought with
               grip the real ground does not have. -->
          <surface><friction><ode><mu>0.7</mu><mu2>0.5</mu2></ode></friction></surface>
        </collision>
      </link>
    </model>
  </world>
</sdf>
EOFWORLD

MODELS="$SELENE_WS/selene_sim/models"
SCOUT="$MODELS/scout/model.sdf"
[ -f "$SCOUT" ] || { echo "ERROR: no scout model at $SCOUT" >&2; exit 1; }
export GZ_SIM_RESOURCE_PATH="$MODELS:${GZ_SIM_RESOURCE_PATH:-}"

GZ_PID=""
# Kill ONLY the server this script started. Never pattern-match on "gz sim":
# the pattern also matches this script's own command line, and it would take down
# any other simulation on the machine.
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
trap stop_gz EXIT INT TERM

echo "SELENE plane-only drive smoke test (NOT terrain validation)"
echo "  models:  $MODELS"
echo "  gravity: -1.62 m/s^2 (lunar), flat plane"
echo ""

gz sim -s -r "$WORLD" > /tmp/selene_verify_drive.log 2>&1 &
GZ_PID=$!
for _ in $(seq 1 40); do
    gz topic -l 2>/dev/null | grep -q "/world/flat/" && break
    sleep 0.5
done

echo "Spawning scout as 's1'..."
gz service -s /world/flat/create \
  --reqtype gz.msgs.EntityFactory --reptype gz.msgs.Boolean --timeout 8000 \
  --req "sdf_filename: \"$SCOUT\", name: \"s1\", pose: {position: {x: 0, y: 0, z: 0.5}}" \
  >/dev/null 2>&1 || { echo "FAIL: spawn service call failed. See /tmp/selene_verify_drive.log"; exit 1; }
sleep 4

pose() {
    gz model -m s1 -p 2>/dev/null | tr -d '[]' | tr -s ' ' | awk '/^ *-?[0-9]/{print}'
}

echo ""
echo "=== TOPICS ==="
gz topic -l | grep -E "s1/(cmd_vel|odometry)" || echo "  WARNING: no s1 cmd_vel/odometry topic"

P0=$(pose)
[ -n "$P0" ] || { echo "FAIL: s1 has no pose — did it spawn?"; exit 1; }

# DiffDrive subscribes to /model/<name>/cmd_vel unless the model overrides <topic>.
# The old version of this script published to /cmd_vel, which nothing listened to.
echo ""
echo "=== DRIVING linear.x=$SPEED for ${SECONDS_DRIVE}s on /model/s1/cmd_vel ==="
END=$(( $(date +%s) + SECONDS_DRIVE ))
while [ "$(date +%s)" -lt "$END" ]; do
    gz topic -t /model/s1/cmd_vel -m gz.msgs.Twist -p "linear: {x: $SPEED}" >/dev/null 2>&1
done
gz topic -t /model/s1/cmd_vel -m gz.msgs.Twist -p 'linear: {x: 0.0}' >/dev/null 2>&1
sleep 1
P1=$(pose)

stop_gz

python3 - "$SPEED" "$SECONDS_DRIVE" "$MIN_FRACTION" "$P0" "$P1" <<'PY'
import math
import sys

speed, secs, min_frac = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
nums = [float(v) for v in ' '.join(sys.argv[4:]).split()]
if len(nums) != 12:
    print(f"FAIL: expected 12 pose numbers from Gazebo, got {len(nums)}: {nums}")
    raise SystemExit(1)
p0, p1 = nums[0:6], nums[6:12]
commanded = speed * secs
moved = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
print(f"\n=== POSE BEFORE ===  x={p0[0]:.6f} y={p0[1]:.6f} z={p0[2]:.6f}")
print(f"=== POSE AFTER  ===  x={p1[0]:.6f} y={p1[1]:.6f} z={p1[2]:.6f}")
print(f"\n  commanded {commanded:.2f} m, moved {moved:.4f} m "
      f"({100 * moved / commanded:.1f}%)")
if moved < min_frac * commanded:
    print(f"\nRESULT: FAIL — moved {moved:.4f} m, under {min_frac:.0%} of the "
          f"commanded {commanded:.2f} m on a flat plane. Something is wrong with "
          f"the model, the DiffDrive wiring or the Gazebo install itself.")
    raise SystemExit(1)
print("\nRESULT: PASS (plane only). This says nothing about the lunar terrain — "
      "run scripts/check_drive.sh for that.")
PY
RC=$?
echo ""
echo "Gazebo log: /tmp/selene_verify_drive.log"
exit "$RC"
