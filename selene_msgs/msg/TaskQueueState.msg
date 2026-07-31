# Complete snapshot of the orchestrator's task queue plus a bounded event ring —
# FR-DASH-3, and FR-DASH-6(d)'s "visible in the task history".
#
# Published on /orchestrator/task_queue at task_queue_publish_rate (default
# 2.0 Hz, orchestrator_params.yaml). A rate <= 0 disables publishing with a
# warning rather than dividing by zero — the same convention as
# resource_map_publish_rate (orchestrator_node.py:1189-1196).
#
# COMPLETE SNAPSHOT, NEVER A DELTA — the same choice, for the same reasons, as
# ResourceMap.msg. A subscriber that joins late or drops a message is fully
# correct from the next one. Concretely: a browser loaded mid-mission is correct
# within 500 ms with NO durability negotiation, which matters because
# transient_local latching is the part of ROS QoS that rosbridge handles least
# predictably — the bridge subscribes with its own profile and a durability
# mismatch drops the sample with nothing surfaced client-side. A 2 Hz snapshot
# needs none of that, so this topic uses the DEFAULT volatile QoS.
#
# SIZE. Bounded by the mission decomposition, not by runtime: HTNPlanner creates
# SURVEY_WAYPOINT_COUNT (10) prospect tasks + 1 select_site, and _generate_cycles
# creates ceil(quantity_kg / HOPPER_CAPACITY_KG) = ceil(100/20) = 5
# excavate+haul pairs — 21 tasks nominal, plus operator injections. At roughly
# 180 B/task that is under 4 kB, about a third of the ResourceMap snapshot
# already on the wire, and some three orders of magnitude below the dense grid
# whose rosbridge extract_values cost D-09 measured at ~284 ms. ESTIMATE, scaled
# from the measurements in ResourceMap.msg — not itself measured.
#
# 2 Hz is chosen against docs/PRD.md:1505 — "Task queue reflects orchestrator
# state within 1 second" — leaving a worst-case 500 ms publish latency before
# transport.

# Snapshot acquisition time. frame_id is unused and left ''.
std_msgs/Header header

# Every task the orchestrator knows about, in no guaranteed order. Tasks are
# never removed from the queue, so completed work stays visible and a
# freshly-loaded browser sees the full history.
TaskStatus[] tasks

# The most recent events, OLDEST FIRST, capped at task_queue_event_history
# (default 32). Replayed in full every message; dedupe on TaskEvent.seq.
TaskEvent[] events

# The seq the NEXT event will be given. With the lowest seq present in `events`,
# this tells a client the exact range the ring currently covers.
uint32 event_seq_next

# Events evicted from the ring since startup. Non-zero means this snapshot is
# not the complete history — the dashboard must say so rather than imply the
# list is exhaustive. Not derivable client-side by a browser that joined late,
# which is why it is on the wire.
uint32 events_dropped

# NOTE ON WHAT IS DELIBERATELY ABSENT. No pending_count / active_count /
# completed_count fields: all are derivable from `tasks`, and a redundant scalar
# beside the array it summarises is exactly how MissionProgress.target_quantity
# came to carry a task count into a kg formatter (orchestrator_node.py:1640-1643).
