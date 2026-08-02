"""Task lifecycle management for the SELENE orchestrator."""

import math
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    AUCTIONING = "AUCTIONING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


#: Statuses from which ``get_next_ready`` will re-auction a task.
#:
#: INTERRUPTED IS A RESTING STATE as of 2026-07-30 (deviation D-03). Before
#: that every caller of ``interrupt_task`` immediately overwrote the result
#: with PENDING -- ``override_robot_logic`` and ``_on_robot_state`` both did --
#: so INTERRUPTED existed for microseconds, never appeared in any snapshot, and
#: a cancelled task was indistinguishable from one that ran to completion. That
#: is exactly the defect D-03 names. Making it re-auctionable here is what lets
#: it rest: "was started, was stopped, awaiting re-auction".
REQUEUEABLE_STATUSES = (TaskStatus.PENDING, TaskStatus.INTERRUPTED)


#: Statuses from which ``recover_tasks_for_robot`` takes a task off a robot.
#:
#: WIDER THAN ``get_task_for_robot``'s tuple and deliberately so; the two used
#: to be the same literal and are now not, which is the kind of divergence that
#: has to be written down or it gets "tidied" back. That one answers "what is
#: this robot RUNNING" and feeds the IN_PROGRESS promotion and the ERROR
#: re-queue, both of which must stay narrow -- widening it would license
#: ``interrupt_task`` to yank a task out of a live auction, which is a change to
#: auction semantics. This one answers "what would be STRANDED if this robot
#: never spoke again", and the only wrong answer is a task that has already
#: finished.
#:
#: COMPLETED and FAILED are excluded because "recovering" one resurrects
#: finished work (pinned by ``test_recover_never_resurrects_a_terminal_task``).
#: PENDING is excluded because it is already re-auctionable -- including it
#: would make the operator alert's "N task(s) re-queued" count tasks that did
#: not move.
#:
#: AUCTIONING and INTERRUPTED are the widening, and it is D3(a). At the
#: ``TaskQueue`` API a task in either status can still carry a non-empty
#: ``assigned_robot``; through the orchestrator as wired today it cannot, so
#: this is NOT a live production leak being plugged. It is what makes the
#: OFFLINE sweep total rather than status-shaped, so the next path that leaves
#: ``assigned_robot`` set cannot silently re-open the hole.
RECOVERABLE_STATUSES = (
    TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS,
    TaskStatus.AUCTIONING, TaskStatus.INTERRUPTED,
)


