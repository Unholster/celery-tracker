from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import tracker.backend
from tracker.backend import TrackerBackend
from tracker.models import ExecutionState, TrackerState

# ---------------------------------------------------------------------------
# In-memory backend (no Redis required)
# ---------------------------------------------------------------------------


class InMemoryTrackerBackend(TrackerBackend):
    """A pure-Python tracker backend for tests — no external services."""

    def __init__(self) -> None:
        self._trackers: dict[str, TrackerState] = {}
        self._members: dict[str, set[str]] = {}
        self._steps: dict[str, list[ExecutionState]] = {}

    # -- tracker CRUD --------------------------------------------------------

    def save(self, state: TrackerState) -> None:
        self._trackers[state.id] = state

    def load(self, tracker_id: str) -> TrackerState:
        return self._trackers[tracker_id]

    def list_all(self) -> list[TrackerState]:
        return list(self._trackers.values())

    # -- members -------------------------------------------------------------

    def add_member(self, tracker_id: str, task_id: str) -> None:
        self._members.setdefault(tracker_id, set()).add(task_id)

    def get_members(self, tracker_id: str) -> list[str]:
        return sorted(self._members.get(tracker_id, set()))

    # -- steps ---------------------------------------------------------------

    def add_step(self, tracker_id: str, step: ExecutionState) -> int:
        self._steps.setdefault(tracker_id, []).append(step)
        return len(self._steps[tracker_id]) - 1

    def update_step(
        self, tracker_id: str, step_index: int, step: ExecutionState
    ) -> None:
        self._steps[tracker_id][step_index] = step

    def get_steps(self, tracker_id: str) -> list[ExecutionState]:
        return list(self._steps.get(tracker_id, []))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TASK_ID = "test-task-id"
TRACKER_ID = "test-tracker-id"


@pytest.fixture()
def backend():
    """Provide a fresh InMemoryTrackerBackend configured as the default."""
    b = InMemoryTrackerBackend()
    tracker.backend.configure(b)
    yield b
    tracker.backend._default_backend = None


@pytest.fixture()
def fake_task_context(backend: InMemoryTrackerBackend):
    """Simulate running inside a Celery task whose signature was stamped.

    Sets up:
      - A TrackerState persisted in the in-memory backend.
      - ``celery.current_task`` patched with ``request.stamps``
        set to ``{"tracker_id": TRACKER_ID}`` (mimics the stamp
        that Celery nests under ``request.stamps``).

    Yields a dict with ``task_id``, ``tracker_id``, and ``backend``
    for assertions.
    """
    backend.save(TrackerState(id=TRACKER_ID))

    mock_task = MagicMock()
    mock_task.request.id = TASK_ID
    mock_task.request.stamps = {"tracker_id": TRACKER_ID}

    with patch("tracker.step.current_task", mock_task):
        yield {"task_id": TASK_ID, "tracker_id": TRACKER_ID, "backend": backend}
