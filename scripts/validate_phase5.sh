#!/bin/bash
# Phase 5 exit gate validation.
#
# Runs from a WSL2 environment with ROS 2 Jazzy + the SELENE workspace built.
# Usage:
#   bash scripts/sync_and_build.sh    # ensure the workspace is built first
#   bash scripts/validate_phase5.sh
#
# For the fast dashboard path, build the production bundle first:
#   SELENE_PREBUILD_DASHBOARD=1 bash scripts/sync_and_build.sh
# This script then auto-selects prebuilt:=true.
#
# Environment overrides:
#   NUM_SCOUTS / NUM_EXCAVATORS / NUM_HAULERS   fleet size (default 2/1/1)
#   SELENE_PHASE5_REPORT                        report path
#   SELENE_PREBUILT_DASHBOARD                   1 / 0 to force the dashboard mode
#   SELENE_WORLD_NAME                           gz world name (default lunar_psr)
#   SELENE_READY_TIMEOUT                        boot readiness cap, s (default 90)
#
# EXIT CODES — this is the whole D-10 lesson expressed as an exit status:
#   0  every PRD exit-gate row is PASS, or is an explicitly listed NOT COVERED row
#   1  at least one check FAILED
#   2  at least one check was SKIPPED — a measurement that could not be taken
#      is NOT a pass, and this gate will not certify what it did not measure
#   3  the gate could not start (no ROS, no workspace, launch died)
#
# ---------------------------------------------------------------------------
# WHAT CHANGED, AND WHY (deviation D-10, docs/phase5_deviation_register.md)
#
# The previous version of this script ran eight checks, passed 8/8, and printed
# a report that read as though the Phase 5 exit gate had been met. Mapped against
# the PRD's own seven exit-gate rows (docs/PRD.md:1503-1509) it covered ONE row
# end to end, three with liveness proxies, and three not at all — and the one it
# covered end to end tested a different override (force_recharge) from the one
# the row names (send-to-location).
#
# The proxies were not merely weak, they were each satisfiable by the failure
# they looked like they were testing:
#   * "Single launch command starts full system" was `kill -0` on the launch PID.
#     VERIFIED by grep: no launch file in this repository converts a child exit
#     into a launch shutdown (`on_exit`, `OnProcessExit`, `required=` and
#     `Shutdown` appear in none of selene_sim/launch, selene_agent/launch or
#     selene_orchestrator/launch), so `ros2 launch` stays alive with Gazebo, the
#     orchestrator, or every agent dead. That check passed on a dead system.
#   * "Dashboard shows all robots" counted topic NAMES ending in /state and
#     required >= 4. It asserted nothing about content, rate or freshness, and
#     since D-07 made the fleet size configurable the literal 4 was also wrong:
#     this script passed no num_* argument, so it silently tested the default
#     and would have passed a 4/3/3 launch that started only four agents.
#   * "Dashboard renders" was `curl` returning 200, which a static file server
#     satisfies while serving a broken bundle.
#   * "Operator-injected task enters auction" echoed ONE task_announcement after
#     injecting and never compared the id — and ten HTN survey tasks are queued
#     at startup, so an announcement appears whether or not the injection worked.
#
# What replaced them:
#   * the fleet is DERIVED here and PASSED to `ros2 launch`, so the expected node
#     set and the launched fleet come from one source;
#   * the blind `sleep 30` became a readiness poll on the real node set and on
#     Gazebo's own sim_time advancing;
#   * the content, rate, freshness, latency and correlation checks moved into
#     scripts/phase5_probe.py — one long-lived rclpy node with a continuous
#     recording window, because none of those quantities is expressible with
#     `ros2 topic echo --once`;
#   * PASS/FAIL/**SKIP**, and a footer GENERATED from a machine-readable mapping
#     of the seven PRD rows to the checks covering them, so the report and the
#     script cannot drift apart again. That mapping is itself asserted by
#     selene_orchestrator/test/test_phase5_gate_coverage.py in the ROS-free CI
#     lane.
#
# WHAT THIS SCRIPT STILL CANNOT DO. Every one of the PRD's stated exit-gate
# METHODS is human or visual — "visual inspection", "side-by-side comparison",
# "observe robot execution", "performance profiling in browser dev tools". None
# of them is performed here and none of them can be performed by a script. What
# a green run means is stated in the generated footer, in those terms, and the
# footer is built from the mapping rather than written by hand for exactly the
# reason D-10 exists.
#
# EXPECTED WALL CLOCK, end to end: roughly 2.6 minutes with a prebuilt dashboard
# bundle and a fleet that goes idle promptly (the check 10 seed added ~4 s on
# 2026-07-31); up to about 6 minutes worst case
# (dev-server compile, plus the probe waiting its full 60 s for an idle
# prospect-capable robot). The old script was about 100 s. Every check below
# states its own expected cost, because a gate nobody is willing to run is worth
# nothing.
# ---------------------------------------------------------------------------

set -uo pipefail

P=$HOME/selene
# ABSOLUTE, and anchored to the workspace. This was a bare relative filename, so
# the report landed in whatever directory the caller happened to be in —
# including the repo checkout, where nothing gitignores it and a `git add -A`
# would commit it. It is written before the first check, so it landed there even
# on runs that then failed immediately.
REPORT="${SELENE_PHASE5_REPORT:-$P/phase5_validation_report.md}"
LAUNCH_LOG=/tmp/selene_unified_launch.log
PROBE_LOG="/tmp/selene_phase5_probe.$$.log"
PROBE_OUT="/tmp/selene_phase5_probe.$$.txt"
PROBE_JSON="/tmp/selene_phase5_probe.$$.json"
WORLD_NAME="${SELENE_WORLD_NAME:-lunar_psr}"
READY_TIMEOUT="${SELENE_READY_TIMEOUT:-90}"

# THE FLEET IS DERIVED HERE AND PASSED TO THE LAUNCH. Since D-07 the counts are
# real launch arguments; this script used to pass none of them and then assert a
# hardcoded ">= 4" state topics, which is a latent defect in both directions.
NUM_SCOUTS="${NUM_SCOUTS:-2}"
NUM_EXCAVATORS="${NUM_EXCAVATORS:-1}"
NUM_HAULERS="${NUM_HAULERS:-1}"

