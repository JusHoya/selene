# One row of the orchestrator's task table — FR-DASH-3 (deviation D-03).
# A direct projection of selene_orchestrator.task_queue.TaskEntry onto the wire;
# every field here has an origin in that dataclass.
#
# Never published alone: always an element of TaskQueueState.tasks.

# Stable identifier. HTN ids look like 'survey_<hex>' / 'excavate_<hex>';
# operator-injected ids are 'manual_NNNN' (TaskQueue.make_unique_task_id).
string task_id

# 'prospect' | 'excavate' | 'haul' | 'select_site'. 'select_site' is a VIRTUAL
# task resolved by the HTN planner, never auctioned (orchestrator_node.py:1502).
string task_type

# TaskStatus enum NAME, verbatim from task_queue.TaskStatus:
#   PENDING | AUCTIONING | ASSIGNED | IN_PROGRESS | COMPLETED | FAILED |
#   INTERRUPTED
# A string, not an integer: the enum is `class TaskStatus(str, Enum)` and the
# dashboard already switches on these exact spellings (TaskQueue.jsx:41-63).
#
# INTERRUPTED IS A RESTING STATE as of this change. interrupt_task() no longer
# has its result immediately overwritten with PENDING, and get_next_ready()
# re-auctions from PENDING or INTERRUPTED. It means "was started, was stopped,
# awaiting re-auction" and is how a cancelled task is told apart from a
# completed one — the defect D-03 names.
string status

# Robot currently holding the task, or '' when unassigned. Cleared by
# interrupt_task() and recover_tasks_for_robot().
string assigned_robot

# FR-DASH-5: the robot the operator asked for on injection, or '' for an
# unconstrained auction. This is a PREFERENCE, not an assignment: the task still
# enters the auction, and the preference only decides the winner when that robot
# bids. Cleared once auction_rounds exceeds inject_preferred_robot_max_rounds,
# after which the auction is fully open.
string preferred_robot

# Higher wins the auction queue. HTN: 5.0 survey, 4.0 select_site, 3.0
# excavate/haul. Operator injections: 10.0 (orchestrator_node.py:468).
float32 priority

# 0.0..1.0. Sourced from RobotState.task_progress on the assigned robot, which
# the orchestrator now records into the queue entry. 0.0 for any task no robot
# is currently running. NOT a mass fraction.
float32 progress

# FR-DASH-5 operator quantity, KILOGRAMS. 0.0 means unconstrained — fill to the
# robot's own RCDL capacity, which is the pre-existing behaviour, so 0.0 is
# exactly backward-compatible. Ignored for 'prospect' and 'select_site'.
# The orchestrator does NOT clamp this: it has no HAL and no RCDL, so the
# capacity limit is applied by the agent against selene_hal/config/<type>.yaml
# (excavator hopper_fill capacity_kg 20, hauler load_cell capacity_kg 50).
float32 quantity_kg

# World coordinates of the task target, metres. z unused.
# FRAME: world, and as of 2026-07-31 that is finally literal. This comment used
# to read "the same dead-reckoned odom-derived frame as everything else in this
# system - see D-08": every pose in SELENE was expressed relative to the
# reporting robot's own spawn, so a target here and a robot's reported position
# were in DIFFERENT frames, one per robot. Position is now converted once, by
# selene_sim/selene_sim/world_odometry_node.py, and the two are comparable.
geometry_msgs/Point target_location

# HTN mission id this task belongs to, or ''.
string parent_task_id

# task_ids this task waits on (TaskQueue.get_next_ready, via
# TaskQueue.dependencies_met).
#
# ORDINARILY ALL OF THEM MUST BE COMPLETED, and that is the rule for every task
# type here except one.
#
# THE EXCEPTION IS A SOFT / EVIDENTIAL EDGE, D2. A task may carry a dependency
# QUORUM (TaskQueue.TaskEntry.depends_on_quorum), and one does: the HTN
# planner's select_site task, whose quorum is htn_planner.SELECT_SITE_SURVEY_QUORUM
# = 1. Such a task becomes eligible when every dependency is RESOLVED --
# COMPLETED, or FAILED with all task_feed.TASK_MAX_ATTEMPTS attempts spent --
# AND at least `quorum` of them COMPLETED. It exists because survey ->
# select_site is evidential rather than causal: htn_planner._pick_best_site
# scores the fused ResourceMap posterior and never reads the survey task list,
# so one dead survey degrades confidence, not correctness. Before it, one FAILED
# survey killed select_site and with it every excavate and haul, permanently.
# The excavate -> haul -> excavate chain is CAUSAL and carries no quorum.
#
# THE QUORUM IS NOT PUBLISHED. It is a plain Python field on the queue entry,
# because adding one here needs a rosidl regeneration across all six packages
# and this branch has had none. What a consumer sees instead is the
# 'site_selected_partial' status_reason below, after the fact -- so this field
# alone cannot tell you whether a given row's edge is hard or soft.
string[] depends_on

