from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from celery.result import AsyncResult
from pydantic import BaseModel

from tracker.backend import TrackerBackend, TrackerNotFoundError, get_backend
from tracker.models import CeleryTaskState, ExecutionState, TrackerState

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED", "REJECTED", "IGNORED"}


# Service
class TrackerService:
    def __init__(self, backend: TrackerBackend | None = None) -> None:
        self._backend = backend or get_backend()

    def get_tracker(self, identifier: str) -> TrackerState:
        try:
            state = self._backend.load(identifier)
            tracker_id = identifier
        except TrackerNotFoundError:
            mapped = self._backend.find_tracker_id_for_member(identifier)
            if mapped is None:
                raise TrackerNotFoundError(f"Tracker {identifier} not found")
            tracker_id = mapped
            state = self._backend.load(tracker_id)

        member_ids = self._backend.get_members(tracker_id)
        steps = self._backend.get_steps(tracker_id)

        if not member_ids:
            return TrackerState(**{**state.model_dump(), "steps": steps})

        results = [AsyncResult(tid) for tid in member_ids]
        tasks = {
            r.id: ExecutionState(
                state=r.state,
                info=r.info,
                title=_label_from_celery_task_name(getattr(r, "name", None)),
            )
            for r in results
        }
        celery_states = [r.state for r in results]
        completed = sum(1 for s in celery_states if s in TERMINAL_STATES)
        aggregate_state = _reduce_states(celery_states)
        started_on, completed_on = _derive_timestamps(
            aggregate_state, steps, results, state.created_on,
        )

        return TrackerState(
            **{
                **state.model_dump(),
                "state": aggregate_state,
                "tasks": tasks,
                "info": results[0].info if len(results) == 1 else None,
                "progress_target": float(len(results)),
                "progress_completed": float(completed),
                "started_on": started_on,
                "completed_on": completed_on,
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


def primary_member_celery_task_id(state: TrackerState) -> str | None:
    """Return the Celery task id when the tracker has exactly one member task."""
    if len(state.tasks) == 1:
        return next(iter(state.tasks))
    return None


# Helpers
def _label_from_celery_task_name(task_name: object | None) -> str | None:
    """Short display label from a Celery task name (e.g. ``…report_chained.fetch_data``)."""
    if not task_name or not isinstance(task_name, str):
        return None
    short = task_name.rsplit(".", 1)[-1]
    return short.replace("_", " ").title()


def _derive_timestamps(
    aggregate_state: CeleryTaskState,
    steps: list[ExecutionState],
    results: list[AsyncResult],
    created_on: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Derive tracker-level started/completed timestamps from steps and results."""
    started_on: datetime | None = None
    completed_on: datetime | None = None

    step_starts = [s.started_on for s in steps if s.started_on]
    if step_starts:
        started_on = min(step_starts)
    elif aggregate_state != "PENDING":
        started_on = created_on

    if aggregate_state in TERMINAL_STATES:
        step_ends = [s.completed_on for s in steps if s.completed_on]
        result_dates = [
            _parse_date_done(r.date_done)
            for r in results
            if getattr(r, "date_done", None)
        ]
        result_dates = [d for d in result_dates if d is not None]
        all_ends = step_ends + result_dates
        if all_ends:
            completed_on = max(all_ends)

    return started_on, completed_on


def _parse_date_done(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


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