# ROS 2 setup.bash references unset vars; disable nounset just for sourcing.
#
# THE PRE-FLIGHT IS CHECKED. `set +u` with no `set -e` meant a missing workspace
# was survivable: `cd` failed, the script carried on IN THE CALLER'S DIRECTORY,
# `source install/setup.bash` failed too, and every check below then ran against
# a workspace that had never been sourced — reporting failures whose real cause
# ("there is no build here") appeared nowhere in the report.
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
    echo "ERROR: ROS 2 Jazzy not found at /opt/ros/jazzy/setup.bash" >&2
    echo "       run scripts/setup_wsl2.sh first." >&2
    exit 3
fi
if [ ! -f "$P/install/setup.bash" ]; then
    echo "ERROR: no built workspace at $P/install/setup.bash" >&2
    echo "       run scripts/sync_and_build.sh first." >&2
    exit 3
fi
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
cd "$P" || { echo "ERROR: cannot cd to $P" >&2; exit 3; }
# shellcheck disable=SC1091
source "$P/install/setup.bash"
set -u

# The probe travels with this script. Prefer the copy beside it (works from a
# source checkout and from an rsynced workspace alike) and fall back to the
# workspace copy.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROBE="$SCRIPT_DIR/phase5_probe.py"
[ -f "$PROBE" ] || PROBE="$P/scripts/phase5_probe.py"
if [ ! -f "$PROBE" ]; then
    echo "ERROR: cannot find phase5_probe.py (looked beside this script and in" >&2
    echo "       $P/scripts). The gate cannot measure anything without it." >&2
    exit 3
fi

# The probe reads ice_deposits.yaml (to decide whether the hottest posterior
# cell landed on a real deposit) and selene_sim.rviz (to check the overlay's
# frame_id against RViz2's Fixed Frame — nothing in this repo publishes TF, so
# those two strings must agree or the overlay renders into an empty scene).
# Both are optional to the probe: it degrades those sub-assertions and says so
# rather than failing on a path it could not resolve.
SIM_PREFIX=$(ros2 pkg prefix selene_sim 2>/dev/null) || SIM_PREFIX=""
if [ -n "$SIM_PREFIX" ]; then
    ICE_CONFIG="$SIM_PREFIX/share/selene_sim/config/ice_deposits.yaml"
    RVIZ_CONFIG="$SIM_PREFIX/share/selene_sim/rviz/selene_sim.rviz"
else
    ICE_CONFIG=""
    RVIZ_CONFIG=""
    echo "WARNING: ros2 pkg prefix selene_sim failed; check 10 will run without" >&2
    echo "         the deposit layout and the RViz2 fixed-frame comparison." >&2
fi

# --------------------------------------------------------------------------
# Derived fleet, expected nodes and expected topics.
#
# Node names are read from launch-file source, not observed:
#   orchestrator.launch.py      no name= -> the node's own name,
#                               orchestrator_node.py:873     -> /orchestrator_node
#   agent.launch.py             name=['agent_', robot_id]    -> /agent_<rid>
#   simulation.launch.py:163    name=f'bridge_{robot_id}'    -> /bridge_<rid>
#   simulation.launch.py        name=f'world_odom_{robot_id}' -> /world_odom_<rid>
#   simulation.launch.py:196    name=f'battery_{robot_id}'   -> /battery_<rid>
#   simulation.launch.py:208    neutron_spec_<rid>   (scouts only)
#   simulation.launch.py:216    hopper_<rid>         (excavators only)
#   simulation.launch.py:227    extraction_<rid>     (excavators only)
#   simulation.launch.py:235    bin_load_<rid>       (haulers only)
# plus /rosbridge_websocket from rosbridge_suite's own launch file.
#
# /rosapi is deliberately NOT required here: its node name varies between
# rosbridge_suite releases and this script cannot verify which one is installed.
# The rosapi service is exercised functionally instead, inside check 4, over the
# same call path useFleetDiscovery.js uses.
#
# THE ORCHESTRATOR IS /orchestrator_node, NOT /orchestrator, SINCE 2026-07-31.
# orchestrator.launch.py used to override the name to `orchestrator`, which is
# what made orchestrator_params.yaml (keyed `orchestrator_node:`) match nothing
# and apply none of its values — deviation D-12. The override is gone, so every
# entry point now produces the one name the node gives itself. If this list ever
# says /orchestrator again while the parameter file says orchestrator_node, the
# gate will fail loudly on a missing node instead of certifying a system running
# entirely on defaults.
# --------------------------------------------------------------------------
#
# /world_odom_<rid> IS NOT OPTIONAL FURNITURE. It is the single place a
# dead-reckoned pose becomes a world pose, and it publishes the only odometry
# topic the RCDLs declare. If it is missing, every agent waits in IDLE for
# odometry that never arrives, the battery samples shadow at (0, 0) and the
# spectrometer surveys the origin — a fleet that is up, healthy and doing
# nothing. Required here so that presents as a named missing node instead.
# --------------------------------------------------------------------------
FLEET=()
EXPECTED_NODES=("/orchestrator_node" "/rosbridge_websocket")
for i in $(seq 1 "$NUM_SCOUTS"); do
    rid=$(printf 'scout_%02d' "$i")
    FLEET+=("$rid")
    EXPECTED_NODES+=("/agent_$rid" "/bridge_$rid" "/world_odom_$rid" \
                     "/battery_$rid" "/neutron_spec_$rid")
done
for i in $(seq 1 "$NUM_EXCAVATORS"); do
    rid=$(printf 'excavator_%02d' "$i")
    FLEET+=("$rid")
    EXPECTED_NODES+=("/agent_$rid" "/bridge_$rid" "/world_odom_$rid" \
                     "/battery_$rid" "/hopper_$rid" "/extraction_$rid")
done
for i in $(seq 1 "$NUM_HAULERS"); do
    rid=$(printf 'hauler_%02d' "$i")
    FLEET+=("$rid")
    EXPECTED_NODES+=("/agent_$rid" "/bridge_$rid" "/world_odom_$rid" \
                     "/battery_$rid" "/bin_load_$rid")
done
FLEET_CSV=$(IFS=,; echo "${FLEET[*]}")

