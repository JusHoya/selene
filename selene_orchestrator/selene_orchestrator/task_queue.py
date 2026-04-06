"""Task lifecycle management for the SELENE orchestrator."""

from enum import Enum
from dataclasses import dataclass, field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    AUCTIONING = "AUCTIONING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


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


class TaskQueue:
    def __init__(self):
        self._tasks: dict[str, TaskEntry] = {}

    def add_task(self, task_id: str, task_type: str, target_x: float, target_y: float,
                 priority: float = 1.0, required_capabilities: list[str] | None = None,
                 estimated_energy_cost: float = 0.0, estimated_duration: float = 0.0,
                 parent_task_id: str = "", depends_on: list[str] | None = None) -> None:
        self._tasks[task_id] = TaskEntry(
            task_id=task_id, task_type=task_type,
            target_x=target_x, target_y=target_y,
            priority=priority,
            required_capabilities=required_capabilities or [],
            estimated_energy_cost=estimated_energy_cost,
            estimated_duration=estimated_duration,
            parent_task_id=parent_task_id,
            depends_on=depends_on or [],
        )

    def get_next_pending(self) -> TaskEntry | None:
        """Return highest-priority PENDING task, or None."""
        pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if not pending:
            return None
        return max(pending, key=lambda t: t.priority)

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = status

    def assign_to_robot(self, task_id: str, robot_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.ASSIGNED
            self._tasks[task_id].assigned_robot = robot_id

    def get_task_for_robot(self, robot_id: str) -> str | None:
        """Return task_id assigned to robot, or None."""
        for t in self._tasks.values():
            if t.assigned_robot == robot_id and t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                return t.task_id
        return None

    def recover_tasks_for_robot(self, robot_id: str) -> list[str]:
        """Reset ASSIGNED/IN_PROGRESS tasks for robot back to PENDING. Returns re-queued task_ids."""
        recovered = []
        for t in self._tasks.values():
            if t.assigned_robot == robot_id and t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                t.status = TaskStatus.PENDING
                t.assigned_robot = ""
                recovered.append(t.task_id)
        return recovered

    def mark_complete(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.COMPLETED

    def get_task(self, task_id: str) -> TaskEntry | None:
        return self._tasks.get(task_id)

    def get_completed_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)

    def get_pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def get_total_count(self) -> int:
        return len(self._tasks)

    def get_next_ready(self) -> TaskEntry | None:
        """Return highest-priority PENDING task whose dependencies are all COMPLETED.

        Unlike get_next_pending(), this method checks that every task_id in
        the candidate's depends_on list has status COMPLETED before
        considering it eligible. Tasks with no dependencies are always eligible.
        """
        ready = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            # All dependencies must be COMPLETED
            deps_met = all(
                self._tasks.get(dep_id) is not None
                and self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in t.depends_on
            )
            if deps_met:
                ready.append(t)
        if not ready:
            return None
        return max(ready, key=lambda t: t.priority)

    def get_dependent_tasks(self, task_id: str) -> list[TaskEntry]:
        """Return all tasks whose depends_on list contains the given task_id."""
        return [t for t in self._tasks.values() if task_id in t.depends_on]

    def interrupt_task(self, task_id: str, metadata: dict) -> None:
        """Set task status to INTERRUPTED, store metadata, and clear assignment.

        Args:
            task_id: Identifier of the task to interrupt.
            metadata: Progress information (e.g. partial work done) to preserve.
        """
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.status = TaskStatus.INTERRUPTED
            task.progress_metadata = metadata
            task.assigned_robot = ""

    def get_all_tasks(self) -> list[TaskEntry]:
        return list(self._tasks.values())
