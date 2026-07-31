#!/bin/bash
# DEPRECATED (Phase 5+): use `ros2 launch selene_sim unified_sim.launch.py` instead.
# Preserved for backward compatibility and as a reference for the legacy hardcoded
# fleet startup. The unified launch supports parameterized robot counts and
# integrates rosbridge + dashboard via standard ROS 2 launch.
#
# Start the SELENE simulation with Mission Control Dashboard.
#
# Usage:
#   bash scripts/start.sh                  # Phase 2: single scout standalone
#   bash scripts/start.sh --orchestrated   # Phase 4: full ISRU fleet (2 scouts + excavator + hauler)
#   bash scripts/start.sh --headless       # No dashboard
#
# Run scripts/sync_and_build.sh first if code has changed.

set -e
source /opt/ros/jazzy/setup.bash
cd ~/selene
source install/setup.bash

P=$HOME/selene
export GZ_SIM_RESOURCE_PATH=$P/selene_sim/models

cleanup() {
    echo ""
    echo "Shutting down..."
    # shellcheck disable=SC2046  # word splitting is intended: one PID per argument
    kill $(jobs -p) 2>/dev/null
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT

HEADLESS=false
ORCHESTRATED=false
for arg in "$@"; do
    [ "$arg" = "--headless" ] && HEADLESS=true
    [ "$arg" = "--orchestrated" ] && ORCHESTRATED=true
done

# Resolve npm via PATH (hardcoding /usr/bin/npm breaks nvm / fnm / asdf installs).
# Only required when the dashboard is started.
NPM="$(command -v npm || true)"
if [ "$HEADLESS" = false ] && [ -z "$NPM" ]; then
    echo "ERROR: npm was not found on PATH, so the dashboard cannot start." >&2
    echo "  Install Node.js 18+ (bash scripts/setup_wsl2.sh) or run with --headless." >&2
    exit 1
fi

# Helper: spawn a robot with bridge + sim nodes
spawn_robot() {
    local ROBOT_ID=$1 ROBOT_TYPE=$2 SDF=$3 X=$4 Y=$5

    gz service -s /world/lunar_psr/create \
        --reqtype gz.msgs.EntityFactory --reptype gz.msgs.Boolean --timeout 10000 \
        --req "sdf_filename: \"$SDF\", name: \"$ROBOT_ID\", pose: {position: {x: $X, y: $Y, z: 3}}"

    ros2 run ros_gz_bridge parameter_bridge \
        /model/${ROBOT_ID}/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
        /model/${ROBOT_ID}/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
        /model/${ROBOT_ID}/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V \
        --ros-args \
        -r /model/${ROBOT_ID}/cmd_vel:=/${ROBOT_ID}/cmd_vel \
        -r /model/${ROBOT_ID}/odometry:=/${ROBOT_ID}/odom \
        -r /model/${ROBOT_ID}/pose:=/${ROBOT_ID}/pose_truth &

    # /${ROBOT_ID}/pose_truth is the model's TRUE world pose, published by the
    # PosePublisher block in models/<type>/model.sdf. world_odometry_node
    # publishes it as /${ROBOT_ID}/odom_world when pose_source is `localisation`
    # (the default), and compares it against the dead-reckoned estimate either
    # way. Without the bridge entry that node runs degraded and raises a
    # CRITICAL FleetAlert about it once a minute — which is the intended
    # behaviour, not a reason to silence the alert.
    #
    # THE FRAME CONVERSION. Without this node nothing publishes
    # /${ROBOT_ID}/odom_world, which is the topic every RCDL now declares for
    # the odometry sensor and the topic the four sim nodes below subscribe to —
    # the agent would wait in IDLE for odometry that never arrives, and the
    # battery and the spectrometer would sample forever at (0, 0).
    #
    # spawn_yaw is 0 here because THIS SCRIPT SPAWNS WITH NO YAW (the create
    # call above sets position only), unlike simulation.launch.py which takes
    # the full pose from spawn_positions.yaml. The transform must describe the
    # placement that actually happened, so passing -2.33 "to match the config"
    # would be exactly wrong. spawn_z is likewise the literal 3 used above.
    ros2 run selene_sim world_odometry_node --ros-args \
        -p robot_id:=$ROBOT_ID \
        -p spawn_x:=$X -p spawn_y:=$Y -p spawn_z:=3.0 -p spawn_yaw:=0.0 &

    ros2 run selene_sim battery_node --ros-args \
        -p robot_id:=$ROBOT_ID -p robot_type:=$ROBOT_TYPE \
        -p world_params_file:=$P/selene_sim/config/world_params.yaml &

    if [ "$ROBOT_TYPE" = "scout" ]; then
        ros2 run selene_sim neutron_spectrometer_node --ros-args \
            -p robot_id:=$ROBOT_ID \
            -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
    fi

    if [ "$ROBOT_TYPE" = "excavator" ]; then
        ros2 run selene_sim extraction_node --ros-args \
            -p robot_id:=$ROBOT_ID \
            -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
        # rcdl_path is REQUIRED by hopper_node: it reads capacity_kg and
        # transfer_rate out of the same RCDL the agent's HAL is built from, so
        # the fraction the node publishes and the kilograms the HAL derives
        # cannot disagree (deviation D-06). Without it the node raises
        # ValueError at construction and the excavator's fill sensor never
        # publishes -- the same silent failure class D-06 is about.
        # simulation.launch.py resolves the same file via FindPackageShare;
        # this hand-rolled script uses the $P/selene_hal/config/ form that
        # start_agent already uses at :95.
        ros2 run selene_sim hopper_node --ros-args \
            -p robot_id:=$ROBOT_ID \
            -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml \
            -p rcdl_path:=$P/selene_hal/config/excavator.yaml &
    fi

    if [ "$ROBOT_TYPE" = "hauler" ]; then
        # rcdl_path is REQUIRED by bin_load_node -- see the hopper_node note.
        ros2 run selene_sim bin_load_node --ros-args \
            -p robot_id:=$ROBOT_ID \
            -p rcdl_path:=$P/selene_hal/config/hauler.yaml &
    fi
}

# Helper: start an agent node
#
# BID WEIGHTS ARE NOT SET HERE, DELIBERATELY (deviation D-13). `ros2 run` with
# no override leaves agent_node.py:114-116's declared defaults in place, which
# are the same three numbers selene_agent/launch/agent.launch.py now passes.
# Restating them here would create a second copy to keep in step with the first
# — and the whole of D-13 is a number written in a place that did not feed the
# code that reads it. To tune bidding under this script, add
# `-p bid_weight_distance:=<x>` below; the deployment knob for the launch path
# is agent.launch.py.
start_agent() {
    local ROBOT_ID=$1 ROBOT_TYPE=$2 RCDL=$3 ORCH=$4
    ros2 run selene_agent agent_node --ros-args \
        -p robot_id:=$ROBOT_ID -p robot_type:=$ROBOT_TYPE \
        -p rcdl_path:=$P/selene_hal/config/$RCDL \
        -p hal_backend:=gazebo \
        -p nav_config_path:=$P/selene_agent/config/nav_params.yaml \
        -p orchestrated:=$ORCH &
}

STEPS=$( [ "$ORCHESTRATED" = true ] && echo 7 || echo 6 )

# 1. Gazebo server
echo "[1/$STEPS] Starting Gazebo server..."
gz sim -s -r $P/selene_sim/worlds/lunar_psr.sdf &
sleep 12

# 2. rosbridge
echo "[2/$STEPS] Starting rosbridge (ws://localhost:9090)..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml > /dev/null 2>&1 &
sleep 3

# 3. Dashboard
if [ "$HEADLESS" = false ]; then
    echo "[3/$STEPS] Starting dashboard (http://localhost:3000)..."
    cd $P/selene_dashboard
    HOST=0.0.0.0 BROWSER=none "$NPM" start > /dev/null 2>&1 &
    cd $P
    sleep 8
else
    echo "[3/$STEPS] Skipping dashboard (headless mode)"
fi

if [ "$ORCHESTRATED" = true ]; then
    # --- PHASE 4: Full ISRU Fleet ---
    echo "[4/$STEPS] Spawning fleet (2 scouts, 1 excavator, 1 hauler)..."
    spawn_robot scout_01 scout $P/selene_sim/models/scout/model.sdf -70 -110
    sleep 2
    spawn_robot scout_02 scout $P/selene_sim/models/scout/model.sdf -80 -110
    sleep 2
    spawn_robot excavator_01 excavator $P/selene_sim/models/excavator/model.sdf -65 -105
    sleep 2
    spawn_robot hauler_01 hauler $P/selene_sim/models/hauler/model.sdf -75 -105
    sleep 3

    echo "[5/$STEPS] Starting orchestrator..."
    ros2 run selene_orchestrator orchestrator_node --ros-args \
        --params-file $P/selene_orchestrator/config/orchestrator_params.yaml \
        -p fleet_robot_ids:="['scout_01', 'scout_02', 'excavator_01', 'hauler_01']" &
    sleep 3

    echo "[6/$STEPS] Starting agents (orchestrated mode)..."
    start_agent scout_01 scout scout.yaml true
    start_agent scout_02 scout scout.yaml true
    start_agent excavator_01 excavator excavator.yaml true
    start_agent hauler_01 hauler hauler.yaml true
    sleep 2

    echo ""
    echo "  ============================================"
    echo "  SELENE Phase 4 — Full ISRU Fleet"
    echo "  ============================================"
    echo "  Dashboard:     http://localhost:3000"
    echo "  rosbridge:     ws://localhost:9090"
    echo "  Orchestrator:  HTN planning + auction coordination"
    echo "  Fleet:         scout_01, scout_02, excavator_01, hauler_01"
    echo "  Mission:       Collect 100 kg ice from PSR zone"
    echo "  ============================================"
    echo "  Press Ctrl+C to stop everything"
    echo ""

    echo "[7/$STEPS] Fleet running. Waiting..."
    wait

else
    # --- PHASE 2: Single scout standalone mode ---
    echo "[4/$STEPS] Spawning scout_01..."
    spawn_robot scout_01 scout $P/selene_sim/models/scout/model.sdf -70 -110
    sleep 3

    echo "[5/$STEPS] Starting agent (standalone mode)..."
    echo ""
    echo "  ============================================"
    echo "  SELENE Phase 2 — Single Agent Autonomy"
    echo "  ============================================"
    echo "  Dashboard:  http://localhost:3000"
    echo "  rosbridge:  ws://localhost:9090"
    echo "  Agent:      scout_01 (standalone prospecting)"
    echo "  Waypoints:  5 targets near PSR ice deposits"
    echo "  ============================================"
    echo "  Press Ctrl+C to stop everything"
    echo ""

    start_agent scout_01 scout scout.yaml false
    wait
fi