# Topics that must have at least one live PUBLISHER. `ros2 topic list` reports
# names the graph has heard of; a name can appear there with no publisher behind
# it, which is why this asks the publisher-count question instead.
REQUIRED_TOPICS=(
    "/orchestrator/task_announcement"
    "/orchestrator/task_assignment"
    "/orchestrator/mission_progress"
    "/orchestrator/resource_map"
    "/orchestrator/resource_map_markers"
)

# --------------------------------------------------------------------------
# THE PRD MAPPING. Everything the report says about coverage is generated from
# the three tables below, and selene_orchestrator/test/test_phase5_gate_coverage.py
# fails the ROS-free CI lane if they drift from docs/PRD.md or from
# scripts/phase5_probe.py's CHECK_TITLES.
# --------------------------------------------------------------------------

# VERBATIM from the exit-gate table at docs/PRD.md:1503-1509. Do not paraphrase:
# the coverage test compares these strings byte for byte against the PRD.
PRD_ROWS=(
    "Dashboard shows all robots with correct real-time state"
    "Resource heatmap matches RViz2 visualization"
    "Task queue reflects orchestrator state within 1 second"
    "Operator-injected task enters auction and gets assigned"
    "Robot override (send-to-location) works"
    "Single launch command starts full system"
    "Dashboard renders at 1 Hz with 4 robots without lag"
)

# Checks covering each row, index-aligned with PRD_ROWS. "none" is a legal and
# explicit value meaning NOT COVERED; NOT_COVERED_REASONS then has to say why.
ROW_CHECKS=(
    "4"
    "10"
    "9"
    "5 6"
    "11"
    "1 2 3"
    "none"
)

# Index-aligned with PRD_ROWS; only rows whose ROW_CHECKS is "none" need one.
NOT_COVERED_REASONS=(
    ""
    ""
    ""
    ""
    ""
    ""
    "needs a browser: frame timing and dropped frames are visible only in devtools, and no browser is started anywhere in this gate. Check 2 fetches and inspects the bundle and MUST NOT be read as a proxy for it."
)

# WHAT KIND OF EVIDENCE each row's checks produce, index-aligned with PRD_ROWS
# and printed as its own column of the generated table.
#
# WHY THIS IS A COLUMN AND NOT A PARAGRAPH. The register table this generator
# replaced (D-10) had exactly this column — its values were "weak proxy", "no
# check", "partial". Keeping the verdicts and dropping the qualifier prints an
# unqualified PASS beside a row whose PRD method — a browser, RViz2, an operator
# at the dashboard — was never performed, and pushes the caveat into prose
# further down that a reader scanning a verdict table will not weigh. That is
# D-10 again at reduced amplitude, which is why it is generated from a table the
# ROS-free lane asserts rather than written once by hand.
#
# "end-to-end" is reserved for a row the gate really does exercise from stimulus
# to consequence. Anything else must start "proxy:" and NAME THE UNMEASURED
# HALF; there is no comfortable third value. No entry may contain a "|", which
# would break the markdown table it is printed into.
ROW_COVERAGE_KIND=(
    "proxy: message content, rate, freshness and the exact fleet membership the dashboard's own rosapi discovery call returns. No browser renders any of it, so 'shows' is not tested — only that correct state is available to be shown."
    "proxy: both renderers are proven to be functions of ONE snapshot through ONE colour law, and the hottest cell of the fused posterior is proven to decode row-major onto the ice. THE MAP IS SEEDED BY THE GATE to make that second half reachable: the probe publishes synthetic ResourceMapUpdate readings shaped like ice_deposits.yaml onto /orchestrator/map_update, so the fusion, sparse encoding and marker publishing are the system's own but the readings are not. That proves the map pipeline is correct on that input; it does NOT prove that robots autonomously survey the deposits, which is a slower property this gate does not measure. RViz2 is never launched and no image is compared; the recomputation uses selene_orchestrator.resource_map_viz, the same module the publisher used, so a defect inside that module is invisible to this check."
    "proxy: measured from the orchestrator's TaskAssignment to websocket arrival only. The 2 Hz snapshot carries up to 500 ms of quantisation and the React reducer and canvas draw are unmeasured, so this bounds the row from below — it can prove a violation, not conformance."
    "end-to-end: the injected task_id is correlated through announcement and assignment with the target matched to 1e-3. Check 5 names the transport actually used; it is the dashboard's own rosbridge call_service path unless it reports the rclpy fallback. No browser issues the call."
    "proxy: the override is issued over the ROS service and verified through FSM state, planned path and odometry. The dashboard's transport and its UI are not exercised. The displacement is read off a pose that is world-referenced since 2026-07-31 (register D-08's open item; selene_sim world_odometry_node applies each robot's spawn SE(2) once) but STILL DEAD-RECKONED, so it advances whether or not the robot moved in the world — scripts/check_drive.sh is the only thing here that asks Gazebo. The planned-path assertion is what proves the target itself was honoured."
    "end-to-end: one ros2 launch, then the derived node set, Gazebo stepping with every model present, and publisher counts on the orchestrator's topics. 'Full system' here means the ROS graph plus a served bundle — the dashboard half is check 2, which inspects the bundle and never executes it."
    "not covered"
)

# Checks that cover no PRD row, each with the reason it is kept. Listed so that
# "every check is mapped somewhere" stays a real invariant instead of a fiction.
EXTRA_CHECKS=(
    "7|force_recharge override, FR-DASH-6. PRD row 5 names send-to-location, which is check 11; this is kept because it was the one end-to-end path the pre-D-10 gate had."
    "8|the FSM consequence of check 7, kept with it."
)

# Every check this gate emits: number|owner|title. Titles for probe-owned checks
# are the SAME STRINGS as CHECK_TITLES in scripts/phase5_probe.py, and the
# coverage test enforces that.
CHECK_CATALOG=(
    "1|shell|Single launch command starts the full system"
    "2|probe|Dashboard bundle is served and is a compiled application bundle"
    "3|probe|rosbridge speaks the websocket protocol"
    "4|probe|Robot state content, freshness, rate and fleet membership"
    "5|probe|Operator-injected task accepted"
    "6|probe|Injected task is announced and assigned, correlated by task_id"
    "7|probe|Robot override (force_recharge) accepted"
    "8|probe|Robot FSM reaches RECHARGING after force_recharge"
    "9|probe|Task queue reflects orchestrator state within 1 second"
    "10|probe|Resource heatmap and RViz2 overlay derive from one snapshot"
    "11|probe|Robot override (send_to_location) drives the robot to the target"
)

