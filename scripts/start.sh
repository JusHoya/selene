#!/bin/bash
# Start the SELENE simulation with Gazebo + autonomous scout agent.
# Usage: bash scripts/start.sh [--headless]
#
# The Gazebo server runs separately from the GUI so a GUI crash
# doesn't kill the simulation. On WSL2, software rendering is used
# for GPU compatibility.
#
# Run scripts/sync_and_build.sh first if code has changed.

set -e
source /opt/ros/jazzy/setup.bash
cd ~/selene
source install/setup.bash

P=$HOME/selene
export GZ_SIM_RESOURCE_PATH=$P/selene_sim/models

# WSL2 software rendering (prevents Ogre2 shader crashes)
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_GL_VERSION_OVERRIDE=3.3

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

# 1. Start Gazebo server (always headless — server is stable)
echo "[1/5] Starting Gazebo server..."
gz sim -s -r $P/selene_sim/worlds/lunar_psr.sdf &
sleep 12

# 2. Optionally start Gazebo GUI (connects to running server)
#    Uses Ogre 1.x render engine for WSL2 compatibility (Ogre2 crashes on WSL2 GPU shaders)
if [ "$HEADLESS" = false ]; then
    echo "[2/5] Starting Gazebo GUI (ogre engine for WSL2 compatibility)..."
    gz sim -g --render-engine ogre &
    sleep 5
else
    echo "[2/5] Skipping GUI (headless mode)"
fi

# 3. Spawn robot
echo "[3/5] Spawning scout_01..."
gz service -s /world/lunar_psr/create \
    --reqtype gz.msgs.EntityFactory \
    --reptype gz.msgs.Boolean \
    --timeout 10000 \
    --req "sdf_filename: \"$P/selene_sim/models/scout/model.sdf\", name: \"scout_01\", pose: {position: {x: 55, y: 45, z: 3}}" >/dev/null 2>&1
sleep 3

# 4. Bridge + simulation nodes
echo "[4/5] Starting bridge + sim nodes..."
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

# 5. Agent node
echo "[5/5] Starting agent..."
echo ""
echo "  Scout autonomously prospecting 5 waypoints near PSR ice deposits."
echo "  Gazebo GUI: $([ "$HEADLESS" = false ] && echo 'running (may take a moment to render)' || echo 'disabled')"
echo "  Monitor:    ros2 topic echo /scout_01/state  (in second terminal)"
echo "  Stop:       Ctrl+C"
echo ""

ros2 run selene_agent agent_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p rcdl_path:=$P/selene_hal/config/scout.yaml \
    -p hal_backend:=gazebo \
    -p nav_config_path:=$P/selene_agent/config/nav_params.yaml
