#!/bin/bash
# Phase 5 exit gate validation script.
#
# Runs from a WSL2 environment with ROS 2 Jazzy + the SELENE workspace built.
# Usage:
#   bash scripts/sync_and_build.sh    # ensure workspace is built first
#   bash scripts/validate_phase5.sh
#
# For the fast dashboard path, build the production bundle first:
#   SELENE_PREBUILD_DASHBOARD=1 bash scripts/sync_and_build.sh
# This script then auto-selects prebuilt:=true.
#
# Exits 0 on full pass, 1 on any failure. Writes phase5_validation_report.md.

set -uo pipefail

P=$HOME/selene
# ABSOLUTE, and anchored to the workspace. This was a bare relative filename, so
# the report landed in whatever directory the caller happened to be in — including
# the repo checkout, where it is gitignored by nothing and would be committed by a
# `git add -A`. It is written before the first check, so it landed there even on
# runs that then failed immediately.
REPORT="${SELENE_PHASE5_REPORT:-$P/phase5_validation_report.md}"
LAUNCH_LOG=/tmp/selene_unified_launch.log
PASS=0
FAIL=0

# ROS 2 setup.bash references unset vars; disable nounset just for sourcing.
#
# THE PRE-FLIGHT IS CHECKED. `set +u` with no `set -e` meant a missing workspace
# was survivable: `cd` failed, the script carried on IN THE CALLER'S DIRECTORY,
# `source install/setup.bash` failed too, and every check below then ran against a
# workspace that had never been sourced — reporting failures whose real cause
# ("there is no build here") appeared nowhere in the report.
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
    echo "ERROR: ROS 2 Jazzy not found at /opt/ros/jazzy/setup.bash" >&2
    echo "       run scripts/setup_wsl2.sh first." >&2
    exit 1
fi
if [ ! -f "$P/install/setup.bash" ]; then
    echo "ERROR: no built workspace at $P/install/setup.bash" >&2
    echo "       run scripts/sync_and_build.sh first." >&2
    exit 1
fi
set +u
source /opt/ros/jazzy/setup.bash
cd "$P" || { echo "ERROR: cannot cd to $P" >&2; exit 1; }
source "$P/install/setup.bash"
set -u


# PROVENANCE IN THE REPORT, not just a date. A validation report that cannot name
# the commit and the toolchain it validated is not evidence — it is an assertion.
# The commit comes from .selene_source_commit, which scripts/sync_and_build.sh
# writes at rsync time, because the rsync excludes .git and nothing here could
# otherwise work it out.
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

| # | Check | Result | Details |
|---|---|---|---|
HEADER

check() {
    local n=$1 desc="$2" result=$3 details="$4"
    if [ "$result" = "PASS" ]; then
        PASS=$((PASS + 1))
        echo "| $n | $desc | PASS | $details |" >> "$REPORT"
    else
        FAIL=$((FAIL + 1))
        echo "| $n | $desc | FAIL | $details |" >> "$REPORT"
    fi
    echo "[$result] $n. $desc - $details"
}

# Tear down ONLY the process group this script started.
#
# This used to finish with a burst of host-wide pattern kills:
#     pkill -f "gz sim"; pkill -f "gz-sim-server"; pkill -f rosbridge
#     pkill -f "react-scripts"; pkill -f "http.server 3000"
# which is exactly the pattern check_drive.sh:145 forbids ("Never pattern-match on
# 'gz sim' ... a broad pkill here would take down a developer's session"). It is
# worse now than it was: scripts/check_terrain.sh and scripts/check_drive.sh are
# wired into CI and both run `gz sim`, so this teardown would SIGKILL a concurrent
# gate mid-measurement and the gate would report a Gazebo failure it did not cause.
#
# `ros2 launch` is started with setsid below, so it leads its own process group and
# the negative-PID kill reaches every child it spawned — gz, rosbridge, the node
# server — without matching anything this script did not start.
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
# The signal traps EXIT EXPLICITLY. A handler ending in `return` does not stop the
# script — it runs and execution RESUMES — so folding INT/TERM into the EXIT trap
# would let a cancelled run tear the system down and then carry on writing PASS
# rows for checks it never made. Same fix as check_terrain.sh / check_drive.sh.
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
    LAUNCH_ARGS="prebuilt:=true"
    echo "Dashboard mode: prebuilt static bundle ($P/selene_dashboard/build)"
