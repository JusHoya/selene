# One entry in the orchestrator's bounded event log: a task status transition,
# or an operator action — D-05, plus the part of D-03 a status table cannot
# carry.
#
# Never published alone: always an element of TaskQueueState.events.
#
# WHY THIS EXISTS SEPARATELY FROM TaskStatus. Two things a status snapshot
# cannot express:
#  (1) A transition that does not rest. INTERRUPTED -> re-auction -> COMPLETED
#      leaves no trace in the final row, so "this task was cancelled once" is
#      unrecoverable from the table alone.
#  (2) An operator action that touches NO task at all — 'force_recharge' on an
#      idle robot, 'send_to_location'. FR-DASH-6(d) (docs/PRD.md:543) requires
#      overrides to be "logged and visible in the task history", and there is no
#      task to hang them on.

# Monotonic from orchestrator startup, never reused. The ring is replayed in
# full in every snapshot, so a client MUST dedupe on this. It also lets a
# continuously-connected client detect that it missed events (lowest seq in this
# snapshot > highest seq it holds + 1).
uint32 seq

# When the event happened — NOT when the snapshot carrying it was taken.
builtin_interfaces/Time stamp

# 'status'   -- a task changed TaskStatus. `action` is the new status name.
# 'operator' -- a dashboard-initiated command. `action` is the command.
string kind

# Task the event is about, or '' when it is not about a task (an override on an
# idle robot).
string task_id

# Robot the event is about, or '' when it is not robot-specific.
string robot_id

# Who caused it: 'operator', 'orchestrator', or a robot_id.
string actor

# kind == 'status'   : the new TaskStatus name (PENDING | AUCTIONING |
#                      ASSIGNED | IN_PROGRESS | COMPLETED | FAILED |
#                      INTERRUPTED).
# kind == 'operator' : the command — 'cancel_task' | 'send_to_location' |
#                      'force_recharge' (OverrideRobot.command) or
#                      'inject_task' (InjectTask).
string action

# Free text for a human. For a status event, the status_reason. For an operator
# event, the exact response.message the service returned to the dashboard, so
# the history and the operator's own feedback toast cannot disagree.
string detail

# kind == 'operator' only: did the command succeed. Rejections are logged too
# and are often the more interesting record ("robot in ERROR, override
# rejected"). Always false for kind == 'status'; read it only when kind is
# 'operator'.
bool accepted

# kind == 'operator', action == 'send_to_location' or 'inject_task': the target
# the operator picked, world metres. Zero otherwise.
geometry_msgs/Point target
