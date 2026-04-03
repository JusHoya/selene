#!/bin/bash
# Phase 1 Drive Verification Test
source /opt/ros/jazzy/setup.bash

cat > /tmp/flat.sdf << 'EOFWORLD'
<?xml version="1.0"?>
<sdf version="1.9">
  <world name="flat">
    <physics type="ode">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>0</real_time_factor>
      <gravity>0 0 -9.81</gravity>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <model name="ground">
      <static>true</static>
      <link name="l">
        <collision name="c">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface>
        </collision>
      </link>
    </model>
  </world>
</sdf>
EOFWORLD

MODELS=/mnt/c/Users/hoyer/WorkSpace/Projects/selene/selene_sim/models
export GZ_SIM_RESOURCE_PATH=$MODELS

echo "Starting Gazebo..."
gz sim -s -r /tmp/flat.sdf &
GZ_PID=$!
sleep 5

echo "Spawning scout..."
gz service -s /world/flat/create \
  --reqtype gz.msgs.EntityFactory \
  --reptype gz.msgs.Boolean \
  --timeout 5000 \
  --req "sdf_filename: \"$MODELS/scout/model.sdf\", name: \"s1\", pose: {position: {x: 0, y: 0, z: 0.5}}"
sleep 3

echo ""
echo "=== TOPICS ==="
gz topic -l | grep -E "cmd|odom"

echo ""
echo "=== POSE BEFORE ==="
gz model -m s1 -p

echo ""
echo "=== DRIVING (100 msgs to /cmd_vel at 20Hz) ==="
for i in $(seq 1 100); do
  gz topic -t /cmd_vel -m gz.msgs.Twist -p "linear: {x: 0.5}"
  sleep 0.05
done

echo ""
echo "=== POSE AFTER ==="
gz model -m s1 -p

echo ""
echo "Stopping Gazebo..."
kill $GZ_PID
wait $GZ_PID 2>/dev/null
echo "DONE"
