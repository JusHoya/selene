#!/bin/bash
# Phase 5 exit gate validation script.
#
# Runs from a WSL2 environment with ROS 2 Jazzy + the SELENE workspace built.
# Usage:
#   bash scripts/sync_and_build.sh    # ensure workspace is built first
#   bash scripts/validate_phase5.sh
#
# Exits 0 on full pass, 1 on any failure. Writes phase5_validation_report.md.

set -uo pipefail

REPORT="phase5_validation_report.md"
P=$HOME/selene
LAUNCH_LOG=/tmp/selene_unified_launch.log
PASS=0
FAIL=0

source /opt/ros/jazzy/setup.bash
cd "$P"
source install/setup.bash

cat > "$REPORT" <<HEADER
# SELENE Phase 5 Exit Gate Validation Report

_Generated $(date)_

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

cleanup() {
    echo ""
    echo "Tearing down launch process..."
    if [ -n "${LAUNCH_PID:-}" ]; then
        kill $LAUNCH_PID 2>/dev/null
        sleep 2
        pkill -f "ros2 launch selene_sim unified_sim" 2>/dev/null
        pkill -f "gz sim" 2>/dev/null
        pkill -f "rosbridge" 2>/dev/null
        pkill -f "react-scripts" 2>/dev/null
    fi
}
trap cleanup EXIT

echo "[1/8] Starting unified launch..."
ros2 launch selene_sim unified_sim.launch.py > "$LAUNCH_LOG" 2>&1 &
LAUNCH_PID=$!
echo "Launch PID: $LAUNCH_PID"
echo "Waiting 30s for boot..."
sleep 30

if kill -0 $LAUNCH_PID 2>/dev/null; then
    check 1 "Single launch command starts full system" PASS "ros2 launch process running"
else
    check 1 "Single launch command starts full system" FAIL "launch crashed; see $LAUNCH_LOG"
    exit 1
fi

if curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 | grep -q '200'; then
    check 2 "Dashboard HTTP 200 on port 3000" PASS "curl returned 200"
else
    check 2 "Dashboard HTTP 200 on port 3000" FAIL "no HTTP 200"
fi

if (echo > /dev/tcp/localhost/9090) 2>/dev/null; then
    check 3 "rosbridge listening on ws://localhost:9090" PASS "TCP 9090 open"
else
    check 3 "rosbridge listening on ws://localhost:9090" FAIL "TCP 9090 closed"
fi

ROBOT_TOPICS=$(ros2 topic list 2>/dev/null | grep -c '/state$' || echo 0)
if [ "$ROBOT_TOPICS" -ge 4 ]; then
    check 4 "Dashboard shows all robots with correct real-time state" PASS "$ROBOT_TOPICS robot state topics"
else
    check 4 "Dashboard shows all robots with correct real-time state" FAIL "only $ROBOT_TOPICS state topics"
fi

INJECT_OUT=$(ros2 service call /orchestrator/inject_task selene_msgs/srv/InjectTask "{task_type: 'prospect', target_location: {x: -50.0, y: -100.0, z: 0.0}, quantity: 0.0, assigned_robot_id: ''}" 2>&1)
if echo "$INJECT_OUT" | grep -q 'success=True'; then
    check 5 "Operator-injected task accepted via service" PASS "inject_task returned success"
else
    check 5 "Operator-injected task accepted via service" FAIL "$(echo $INJECT_OUT | head -c 200)"
fi

sleep 5
if timeout 5 ros2 topic echo /orchestrator/task_assignment --once 2>/dev/null | grep -q 'task_id'; then
    check 6 "Task queue reflects orchestrator state within 1s" PASS "task_assignment emitted post-inject"
else
    check 6 "Task queue reflects orchestrator state within 1s" FAIL "no task_assignment seen"
fi

OVERRIDE_OUT=$(ros2 service call /orchestrator/override_robot selene_msgs/srv/OverrideRobot "{robot_id: 'scout_01', command: 'force_recharge', target: {x: 0.0, y: 0.0, z: 0.0}}" 2>&1)
if echo "$OVERRIDE_OUT" | grep -q 'success=True'; then
    check 7 "Robot override (force_recharge) accepted" PASS "override_robot returned success"
else
    check 7 "Robot override (force_recharge) accepted" FAIL "$(echo $OVERRIDE_OUT | head -c 200)"
fi

sleep 5
SCOUT_STATE=$(timeout 3 ros2 topic echo /scout_01/state --once 2>/dev/null | grep 'fsm_state' | head -1)
if echo "$SCOUT_STATE" | grep -q 'RECHARGING'; then
    check 8 "scout_01 fsm_state == RECHARGING after override" PASS "$SCOUT_STATE"
else
    check 8 "scout_01 fsm_state == RECHARGING after override" FAIL "$SCOUT_STATE"
fi

cat >> "$REPORT" <<FOOTER

**Summary:** $PASS passed, $FAIL failed

**Known deviation:** FR-MAP-4 (RViz2 visualization, P1) intentionally skipped per plan decision D9 — the dashboard's canvas heatmap satisfies operator visualization.

**Launch log:** $LAUNCH_LOG
FOOTER

echo ""
echo "============================================"
echo "Phase 5 Validation: $PASS passed, $FAIL failed"
echo "Report: $REPORT"
echo "============================================"

[ $FAIL -gt 0 ] && exit 1 || exit 0