@dataclass
class TaskEntry:
    task_id: str
    task_type: str
    target_x: float
    target_y: float
    priority: float = 1.0
    status: TaskStatus = TaskStatus.PENDING
    assigned_robot: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    estimated_energy_cost: float = 0.0
    estimated_duration: float = 0.0
    parent_task_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    progress_metadata: dict = field(default_factory=dict)

    # ---- Added 2026-07-30 closing D-03 / D-04 / D-06. ----

    #: Orchestrator-allocated extraction site this task works on, or "".
    #:
    #: A DATACLASS FIELD, NOT A progress_metadata KEY, and that is load-bearing:
    #: ``interrupt_task`` assigns ``progress_metadata`` WHOLESALE, so an
    #: operator cancel would erase the site identity of precisely the tasks
    #: about to be re-queued and re-run. A MaterialEvent whose task has no
    #: site_id is dropped by the orchestrator, so losing it here would silently
    #: stop crediting mass to the ledger after the first cancel.
    site_id: str = ""

    #: Operator/ledger-authorised mass for this task, KILOGRAMS. 0.0 means
    #: unconstrained -- fill to the robot's own RCDL capacity, which is what
    #: every task did before this field existed.
    quantity_kg: float = 0.0

    #: FR-DASH-5: the robot the operator asked for, or "". A PREFERENCE, not an
    #: assignment: the task still enters the auction and this only decides the
    #: winner when that robot bids.
    preferred_robot: str = ""

    #: 0.0-1.0, mirrored from RobotState.task_progress of the assigned robot.
    progress: float = 0.0

    #: Why the last status transition happened, or "". See TaskStatus.msg for
    #: the known values.
    status_reason: str = ""

    #: Wall-clock epoch seconds at the last status CHANGE. Wall clock, not
    #: ``time.monotonic()``: this is published as a builtin_interfaces/Time and
    #: a monotonic value has an arbitrary epoch, so the dashboard would render
    #: it as a date in 1970. Nothing in this repo sets use_sim_time (0 code
    #: occurrences), so this is not simulation time either.
    status_changed: float = 0.0

    #: How many auctions this task has entered. > 1 means it was re-queued.
    auction_rounds: int = 0

    # ---- Added 2026-07-31 closing D-20: the auction backoff. ----

    #: CONSECUTIVE auctions that closed with no bid. Reset by any assignment,
    #: by a fleet change, and by a re-queue that was not caused by the auction
    #: itself. Distinct from ``auction_rounds``, which only ever counts up and
    #: is what the dashboard shows: a task assigned on its fifth attempt has
    #: auction_rounds 5 and failed_auctions 0.
    failed_auctions: int = 0

    #: ``time.monotonic()`` before which this task must not be announced, or
    #: 0.0 for "auctionable now". ``math.inf`` means ABANDONED: no timer will
    #: ever release it and only ``wake_deferred_auctions`` can.
    #:
    #: MONOTONIC, unlike ``status_changed`` beside it, and the difference is
    #: deliberate. ``status_changed`` is published as a builtin_interfaces/Time
    #: and has to be wall clock or the dashboard renders 1970. This one is
    #: never published; it is compared against ``_auction_tick``'s own
    #: ``time.monotonic()``, and a wall clock that steps backwards over an NTP
    #: correction would strand every deferred task in the queue.
    auction_backoff_until: float = 0.0

    #: True once a TaskResult from the agent has terminated this task.
    #: ``_on_robot_state``'s positional completion heuristic skips these --
    #: TaskResult is authoritative and the heuristic is only a fallback for an
    #: agent that never sent one.
    terminal_reported: bool = False

    # ---- Added 2026-08-01: operator emergency preemption. ----

    #: True when an operator injected this task with ``InjectTask.emergency``.
    #:
    #: Only ``inject_task_logic`` ever sets it. HTN-generated tasks are never
    #: emergency, and that is not an accident of the default: an emergency is a
    #: statement by a human that the mission has changed, and a planner that
    #: could declare its own work urgent would be able to abort auctions on its
    #: own authority.
    #:
    #: What it grants is narrow and is spelled out in ``task_feed.should_preempt``:
    #: the right to ABORT an auction already in flight for a DIFFERENT,
    #: STRICTLY LOWER-priority task. It does not force an assignment, it does
    #: not free a busy robot, and it does not outrank another emergency at the
    #: same priority -- that last exclusion is what makes the mechanism
    #: terminate instead of letting two injections abort each other forever.
    emergency: bool = False

    #: The status this task held immediately BEFORE ``begin_auction`` moved it
    #: to AUCTIONING, so ``abort_auction`` can put it back exactly there.
    #:
    #: RESTORED RATHER THAN FORCED TO PENDING, and the difference is D-03's.
    #: A task an operator cancelled rests in INTERRUPTED ("was started, was
    #: stopped, awaiting re-auction"); re-PENDing it on the way out of an
    #: aborted auction would erase the one thing that tells a cancelled task
    #: apart from one that never ran -- the exact defect D-03 exists to fix,
    #: reintroduced through a side door.
    #:
    #: Defaults to PENDING, which is where a task that has never been auctioned
    #: rests anyway, so the field is never a source of a status the task could
    #: not legitimately be in.
    status_before_auction: TaskStatus = TaskStatus.PENDING

    #: True once this emergency has actually ABORTED an auction. THE BOUND.
    #:
    #: ``emergency`` is never cleared -- an operator's statement that the
    #: mission has changed does not expire -- so without this the right to
    #: preempt would be a STANDING right rather than an event. That is not a
    #: theoretical distinction: an emergency nobody bids on is backed off by
    #: D-20, ``wake_deferred_auctions`` releases it on every fleet change (and
    #: for a merely-backed-off task resets ``failed_auctions`` to 0, so it can
    #: never escalate to ABANDONED, the one state ``get_next_ready`` skips), and
    #: it would then abort whatever fresh auction happened to be in flight --
    #: forever, once per robot that finishes anything, anywhere.
    #:
    #: ONE INJECTION BUYS ONE ABORT. Aborting a second time cannot help: an
    #: abort frees an auction SLOT, never a robot, and if the emergency did not
    #: attract a bid the first time then the slot was not what it was short of.
    #: After the shot is spent the task is an ordinary priority-10.0 task, which
    #: is already the highest priority anything in this system carries.
    #:
    #: Set by ``TaskQueue.spend_preemption`` and by nothing else.
    preemption_spent: bool = False

    # ---- Added 2026-08-02 closing D2: the bounded skill retry. ----

    #: How many times a SKILL has reported this task FAILED. THE RETRY BOUND,
    #: and it is NEVER reset by anything -- that monotonicity is what makes the
    #: retry sweep terminate without needing a fleet-change gate the way
    #: ``wake_deferred_auctions`` does.
    #:
    #: Distinct from ``failed_auctions`` above, the same way that one is
    #: distinct from ``auction_rounds``: ``failed_auctions`` counts auctions
    #: that closed with NO BID (nobody tried), this counts attempts that RAN AND
    #: FAILED. A task auctioned four times before anyone bid and then failed
    #: once in the field has failed_auctions 0 (cleared by the assignment),
    #: auction_rounds 4 and failed_attempts 1.
    #:
    #: 0 therefore means "no skill has ever reported this task failed", which is
    #: what distinguishes a genuine skill failure from
    #: ``inject_task_logic._reject``'s FAILED row: that one is written through
    #: ``set_status`` rather than ``mark_failed``, so it never counts, and
    #: ``retry_failed_tasks`` refuses it structurally rather than by matching on
    #: ``status_reason``. A rejected operator injection -- "unknown robot",
    #: "robot lacks capabilities" -- must never be auctioned to the fleet.
    failed_attempts: int = 0

    #: How many of ``depends_on`` must actually have COMPLETED for this task to
    #: become ready. 0 MEANS "ALL OF THEM", which is exactly the rule this class
    #: has always applied, so every existing task and every existing call site
    #: is unchanged by this field existing.
    #:
    #: THE MISSION HAS TWO KINDS OF EDGE AND THIS QUEUE ENFORCED ONE.
    #:
    #: HARD / CAUSAL -- select_site -> excavate -> haul -> excavate ...
    #: (``htn_planner._generate_cycles``). Quorum 0, untouched. You cannot haul
    #: what was not excavated, and admitting a haul on a partial quorum would
    #: put a mass in the ISRU ledger with no extraction behind it -- and that
    #: ledger's entire value is being the one source of truth (D-06).
    #:
    #: SOFT / EVIDENTIAL -- survey -> select_site, the only one in the shipped
    #: mission. ``htn_planner._pick_best_site`` scores the FUSED ResourceMap
    #: posterior and never reads the survey task list at all, so losing one of
    #: ten surveys degrades the CONFIDENCE of the choice; it does not invalidate
    #: it. D2 was mission-fatal precisely because that soft edge was enforced as
    #: if it were causal: ONE failed survey killed select_site permanently, and
    #: every excavate and haul is generated only after select_site COMPLETES.
    #:
    #: 0 IS "ALL", NOT "NONE", AND THE ASYMMETRY IS DELIBERATE -- it makes a
    #: quorum of zero UNREPRESENTABLE by the default. ``_pick_best_site`` falls
    #: back to the zone centre when there are no readings at all
    #: (``htn_planner.py:474-477``), so k=0 would let this mission choose an
    #: extraction site having surveyed NOTHING and report success. That is the
    #: shape of deviation D-29, where an exit-gate check passed vacuously on a
    #: map with total_observations = 0, and this repository treats vacuous
    #: success as a defect.
    #:
    #: NOT ON THE WIRE, deliberately. ``task_feed.task_rows`` builds an explicit
    #: dict of TaskStatus.msg field names and the node copies it field by field,
    #: so a new dataclass field publishes nothing and needs no rosidl run --
    #: which this branch has not had. What the operator sees instead is
    #: ``status_reason`` ('site_selected_partial') and a WARNING FleetAlert. The
    #: cost is stated rather than hidden: the wire cannot say "this task HAS a
    #: soft edge", only that a site was chosen on partial evidence after it did.
    #:
    #: Written by exactly one production call site
    #: (``htn_planner.decompose_collect_ice``, for select_site) and read by
    #: exactly one (``TaskQueue.dependencies_met``).
    depends_on_quorum: int = 0