declare -A CHECK_RESULT
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

catalog_title() {   # $1 = check number
    local entry
    for entry in "${CHECK_CATALOG[@]}"; do
        if [ "${entry%%|*}" = "$1" ]; then
            printf '%s' "${entry##*|}"
            return 0
        fi
    done
    printf 'check %s' "$1"
}

# THREE RESULTS, NOT TWO. A SKIP is a measurement that could not be taken; it is
# never counted as a PASS and it changes the exit code. The old two-way check()
# had no way to say "the fleet never went idle, so this row was not tested" and
# would have had to choose between a false PASS and a misleading FAIL.
record_check() {   # $1=number $2=PASS|FAIL|SKIP $3=title $4=details
    local number="$1" result="$2" title="$3" details="$4"
    case "$result" in
        PASS) PASS_COUNT=$((PASS_COUNT + 1)) ;;
        FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
        SKIP) SKIP_COUNT=$((SKIP_COUNT + 1)) ;;
        *)    result=FAIL; FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
    esac
    CHECK_RESULT["$number"]="$result"
    printf '| %s | %s | %s | %s |\n' "$number" "$title" "$result" "$details" >> "$REPORT"
    printf '[%s] %s. %s - %s\n' "$result" "$number" "$title" "$details"
}

# --------------------------------------------------------------------------
# Provenance and the report header.
#
# PROVENANCE IN THE REPORT, not just a date. A validation report that cannot
# name the commit and the toolchain it validated is not evidence — it is an
# assertion. The commit comes from .selene_source_commit, which
# scripts/sync_and_build.sh writes at rsync time, because the rsync excludes
# .git and nothing here could otherwise work it out.
# --------------------------------------------------------------------------
SRC_COMMIT=$(cat "$P/.selene_source_commit" 2>/dev/null) || SRC_COMMIT=""
[ -n "$SRC_COMMIT" ] || SRC_COMMIT="unknown (run scripts/sync_and_build.sh to record it)"
GZ_VER=$(gz sim --versions 2>/dev/null | head -1)
[ -n "$GZ_VER" ] || GZ_VER="not found"
OS_VER=$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -sr)

cat > "$REPORT" <<HEADER
# SELENE Phase 5 Exit Gate Validation Report

_Generated $(date)_

