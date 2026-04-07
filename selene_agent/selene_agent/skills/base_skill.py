"""Base skill class for SELENE agent task execution."""

from abc import ABC, abstractmethod
from enum import Enum


class SkillState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ABORTED = "aborted"
    FAILED = "failed"


class BaseSkill(ABC):
    """Abstract base class for all agent skills.

    Skills have a lifecycle: start -> update (repeated) -> complete/abort.
    Each skill receives a HAL interface and Navigator for hardware access.
    """

    def __init__(self, name: str):
        self._name = name
        self._state = SkillState.IDLE
        self._progress = 0.0
        self._error_message = ""

    @abstractmethod
    def start(self, hal, navigator, **params) -> None:
        """Initialize the skill. Set state to RUNNING."""
        ...

    @abstractmethod
    def update(self, dt: float) -> None:
        """Called once per agent tick (~10 Hz). Drives skill logic."""
        ...

    def is_complete(self) -> bool:
        return self._state == SkillState.COMPLETE

    def is_running(self) -> bool:
        return self._state == SkillState.RUNNING

    def has_failed(self) -> bool:
        return self._state in (SkillState.ABORTED, SkillState.FAILED)

    def abort(self) -> None:
        """Graceful abort."""
        self._state = SkillState.ABORTED

    def get_progress(self) -> float:
        return self._progress

    def get_name(self) -> str:
        return self._name

    def get_state(self) -> SkillState:
        return self._state

    def get_error(self) -> str:
        return self._error_message
