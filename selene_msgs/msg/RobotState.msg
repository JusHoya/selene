string robot_id
string robot_type
string fsm_state
geometry_msgs/Pose2D pose
geometry_msgs/Twist velocity
float32 battery_level            # 0.0-1.0 state of charge
string current_task_id
float32 task_progress            # 0.0-1.0, from the running skill
string[] capabilities
builtin_interfaces/Time stamp

# ---- Added 2026-07-30 closing D-06 (FR-DASH-7 energy clause). ----

# This robot's battery capacity in WATT-HOURS, from its own RCDL
# (selene_hal/config/<type>.yaml battery.capacity) via
# HalInterface.get_battery().get_capacity_wh(): scout 50, excavator 80,
# hauler 65. The orchestrator's FleetMonitor converts battery_level deltas to Wh
# with it. It previously used a single hardcoded 50 Wh for every robot
# (fleet_monitor.py:9,16,65) — that is the scout's capacity, and it understates
# an excavator by 37.5% and a hauler by 23%. Reported BY THE ROBOT rather than
# looked up by the orchestrator so the RCDL stays the single source of truth and
# selene_orchestrator needs no dependency on selene_hal or pydantic.
# FleetMonitor falls back to DEFAULT_BATTERY_CAPACITY_WH (50.0) on a 0.0, so an
# agent built before this field still reports plausible energy rather than zero.
float32 battery_capacity_wh

# ---- Added 2026-07-31 closing D-31 (the fabricated pose). ----

# true iff `pose` above carries a real odometry reading.
#
# WHAT WAS WRONG. `GazeboOdometrySensor.read()` never raises; before the first
# `/odom_world` message arrives it returns a cached `OdometryReading` built in
# its constructor with an explicit `is_valid=False` and `x`/`y` left at the
# dataclass default 0.0 (selene_hal/selene_hal/gazebo_hal.py:357-359, :385-387;
# selene_hal/selene_hal/data_types.py:102-109). Note `is_valid` is NOT
# false by default -- `SensorReading.is_valid` defaults to True
# (data_types.py:39) and the odometry sensor passes False deliberately; the
# fail-safe on that side is a decision, not a language default.
# `AgentNode._publish_state`
# copied `odom.x`/`odom.y` into `pose` with no validity test, so every robot
# published a confident (0, 0) at 2 Hz from node start until its model existed
# in Gazebo — and this message had no way to say so. The orchestrator's
# FleetMonitor seeded its distance accumulator from that fabricated origin and
# booked |spawn| — 90.050 m to 127.224 m per robot on the shipped ten-robot
# fleet — as travelled distance the first time a real pose arrived. Launch
# staggers spawns 2 s apart while every agent starts at t=12 s
# (selene_sim/launch/simulation.launch.py:206-210,
# selene_sim/launch/unified_sim.launch.py:177-178), so robots 7-10 fabricate
# for 2-8 s each.
#
# `pose` IS STILL POPULATED when this is false — the flag, not the value,
# carries the meaning, and the message keeps flowing because it is also the
# heartbeat `FleetMonitor.check_heartbeats` reads. A consumer that integrates,
# averages or renders `pose` must test this field first.
#
# THE COST OF THE FAIL-SAFE DEFAULT, stated rather than assumed. ROS 2
# default-initialises bool to false and a subscriber cannot distinguish "the
# publisher set it false" from "the publisher never set it", so any RobotState
# built by code not updated in this same pass reports "no fix" and its robot
# drops out of the distance total and out of the orchestrator's survey centroid
# (`_survey_reference_position`). That direction is deliberate — a silent zero is what
# caused D-31 — but it is not free. In practice the exposure is a partially
# rebuilt workspace: appending a field changes the type hash, and a node built
# against the old definition does not error, it simply never connects (the D-11
# class). Rebuild all six packages in one `colcon build` and verify a message
# actually arrives.
bool pose_valid
