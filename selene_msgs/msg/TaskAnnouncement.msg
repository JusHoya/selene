string task_id
string task_type
geometry_msgs/Point target_location
float32 estimated_energy_cost
string[] required_capabilities
float32 priority
float32 estimated_duration
string parent_task_id
builtin_interfaces/Time deadline

# FR-DASH-5. Operator-requested quantity for this task, KILOGRAMS.
# 0.0 means unconstrained. Ignored for 'prospect' and 'select_site'.
# Announced as well as assigned so a bidder can see the size of the job; today
# no bid weight uses it (agent_node.py:627-641 scores distance, energy and
# capability only). Appended at the end so the wire layout of every existing
# field is unchanged.
float32 quantity_kg

# True when this task was injected by an operator with InjectTask.emergency
# set, i.e. when it is allowed to abort an auction already in flight for a
# lower-priority task. Origin: task_queue.TaskEntry.emergency, copied here by
# orchestrator_node._publish_announcement.
#
# NO BIDDER READS THIS, AND SAYING SO IS THE POINT. agent_node._on_task_announced
# scores distance, energy and capability; nothing in the bid weight looks at
# urgency, and this field does not make a robot bid that would otherwise not.
#
# ITS ONE READER IS THE EXIT-GATE PROBE, and it is named here because this
# repository has shipped seven fields that were declared and never read (see
# CLAUDE.md) and an eighth would not be excused by a comment saying so.
# scripts/phase5_probe.py records it in ProbeNode._on_announcement and check 6
# ASSERTS it: an injection made with InjectTask.emergency=True must produce an
# announcement carrying emergency=True for that same task_id. So the hop
# inject_task_logic -> TaskEntry.emergency -> _publish_announcement is verified
# end to end on a live DDS wire, and an edit that dropped it would fail the
# gate rather than only a unit test.
#
# Appended at the end so the wire layout of every existing field is unchanged.
bool emergency
