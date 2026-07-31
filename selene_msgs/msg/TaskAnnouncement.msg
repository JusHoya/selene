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