# Capabilities a bidder must have. Matched against RobotState.capabilities.
string[] required_capabilities

# Why the last status transition happened, or '' when there was no reason to
# record ('' is also what an ordinary highest-bid auction win carries —
# task_feed.resolve_auction_winner returns '' for that case).
# This is what lets the dashboard render 'cancelled' rather than 'done'.
#
# Known values, each traced to the line that writes it. NOT a closed set: the
# FAILED case below passes TaskResult.failure_reason through verbatim, so any
# string an agent skill produces can appear. Treat an unrecognised value as
# opaque text rather than switching on it exhaustively.
#   auction lifecycle (task_queue.py:181, task_feed.py:203/207/210)
#     'auction_started' | 'preferred_robot' | 'auction_no_bids' |
#     'preferred_robot_absent' | 'preference_dropped'
#     'auction_preempted' -- this task's auction was ABORTED, not resolved.
#                            An operator injected an EMERGENCY task at a higher
#                            priority while this auction was in flight, and the
#                            orchestrator handed it the single auction slot
#                            (task_queue.abort_auction, called from
#                            orchestrator_node._preempt_for_emergency). The
#                            status returns to whatever it was BEFORE the
#                            auction started: PENDING for a task that was never
#                            started, INTERRUPTED for one an operator had
#                            cancelled -- D-03's distinction survives the
#                            preemption. `auction_rounds` is REFUNDED, because
#                            the round was never resolved and charging it would
#                            expire another operator's preferred_robot for a
#                            reason that has nothing to do with that robot.
#                            A preemption is the ORCHESTRATOR'S OWN CHOICE and
#                            is not evidence the fleet declined the task, so it
#                            deliberately does NOT feed the D-20 backoff:
#                            failed_auctions and the backoff deadline are left
#                            untouched. Bids collected in the aborted window are
#                            discarded (TaskAuction.reset).
#   auction backoff, D-20 (task_feed.auction_failure_reason,
#                          task_queue.wake_deferred_auctions)
#     'auction_backoff'   -- two or more consecutive auctions closed with no
#                            bid. The task is held off for base * 2**(n-1)
#                            seconds before being announced again, so the
#                            single auction slot is not burned on it. Still
#                            PENDING: it was never started.
#     'auction_abandoned' -- auction_max_failed_rounds consecutive no-bid
#                            auctions. The orchestrator has STOPPED announcing
#                            it. This is the "visibly blocked" state and it is
#                            the one an operator has to act on: it usually
#                            means no robot in the fleet has the capability or
#                            the energy range to service the task. It is
#                            re-announced automatically the next time any robot
#                            arrives in IDLE, so it is not terminal.
#     'fleet_changed'     -- a robot became IDLE and every backed-off or
#                            abandoned task was made auctionable again.
#                            Written without a status transition (the status
#                            was already PENDING/INTERRUPTED), so it appears in
#                            this field with no matching TaskEvent; the wake is
#                            logged once, with a count, on the orchestrator.
#   material authorisation, D-06 (orchestrator_node.py:278/282/284)
#     'haul_no_site'      -- the task names no site, or no site is selected yet
#     'haul_no_material'  -- the ledger says that site holds nothing to haul
#   robot-reported (orchestrator_node.py:324/1278/1299/1331/1333)
#     'robot_started' -- the ASSIGNED -> IN_PROGRESS promotion, D-03
#     'inferred_from_robot_state' | 'skill_complete' | 'skill_failed' |
#     'robot_error'
#   bounded skill retry, D2 (task_feed.py TASK_RETRY_REQUEUED /
#                            TASK_ATTEMPTS_EXHAUSTED, written by
#                            orchestrator_node._retry_failed_tasks and
#                            _report_attempts_exhausted)
#     'skill_failed_requeued'
#                         -- a skill reported this task FAILED and it had an
#                            attempt left, so it was returned to PENDING and
#                            re-enters the ordinary auction. The status here is
#                            PENDING, not FAILED: this reason is the only thing
#                            that says the row is a SECOND attempt rather than
#                            work nobody has tried. `assigned_robot` is cleared
#                            and no robot is reserved for the retry.
#     'attempts_exhausted'
#                         -- the task has now FAILED task_feed.TASK_MAX_ATTEMPTS
#                            (3) times and the orchestrator has STOPPED
#                            retrying it. TERMINAL, and the only terminal
#                            status_reason in this list: nothing in the system
#                            moves a task out of it. Every task that depends_on
#                            this one -- directly or transitively -- through an
#                            ORDINARY edge can therefore never become ready,
#                            because such a dependency is satisfied only by
#                            COMPLETED. THE ONE EXCEPTION is a dependent
#                            carrying a soft dependency quorum (see depends_on
#                            above): an exhausted task counts as RESOLVED, so
#                            select_site can still resolve on partial evidence
#                            and will carry 'site_selected_partial' when it
#                            does. It REPLACES the
#                            skill's own failure_reason on this field; that
#                            string survives in the FAILED TaskEvent's detail
#                            and is quoted verbatim in the CRITICAL FleetAlert
#                            raised once when this is written. An operator has
#                            to act: re-inject the work or cancel what depends
#                            on it.
#   soft dependency quorum, D2 (task_feed.py SITE_SELECTED /
#                               SITE_SELECTED_PARTIAL, both written by
#                               htn_planner.check_and_advance)
#     'site_selected'     -- the virtual select_site task resolved with EVERY
#                            survey it depends_on COMPLETED. The ordinary case.
#     'site_selected_partial'
#                         -- select_site resolved on a PARTIAL quorum: every
#                            survey was RESOLVED and at least
#                            htn_planner.SELECT_SITE_SURVEY_QUORUM of them
#                            COMPLETED, but the rest exhausted every attempt and
#                            stay FAILED. The mission PROCEEDED instead of
#                            deadlocking, and the extraction site is the best
#                            cell of a SMALLER surveyed area than was planned.
#                            The site is never re-selected. A WARNING FleetAlert
#                            from orchestrator_node._htn_advance carries the
#                            counts once; this field carries the fact for the
#                            rest of the mission.
#   fleet health (task_queue.py:200, recover_tasks_for_robot's default)
#     'heartbeat_timeout' -- FleetMonitor declared the holding robot OFFLINE
#                            and its tasks were re-queued (the default reason
#                            of recover_tasks_for_robot).
#     'robot_offline'     -- the D3(b) backstop sweep,
#                            orchestrator_node._recover_offline_robot_tasks,
#                            found a task still held by an ALREADY-OFFLINE
#                            robot after that robot's one-and-only heartbeat
#                            recovery had run. Same effect as
#                            'heartbeat_timeout' -- re-queued as PENDING with
#                            assigned_robot cleared -- and a different reason
#                            because the two say different things about the
#                            orchestrator: the first is the recovery working,
#                            the second is the recovery having missed.
#   operator (orchestrator_node.py:477/584-585)
#     'inject_rejected' | 'operator_cancel_task' | 'operator_force_recharge'
#     Only those two commands re-queue a task; 'send_to_location' does not
#     touch the queue, so there is no 'operator_send_to_location' reason.
string status_reason