| | |
|---|---|
| Source commit | \`$SRC_COMMIT\` |
| Workspace | \`$P\` |
| ROS 2 | ${ROS_DISTRO:-unknown} |
| Gazebo (gz sim) | $GZ_VER |
| OS | $OS_VER |
| Fleet | ${#FLEET[@]} robots: $FLEET_CSV |
| Launch arguments | num_scouts:=$NUM_SCOUTS num_excavators:=$NUM_EXCAVATORS num_haulers:=$NUM_HAULERS |

| # | Check | Result | Details |
|---|---|---|---|
HEADER

# --------------------------------------------------------------------------
# Tear down ONLY the process group this script started.
#
# This used to finish with a burst of host-wide pattern kills:
#     pkill -f "gz sim"; pkill -f "gz-sim-server"; pkill -f rosbridge
#     pkill -f "react-scripts"; pkill -f "http.server 3000"
# which is exactly the pattern check_drive.sh:159 forbids ("Never pattern-match
# on 'gz sim' ... a broad pkill here would take down a developer's session"). It
# is worse now than it was: scripts/check_terrain.sh and scripts/check_drive.sh
# are wired into CI and both run `gz sim`, so this teardown would SIGKILL a
# concurrent gate mid-measurement and the gate would report a Gazebo failure it
# did not cause.
#
# `ros2 launch` is started with setsid below, so it leads its own process group
# and the negative-PID kill reaches every child it spawned — gz, rosbridge, the
# node server — without matching anything this script did not start.
# --------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "Tearing down launch process group..."
    [ -n "${LAUNCH_PGID:-}" ] || return 0
    kill -TERM "-$LAUNCH_PGID" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "-$LAUNCH_PGID" 2>/dev/null || return 0
        sleep 0.5
    done
    kill -KILL "-$LAUNCH_PGID" 2>/dev/null
    return 0
}
# The signal traps EXIT EXPLICITLY. A handler ending in `return` does not stop
# the script — it runs and execution RESUMES — so folding INT/TERM into the EXIT
# trap would let a cancelled run tear the system down and then carry on writing
# PASS rows for checks it never made. Same fix as check_terrain.sh /
# check_drive.sh.
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

# Prefer the prebuilt dashboard bundle when one exists: the react-scripts dev
# server has to compile the bundle before port 3000 answers, which dominated the
# runtime of this script. Falls back to the dev server if there is no build.
# Force either mode with SELENE_PREBUILT_DASHBOARD=1 / =0.
if [ -n "${SELENE_PREBUILT_DASHBOARD:-}" ]; then
    PREBUILT="$SELENE_PREBUILT_DASHBOARD"
elif [ -f "$P/selene_dashboard/build/index.html" ]; then
    PREBUILT=1
else
    PREBUILT=0
fi
if [ "$PREBUILT" = "1" ]; then
    PREBUILT_ARG="prebuilt:=true"
    echo "Dashboard mode: prebuilt static bundle ($P/selene_dashboard/build)"
else
    PREBUILT_ARG="prebuilt:=false"
    echo "Dashboard mode: react-scripts dev server (no prebuilt bundle found;"
    echo "  run 'cd $P/selene_dashboard && npm run build' to skip the compile wait)"
fi

# CLI tools (ros2 node list, ros2 topic info) create short-lived DDS
# participants whose SHM ports can exhaust /dev/shm on WSL2. Restrict them to
# UDP-only; the launched nodes keep default SHM+UDP for fast inter-node comms.
# scripts/phase5_probe.py needs no such workaround — it creates ONE participant
# for its whole run, which is a large part of why the measurements moved there.
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

# ISOLATE THIS RUN'S GAZEBO TRANSPORT, exactly as check_terrain.sh:161 and
# check_drive.sh:118 do. The default partition is shared, so any other Gazebo on
# the host — including a server left behind by a crashed earlier run — advertises
# the same world name and the same /world/<name>/stats topic and could be the
# thing answered below instead of the server this launch starts. D-07 measured
# exactly that failure: "5 of 10 models in Gazebo while all ten create nodes
# logged Entity creation successful — the signature of querying the wrong
# server."
#
# UNAUDITED: whether exporting GZ_PARTITION here actually places the `gz sim`
# that `ros2 launch` starts into this partition has not been verified on a
# running system. launch inherits os.environ into child processes and
# simulation.launch.py only ADDS to the environment (GZ_SIM_RESOURCE_PATH), so
# it should; if it does not, check 1(b) fails closed rather than reading a
# stranger's server, because nothing would answer at all.
export GZ_PARTITION="${GZ_PARTITION:-selene_phase5_$$}"

# STRAGGLER SCAN — REPORT ONLY, NEVER KILL. A leftover server cannot answer this
# run's queries now that the partition is per-PID, but it can still hold GPU and
# memory and slow the box enough to skew a rate measurement, so it is worth
# saying out loud. Killing it is forbidden here for the same reason the pattern
# kills were removed from cleanup().
STRAGGLERS=$(pgrep -fc "gz sim" 2>/dev/null) || STRAGGLERS=0
if [ "${STRAGGLERS:-0}" -gt 0 ]; then
    echo "NOTE: $STRAGGLERS existing 'gz sim' process(es) on this host."
    echo "      This run is isolated on GZ_PARTITION=$GZ_PARTITION and will not"
    echo "      read them, but they share the machine. Not killed: a host-wide"
    echo "      pkill is forbidden here (check_drive.sh:159-162)."
fi

echo "[launch] ros2 launch selene_sim unified_sim.launch.py \\"
echo "         num_scouts:=$NUM_SCOUTS num_excavators:=$NUM_EXCAVATORS num_haulers:=$NUM_HAULERS $PREBUILT_ARG"
# setsid so the launch leads its OWN process group. That is what lets cleanup()
# kill the whole tree it spawns (gz, rosbridge, the dashboard server) with a
# single negative-PID signal, instead of the host-wide pattern kills this script
# used to end with. Without setsid the launch shares this script's group and
# `kill -TERM -$$` would signal the script itself.
LAUNCH_ARGS=(
    "num_scouts:=$NUM_SCOUTS"
    "num_excavators:=$NUM_EXCAVATORS"
    "num_haulers:=$NUM_HAULERS"
    "$PREBUILT_ARG"
)
setsid ros2 launch selene_sim unified_sim.launch.py "${LAUNCH_ARGS[@]}" \
    > "$LAUNCH_LOG" 2>&1 &
LAUNCH_PID=$!
# With setsid the child is its own group leader, so PGID == PID. Read it back
# rather than assuming, and fall back to the PID if ps is unavailable.
LAUNCH_PGID=$(ps -o pgid= -p "$LAUNCH_PID" 2>/dev/null | tr -d ' ')
LAUNCH_PGID="${LAUNCH_PGID:-$LAUNCH_PID}"
echo "Launch PID: $LAUNCH_PID (process group $LAUNCH_PGID)"

# --------------------------------------------------------------------------
# Gazebo readers, lifted from scripts/check_drive.sh:197-204 rather than
# reinvented. `gz topic -e -n 1` prints one human-readable message; sim_time is
# a nested {sec, nsec} block, which is why this parses rather than greps.
# --------------------------------------------------------------------------
sim_ms() {   # simulation time in integer milliseconds; empty if unreadable
    timeout 8 gz topic -e -t "/world/$WORLD_NAME/stats" -n 1 2>/dev/null | python3 -c '
import re, sys
m = re.search(r"sim_time\s*\{(.*?)\}", sys.stdin.read(), re.S)
if m:
    d = dict(re.findall(r"(sec|nsec):\s*(\d+)", m.group(1)))
    print(int(d.get("sec", 0)) * 1000 + int(d.get("nsec", 0)) // 1000000)'
}

missing_nodes() {   # $1 = file containing `ros2 node list` output
    local node missing=""
    for node in "${EXPECTED_NODES[@]}"; do
        grep -Fxq -- "$node" "$1" || missing="$missing $node"
    done
    printf '%s' "${missing# }"
}

# --------------------------------------------------------------------------
# READINESS POLL, replacing a blind `sleep 30`.
#
# EXPECTED WALL CLOCK: ~35-50 s typically (unified_sim.launch.py delays the
# orchestrator and agents by 12 s and simulation.launch.py staggers the spawns
# 2 s apart), capped at SELENE_READY_TIMEOUT (default 90 s).
#
# POLLED, NOT SAMPLED ONCE — and this is measured, not defensive. `ros2 node
# list` and `ros2 topic list` report whatever DDS discovery has converged on at
# that instant, and discovery is asynchronous. MEASURED 2026-07-30 on two
# consecutive runs of the same commit: run A "4 robot state topics" PASS, run B
# "only 0 state topics" FAIL — while check 8, further down, successfully read
# fsm_state off /scout_01/state in that same run B. The report contradicted
# itself. Failing closed on a race is still better than failing open, but it is
# not evidence.
# --------------------------------------------------------------------------
NODE_LIST=/tmp/selene_phase5_nodes.$$.txt
READY=false
READY_ELAPSED=0
LAUNCH_DIED=false
MISSING=""
SIM_MS_FIRST=""
SIM_MS_SECOND=""
echo "Waiting for the system to come up (cap ${READY_TIMEOUT}s)..."
while [ "$READY_ELAPSED" -lt "$READY_TIMEOUT" ]; do
    if ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
        # The launch supervisor dying is a DIFFERENT failure from a node never
        # appearing, and reporting the second when the first happened is how an
        # operator ends up debugging DDS instead of reading a traceback.
        LAUNCH_DIED=true
        echo "ERROR: ros2 launch exited during boot; see $LAUNCH_LOG" >&2
        break
    fi
    ros2 node list > "$NODE_LIST" 2>/dev/null
    MISSING=$(missing_nodes "$NODE_LIST")
    SIM_MS_FIRST=$(sim_ms)
    if [ -z "$MISSING" ] && [ -n "$SIM_MS_FIRST" ]; then
        READY=true
        break
    fi
    sleep 3
    READY_ELAPSED=$((READY_ELAPSED + 3))
done

