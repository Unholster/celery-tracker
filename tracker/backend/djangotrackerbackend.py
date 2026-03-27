from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from ..models import CeleryTaskState, ExecutionState, TrackerResult, TrackerState
from .trackerbackend import TrackerBackend, TrackerNotFoundError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State mapping between Celery task states and Django model status choices
# ---------------------------------------------------------------------------

_CELERY_STATE_TO_STATUS: dict[str, str] = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "STARTED": "running",
    "SUCCESS": "completed",
    "FAILURE": "failed",
    "REVOKED": "cancelled",
    "REJECTED": "failed",
    "RETRY": "retrying",
    "IGNORED": "cancelled",
}

_STATUS_TO_CELERY_STATE: dict[str, str] = {
    "pending": "PENDING",
    "running": "STARTED",
    "completed": "SUCCESS",
    "failed": "FAILURE",
    "cancelled": "REVOKED",
    "partial_success": "SUCCESS",
    "retrying": "RETRY",
}

_STEP_STATE_TO_STATUS: dict[str, str] = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "STARTED": "running",
    "SUCCESS": "completed",
    "FAILURE": "failed",
    "REVOKED": "failed",
    "REJECTED": "failed",
    "RETRY": "running",
    "IGNORED": "failed",
}

_STEP_STATUS_TO_STATE: dict[str, str] = {
    "pending": "PENDING",
    "running": "STARTED",
    "completed": "SUCCESS",
    "skipped": "SUCCESS",
    "failed": "FAILURE",
}


