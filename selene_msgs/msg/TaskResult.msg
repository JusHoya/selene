# Terminal outcome of one task, reported by the agent that ran it — D-03.
#
# THIS IS THE ONLY WAY TaskStatus.FAILED BECOMES REACHABLE. Before this message
# existed, agent_node._handle_working fired FSMEvent.TASK_COMPLETE on skill
# FAILURE as well as on success (agent_node.py:516 and :546 are still identical
# TASK_COMPLETE events — see the next paragraph for why that was left alone), so
# orchestrator_node._on_robot_state saw RETURNING/IDLE with an empty
# current_task_id and called mark_complete(). A failed excavate was recorded as
# a COMPLETED task in the orchestrator's own queue, and no dashboard change
# could have fixed it.
#
# THE FSM EVENT IS DELIBERATELY NOT CHANGED. Firing FSMEvent.FAULT instead would
# route the robot to ERROR and change fleet recovery behaviour under any
# transient skill failure. The agent keeps its recovery semantics and simply
# TELLS the orchestrator what happened.
#
# NO MASS FIELDS. Mass travels on MaterialEvent, one message per measured
# transfer. A haul performs two transfers (load, unload) and terminates once, so
# a single per-task message cannot carry both without losing one.

string task_id
string robot_id

# 'prospect' | 'excavate' | 'haul'. Echoed from the assignment.
string task_type

# Did the skill reach SkillState.COMPLETE (true) or SkillState.FAILED (false)?
bool success

# BaseSkill.get_error() when success is false; '' otherwise. Becomes
# TaskStatus.status_reason and TaskEvent.detail.
string failure_reason

# Agent wall clock at task termination.
builtin_interfaces/Time stamp
