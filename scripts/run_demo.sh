#!/bin/bash
# SELENE Phase 2 Demo — Single Scout Autonomous Prospecting
#
# Run this in your WSL2 Ubuntu terminal:
#   cd /mnt/c/Users/hoyer/WorkSpace/Projects/selene
#   bash scripts/run_demo.sh
#
# This launches:
#   1. Gazebo Harmonic with lunar world (GUI window)
#   2. ros_gz_bridge for scout_01
#   3. Simulation nodes (battery, neutron spectrometer)
#   4. Agent node (autonomous prospect-recharge loop)
#
# Press Ctrl+C to stop everything.

set -e

source /opt/ros/jazzy/setup.bash
cd /mnt/c/Users/hoyer/WorkSpace/Projects/selene
source install/setup.bash

MODELS=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_sim/models
CONFIGS=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_sim/config
AGENT_CFG=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_agent/config
HAL_CFG=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_hal/config
WORLD=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_sim/worlds/lunar_psr.sdf

export GZ_SIM_RESOURCE_PATH=$MODELS

# Cleanup on exit
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

# 1. Start Gazebo with GUI
echo "[1/5] Starting Gazebo Harmonic (GUI)..."
gz sim -r $WORLD &
sleep 10

# 2. Spawn scout
echo "[2/5] Spawning scout_01..."
gz service -s /world/lunar_psr/create \
    --reqtype gz.msgs.EntityFactory \
    --reptype gz.msgs.Boolean \
    --timeout 5000 \
    --req "sdf_filename: \"$MODELS/scout/model.sdf\", name: \"scout_01\", pose: {position: {x: 55, y: 45, z: 3}}"
sleep 3

# 3. Start ros_gz_bridge
echo "[3/5] Starting ROS-Gazebo bridge..."
ros2 run ros_gz_bridge parameter_bridge \
    /model/scout_01/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
    /model/scout_01/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry &
sleep 2

# 4. Start simulation nodes
echo "[4/5] Starting simulation nodes..."
ros2 run selene_sim battery_node --ros-args \
    -p robot_id:=scout_01 -p robot_type:=scout \
    -p world_params_file:=$CONFIGS/world_params.yaml \
    -r /scout_01/odom:=/model/scout_01/odometry &

ros2 run selene_sim neutron_spectrometer_node --ros-args \
    -p robot_id:=scout_01 \
    -p ice_config_file:=$CONFIGS/ice_deposits.yaml \
    -r /scout_01/odom:=/model/scout_01/odometry &
sleep 2

# 5. Start agent node
echo "[5/5] Starting agent node..."
echo ""
echo "  Waypoints: (-60,-120) (-80,-140) (-100,-150) (-110,-170) (-90,-130)"
echo "  Recharge station: (40, 40)"
echo "  Battery critical: 15%"
echo ""
echo "  Watch the Gazebo window for robot movement."
echo "  Monitor with: ros2 topic echo /scout_01/state"
echo "============================================"
echo ""

ros2 run selene_agent agent_node --ros-args \
    -p robot_id:=scout_01 \
    -p robot_type:=scout \
    -p rcdl_path:=$HAL_CFG/scout.yaml \
    -p hal_backend:=gazebo \
    -p nav_config_path:=$AGENT_CFG/nav_params.yaml \
    -p recharge_x:=40.0 \
    -p recharge_y:=40.0 \
    -p energy_critical_threshold:=0.15 \
    -p energy_recharge_target:=0.90 \
    -p tick_rate:=10.0

# This blocks until Ctrl+C
