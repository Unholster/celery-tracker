from __future__ import annotations

import logging
from typing import Iterable

from celery.result import AsyncResult
from pydantic import BaseModel

from tracker.backend import TrackerBackend, get_backend
from tracker.models import CeleryTaskState, ExecutionState, TrackerState

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED", "REJECTED", "IGNORED"}


# Service
class TrackerService:
    def __init__(self, backend: TrackerBackend | None = None) -> None:
        self._backend = backend or get_backend()

    def get_tracker(self, tracker_id: str) -> TrackerState:
        state = self._backend.load(tracker_id)
        member_ids = self._backend.get_members(tracker_id)
        steps = self._backend.get_steps(tracker_id)

        if not member_ids:
            return TrackerState(**{**state.model_dump(), "steps": steps})

        results = [AsyncResult(tid) for tid in member_ids]
        tasks = {r.id: ExecutionState(state=r.state, info=r.info) for r in results}
        celery_states = [r.state for r in results]
        completed = sum(1 for s in celery_states if s in TERMINAL_STATES)

        return TrackerState(
            **{
                **state.model_dump(),
                "state": _reduce_states(celery_states),
                "tasks": tasks,
                "info": results[0].info if len(results) == 1 else None,
                "progress_target": float(len(results)),
                "progress_completed": float(completed),
                "steps": steps,
            }
        )

    def list_trackers(self) -> list[TrackerState]:
        return self._backend.list_all()

    def revoke_tracked_tasks(self, tracker_id: str) -> "RevocationResult":
        state = self.get_tracker(tracker_id)
        task_ids = list(state.tasks.keys()) if state.tasks else [state.id]
        revoked_task_ids = [task_id for task_id in task_ids if _revoke_task(task_id)]
        return RevocationResult(revoked_task_ids=revoked_task_ids)


# Models
class RevocationResult(BaseModel):
    revoked_task_ids: list[str]


# Helpers
def _reduce_states(states: Iterable[str]) -> CeleryTaskState:
    """Reduce a list of child task states into a single parent state.

    Rules (from spec):
      - FAILURE  if at least one child is FAILURE
      - STARTED  if at least one child is STARTED or RETRY
      - PENDING  if all children are PENDING
      - SUCCESS  if all children are SUCCESS or REVOKED
    """
    state_set = set(states)

    if "FAILURE" in state_set:
        return "FAILURE"
    if state_set & {"STARTED", "RETRY"}:
        return "STARTED"
    if state_set <= {"SUCCESS", "REVOKED"}:
        return "SUCCESS"
    return "PENDING"


def _revoke_task(task_id: str) -> bool:
    """Revoke a single Celery task, returning True on success."""
    try:
        AsyncResult(task_id).revoke(terminate=True)
        logger.info("Revoked task %s", task_id)
        return True
    except Exception:
        logger.exception("Failed to revoke task %s", task_id)
        return False
