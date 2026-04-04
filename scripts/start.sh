#!/bin/bash
# Start the SELENE simulation with Mission Control Dashboard.
# Usage: bash scripts/start.sh [--headless]
#
# Launches:
#   1. Gazebo simulation server (headless)
#   2. rosbridge WebSocket (port 9090) for dashboard connectivity
#   3. Mission Control Dashboard (port 3000) — open http://localhost:3000
#   4. ROS-Gazebo bridge + simulation nodes (battery, neutron spec)
#   5. Autonomous scout agent
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
[ "$1" = "--headless" ] && HEADLESS=true

# 1. Gazebo server
echo "[1/6] Starting Gazebo server..."
gz sim -s -r $P/selene_sim/worlds/lunar_psr.sdf &
sleep 12

# 2. rosbridge WebSocket (connects dashboard to ROS 2)
echo "[2/6] Starting rosbridge (ws://localhost:9090)..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml > /dev/null 2>&1 &
sleep 3

# 3. Dashboard (React dev server on port 3000)
if [ "$HEADLESS" = false ]; then
    echo "[3/6] Starting Mission Control Dashboard (http://localhost:3000)..."
    cd $P/selene_dashboard
    npm start > /dev/null 2>&1 &
    cd $P
    sleep 5
else
    echo "[3/6] Skipping dashboard (headless mode)"
fi

# 4. Spawn robot + bridge + sim nodes
echo "[4/6] Spawning scout_01..."
gz service -s /world/lunar_psr/create \
    --reqtype gz.msgs.EntityFactory \
    --reptype gz.msgs.Boolean \
    --timeout 10000 \
    --req "sdf_filename: \"$P/selene_sim/models/scout/model.sdf\", name: \"scout_01\", pose: {position: {x: 55, y: 45, z: 3}}" >/dev/null 2>&1
sleep 3

echo "[5/6] Starting bridge + sim nodes..."
ros2 run ros_gz_bridge parameter_bridge \
    /model/scout_01/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
    /model/scout_01/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
    --ros-args \
    -r /model/scout_01/cmd_vel:=/scout_01/cmd_vel \
    -r /model/scout_01/odometry:=/scout_01/odom &

ros2 run selene_sim battery_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p world_params_file:=$P/selene_sim/config/world_params.yaml &

ros2 run selene_sim neutron_spectrometer_node --ros-args \
    -p robot_id:=scout_01 \
    -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
sleep 2

# 6. Agent node
echo "[6/6] Starting agent..."
echo ""
echo "  ============================================"
echo "  SELENE Mission Control"
echo "  ============================================"
echo "  Dashboard:  http://localhost:3000"
echo "  rosbridge:  ws://localhost:9090"
echo "  Agent:      scout_01 (autonomous prospecting)"
echo "  Waypoints:  5 targets near PSR ice deposits"
echo "  ============================================"
echo "  Press Ctrl+C to stop everything"
echo ""

ros2 run selene_agent agent_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p rcdl_path:=$P/selene_hal/config/scout.yaml \
    -p hal_backend:=gazebo \
    -p nav_config_path:=$P/selene_agent/config/nav_params.yaml
