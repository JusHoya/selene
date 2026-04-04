#!/bin/bash
# SELENE Phase 2 Demo — Single Scout Autonomous Prospecting
#
# Prerequisites:
#   1. Copy project to Linux-native filesystem:
#      rsync -a --exclude=build --exclude=install --exclude=log --exclude=.git \
#        --exclude=__pycache__ --exclude='*.egg-info' --exclude=node_modules \
#        /mnt/c/Users/hoyer/WorkSpace/Projects/selene/ ~/selene/
#
#   2. Build:
#      source /opt/ros/jazzy/setup.bash
#      cd ~/selene && colcon build --symlink-install && source install/setup.bash
#
#   3. Run:
#      bash scripts/run_demo.sh
#
# Press Ctrl+C to stop everything.

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

echo "============================================"
echo " SELENE Phase 2 Demo"
echo " Scout Autonomous Prospecting Mission"
echo "============================================"
echo ""

# 1. Start Gazebo (headless for non-GUI, or remove -s for GUI)
echo "[1/5] Starting Gazebo..."
gz sim -s -r $P/selene_sim/worlds/lunar_psr.sdf &
sleep 12

# 2. Spawn scout
echo "[2/5] Spawning scout_01..."
gz service -s /world/lunar_psr/create \
    --reqtype gz.msgs.EntityFactory \
    --reptype gz.msgs.Boolean \
    --timeout 10000 \
    --req "sdf_filename: \"$P/selene_sim/models/scout/model.sdf\", name: \"scout_01\", pose: {position: {x: 55, y: 45, z: 3}}"
sleep 3

# 3. Bridge with remappings (Gazebo topics → RCDL-expected topics)
echo "[3/5] Starting ROS-Gazebo bridge..."
ros2 run ros_gz_bridge parameter_bridge \
    /model/scout_01/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
    /model/scout_01/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
    --ros-args \
    -r /model/scout_01/cmd_vel:=/scout_01/cmd_vel \
    -r /model/scout_01/odometry:=/scout_01/odom &
sleep 2

# 4. Simulation nodes
echo "[4/5] Starting simulation nodes..."
ros2 run selene_sim battery_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p world_params_file:=$P/selene_sim/config/world_params.yaml &

ros2 run selene_sim neutron_spectrometer_node --ros-args \
    -p robot_id:=scout_01 \
    -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
sleep 2

# 5. Agent node
echo "[5/5] Starting agent node..."
echo ""
echo "  Waypoints: (-60,-120) (-80,-140) (-100,-150) (-110,-170) (-90,-130)"
echo "  Recharge station: (40, 40)"
echo "  Battery critical: 15%"
echo ""
echo "  Monitor: ros2 topic echo /scout_01/state"
echo "============================================"
echo ""

ros2 run selene_agent agent_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p rcdl_path:=$P/selene_hal/config/scout.yaml \
    -p hal_backend:=gazebo \
    -p nav_config_path:=$P/selene_agent/config/nav_params.yaml
