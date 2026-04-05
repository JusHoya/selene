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


class TaskQueue:
    def __init__(self):
        self._tasks: dict[str, TaskEntry] = {}

    def add_task(self, task_id: str, task_type: str, target_x: float, target_y: float,
                 priority: float = 1.0, required_capabilities: list[str] | None = None,
                 estimated_energy_cost: float = 0.0, estimated_duration: float = 0.0) -> None:
        self._tasks[task_id] = TaskEntry(
            task_id=task_id, task_type=task_type,
            target_x=target_x, target_y=target_y,
            priority=priority,
            required_capabilities=required_capabilities or [],
            estimated_energy_cost=estimated_energy_cost,
            estimated_duration=estimated_duration,
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

    def get_all_tasks(self) -> list[TaskEntry]:
        return list(self._tasks.values())