else
    LAUNCH_ARGS="prebuilt:=false"
    echo "Dashboard mode: react-scripts dev server (no prebuilt bundle found;"
    echo "  run 'cd $P/selene_dashboard && npm run build' to skip the compile wait)"
fi

echo "[1/8] Starting unified launch..."
# setsid so the launch leads its OWN process group. That is what lets cleanup()
# kill the whole tree it spawns (gz, rosbridge, the dashboard server) with a
# single negative-PID signal, instead of the host-wide pattern kills this script
# used to end with. Without setsid the launch shares this script's group and
# `kill -TERM -$$` would signal the script itself.
setsid ros2 launch selene_sim unified_sim.launch.py $LAUNCH_ARGS \
    > "$LAUNCH_LOG" 2>&1 &
LAUNCH_PID=$!
# With setsid the child is its own group leader, so PGID == PID. Read it back
# rather than assuming, and fall back to the PID if ps is unavailable.
LAUNCH_PGID=$(ps -o pgid= -p "$LAUNCH_PID" 2>/dev/null | tr -d ' ')
LAUNCH_PGID="${LAUNCH_PGID:-$LAUNCH_PID}"
echo "Launch PID: $LAUNCH_PID (process group $LAUNCH_PGID)"
echo "Waiting 30s for boot..."
sleep 30

# CLI tools (ros2 topic echo, ros2 service call) create short-lived DDS
# participants whose SHM ports can exhaust /dev/shm on WSL2.  Restrict
# them to UDP-only — the launched nodes keep default SHM+UDP for fast
# inter-node comms.
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

if kill -0 $LAUNCH_PID 2>/dev/null; then
    check 1 "Single launch command starts full system" PASS "ros2 launch process running"
else
    check 1 "Single launch command starts full system" FAIL "launch crashed; see $LAUNCH_LOG"
    exit 1
fi

# -- Checks 3-8 run first while webpack compiles in background --

# rosbridge starts in the 12s-delayed block; retry in case it's still booting.
RB_OK=false
for _try in $(seq 1 10); do
    if (echo > /dev/tcp/localhost/9090) 2>/dev/null; then
        RB_OK=true
        break
    fi
    sleep 2
done
if $RB_OK; then
    check 3 "rosbridge listening on ws://localhost:9090" PASS "TCP 9090 open"
else
    check 3 "rosbridge listening on ws://localhost:9090" FAIL "TCP 9090 closed"
fi

# POLLED, not sampled once. `ros2 topic list` reports whatever DDS discovery has
# converged on at that instant, and discovery is asynchronous — so a single call
# can return fewer topics than exist and this check reported a FALSE FAIL.
# MEASURED 2026-07-30 on two consecutive runs of the same commit: run A "4 robot
# state topics" PASS, run B "only 0 state topics" FAIL — while check 8, further
# down, successfully read fsm_state off /scout_01/state in that same run B. The
# report contradicted itself.
#
# Every other timing-sensitive check here already polls (check 3 loops on the
# rosbridge port, check 6 waits for the announcement). This one did not. Failing
# closed on a race is still better than failing open, but it is not evidence.
TOPIC_LIST_ERR=/tmp/selene_topic_list.err
ROBOT_TOPICS=0
for _ in $(seq 1 15); do
    ROBOT_TOPICS=$(ros2 topic list 2>"$TOPIC_LIST_ERR" | grep -c '/state$' || true)
    [ "$ROBOT_TOPICS" -ge 4 ] && break
    sleep 2
done
if [ "$ROBOT_TOPICS" -ge 4 ]; then
    check 4 "Dashboard shows all robots with correct real-time state" PASS "$ROBOT_TOPICS robot state topics"
