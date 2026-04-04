#!/bin/bash
# Start the SELENE simulation with Gazebo GUI + autonomous scout agent.
# Usage: bash scripts/start.sh [--headless]
#
# Run scripts/sync_and_build.sh first if code has changed.

set -e
source /opt/ros/jazzy/setup.bash
cd ~/selene
source install/setup.bash

P=$HOME/selene
export GZ_SIM_RESOURCE_PATH=$P/selene_sim/models

cleanup() { echo ""; echo "Shutting down..."; kill $(jobs -p) 2>/dev/null; wait 2>/dev/null; echo "Done."; }
trap cleanup EXIT

GZ_FLAGS="-r"
[ "$1" = "--headless" ] && GZ_FLAGS="-s -r"

echo "Starting Gazebo..."
gz sim $GZ_FLAGS $P/selene_sim/worlds/lunar_psr.sdf &
sleep 12

echo "Spawning scout_01..."
gz service -s /world/lunar_psr/create --reqtype gz.msgs.EntityFactory --reptype gz.msgs.Boolean --timeout 10000 \
  --req "sdf_filename: \"$P/selene_sim/models/scout/model.sdf\", name: \"scout_01\", pose: {position: {x: 55, y: 45, z: 3}}" >/dev/null 2>&1
sleep 3

echo "Starting bridge + sim nodes..."
ros2 run ros_gz_bridge parameter_bridge \
  /model/scout_01/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /model/scout_01/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  --ros-args -r /model/scout_01/cmd_vel:=/scout_01/cmd_vel -r /model/scout_01/odometry:=/scout_01/odom &

ros2 run selene_sim battery_node --ros-args -p robot_id:=scout_01 -p robot_type:=scout \
  -p world_params_file:=$P/selene_sim/config/world_params.yaml &
ros2 run selene_sim neutron_spectrometer_node --ros-args -p robot_id:=scout_01 \
  -p ice_config_file:=$P/selene_sim/config/ice_deposits.yaml &
sleep 2

echo "Starting agent... (Ctrl+C to stop)"
echo ""
ros2 run selene_agent agent_node --ros-args \
  -p robot_id:=scout_01 -p robot_type:=scout \
  -p rcdl_path:=$P/selene_hal/config/scout.yaml \
  -p hal_backend:=gazebo \
  -p nav_config_path:=$P/selene_agent/config/nav_params.yaml