# --------------------------------------------------------------------------
# CHECK 1 — real liveness, from three independent authorities.
#
# EXPECTED WALL CLOCK: ~15 s (one `ros2 node list`, two `gz topic` reads 3 s
# apart, one `gz model --list`, and one `ros2 topic info` per required topic).
#
# WHY THREE. `kill -0 $LAUNCH_PID` — the whole of the old check 1 — proves only
# that the launch supervisor is alive. VERIFIED by grep across
# selene_sim/launch, selene_agent/launch and selene_orchestrator/launch: not one
# launch file uses on_exit / OnProcessExit / required= / Shutdown, so nothing
# converts a child's death into a launch shutdown. The old check passed with
# Gazebo, the orchestrator, or every agent dead.
#   (a) the ROS graph contains every node the derived fleet implies;
#   (b) Gazebo is STEPPING — sim_time strictly increases between two reads — and
#       `gz model --list` names every robot;
#   (c) every required topic has publisher count >= 1.
# --------------------------------------------------------------------------
C1_PROBLEMS=""
if [ "$READY" != "true" ]; then
    if [ "$LAUNCH_DIED" = "true" ]; then
        C1_PROBLEMS="ros2 launch exited during boot after ${READY_ELAPSED}s"
    elif [ -n "$MISSING" ]; then
        C1_PROBLEMS="nodes missing after ${READY_TIMEOUT}s:$MISSING (graph as seen: $NODE_LIST)"
    else
        C1_PROBLEMS="Gazebo published no sim_time on /world/$WORLD_NAME/stats within ${READY_TIMEOUT}s"
    fi
else
    # (b) Gazebo stepping. Two reads, 3 s apart: at the 1.0 real-time-factor cap
    # in lunar_psr.sdf that is thousands of milliseconds of headroom, so a
    # strictly-greater comparison is safe and a paused or dead server is caught.
    sleep 3
    SIM_MS_SECOND=$(sim_ms)
    if [ -z "$SIM_MS_SECOND" ]; then
        C1_PROBLEMS="$C1_PROBLEMS; second /world/$WORLD_NAME/stats read returned nothing"
    elif [ "$SIM_MS_SECOND" -le "$SIM_MS_FIRST" ]; then
        C1_PROBLEMS="$C1_PROBLEMS; sim_time did not advance (${SIM_MS_FIRST}ms -> ${SIM_MS_SECOND}ms)"
    fi

    GZ_MODELS=$(timeout 15 gz model --list 2>/dev/null)
    MISSING_MODELS=""
    for rid in "${FLEET[@]}"; do
        printf '%s\n' "$GZ_MODELS" | grep -Fq -- "$rid" || MISSING_MODELS="$MISSING_MODELS $rid"
    done
    if [ -n "$MISSING_MODELS" ]; then
        C1_PROBLEMS="$C1_PROBLEMS; models absent from Gazebo:$MISSING_MODELS"
    fi

    # (c) publisher counts.
    NO_PUBLISHER=""
    for topic in "${REQUIRED_TOPICS[@]}"; do
        COUNT=$(timeout 20 ros2 topic info "$topic" 2>/dev/null \
            | awk -F': ' '/^Publisher count:/ {print $2}')
        # No `${COUNT:-0}` default here on purpose: an empty COUNT means
        # `ros2 topic info` failed or timed out, which is a different fact from
        # "the topic exists with zero publishers", and collapsing the two would
        # report a tooling failure as a system failure.
        case "$COUNT" in
            '')          NO_PUBLISHER="$NO_PUBLISHER $topic(unreadable)" ;;
            *[!0-9]*)    NO_PUBLISHER="$NO_PUBLISHER $topic(unparsable:$COUNT)" ;;
            0)           NO_PUBLISHER="$NO_PUBLISHER $topic(0)" ;;
        esac
    done
    if [ -n "$NO_PUBLISHER" ]; then
        C1_PROBLEMS="$C1_PROBLEMS; topics without a publisher:$NO_PUBLISHER"
    fi
fi
C1_PROBLEMS="${C1_PROBLEMS#; }"

if [ -z "$C1_PROBLEMS" ]; then
    record_check 1 PASS "$(catalog_title 1)" \
        "${#EXPECTED_NODES[@]} expected nodes present, sim_time ${SIM_MS_FIRST}ms -> ${SIM_MS_SECOND}ms, ${#FLEET[@]} Gazebo models, ${#REQUIRED_TOPICS[@]} topics with a live publisher (ready after ${READY_ELAPSED}s)"
else
    record_check 1 FAIL "$(catalog_title 1)" "$C1_PROBLEMS; see $LAUNCH_LOG"
fi

# --------------------------------------------------------------------------
# CHECKS 2-11 — scripts/phase5_probe.py.
#
# EXPECTED WALL CLOCK: about 65 s when a prospect-capable robot is already idle
# and the dashboard is prebuilt; up to about 3 minutes worst case (60 s waiting
# for an idle robot, then the recording window, with the dashboard fetch running
# concurrently on its own thread).
#
# ABOUT 4 s OF THAT IS NEW as of 2026-07-31: the probe seeds the fused resource
# map before the stimulus timeline so check 10's hottest-cell assertion can run
# at all (1.5 s to emit 49 readings, then one 0.5 Hz map period for the snapshot
# that carries them). Worst case is ~47 s, and every second of it is a system
# not answering rather than a wait built into the measurement.
#
# The probe is run even when check 1 failed. A partially-up system still yields
# real information — "rosbridge answers but no robot publishes state" is a more
# useful report than a blank table — and every check it cannot take comes back
# as a SKIP with a reason, which the exit code already treats as not-a-pass.
# --------------------------------------------------------------------------
echo ""
echo "[probe] running scripts/phase5_probe.py (stderr -> $PROBE_LOG)"
timeout 420 python3 "$PROBE" \
    --fleet "$FLEET_CSV" \
    --ice-config "$ICE_CONFIG" \
    --rviz-config "$RVIZ_CONFIG" \
    --json-out "$PROBE_JSON" \
    > "$PROBE_OUT" 2> "$PROBE_LOG"
PROBE_RC=$?

while IFS='|' read -r tag number result title details; do
    [ "$tag" = "CHECK" ] || continue
    record_check "$number" "$result" "$title" "$details"
done < "$PROBE_OUT"