class TaskQueue:
    def __init__(self):
        self._tasks: dict[str, TaskEntry] = {}
        self._status_listener: Callable[[TaskEntry, TaskStatus], None] | None = None

    def set_status_listener(
        self, listener: Callable[[TaskEntry, TaskStatus], None] | None,
    ) -> None:
        """Register one callback invoked on every real status CHANGE.

        Called as ``listener(task, previous_status)`` AFTER the entry has been
        mutated, and only when the status actually differs from what it was.

        One hook rather than a call at each of the eleven transition sites:
        D-05 needs *every* transition in the event log, and a per-site append
        is a list that rots the first time someone adds a twelfth transition.
        """
        self._status_listener = listener

    def add_task(self, task_id: str, task_type: str, target_x: float, target_y: float,
                 priority: float = 1.0, required_capabilities: list[str] | None = None,
                 estimated_energy_cost: float = 0.0, estimated_duration: float = 0.0,
                 parent_task_id: str = "", depends_on: list[str] | None = None,
                 site_id: str = "", quantity_kg: float = 0.0,
                 preferred_robot: str = "", emergency: bool = False,
                 depends_on_quorum: int = 0) -> None:
        """Create a task. *emergency* is the operator's, and only the operator's.

        Trailing and defaulted, so every existing call site -- the four in
        ``htn_planner`` and every test -- keeps creating ordinary tasks with no
        edit. ``inject_task_logic`` is the only caller that ever passes True;
        see ``TaskEntry.emergency`` for what the flag grants and what it does
        not.

        *depends_on_quorum* is trailing and defaulted for the same reason and in
        the same shape: 0 is "every dependency must be COMPLETED", which is what
        every caller but one passes. See ``TaskEntry.depends_on_quorum``.
        """
        self._tasks[task_id] = TaskEntry(
            task_id=task_id, task_type=task_type,
            target_x=target_x, target_y=target_y,
            priority=priority,
            required_capabilities=required_capabilities or [],
            estimated_energy_cost=estimated_energy_cost,
            estimated_duration=estimated_duration,
            parent_task_id=parent_task_id,
            depends_on=depends_on or [],
            site_id=site_id,
            quantity_kg=quantity_kg,
            preferred_robot=preferred_robot,
            emergency=bool(emergency),
            depends_on_quorum=int(depends_on_quorum),
            status_changed=time.time(),
        )

    def get_next_pending(self) -> TaskEntry | None:
        """Return highest-priority PENDING task, or None.

        Literally PENDING, unlike ``get_next_ready``. Kept for symmetry with
        ``get_pending_count``; neither has a production caller.

        IT DELIBERATELY DOES NOT TIE-BREAK ON ``emergency``, and the divergence
        from ``get_next_ready`` is written down rather than left to be found.
        Nothing dispatches through here, so adding the tie-break would be
        mirroring a rule into a method no auction consults -- and the day this
        does acquire a caller, the two would have to be compared anyway.
        """
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if not pending:
            return None
        return max(pending, key=lambda t: t.priority)

    def set_status(self, task_id: str, status: TaskStatus,
                   reason: str = "") -> None:
        """Set a task's status, stamping why and when.

        Every other status-changing method on this class routes through here,
        so the event log and ``status_changed`` cannot miss a transition.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return
        previous = task.status
        task.status_reason = reason
        if previous == status:
            return
        task.status = status
        task.status_changed = time.time()
        if self._status_listener is not None:
            self._status_listener(task, previous)

    def assign_to_robot(self, task_id: str, robot_id: str,
                        reason: str = "") -> None:
        if task_id in self._tasks:
            self._tasks[task_id].assigned_robot = robot_id
            # An assignment proves the fleet can service this task, so any
            # backoff it accumulated is stale evidence (D-20). Clearing it here
            # rather than at the call site means every path that assigns --
            # ordinary auction, preferred robot, operator injection -- gets it.
            self.clear_auction_backoff(task_id)
            self.set_status(task_id, TaskStatus.ASSIGNED, reason)

    def begin_auction(self, task_id: str) -> int:
        """Move a task into AUCTIONING and count the round. Returns the count.

        The round counter lives here rather than in the auction because it must
        survive the auction object's ``reset()``: a task that has been through
        three auctions without a bid from its preferred robot is the state
        ``resolve_auction_winner`` decides on.

        It also records ``status_before_auction`` so ``abort_auction`` can put
        an interrupted task back in INTERRUPTED rather than in PENDING. The
        recording is SKIPPED when the task is already AUCTIONING, and that
        guard is not theoretical: ``begin_auction`` is not idempotent, two
        consecutive calls with no intervening resolution would otherwise record
        AUCTIONING as the pre-auction status, and a later abort would then
        "restore" the task to the state it was trying to leave. Production
        cannot do that today (``_auction_tick`` returns early while an auction
        is active) but the tests in test_task_feed.py do, deliberately, to age a
        preferred_robot's round count.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return 0
        if task.status != TaskStatus.AUCTIONING:
            task.status_before_auction = task.status
        task.auction_rounds += 1
        self.set_status(task_id, TaskStatus.AUCTIONING, reason="auction_started")
        return task.auction_rounds

    def abort_auction(self, task_id: str, reason: str) -> bool:
        """Undo ``begin_auction``: an auction ENDED WITHOUT BEING RESOLVED.

        The only caller is the operator emergency preemption
        (``orchestrator_node._preempt_for_emergency``), which takes the single
        auction slot away from this task and gives it to an emergency injection.
        Returns True when a running auction was actually undone.

        Three decisions, each of which is the difference between an honest
        record and a quiet lie:

        * THE STATUS IS RESTORED, not forced to PENDING. See
          ``TaskEntry.status_before_auction``: an operator-cancelled task rests
          in INTERRUPTED and D-03 exists to keep that distinction visible.

        * ``auction_rounds`` IS REFUNDED, floored at 0. The round never
          resolved, so nothing was learned from it. Charging it would let one
          operator's emergency silently expire a DIFFERENT operator's
          ``preferred_robot`` -- ``resolve_auction_winner`` drops the preference
          once ``auction_rounds`` reaches ``inject_preferred_robot_max_rounds``,
          and that count is supposed to mean "the robot you asked for did not
          bid this many times", not "somebody else jumped the queue".

        * ``failed_auctions`` AND ``auction_backoff_until`` ARE LEFT ALONE, and
          this is the asymmetry against ``assign_to_robot`` /
          ``recover_tasks_for_robot`` / ``interrupt_task``, all three of which
          call ``clear_auction_backoff``. Those three carry new evidence about
          the FLEET: a robot took the task, a robot died, an operator
          intervened. A preemption carries none -- it is the orchestrator's own
          scheduling choice about its own auction slot. Feeding D-20's backoff
          with it would punish a task for being interrupted, and clearing the
          backoff would reward it; neither is true, so it is left exactly as it
          was found.

        The TaskEvent comes free: AUCTIONING -> (PENDING|INTERRUPTED) is a real
        change, so ``set_status`` fires the status listener exactly once. Do not
        add a second event at the call site.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        # Guarded on AUCTIONING rather than aborting whatever it finds: between
        # the tick that opened the auction and this one the task may have been
        # assigned, completed or cancelled, and "restoring" a COMPLETED task to
        # PENDING would resurrect finished work.
        if task.status != TaskStatus.AUCTIONING:
            return False
        task.auction_rounds = max(0, task.auction_rounds - 1)
        self.set_status(task_id, task.status_before_auction, reason)
        return True

    def set_progress(self, task_id: str, progress: float) -> None:
        """Mirror RobotState.task_progress (0.0-1.0) onto the queue entry."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.progress = min(max(float(progress), 0.0), 1.0)

    def get_task_for_robot(self, robot_id: str) -> str | None:
        """Return task_id assigned to robot, or None."""
        active_statuses = (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
        for t in self._tasks.values():
            if t.assigned_robot == robot_id and t.status in active_statuses:
                return t.task_id
        return None

    def recover_tasks_for_robot(self, robot_id: str,
                                reason: str = "heartbeat_timeout") -> list[str]:
        """Reset every NON-TERMINAL task held by *robot_id* back to PENDING.

        Returns re-queued task_ids.

        D3(a): the status set is ``RECOVERABLE_STATUSES`` and is WIDER than the
        ``(ASSIGNED, IN_PROGRESS)`` this used to test -- see that constant for
        why, and for why ``get_task_for_robot``'s narrower tuple is deliberately
        no longer the same literal.

        RECOVERING AN AUCTIONING TASK DOES NOT CANCEL THE IN-FLIGHT
        ``TaskAuction``, and it does not need to. ``_resolve_auction`` copes
        either way: an assignment is legal from PENDING, and if the auction
        resolves to a requeue instead then setting PENDING on a task already in
        PENDING is a no-op change ``set_status`` swallows at its
        ``previous == status`` guard.
        """
        recovered = []
        for t in list(self._tasks.values()):
            if t.assigned_robot == robot_id and t.status in RECOVERABLE_STATUSES:
                # D-20: a task taken off a dead robot is fresh work, not a
                # task the fleet declined. It must not inherit a backoff.
                self.clear_auction_backoff(t.task_id)
                # Status FIRST, then clear the robot: the listener reads
                # assigned_robot to attribute the event, and clearing it first
                # would drop the one piece of information a "task re-queued"
                # entry needs -- which robot lost it.
                self.set_status(t.task_id, TaskStatus.PENDING, reason)
                t.assigned_robot = ""
                recovered.append(t.task_id)
        return recovered

    def mark_complete(self, task_id: str, reason: str = "") -> None:
        self.set_status(task_id, TaskStatus.COMPLETED, reason)

    def mark_failed(self, task_id: str, reason: str = "") -> None:
        """Terminate a task as FAILED.

        Until a TaskResult message existed this status was UNREACHABLE in
        production: the agent fired FSMEvent.TASK_COMPLETE on skill failure as
        well as on success, so ``_on_robot_state`` saw an idle robot with no
        task and called mark_complete(). A failed excavate was recorded as a
        COMPLETED task in the orchestrator's own queue.

        D2: it also COUNTS the attempt, and it is the only thing that does.
        ``retry_failed_tasks`` uses that count both as its bound and as the test
        that this FAILED row came from a skill rather than from
        ``inject_task_logic._reject``, which writes FAILED through
        ``set_status`` and must never be retried.
        """
        task = self._tasks.get(task_id)
        # Counted only on a REAL transition, mirroring set_status's own rule at
        # its ``previous == status`` guard. A duplicate TaskResult for the same
        # task must not burn a retry -- and ``_on_task_result`` has no re-entry
        # guard of its own (defect D4), so this has to hold independently of
        # whether that one lands.
        if task is not None and task.status != TaskStatus.FAILED:
            task.failed_attempts += 1
        self.set_status(task_id, TaskStatus.FAILED, reason)

    @staticmethod
    def attempts_exhausted(task: TaskEntry, max_attempts: int) -> bool:
        """Has *task* spent every attempt it will ever get? THE predicate, once.

        It was written out twice before D2's soft-quorum edge needed it a third
        time: as ``retry_failed_tasks``' skip guard, and as
        ``orchestrator_node._report_attempts_exhausted``'s, the latter under a
        comment saying it is deliberately "the SAME predicate ... written the
        same way round". That comment was an instruction to a human; this makes
        it structural. Three copies of a bound is how a dependency starts being
        treated as finished by a task the retry sweep is still going to re-run.

        ``max_attempts <= 0`` MEANS RETRY FOREVER, so nothing is ever exhausted
        -- the supported configuration ``retry_failed_tasks`` documents,
        preserved here rather than re-derived. It is also this method's default
        behaviour for a caller that has no bound to give: see
        ``dependencies_met``.

        It says nothing about whether the task FAILED. ``retry_failed_tasks``
        has already filtered on that, and ``_dependency_resolved`` does so
        immediately before calling this.
        """
        return 0 < int(max_attempts) <= task.failed_attempts

    def retry_failed_tasks(self, max_attempts: int,
                           reason: str = "") -> list[str]:
        """Return every FAILED task that still has an attempt left to PENDING.

        THE SIBLING OF ``wake_deferred_auctions``, and deliberately a separate
        method rather than a clause in it: that one walks REQUEUEABLE_STATUSES
        and a FAILED task is by construction not in them.

        FAILED IS NOT ADDED TO REQUEUEABLE_STATUSES, and that is the decision. A
        FAILED task must not be silently auctionable the way an INTERRUPTED one
        is: it rests visibly in FAILED and becomes work again only when this
        method says so, which is exactly the relationship ``abandon_auction``
        has with ``wake_deferred_auctions``. ``get_next_ready`` therefore still
        never returns a FAILED task, before or after a failure.

        WHY RETRY IS A POLICY AND NOT A WORKAROUND. Every failure_reason a skill
        can actually produce is transient or environmental -- 'Path blocked, no
        alternate route', 'Drill actuator unavailable', 'Loading timed out'.
        None is a statement that the task is impossible, and the agent itself
        already treats them as recoverable: it fires FSMEvent.TASK_COMPLETE
        rather than FAULT on a failed skill. The layer below already retries and
        is already bounded -- ``PathFollower`` replans up to
        MAX_REPLAN_ATTEMPTS = 3 before the skill fails at all -- which is both
        why bounded retry is the layered design's own idiom and why the bound
        HERE should be small.

        ``failed_attempts <= 0`` IS THE GUARD THAT MATTERS. Only ``mark_failed``
        increments it, and ``inject_task_logic._reject`` writes FAILED through
        ``set_status`` instead -- so a rejected operator injection ("unknown
        robot", "robot lacks capabilities") has a count of 0 and is never
        resurrected. The test is structural rather than a match on
        ``status_reason``, because a string comparison would silently start
        auctioning phantom rows to the fleet the day somebody spells that
        reason differently.

        ``max_attempts <= 0`` DISABLES GIVING UP and retries forever. A
        supported configuration, not a mistake, and the same edge case
        ``task_feed.auction_failure_reason`` documents for ``max_rounds``.

        ``failed_attempts`` IS NOT RESET, by this or by anything else. It is the
        whole record of how many attempts have happened, exactly as
        ``failed_auctions`` survives ``wake_deferred_auctions`` for an
        already-abandoned task. That monotonicity is load-bearing: it is what
        lets the caller run this sweep UNCONDITIONALLY rather than gated on a
        fleet change, because a task can be retried at most
        ``max_attempts - 1`` times in its entire life whatever the fleet does.
        ``auction_rounds`` is not refunded either, unlike ``abort_auction``:
        that round really did resolve, into an assignment that ran.
        """
        retried = []
        for task in list(self._tasks.values()):
            if task.status != TaskStatus.FAILED:
                continue
            if task.failed_attempts <= 0:
                continue
            if self.attempts_exhausted(task, max_attempts):
                continue
            # D-20, same reasoning as recover_tasks_for_robot: a retried task is
            # fresh work, not a task the fleet declined.
            self.clear_auction_backoff(task.task_id)
            # Status FIRST, then clear the robot -- the listener reads
            # assigned_robot to attribute the event.
            self.set_status(task.task_id, TaskStatus.PENDING, reason)
            task.assigned_robot = ""
            # MUST be cleared, or the retried attempt can never terminate: the
            # completion-inference fallback in ``_on_robot_state`` skips a task
            # with this set, and D4's re-entry guard on ``_on_task_result`` will
            # reject its TaskResult. The task would sit ASSIGNED forever.
            task.terminal_reported = False
            retried.append(task.task_id)
        return retried

    def get_task(self, task_id: str) -> TaskEntry | None:
        return self._tasks.get(task_id)

    def get_completed_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)

    def get_pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def get_total_count(self) -> int:
        return len(self._tasks)

    @staticmethod
    def _dependency_resolved(dep: TaskEntry, max_attempts: int) -> bool:
        """Has *dep* STOPPED MOVING? Clause (a) of the soft-edge rule.

        RESOLVED means "nothing in this orchestrator will change this task's
        status by itself", NOT "this task succeeded". The full table, every
        member of ``TaskStatus``, because a status omitted from a table like
        this is how a soft edge quietly becomes a hard one again -- or, worse,
        how a survey still driving to its waypoint gets counted as finished:

          COMPLETED    RESOLVED, and the only status that also COUNTS toward a
                       quorum.
          FAILED, attempts exhausted (``attempts_exhausted``)
                       RESOLVED. This is D2's terminal state: nothing in
                       ``TaskQueue`` or ``orchestrator_node`` moves a task out
                       of it, and ``_report_attempts_exhausted`` has already
                       raised the CRITICAL alert saying exactly that.
          FAILED, attempts left
                       NOT resolved. THE CASE THAT MAKES THIS METHOD WORTH
                       HAVING: ``_retry_failed_tasks`` returns the task to
                       PENDING within one 0.5 s tick, so calling it resolved
                       would abandon a survey that is about to run again. It is
                       a REAL race, not a hypothetical one -- ``mark_failed``
                       runs from ``_on_task_result`` on a DDS callback thread of
                       the MultiThreadedExecutor, so a dependency can flip to
                       FAILED between ``_auction_tick``'s retry sweep and its
                       ``get_next_ready`` in the SAME tick.
          FAILED, ``failed_attempts == 0``
                       NOT resolved. That row is ``inject_task_logic._reject``
                       (written through ``set_status``, never counted): not a
                       task that ran and failed, a request that was refused. It
                       is also unretryable, so it would block a quorum forever;
                       it cannot arise as a DEPENDENCY today only because
                       injected tasks have no dependents, which is a fact about
                       the caller and not a guarantee from here.
          PENDING      NOT resolved -- work still owed. That includes a task
                       inside D-20's backoff and one ABANDONED with
                       ``auction_backoff_until == math.inf``: abandonment is
                       explicitly NOT terminal (``wake_deferred_auctions``
                       un-abandons it on any idle arrival), so calling it
                       resolved would fire a quorum against a survey one fleet
                       change away from running.
          AUCTIONING   NOT resolved -- a bid may land this tick.
          ASSIGNED     NOT resolved -- a robot holds it.
          IN_PROGRESS  NOT resolved -- a skill is running.
          INTERRUPTED  NOT resolved. A RESTING state (D-03), but it is in
                       ``REQUEUEABLE_STATUSES`` and the auction re-dispatches
                       it. So an operator cancel blocks the quorum, and that is
                       the right answer: the operator who cancelled it is the
                       one who can unblock it.

        ``failed_attempts`` IS AUTHORITATIVE AND ``status_reason`` IS NOT.
        The count is written by ``mark_failed`` -- this class, on the real
        transition only -- and is never reset. ``TASK_ATTEMPTS_EXHAUSTED`` is
        stamped by a 2 Hz sweep in the NODE, so between the third
        ``mark_failed`` and the next ``_report_attempts_exhausted`` there is a
        window of up to 500 ms in which the task IS exhausted and the string
        does not say so, and ``check_and_advance`` runs on a
        ReentrantCallbackGroup that can land inside it. ``status_reason`` is
        also free text that several paths overwrite, so a string test would be
        a test on the last writer.
        """
        if dep.status == TaskStatus.COMPLETED:
            return True
        if dep.status != TaskStatus.FAILED:
            return False
        return TaskQueue.attempts_exhausted(dep, max_attempts)

    def dependencies_met(self, task: TaskEntry,
                         max_attempts: int = 0) -> bool:
        """Are *task*'s dependencies satisfied? THE ONE EXPRESSION OF THAT RULE.

        TWO PRODUCTION CALLERS AND THAT IS THE POINT: ``_ready_tasks`` (2 Hz,
        the auction) and ``htn_planner.check_and_advance`` (1 Hz, the only
        thing that ever resolves the VIRTUAL select_site task -- ``_auction_tick``
        skips it by task_type and never announces it). Those two used to answer
        this question separately, ``htn_planner`` restating "every dependency
        must be COMPLETED" for itself, so D2's deadlock lived in the copy and a
        fix applied to ``_ready_tasks`` alone would have changed nothing an
        operator could see. The register has paid for that shape twice already
        (D-28's per-cell/per-step split, D-31's two distance totals), and
        ``_ready_tasks`` was itself factored out of ``get_next_ready`` for the
        same reason.

        HARD EDGE -- ``depends_on_quorum == 0``, the default, every task in this
        system but one -- IS BIT-FOR-BIT THE OLD RULE: every dependency
        COMPLETED. See ``TaskEntry.depends_on_quorum`` for why relaxing one
        would corrupt the ISRU ledger.

        SOFT EDGE -- ``depends_on_quorum == k > 0`` -- requires BOTH clauses,
        and the first is the one a reader skips:

        (a) EVERY dependency RESOLVED -- see ``_dependency_resolved`` for the
            per-status table. Without it select_site fires the instant the k-th
            survey lands and the other nine are abandoned in flight: a deadlock
            traded for silent evidence loss, which is a worse defect than D2.
        (b) at least *k* of them actually COMPLETED. NEVER ZERO -- see
            ``htn_planner.SELECT_SITE_SURVEY_QUORUM`` for why k=0 is D-29.

        *max_attempts* is the retry bound clause (a) tests exhaustion against:
        ``task_feed.TASK_MAX_ATTEMPTS`` at both production call sites. IT
        DEFAULTS TO 0, meaning "retries never exhaust" exactly as it means
        "never give up" in ``retry_failed_tasks`` -- so a FAILED dependency is
        never resolved and every caller that does not pass it, INCLUDING EVERY
        EXISTING TEST, gets today's behaviour unchanged.

        A quorum LARGER than ``len(depends_on)`` is CLAMPED to it rather than
        honoured. An unsatisfiable readiness predicate is the permanent silent
        deadlock this whole change exists to remove; the clamped worst case is
        "every dependency COMPLETED", which is the default this class has always
        had. The cost is that a mis-set quorum is masked rather than loud, and
        that is accepted rather than hidden.

        A quorum over an EMPTY ``depends_on`` is vacuous, not deadlocked: the
        first guard returns True, exactly as before.

        AN UNKNOWN dependency id is NOT satisfied, in either branch, exactly as
        before -- ``add_task`` never validates ``depends_on`` (a cycle is
        representable; see ``get_transitive_dependents``), so a typo must block
        loudly rather than let a dependency evaporate into a satisfied quorum.

        CONCURRENT-SAFE BY CONSTRUCTION, which matters because ``_htn_advance``
        runs on a ReentrantCallbackGroup under a 4-thread MultiThreadedExecutor
        while ``_auction_tick`` mutates the queue. It iterates
        ``task.depends_on`` -- a list nothing mutates after ``add_task`` -- and
        touches ``self._tasks`` only through ``.get()``, so it cannot raise
        "dictionary changed size during iteration".

        HOT PATH: one pass, short-circuiting on the first unresolved dependency,
        and no allocation in the quorum branch.
        """
        deps = task.depends_on
        if not deps:
            return True
        quorum = int(task.depends_on_quorum)
        if quorum <= 0:
            # VERBATIM the expression this method replaced in ``_ready_tasks``.
            # Every task that does not set a quorum takes this branch and cannot
            # behave differently from the way it did before the field existed.
            return all(
                self._tasks.get(dep_id) is not None
                and self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in deps
            )
        completed = 0
        for dep_id in deps:
            dep = self._tasks.get(dep_id)
            if dep is None or not self._dependency_resolved(dep, max_attempts):
                return False
            if dep.status == TaskStatus.COMPLETED:
                completed += 1
        return completed >= min(quorum, len(deps))

    def completed_dependencies(self, task: TaskEntry) -> int:
        """How many of *task*'s dependencies are COMPLETED. FOR THE REPORT ONLY.

        The DECISION is ``dependencies_met``; this is what tells an operator how
        much evidence that decision was taken on. It lives here rather than in
        the planner so "COMPLETED" is spelled once and cannot drift from the
        predicate beside it. One production caller:
        ``htn_planner.check_and_advance``.
        """
        return sum(
            1 for dep_id in task.depends_on
            if (self._tasks.get(dep_id) is not None
                and self._tasks[dep_id].status == TaskStatus.COMPLETED)
        )

    def _ready_tasks(self, moment: float, servable=None,
                     through_backoff=None,
                     max_attempts: int = 0) -> list[TaskEntry]:
        """The re-auctionable, dependency-satisfied tasks at *moment*.

        Factored out of ``get_next_ready`` so ``get_preemption_candidate`` asks
        the SAME question with one clause relaxed, rather than restating the
        eligibility rules and drifting from them. The register has this failure
        twice already (D-28's per-cell/per-step split, D-31's two distance
        totals); one expression of "which tasks are eligible" is the defence.

        *servable* is an optional ``TaskEntry -> bool``. None means "ask
        nothing", which is what every direct TaskQueue caller and every test
        wants; the orchestrator passes a predicate that answers "is some IDLE
        robot capable of this?".

        *through_backoff* is an optional ``TaskEntry -> bool`` naming tasks
        whose D-20 backoff is to be IGNORED for this query. None means the
        backoff binds on everything, which is ``get_next_ready``'s contract and
        must stay so.

        *max_attempts* is the retry bound handed to ``dependencies_met``, and it
        matters only for a task carrying a SOFT dependency quorum. 0 -- the
        default, and what every direct TaskQueue caller and every test passes --
        means "retries never exhaust", which is exactly this method's
        pre-quorum behaviour.
        """
        ready = []
        for t in self._tasks.values():
            if t.status not in REQUEUEABLE_STATUSES:
                continue
            if through_backoff is None or not through_backoff(t):
                # isinf first: ABANDONED is encoded as math.inf, and
                # `inf > inf` is False, so a caller passing an infinite clock
                # would release exactly the tasks that must never be released
                # by time.
                if math.isinf(t.auction_backoff_until):
                    continue
                if t.auction_backoff_until > moment:
                    continue
            # Dependency satisfaction, D2. ONE expression of the rule, shared
            # with ``htn_planner.check_and_advance``, which used to restate it
            # -- see ``dependencies_met``.
            #
            # Guarded on ``t.depends_on`` before the call, and that is a hot
            # path decision rather than a style one: this loop runs at 2 Hz over
            # the whole queue, and the ten survey waypoints have no dependencies
            # at all, so they now skip a call and the generator object they used
            # to allocate. Nothing scans more than it did.
            if t.depends_on and not self.dependencies_met(t, max_attempts):
                continue
            if servable is not None and not servable(t):
                continue
            ready.append(t)
        return ready

    @staticmethod
    def _rank(task: TaskEntry) -> tuple[float, int]:
        """Sort key for "what runs next": priority, then emergency."""
        return (task.priority, 1 if task.emergency else 0)

    def get_next_ready(self, now: float | None = None, servable=None,
                       max_attempts: int = 0) -> TaskEntry | None:
        """Highest-priority re-auctionable task whose dependencies are satisfied.

        Unlike get_next_pending(), this method checks the candidate's
        ``depends_on`` list before considering it eligible: ORDINARILY every one
        of those task_ids must have status COMPLETED. Tasks with no dependencies
        are always eligible. A task carrying a SOFT dependency quorum
        (``TaskEntry.depends_on_quorum``, which only select_site does) instead
        needs every dependency RESOLVED and at least its quorum COMPLETED --
        ``dependencies_met`` is the whole rule and *max_attempts* is the retry
        bound it tests exhaustion against (0 = "retries never exhaust").

        Considers both PENDING and INTERRUPTED (REQUEUEABLE_STATUSES): an
        interrupted task is work the fleet still owes, and before D-03 the only
        thing that kept it moving was every caller immediately re-PENDing it.

        D-20: a task inside its auction backoff window is SKIPPED, and this is
        where the starvation is actually fixed. One auction runs at a time, so
        while an unbiddable task held the slot it re-announced every ~5.5 s and
        no other PENDING task was ever offered. Skipping it here lets the rest
        of the queue proceed; the backed-off task rejoins when its deadline
        passes or when the fleet changes.

        TIES ARE BROKEN TOWARD AN EMERGENCY. At equal priority an
        operator-injected emergency task is returned ahead of an ordinary one:
        the sort key is ``(priority, 1 if emergency else 0)``. Priority still
        decides first and nothing here lets an emergency outrank a
        higher-priority task -- an emergency at 10.0 does not beat a 12.0. This
        only settles the case the plain ``max`` settled by dict insertion
        order, which is to say arbitrarily.

        *servable* is an optional ``TaskEntry -> bool`` predicate. A task it
        rejects is SKIPPED and the search continues down the ready set, which
        is the difference between this and the caller's own early returns: the
        orchestrator uses it to pass over a task no IDLE robot has the
        capability to bid on, so that round is never opened, never charged to
        D-20's backoff, and never buries the task that could not be served.
        Skipping rather than returning is load-bearing -- a top-priority
        emergency excavate with the only excavator busy must not stop ten
        surveys being auctioned to three idle scouts.

        *now* is ``time.monotonic()`` and is injected so the ROS-free lane can
        drive the clock. It is only ever compared against
        ``TaskEntry.auction_backoff_until``, which is written from the same
        clock.
        """
        moment = time.monotonic() if now is None else float(now)
        ready = self._ready_tasks(moment, servable=servable,
                                  max_attempts=max_attempts)
        if not ready:
            return None
        return max(ready, key=self._rank)

    def get_preemption_candidate(self, now: float | None = None, servable=None,
                                 max_attempts: int = 0) -> TaskEntry | None:
        """``get_next_ready``, except an UNSPENT EMERGENCY is not hidden by D-20.

        THE ONE CLAUSE THAT DIFFERS, and why it has to. An operator emergency
        that has already lost a round is inside its D-20 auction backoff, and a
        backed-off task is invisible to ``get_next_ready``. That is correct for
        the flood D-20 was written against and catastrophic here: the task the
        operator declared an emergency is precisely the task most likely to have
        lost a round -- it was injected into a busy fleet -- so the decision that
        is supposed to act on it could never see it, and a priority-5.0 survey
        would take the auction slot and the one capable robot while the
        emergency slept.

        THIS CANNOT FLOOD, and the bound is not a tuning constant. Only an
        emergency whose ``preemption_spent`` is still False is admitted through
        the backoff, and ``spend_preemption`` latches that flag the moment the
        abort happens. One injection therefore reaches through the backoff at
        most ONCE in its whole life. An ABANDONED emergency
        (``auction_backoff_until`` == inf) is admitted on the same one-shot
        terms: the fleet having changed enough for a capable robot to be idle is
        new information, and ``wake_deferred_auctions`` is not reachable from a
        preemption-stranded bidder in every case.

        *servable* is honoured exactly as in ``get_next_ready``: a task no idle
        robot can bid on is not a preemption candidate either, because aborting
        a live auction to announce something nobody can bid on is the worst of
        both outcomes. *max_attempts* likewise, so the two eligibility queries
        stay ONE question with one clause relaxed rather than two that can
        drift; every operator injection has an empty ``depends_on`` and takes
        ``dependencies_met``'s first guard, so nothing on this path changes
        today.
        """
        moment = time.monotonic() if now is None else float(now)
        ready = self._ready_tasks(
            moment, servable=servable, max_attempts=max_attempts,
            through_backoff=lambda t: t.emergency and not t.preemption_spent)
        if not ready:
            return None
        return max(ready, key=self._rank)

    def spend_preemption(self, task_id: str) -> bool:
        """Latch ``preemption_spent``. Returns False if already spent/unknown.

        The only caller is ``orchestrator_node._preempt_for_emergency``, and it
        calls this BEFORE it aborts anything, so a partially-completed
        preemption cannot leave the shot unspent and repeat.
        """
        task = self._tasks.get(task_id)
        if task is None or task.preemption_spent:
            return False
        task.preemption_spent = True
        return True

    def release_auction_backoff(self, task_id: str) -> None:
        """Make a task auctionable NOW, keeping its failure count.

        Deliberately NOT ``clear_auction_backoff``, which zeroes
        ``failed_auctions`` as well. The preemption path needs the emergency to
        be visible to ``get_next_ready`` in the same tick that aborted the
        auction for it -- otherwise the slot is taken from a live auction and
        given to nobody, which is strictly worse than not preempting. What it
        must NOT do is re-arm D-20's escalation: an emergency that keeps failing
        to attract a bid still has to reach ``auction_max_failed_rounds`` and be
        abandoned, or the one bound on how often it re-announces is gone.
        Keeping the count is what preserves that.
        """
        task = self._tasks.get(task_id)
        if task is not None:
            task.auction_backoff_until = 0.0

    # ------------------------------------------------------------------ #
    #  D-20: the auction backoff                                          #
    # ------------------------------------------------------------------ #

    def defer_auction(self, task_id: str, delay_sec: float,
                      now: float | None = None) -> int:
        """Record one failed auction and hold the task off for *delay_sec*.

        Returns the new consecutive-failure count. Does NOT touch the status:
        the caller sets that once, with the reason the failure count implies,
        so the event log gets exactly one entry per round rather than two.

        A non-positive *delay_sec* still counts the failure. That is what makes
        ``auction_backoff_base_sec: 0.0`` mean "count but never delay" rather
        than "disable the whole mechanism including the give-up bound".
        """
        task = self._tasks.get(task_id)
        if task is None:
            return 0
        moment = time.monotonic() if now is None else float(now)
        task.failed_auctions += 1
        delay = float(delay_sec)
        if delay > 0.0:
            task.auction_backoff_until = moment + delay
        return task.failed_auctions

    def abandon_auction(self, task_id: str) -> None:
        """Stop re-announcing a task until the fleet changes.

        ``math.inf`` rather than a very large number: there is no timer that
        can release this, by design, and a "big enough" constant is a deadline
        that eventually passes on a long mission and re-opens the flood.
        ``wake_deferred_auctions`` is the only way out, and it is driven by a
        robot going IDLE — see ``FleetMonitor.idle_arrivals``.

        The status is deliberately left where it is (PENDING for a task that
        was never started). A new TaskStatus enum value would have to be
        rendered by the dashboard, documented in TaskStatus.msg and handled by
        every switch on that field; the reason string is the mechanism D-03
        built for exactly this, and TaskQueue.jsx already draws it.
        """
        task = self._tasks.get(task_id)
        if task is not None:
            task.auction_backoff_until = math.inf

    def clear_auction_backoff(self, task_id: str) -> None:
        """Make a task immediately auctionable again and forget its failures."""
        task = self._tasks.get(task_id)
        if task is not None:
            task.failed_auctions = 0
            task.auction_backoff_until = 0.0

    def get_deferred_tasks(self, now: float | None = None) -> list[TaskEntry]:
        """Re-auctionable tasks currently held off by the backoff."""
        moment = time.monotonic() if now is None else float(now)
        return [t for t in self._tasks.values()
                if t.status in REQUEUEABLE_STATUSES
                and t.auction_backoff_until > moment]

    def wake_deferred_auctions(self, reason: str = "") -> list[str]:
        """Release every backoff and abandonment. Returns the task_ids woken.

        Called when the fleet CHANGES -- a robot finishes work, recovers from
        an error, or joins -- because that is the only new information that can
        make a task nobody could bid on biddable. Without it an abandoned task
        would be abandoned for the rest of the mission and the mission would
        deadlock, which is a worse failure than the flood D-20 is about.

        THE FAILURE COUNT IS KEPT FOR A TASK THAT WAS ALREADY ABANDONED, and
        that asymmetry is the whole reason this is not a plain reset. A robot
        arrives in IDLE after every completed task, so in a busy fleet this
        runs often; resetting an abandoned task to zero would buy it another
        full run of ``auction_max_failed_rounds`` announcements every time
        anything anywhere finished, and a task no robot in the fleet can EVER
        service (wrong capability, permanently out of range) would be back to
        announcing on a loop. Keeping the count gives it exactly ONE auction
        per fleet change: enough to discover that the fleet has genuinely
        changed, not enough to flood. A task that is merely backed off has not
        exhausted anything, so it does start clean.

        ``assign_to_robot`` clears the count outright, so the escalation only
        ever affects tasks that keep failing to attract a bid.

        ``status_reason`` is written directly rather than through
        ``set_status``: every woken task is already in the status it should be
        in (PENDING, or INTERRUPTED for one an operator cancelled), so
        ``set_status`` would update the reason and fire no listener anyway. The
        caller logs the wake ONCE with the count instead of emitting one
        TaskEvent per task -- a fleet change that wakes eleven survey waypoints
        would otherwise evict a third of the 32-entry ring the dashboard
        replays, which is the same cost D-06's latched haul alert avoids.
        """
        woken = []
        for task in self._tasks.values():
            if task.status not in REQUEUEABLE_STATUSES:
                continue
            if task.auction_backoff_until <= 0.0 and task.failed_auctions == 0:
                continue
            was_abandoned = math.isinf(task.auction_backoff_until)
            task.auction_backoff_until = 0.0
            if not was_abandoned:
                task.failed_auctions = 0
            if reason:
                task.status_reason = reason
            woken.append(task.task_id)
        return woken

    def get_dependent_tasks(self, task_id: str) -> list[TaskEntry]:
        """Return all tasks whose depends_on list contains the given task_id."""
        return [t for t in self._tasks.values() if task_id in t.depends_on]

    def get_transitive_dependents(self, task_id: str) -> list[TaskEntry]:
        """Every task DOWNSTREAM of *task_id*, directly or transitively.

        BFS over ``get_dependent_tasks``, because an ORDINARY dependency is
        satisfied only by COMPLETED: a dead survey blocks select_site, which
        blocks every excavate, which blocks every haul. The direct dependents
        alone would report one blocked task where the real number is the whole
        downstream chain, and understating a blast radius in an operator alert
        is the failure mode that alert exists to prevent.

        IT IS NOT "CAN NEVER RUN", AND THAT SENTENCE USED TO STAND HERE. As of
        D2's soft-quorum edge a dependent carrying ``depends_on_quorum > 0``
        becomes ready once every dependency is RESOLVED -- which a
        permanently-FAILED one is -- and at least its quorum COMPLETED. So this
        set is the blast radius of the edge, and whether each member is
        genuinely dead is ``dependencies_met``'s answer, not this method's. The
        one caller, ``_report_attempts_exhausted``, says so in its alert.

        THE VISITED SET IS REQUIRED RATHER THAN DEFENSIVE. ``add_task`` does not
        validate ``depends_on`` at all, so a cycle is representable and a plain
        recursion would not terminate on one.

        *task_id* itself is never in the result, even if it is inside such a
        cycle: it is the cause, not a casualty.
        """
        seen: set[str] = set()
        frontier = [task_id]
        while frontier:
            current = frontier.pop()
            for dependent in self.get_dependent_tasks(current):
                if dependent.task_id in seen or dependent.task_id == task_id:
                    continue
                seen.add(dependent.task_id)
                frontier.append(dependent.task_id)
        return [self._tasks[tid] for tid in seen]

    def interrupt_task(self, task_id: str, metadata: dict,
                       reason: str = "") -> None:
        """Set task status to INTERRUPTED, store metadata, and clear assignment.

        The task now RESTS in INTERRUPTED and is re-auctioned from there (see
        REQUEUEABLE_STATUSES). Callers must not follow this with
        ``set_status(..., PENDING)``; doing so is what erased the distinction
        between a cancelled task and a completed one.

        Args:
            task_id: Identifier of the task to interrupt.
            metadata: Progress information (e.g. partial work done) to preserve.
                Assigned WHOLESALE -- which is why ``site_id`` is a dataclass
                field and not a key in here.
            reason: Recorded on the entry and published in TaskStatus.
        """
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.progress_metadata = metadata
            # D-20, same reasoning as recover_tasks_for_robot: an operator
            # cancel or a robot fault is a fleet change, not evidence that
            # nobody wants this task.
            self.clear_auction_backoff(task_id)
            derived = reason or str(metadata.get('reason', '') or '')
            # Status first, robot second — see recover_tasks_for_robot.
            self.set_status(task_id, TaskStatus.INTERRUPTED, derived)
            task.assigned_robot = ""

    def get_all_tasks(self) -> list[TaskEntry]:
        return list(self._tasks.values())

    def make_unique_task_id(self, prefix: str) -> str:
        """Generate a unique task_id with the given prefix and a monotonic suffix.

        Returns the smallest ``f"{prefix}_{n:04d}"`` not currently present in
        the task store. Used by manual / operator task injection paths to avoid
        ID collisions with HTN-generated identifiers.
        """
        n = 0
        while True:
            candidate = f"{prefix}_{n:04d}"
            if candidate not in self._tasks:
                return candidate
            n += 1