else
    ERR_SNIP=$(head -c 120 "$TOPIC_LIST_ERR" 2>/dev/null | tr '\n' ' ')
    check 4 "Dashboard shows all robots with correct real-time state" FAIL "only $ROBOT_TOPICS state topics (stderr: $ERR_SNIP)"
fi

INJECT_OUT=$(ros2 service call /orchestrator/inject_task selene_msgs/srv/InjectTask "{task_type: 'prospect', target_location: {x: -50.0, y: -100.0, z: 0.0}, quantity: 0.0, assigned_robot_id: ''}" 2>&1)
if echo "$INJECT_OUT" | grep -q 'success=True'; then
    check 5 "Operator-injected task accepted via service" PASS "inject_task returned success"
else
    check 5 "Operator-injected task accepted via service" FAIL "$(echo $INJECT_OUT | head -c 200)"
fi

# Listen for a task_announcement (auction start) rather than task_assignment
# (auction close).  Assignment requires an idle-and-capable robot to bid,
# which is not guaranteed this early — but the injected task must at least
# be announced within seconds of injection.
if timeout 15 ros2 topic echo /orchestrator/task_announcement --once 2>/dev/null | grep -q 'task_id'; then
    check 6 "Task announced within 15s of injection" PASS "task_announcement emitted post-inject"
else
    check 6 "Task announced within 15s of injection" FAIL "no task_announcement seen"
fi

OVERRIDE_OUT=$(ros2 service call /orchestrator/override_robot selene_msgs/srv/OverrideRobot "{robot_id: 'scout_01', command: 'force_recharge', target: {x: 0.0, y: 0.0, z: 0.0}}" 2>&1)
if echo "$OVERRIDE_OUT" | grep -q 'success=True'; then
    check 7 "Robot override (force_recharge) accepted" PASS "override_robot returned success"
else
    check 7 "Robot override (force_recharge) accepted" FAIL "$(echo $OVERRIDE_OUT | head -c 200)"
fi

sleep 5
SCOUT_STATE=$(timeout 10 ros2 topic echo /scout_01/state --once 2>/dev/null | grep 'fsm_state' | head -1)
if echo "$SCOUT_STATE" | grep -q 'RECHARGING'; then
    check 8 "scout_01 fsm_state == RECHARGING after override" PASS "$SCOUT_STATE"
else
    check 8 "scout_01 fsm_state == RECHARGING after override" FAIL "$SCOUT_STATE"
fi

# -- Check 2 runs last. In dev-server mode webpack has to compile the bundle
# -- before port 3000 answers (previously measured at roughly two minutes on
# -- WSL2), so it is deliberately checked after everything else. In prebuilt
# -- mode the static server should answer almost immediately, but the same
# -- retry loop is kept so the check works in both modes.
DASH_OK=false
for _try in $(seq 1 15); do
    if curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null | grep -q '200'; then
        DASH_OK=true
        break
    fi
    sleep 2
done
if $DASH_OK; then
    check 2 "Dashboard HTTP 200 on port 3000" PASS "curl returned 200"
else
    check 2 "Dashboard HTTP 200 on port 3000" FAIL "no HTTP 200"
fi

cat >> "$REPORT" <<FOOTER

**Summary:** $PASS passed, $FAIL failed

**Deviations:** see \`docs/phase5_deviation_register.md\` (D-01..D-10), which records
what this gate does and does not cover. Note in particular that FR-MAP-4 (RViz2
resource-map visualization) is NOT delivered and is NOT waived — the previous
version of this line claimed it was skipped "per plan decision D9", and no such
decision exists anywhere in the repository or its history.

**What 8/8 here means:** the system launches, rosbridge and a web server answer,
two services accept calls, and one override propagates to a robot's state machine.
Of the PRD's seven exit-gate rows (docs/PRD.md:1499-1509) this script covers one
end to end, three with weak liveness proxies, and three not at all.

**Launch log:** $LAUNCH_LOG
FOOTER

echo ""
echo "============================================"
echo "Phase 5 Validation: $PASS passed, $FAIL failed"
echo "Report: $REPORT"
echo "============================================"

[ $FAIL -gt 0 ] && exit 1 || exit 0