# Anything the probe did not report at all is a FAIL, not a silent gap: the
# probe pre-seeds every check as a SKIP and prints them from a `finally`, so a
# missing row means it died before it could even do that.
for entry in "${CHECK_CATALOG[@]}"; do
    number="${entry%%|*}"
    [ "$number" = "1" ] && continue
    if [ -z "${CHECK_RESULT[$number]:-}" ]; then
        record_check "$number" FAIL "$(catalog_title "$number")" \
            "the probe did not report this check (exit $PROBE_RC); see $PROBE_LOG"
    fi
done

# --------------------------------------------------------------------------
# GENERATED FOOTER.
#
# The old footer was hand-written and had gone factually false: it stated that
# "FR-MAP-4 (RViz2 resource-map visualization) is NOT delivered and is NOT
# waived", which D-08 closed on 2026-07-30. Generating the coverage table from
# the mapping above is what stops the report and the script drifting apart
# again — the same class of failure D-10 names, one level up.
# --------------------------------------------------------------------------
probe_measured() {   # $1 = check number, $2 = key. Prints the value, or nothing.
    # Reads one number out of the probe's own --json-out record. python3 rather
    # than jq: jq is not a declared dependency of this repository, python3 is
    # (this script runs the probe with it three lines up). Anything unreadable —
    # no file, bad JSON, absent key — prints nothing, and every caller treats
    # nothing as "not measured" rather than as zero.
    [ -f "$PROBE_JSON" ] || return 0
    python3 - "$PROBE_JSON" "$1" "$2" <<'PYEOF' 2>/dev/null
import json
import sys
try:
    with open(sys.argv[1]) as handle:
        record = json.load(handle)
except (OSError, ValueError):
    sys.exit(0)
check = (record.get('checks') or {}).get(sys.argv[2]) or {}
value = (check.get('measured') or {}).get(sys.argv[3])
if value is not None:
    sys.stdout.write(str(value))
PYEOF
}

row_verdict() {   # $1 = space-separated check numbers, or "none"
    local checks="$1" number verdict="PASS"
    if [ "$checks" = "none" ]; then
        printf 'NOT COVERED'
        return 0
    fi
    for number in $checks; do
        case "${CHECK_RESULT[$number]:-SKIP}" in
            FAIL) printf 'FAIL'; return 0 ;;
            SKIP) verdict="SKIP" ;;
        esac
    done
    printf '%s' "$verdict"
}

# Read once, outside the report block: a command substitution inside the
# `{ ... } >> "$REPORT"` group would send python3's own stderr into the report
# on a bad day.
MAP_FRAME_BYTES=$(probe_measured 3 resource_map_max_bytes)
INJECT_TRANSPORT=$(probe_measured 5 transport)
# Check 10's provenance. SEED_READINGS is how many synthetic ResourceMapUpdate
# messages the probe published; empty or 0 means the map was not seeded, which
# on a green run can only mean --no-seed-map. Read here rather than inside the
# report block for the same reason as the two above.
SEED_READINGS=$(probe_measured 10 seed_readings)
SEED_DEPOSIT=$(probe_measured 10 seed_deposit)
HOTTEST_CELL=$(probe_measured 10 hottest_cell_world)
HOTTEST_ERROR=$(probe_measured 10 hottest_cell_error_m)

