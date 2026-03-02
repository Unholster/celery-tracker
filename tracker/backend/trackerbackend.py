from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ExecutionState, TrackerState


class TrackerBackend(ABC):
    """Abstract backend for persisting tracker state."""

    # -- tracker state -------------------------------------------------------

    @abstractmethod
    def save(self, state: TrackerState) -> None:
        """Save a tracker state."""
        ...

    @abstractmethod
    def load(self, tracker_id: str) -> TrackerState:
        """Load raw tracker state from persistence by ID."""
        ...

    @abstractmethod
    def list_all(self) -> list[TrackerState]:
        """List all persisted tracker states."""
        ...

    # -- members -------------------------------------------------------------

    @abstractmethod
    def add_member(self, tracker_id: str, task_id: str) -> None:
        """Register a Celery task ID as a member of a tracker.

        Called by the ``before_task_publish`` signal for every stamped
        task message.  Implementations must be safe to call concurrently
        from multiple processes (client and workers).
        """
        ...

    @abstractmethod
    def get_members(self, tracker_id: str) -> list[str]:
        """Return all task IDs registered as members of a tracker."""
        ...

    # -- steps ---------------------------------------------------------------

    @abstractmethod
    def add_step(self, tracker_id: str, step: ExecutionState) -> int:
        """Append a step and return its index."""
        ...

    @abstractmethod
    def update_step(
        self, tracker_id: str, step_index: int, step: ExecutionState
    ) -> None:
        """Update a step by index."""
        ...

    @abstractmethod
    def get_steps(self, tracker_id: str) -> list[ExecutionState]:
        """Return all steps for a tracker."""
        ...


class TrackerNotFoundError(Exception):
    """Raised when a tracker is not found."""