# When `status` last CHANGED — not when this snapshot was taken, which is
# TaskQueueState.header.stamp.
builtin_interfaces/Time status_changed

# How many auctions this task has been through. >1 means it was re-queued: no
# bids, a heartbeat timeout, an operator cancel, or a preferred robot that did
# not bid.
uint32 auction_rounds

# True when this task was injected by an operator with InjectTask.emergency
# set. Origin: task_queue.TaskEntry.emergency, projected by task_feed.task_rows.
#
# WHAT IT MEANS: this task was injected as an emergency, so it was allowed to
# abort ONE auction already in flight for a lower-priority task.
# WHAT IT DOES NOT MEAN: that it did, or that it still may. The entitlement is
# spent the first time it is used (task_queue.TaskEntry.preemption_spent) and
# this field is never cleared, so a true here says what the OPERATOR asked for,
# not what the task can still do. A preemption leaves its evidence on the
# VICTIM's row, as status_reason 'auction_preempted', not here; an emergency
# task that arrived while the auction slot was free preempted nothing.
# It is also NOT a priority: priority is 10.0 for every operator injection, and
# a non-emergency 10.0 waits its turn.
#
# HTN-generated tasks are never emergency -- only inject_task_logic sets it --
# so this is false on every row the planner produced.
#
# Appended at the end so the wire layout of every existing field is unchanged.
bool emergency
