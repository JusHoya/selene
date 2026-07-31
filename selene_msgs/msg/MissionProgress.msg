# Aggregate mission progress — FR-DASH-7 (docs/PRD.md:546-554).
# Published by selene_orchestrator on /orchestrator/mission_progress at 1 Hz.

string objective_description

# kg. The mission's mass objective, from HTNPlanner._target_kg
# (decompose_collect_ice(quantity_kg=100.0)). It briefly carried a TASK COUNT,
# which the dashboard rendered through a kg formatter; that is why every field
# below now states its unit.
float32 target_quantity

float32 extracted_quantity       # kg, cumulative from all sites
float32 in_transit_quantity      # kg, currently on haulers
float32 deposited_quantity       # kg, delivered to the depot
float32 fleet_distance_total     # METRES (the dashboard divides by 1000)

# WATT-HOURS, not kilowatt-hours. docs/PRD.md:690 (MSG-7) says kWh; the
# implementation (fleet_monitor.py:79-83) computes Wh and the dashboard
# (MissionProgress.jsx formatWh) formats Wh, promoting to kWh above 1000. Code
# and UI agree; the PRD is the outlier. Recorded here rather than silently
# changing either side.
float32 fleet_energy_total

# Seconds of ORCHESTRATOR WALL CLOCK since the node started
# (orchestrator_node.py:1061). It is NOT Gazebo simulation time: use_sim_time is
# unset everywhere in this repository (0 code occurrences) and /clock is not
# bridged (0 occurrences of /clock, gz.msgs.Clock or rosgraph_msgs). Making it
# real needs three things, and doing fewer than all three is worse than none:
# (1) a global parameter_bridge entry
#     /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock;
# (2) use_sim_time:=True on every node that times anything — agents,
#     orchestrator, all selene_sim nodes, rosbridge, rviz2;
# (3) replacing every time.monotonic()/time.time() with node-clock reads
#     (fleet_monitor.py:49,123,208; orchestrator_node.py:1246,1484,1934;
#     task_auction; ExcavateResult/HaulResult timestamps). Without (3)
#     heartbeat and auction
#     timeouts stay on wall clock while everything else moves to sim time, and
#     at the 0.5x real-time factor NFR-1.5 permits a 10 s heartbeat timeout
#     becomes 5 s of sim time and healthy robots are marked OFFLINE.
# The name is kept because renaming a published field breaks the dashboard and
# PRD MSG-7; see fleet_uptime_sec below for the honestly-labelled companion.
float32 elapsed_sim_time

# ---- Added 2026-07-30 closing D-06. ----

# Seconds since the FIRST robot heartbeat (FleetMonitor.get_uptime_sec, which
# had no production caller until now). FR-DASH-7(c) "fleet uptime". Distinct
# from elapsed_sim_time above, which starts when the orchestrator node starts —
# several seconds earlier, before any robot exists.
float32 fleet_uptime_sec

# MaterialEvent messages actually applied to the ledger. This is how the
# dashboard tells "the pipeline has reported nothing yet" from "the pipeline is
# not instrumented". It previously had to guess by testing whether any of the
# three masses was > 0 (MissionProgress.jsx massInstrumented) — which is also
# true of a correctly instrumented mission for its first minute of drilling.
uint32 material_events_applied

# Extracted mass lying at a site, not yet loaded onto a hauler, kg. Required for
# the conservation identity to close:
#     extracted == at_site + in_transit + deposited
# Without this term the check fails whenever an excavator has run ahead of a
# hauler, which is the normal state of the pipeline; that is why
# MaterialInventory.check_conservation() as originally shipped asserted
# extracted == in_transit + deposited and only ever passed as 0 == 0+0. (No
# line cited: those lines no longer exist. The current identity, with the
# at_site term, is inventory.py:213 onward.)
float32 at_site_quantity

# Mass a hauler reported loading beyond what any excavator reported extracting
# from that site, kg (MaterialInventory.get_unaccounted_kg). Zero is the only
# healthy value. Non-zero means the hopper and the load cell disagree, which is
# precisely what FR-ISRU-2's acceptance says cannot happen. THIS, not the
# identity above, is the real cross-instrument check: the identity closes
# structurally once at_site is tracked, so it can only fail on float drift.
float32 unaccounted_quantity