{
    echo ""
    echo "## PRD exit-gate coverage"
    echo ""
    echo "Generated from the PRD_ROWS / ROW_CHECKS mapping in this script, which"
    echo "\`selene_orchestrator/test/test_phase5_gate_coverage.py\` pins against"
    echo "\`docs/PRD.md\` and \`scripts/phase5_probe.py\` on every push."
    echo ""
    echo "A PASS in the Verdict column means the checks named beside it passed."
    echo "It does NOT mean the PRD's stated method was performed — read the"
    echo "Coverage column, which says what each row's checks do and do not reach."
    echo ""
    echo "| PRD exit-gate row (docs/PRD.md:1503-1509) | Covering checks | Coverage | Verdict |"
    echo "|---|---|---|---|"
    ROW_INDEX=0
    while [ "$ROW_INDEX" -lt "${#PRD_ROWS[@]}" ]; do
        ROW_TEXT="${PRD_ROWS[$ROW_INDEX]}"
        ROW_CHECK_LIST="${ROW_CHECKS[$ROW_INDEX]}"
        ROW_KIND="${ROW_COVERAGE_KIND[$ROW_INDEX]}"
        ROW_RESULT=$(row_verdict "$ROW_CHECK_LIST")
        if [ "$ROW_CHECK_LIST" = "none" ]; then
            echo "| $ROW_TEXT | — | $ROW_KIND | **NOT COVERED** — ${NOT_COVERED_REASONS[$ROW_INDEX]} |"
        else
            PER_CHECK=""
            for number in $ROW_CHECK_LIST; do
                PER_CHECK="$PER_CHECK $number:${CHECK_RESULT[$number]:-MISSING}"
            done
            echo "| $ROW_TEXT |${PER_CHECK} | $ROW_KIND | $ROW_RESULT |"
        fi
        ROW_INDEX=$((ROW_INDEX + 1))
    done

    echo ""
    echo "Checks that cover no PRD row, and why they are kept:"
    echo ""
    for entry in "${EXTRA_CHECKS[@]}"; do
        number="${entry%%|*}"
        echo "* check $number (${CHECK_RESULT[$number]:-MISSING}) — ${entry#*|}"
    done

    echo ""
    echo "**Summary:** $PASS_COUNT passed, $FAIL_COUNT failed, $SKIP_COUNT skipped."
    echo ""
    echo "## What this run does and does not mean"
    echo ""
    # THIS SECTION IS GENERATED, NOT PRINTED. It used to be a fixed paragraph
    # emitted on every run, which made two claims the checks do not always
    # support: that the resource map was seen under `max_message_size` (check 3
    # PASSES with the size guard UNEXERCISED when no 0.5 Hz frame lands in the
    # window) and that the injection used the dashboard's transport (check 5
    # falls back to the rclpy service whenever tornado is missing or the
    # websocket call returns nothing). Both sentences would have been read as
    # evidence in docs/phase5_validation_report.md. They are now built from what
    # the probe recorded, and the whole "does mean" block is withheld entirely
    # unless the run was green — a standing list of claims beside a red table is
    # the D-10 failure with the numbers changed.
    if [ "$FAIL_COUNT" -eq 0 ] && [ "$SKIP_COUNT" -eq 0 ]; then
        echo "**Does mean.** One \`ros2 launch\` brought up the node set the requested"
        echo "fleet implies, Gazebo is stepping with every robot model present, and the"
        echo "orchestrator's topics have live publishers (check 1). rosbridge answers the"
        echo "websocket protocol rather than merely accepting a TCP connection (check 3)."
        if [ -n "$MAP_FRAME_BYTES" ] && [ "$MAP_FRAME_BYTES" != "0" ]; then
            echo "The largest \`/orchestrator/resource_map\` frame seen on the websocket was"
            echo "$MAP_FRAME_BYTES B, under rosbridge's \`max_message_size\` — the D-09 sparse"
            echo "encoding held (check 3)."
        else
            echo "No \`/orchestrator/resource_map\` frame reached the websocket inside the"
            echo "recording window (it publishes at 0.5 Hz), so check 3 did NOT exercise the"
            echo "D-09 size guard on this run and nothing is claimed about frame size."
        fi
        echo "Every robot publishes RobotState at the rate, freshness and content its own"
        echo "FSM declares, and the set of state publishers EQUALS the launched fleet"
        echo "(check 4)."
        if [ -n "$INJECT_TRANSPORT" ]; then
            echo "A task injected via $INJECT_TRANSPORT was announced and assigned"
            echo "under its own id, with its target matched to 1e-3 (checks 5, 6)."
        else
            echo "A task was injected, announced and assigned under its own id with its"
            echo "target matched to 1e-3 (checks 5, 6); the probe recorded no transport"
            echo "string, so which path carried it is not claimed here — see the check 5 row."
        fi
        echo "Both operator overrides reach a robot's state machine (checks 7, 8, 11). The"
        echo "RViz2 overlay and the posterior on the wire come from one snapshot through one"
        echo "colour law, and the hottest cell of that posterior decodes row-major to"
        echo "${HOTTEST_CELL:-an unrecorded coordinate}, ${HOTTEST_ERROR:-an unrecorded distance} m from the ice it should sit on"
        echo "(check 10)."
    else
        echo "**This run was not green** — $PASS_COUNT passed, $FAIL_COUNT failed,"
        echo "$SKIP_COUNT skipped — so no positive claim is made here. Read the coverage"
        echo "table above and the per-check rows: each states what was measured, or the"
        echo "reason it could not be. The paragraph describing what a green run would mean"
        echo "is printed only on a green run, deliberately."
    fi
    echo ""
    echo "**Does not mean.** NO BROWSER IS STARTED ANYWHERE IN THIS GATE. Nothing"
    echo "here proves the dashboard bundle executes, that React mounts, that roslib"
    echo "connects, or that a single pixel is drawn — check 2 fetches and inspects"
    echo "the bundle and is not a substitute for running it. NO IMAGE IS COMPARED"
    echo "and no RViz2 process runs, so check 10 is not the PRD's \"side-by-side"
    echo "comparison\". Every METHOD the PRD names for these rows — visual"
    echo "inspection, side-by-side comparison, observing robot execution, browser"
    echo "devtools profiling — is a human method, and none of them was performed."
    echo "Check 9 bounds the task-queue latency row from below only: it can prove a"
    echo "violation, and proves conformance only as far as the websocket, since the"
    echo "React reducer and canvas draw are unmeasured."
    echo ""
    # ALWAYS PRINTED, GREEN OR NOT, and above the deviation pointer rather than
    # buried under it. A reader who sees "hottest cell 0.7 m from the deposit"
    # in the check 10 row and is not told where the readings came from will read
    # it as evidence that the fleet surveyed the deposit. It is not, and the
    # whole reason this seeding exists is that the unseeded version of that row
    # PASSED on a map with zero cells in it, twice.
    if [ -n "$SEED_READINGS" ] && [ "$SEED_READINGS" != "0" ]; then
        echo "**Check 10 ran on a map this gate seeded.** The probe published $SEED_READINGS synthetic"
        echo "\`selene_msgs/msg/ResourceMapUpdate\` readings onto \`/orchestrator/map_update\`,"
        echo "shaped like \`${SEED_DEPOSIT:-the strongest deposit}\` in \`selene_sim/config/ice_deposits.yaml\`, because a"
        echo "gate-length run cannot reach the observation count the hottest-cell assertion"
        echo "needs — a scout drives ~100 m to its first waypoint and returns to base after"
        echo "every task. Everything downstream of that stimulus is the system's own code:"
        echo "\`_on_map_update\`, \`ResourceMap.update\`'s Bayesian fusion, the sparse encoder,"
        echo "the colour law and both publishers. So check 10 proves the fusion ->"
        echo "sparse-encode -> marker path is correct on seeded input, and the map was"
        echo "perturbed by the measurement. It does **not** prove that robots autonomously"
        echo "survey the deposits; nothing in this gate measures that."
    else
        echo "**Check 10 was NOT seeded on this run** (\`--no-seed-map\`, or the probe could not"
        echo "read \`ice_deposits.yaml\`), so its hottest-cell assertion depended on the fleet"
        echo "having surveyed. A gate-length run cannot do that, and check 10 SKIPs rather"
        echo "than passing when it cannot make the assertion — see its row above."
    fi
    echo ""
    echo "**Deviations:** see \`docs/phase5_deviation_register.md\` (D-01..D-10) for"
    echo "what is delivered, what is deviated, and what remains open."
    echo ""
    echo "**Launch log:** $LAUNCH_LOG"
    echo "**Probe stderr:** $PROBE_LOG"
    echo "**Probe measurements (JSON):** $PROBE_JSON"
} >> "$REPORT"

echo ""
echo "============================================"
echo "Phase 5 Validation: $PASS_COUNT passed, $FAIL_COUNT failed, $SKIP_COUNT skipped"
echo "Report: $REPORT"
echo "============================================"

# A SKIP IS NOT A PASS. Exit 2 says "this gate did not measure everything it
# claims to cover", which is a different statement from "something is broken",
# and conflating the two is precisely how D-10 happened.
if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
if [ "$SKIP_COUNT" -gt 0 ]; then
    exit 2
fi
exit 0
