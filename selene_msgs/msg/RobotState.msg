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
