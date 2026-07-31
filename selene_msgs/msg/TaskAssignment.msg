string task_id
string robot_id
string task_type

# Where the WORK is. For a haul this is the PICKUP (the extraction site), not
# the depot — see depot_location below for why that needed saying.
geometry_msgs/Point target_location

# RESERVED, UNUSED. Set to [] by every publisher and read by nobody.
# Deliberately NOT repurposed to carry quantity as 'quantity_kg=12.5': an
# untyped, unit-less string side channel is the opposite of what this package's
# other definitions do (see ResourceMap.msg). Delete it or give it a schema; do
# not encode into it.
string[] parameters

builtin_interfaces/Time assigned_at

# ---- Added 2026-07-30 closing D-04 and D-06. ----

# Mass this assignment authorises, KILOGRAMS, >= 0. 0.0 means unconstrained —
# fill to the robot's own RCDL capacity, which is the behaviour every task had
# before this field existed, so 0.0 is exactly backward-compatible.
#   excavate: target extracted mass. Sourced from InjectTask.quantity for an
#             operator task; 0.0 for HTN-generated tasks.
#   haul:     the mass the orchestrator's ledger says is waiting at
#             target_location (MaterialInventory.get_site_available). The agent
#             passes it to TransferActuator.trigger_load(max_kg=...), so the
#             simulated bin can no longer load 50 kg of material that was never
#             extracted — which is what bin_load_node.py did before 2026-07-30,
#             filling to its full capacity on a bare `load` regardless of any
#             excavator (see that file's module docstring).
#
# 0.0 IS UNREACHABLE ON A haul ASSIGNMENT, and deliberately so. An unconstrained
# haul would be read by the agent as "fill to the RCDL capacity", i.e. it would
# fabricate a bin's worth of material the ledger never saw. So when the
# orchestrator cannot authorise a mass it WITHHOLDS the assignment rather than
# publishing 0.0: authorise_task_quantity returns a block reason, and the task is
# re-queued with that reason as its TaskStatus.status_reason
# ('haul_no_site' | 'haul_no_material') instead of being assigned. Three gates
# enforce it — _auction_tick (not announced), _resolve_auction (authoritative,
# catches a site drained during its own auction) and _publish_assignment
# (refuses and logs). The visible cost is that a haul whose excavate reported no
# measured mass STALLS the HTN chain, with a WARNING naming the reason, rather
# than silently moving 50 kg that does not exist.
#
# An operator-named quantity > 0 is a separate case and is still honoured
# unclamped even at an empty site (FR-DASH-5). It is not silent: the overdraw
# surfaces as MissionProgress.unaccounted_quantity and a named WARNING.
#
# NOT clamped by the orchestrator, which has no HAL and no RCDL. The agent
# clamps against selene_hal/config/<type>.yaml.
float32 quantity_kg

# Where a haul must deliver, world metres. Zero (0,0,0) and unused for every
# other task type. Before this field existed, HTNPlanner._generate_cycles
# (now htn_planner.py:336, which records the history in its own docstring at
# :347-350) put the DEPOT in target_location, and agent_node read
# target_location as the PICKUP and used the robot's own recharge station as
# the depot (that read is now agent_node.py:741-750, which takes the depot from
# this field and only falls back to the charger when it is unset). A haul
# therefore drove to the depot,
# "loaded" 50 kg of nothing, drove to the charger and dumped it there, never
# visiting the extraction site at all.
# FRAME: world metres, the same frame as target_location. It said "the same
# dead-reckoned odom-derived frame" until 2026-07-31, when that stopped being
# true: robot position is now published world-referenced by
# selene_sim/selene_sim/world_odometry_node.py, which composes each robot's
# spawn SE(2) onto Gazebo's dead-reckoned odom. This coordinate and the pose a
# robot reports are now in ONE frame, which is what makes comparing them mean
# anything.
geometry_msgs/Point depot_location