class DjangoTrackerBackend(TrackerBackend):
    """Django ORM-based tracker backend.

    Persists :class:`~tracker.models.TrackerState` as ``TrackedTask`` rows
    and :class:`~tracker.models.ExecutionState` steps as
    ``TrackedTaskStep`` rows using the Django models from the
    ``celery_task_tracking`` application.

    The model classes are injected through the constructor so that this
    library stays decoupled from any particular Django project layout::

        from myapp.models import TrackedTask, TrackedTaskStep

        backend = DjangoTrackerBackend(
            task_model=TrackedTask,
            step_model=TrackedTaskStep,
        )
    """

    def __init__(
        self,
        task_model: type[Any],
        step_model: type[Any],
    ) -> None:
        self._task_model = task_model
        self._step_model = step_model

    # -- public interface (TrackerBackend) ------------------------------------

    def save(self, state: TrackerState) -> None:
        """Persist a :class:`TrackerState` as a ``TrackedTask`` row."""
        defaults = self._tracker_state_to_row(state)
        self._task_model.objects.update_or_create(
            celery_task_id=state.id,
            defaults=defaults,
        )
        logger.debug("Saved tracker state %s", state.id)

    def load(self, tracker_id: str) -> TrackerState:
        """Load a :class:`TrackerState` from the database by tracker ID."""
        row = self._get_task_row(tracker_id)
        return self._row_to_tracker_state(row)

    def list_all(self) -> list[TrackerState]:
        """Return all persisted tracker states."""
        return [
            self._row_to_tracker_state(row) for row in self._task_model.objects.all()
        ]

    # -- members -------------------------------------------------------------

    def add_member(self, tracker_id: str, task_id: str) -> None:
        """Register a task ID as a member, stored in the row's metadata."""
        row = self._get_task_row(tracker_id)
        members = row.metadata.get("member_task_ids", [])
        if task_id not in members:
            members.append(task_id)
            row.metadata["member_task_ids"] = members
            row.save(update_fields=["metadata"])

    def get_members(self, tracker_id: str) -> list[str]:
        try:
            row = self._get_task_row(tracker_id)
        except TrackerNotFoundError:
            return []
        return row.metadata.get("member_task_ids", [])

    def find_tracker_id_for_member(self, task_id: str) -> str | None:
        from django.db.models import Q

        row = (
            self._task_model.objects.filter(
                Q(celery_task_id=task_id)
                | Q(metadata__member_task_ids__contains=[task_id]),
            )
            .values_list("celery_task_id", "id")
            .first()
        )
        if row is not None:
            celery_task_id, pk = row
            return str(celery_task_id) if celery_task_id else str(pk)
        return None

    # -- steps ---------------------------------------------------------------

    def add_step(self, tracker_id: str, step: ExecutionState) -> int:
        """Append a step and return its zero-based index."""
        row = self._get_task_row(tracker_id)
        current_count = self._step_model.objects.filter(tracked_task=row).count()
        self._step_model.objects.create(
            tracked_task=row,
            name=step.title or f"step_{current_count}",
            label=step.title or "",
            order=current_count,
            status=_STEP_STATE_TO_STATUS.get(step.state, "pending"),
            started_at=step.started_on,
            finished_at=step.completed_on,
        )
        return current_count

    def update_step(
        self, tracker_id: str, step_index: int, step: ExecutionState
    ) -> None:
        """Update a step identified by its zero-based index."""
        row = self._get_task_row(tracker_id)
        try:
            step_row = self._step_model.objects.filter(tracked_task=row).order_by(
                "order"
            )[step_index]
        except IndexError:
            raise TrackerNotFoundError(
                f"Step index {step_index} not found for tracker {tracker_id}"
            )
        step_row.status = _STEP_STATE_TO_STATUS.get(step.state, "pending")
        step_row.started_at = step.started_on
        step_row.finished_at = step.completed_on
        step_row.save(update_fields=["status", "started_at", "finished_at"])

    def get_steps(self, tracker_id: str) -> list[ExecutionState]:
        """Return all steps for a tracker as :class:`ExecutionState` instances."""
        try:
            row = self._get_task_row(tracker_id)
        except TrackerNotFoundError:
            return []
        return [
            self._step_row_to_execution_state(s)
            for s in self._step_model.objects.filter(tracked_task=row).order_by("order")
        ]

    # -- row ↔ Pydantic conversion -------------------------------------------

    def _tracker_state_to_row(self, state: TrackerState) -> dict[str, Any]:
        """Convert a :class:`TrackerState` to ``update_or_create`` defaults."""
        result_dict: dict | None = None
        error_message = ""
        if state.info is not None:
            if state.info.error:
                error_message = str(state.info.error)
            if state.info.result is not None:
                r = state.info.result
                result_dict = r if isinstance(r, dict) else {"value": r}

        return {
            "tracked_task_type": state.result_type,
            "name": state.title or "",
            "status": _CELERY_STATE_TO_STATUS.get(state.state, "pending"),
            "progress_current": int(state.progress_completed or 0),
            "progress_total": int(state.progress_target or 0),
            "result": result_dict,
            "error_message": error_message,
            "started_at": state.started_on,
            "finished_at": state.completed_on,
            "metadata": {},
        }

    def _row_to_tracker_state(self, row: Any) -> TrackerState:
        """Convert a ``TrackedTask`` model instance to a :class:`TrackerState`."""
        celery_state = cast(
            CeleryTaskState, _STATUS_TO_CELERY_STATE.get(row.status, "PENDING")
        )

        info: TrackerResult | None = None
        if row.error_message:
            info = TrackerResult(error=row.error_message)
        elif row.result is not None:
            info = TrackerResult(result=row.result)

        return TrackerState(
            id=str(row.celery_task_id) if row.celery_task_id else str(row.id),
            title=row.name or None,
            state=celery_state,
            result_type=row.tracked_task_type or "task",
            info=info,
            created_on=_to_datetime(row.created_at),
            started_on=row.started_at,
            completed_on=row.finished_at,
            progress_completed=(
                float(row.progress_current) if row.progress_current else None
            ),
            progress_target=(float(row.progress_total) if row.progress_total else None),
        )

    def _step_row_to_execution_state(self, step_row: Any) -> ExecutionState:
        """Convert a ``TrackedTaskStep`` model instance to an :class:`ExecutionState`."""
        celery_state = cast(
            CeleryTaskState, _STEP_STATUS_TO_STATE.get(step_row.status, "PENDING")
        )
        return ExecutionState(
            title=step_row.label or step_row.name,
            state=celery_state,
            started_on=step_row.started_at,
            completed_on=step_row.finished_at,
        )

    # -- helpers --------------------------------------------------------------

    def _get_task_row(self, tracker_id: str) -> Any:
        """Fetch a ``TrackedTask`` row by celery_task_id, or raise."""
        try:
            return self._task_model.objects.get(celery_task_id=tracker_id)
        except self._task_model.DoesNotExist:
            raise TrackerNotFoundError(f"Tracker {tracker_id} not found")


def _to_datetime(value: Any) -> datetime:
    """Coerce a Django ``DateTimeField`` value to a plain :class:`datetime`."""
    if isinstance(value, datetime):
        return value
    return datetime.now(UTC)
