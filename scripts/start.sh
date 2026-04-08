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

# Helper: spawn a robot with bridge + sim nodes
spawn_robot() {
    local ROBOT_ID=$1 ROBOT_TYPE=$2 SDF=$3 X=$4 Y=$5

    gz service -s /world/lunar_psr/create \
        --reqtype gz.msgs.EntityFactory --reptype gz.msgs.Boolean --timeout 10000 \
        --req "sdf_filename: \"$SDF\", name: \"$ROBOT_ID\", pose: {position: {x: $X, y: $Y, z: 3}}"

    ros2 run ros_gz_bridge parameter_bridge \
        /model/${ROBOT_ID}/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
        /model/${ROBOT_ID}/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
        --ros-args \
        -r /model/${ROBOT_ID}/cmd_vel:=/${ROBOT_ID}/cmd_vel \
        -r /model/${ROBOT_ID}/odometry:=/${ROBOT_ID}/odom &

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
        ros2 run selene_sim hopper_node --ros-args \
            -p robot_id:=$ROBOT_ID \
            -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
    fi

    if [ "$ROBOT_TYPE" = "hauler" ]; then
        ros2 run selene_sim bin_load_node --ros-args \
            -p robot_id:=$ROBOT_ID &
    fi
}

# Helper: start an agent node
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
    HOST=0.0.0.0 BROWSER=none /usr/bin/npm start > /dev/null 2>&1 &
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
