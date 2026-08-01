#!/bin/bash
# D-37 exposure campaign: 4/3/3 fleet held DRIVING, fleet-metres instrumented.
#
# Usage:
#   bash scripts/d37_drive_campaign.sh [seconds]
#
# WHY THIS RUNS simulation.launch.py AND NOT unified_sim.launch.py. The abort is
# raised inside SimulationRunner::Step -> Physics::Update -> dartsim
# WorldForwardStep -> ConstraintSolver::solve -> dxHashSpace::collide. No line of
# selene_agent or selene_orchestrator is on that stack, so removing them removes
# nothing the hazard depends on -- and it removes the one thing that made this
# experiment impossible, which is the fleet taking itself to the charger. Nothing
# in the physics consumes BatteryState (no <battery> element and no
# LinearBatteryPlugin anywhere in selene_sim), so with no agents a flat battery
# stops no wheel. See scripts/d37_drive_campaign.py's docstring.
#
# The console is TEE'd and gz is run at -v 4 with stdbuf line buffering, because
# D-37 records that the archived crash logs are no longer on disk and because a
# block-buffered stdout loses the last few KB on SIGABRT -- which is exactly the
# few KB that matter.
# NO `set -u`. ROS 2's own setup.bash dereferences AMENT_TRACE_SETUP_FILES
# unbound and aborts under it, which is a failure of this script rather than of
# the environment -- and a campaign that dies before Gazebo starts measures
# nothing. Every variable below is defaulted explicitly instead.
SECONDS_TO_RUN="${1:-2700}"

# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash
SELENE_DIR="${SELENE_DIR:-$HOME/selene}"
cd "$SELENE_DIR" || { echo "no workspace at $SELENE_DIR" >&2; exit 3; }
# shellcheck source=/dev/null
source install/setup.bash
export GZ_SIM_RESOURCE_PATH="$SELENE_DIR/selene_sim/models"
export GZ_PARTITION="selene_d37_$$"

OUT="$SELENE_DIR/d37_campaign_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
echo "OUT=$OUT"

echo "=== PRE-FLIGHT: this run must be the only stack on the box ==="
if pgrep -f 'selene_sim/battery_node|selene_agent/agent_node|gz sim' >/dev/null 2>&1; then
    echo "ERROR: SELENE processes are already running. A second stack shares every" >&2
    echo "       topic (register D-42) and competes for the CPU this measurement" >&2
    echo "       is timing. Stop them first." >&2
    exit 3
fi

FLEET="scout_01,scout_02,scout_03,scout_04,excavator_01,excavator_02,excavator_03,hauler_01,hauler_02,hauler_03"

echo "=== LAUNCH 4/3/3, simulator layer only (no agents, no orchestrator) ==="
stdbuf -oL -eL ros2 launch selene_sim simulation.launch.py \
    num_scouts:=4 num_excavators:=3 num_haulers:=3 \
    > "$OUT/launch.log" 2>&1 &
LP=$!
echo "launch pid $LP"

# Spawns are staggered 2 s apart; ten robots need ~20 s plus world load.
sleep 40

echo "=== CAMPAIGN (${SECONDS_TO_RUN}s cap) ==="
echo "GO/NO-GO is at minute 3: if the achieved rate is below 0.10 m/robot-second"
echo "the run needs 2 hours rather than 45 minutes and should be abandoned."
python3 "$SELENE_DIR/scripts/d37_drive_campaign.py" \
    --robots "$FLEET" \
    --out-dir "$OUT" \
    --seconds "$SECONDS_TO_RUN" \
    2>&1 | tee "$OUT/campaign.log"

echo
echo "=== THE THREE STRINGS THAT DECIDE THE DIAGNOSIS ==="
echo "--- 1. the ODE assertion (D-37's signature) ---"
grep -F "ODE INTERNAL ERROR" "$OUT/launch.log" || echo "  (absent -- no abort in this run)"
echo "--- 2. the upstream NaN guard (gz-physics PR #706/#707) ---"
grep -F "have invalid poses" "$OUT/launch.log" || echo "  (absent)"
echo "     PRESENT + no abort  => the guard caught it; the post-step inference is WRONG"
echo "     ABSENT  + an abort  => the guard never saw it; the post-step inference STANDS"
echo "--- 3. the simulator dying at all ---"
grep -E "process has died|exit code (134|-6)" "$OUT/launch.log" || echo "  (absent)"

echo
echo "=== FINAL EXPOSURE ==="
cat "$OUT/campaign_state.json" 2>/dev/null

echo
echo "=== TEARDOWN ==="
kill -INT "$LP" 2>/dev/null
sleep 10
pkill -9 -f "GZ_PARTITION=$GZ_PARTITION" 2>/dev/null
pkill -9 -f 'gz sim|ruby.*gz' 2>/dev/null
echo "OUT=$OUT"
