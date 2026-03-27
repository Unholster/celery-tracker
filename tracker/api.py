"""
Django Ninja API for celery-tracker.

Mirrors the endpoint structure of ``celery_task_tracking.api`` so that
frontends built against that interface can talk to either backend.

Supported (backed by :class:`TrackerService`):
  - ``GET  /tracked-tasks``                           — list all trackers
  - ``GET  /tracked-tasks/{tracker_id}``              — detail (live Celery merge)
  - ``GET  /tracked-tasks/by-celery-id/{celery_id}``  — same as detail
  - ``POST /tracked-tasks/{tracker_id}/cancel``        — revoke via Celery control
  - ``GET  /celery-tasks``                            — list registered Celery tasks
  - ``POST /celery-tasks/{task_name}/run``             — run a task by name

Not yet supported (return 501):
  - ``GET  /tracked-tasks/{tracker_id}/children``
  - ``GET  /tracked-tasks/stats/by-type``
  - ``GET  /tracked-tasks/stats/recent``
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from celery import current_app
from ninja import Router, Schema

from .backend import TrackerNotFoundError
from .models import CeleryTaskState, ExecutionState, TrackerState
from .service import TrackerService, primary_member_celery_task_id
from .track import track

logger = logging.getLogger(__name__)

router = Router(tags=["Tracked Task Tracker"])


# =============================================================================
# Schemas — shape-compatible with celery_task_tracking.schemas
# =============================================================================

_STATE_TO_STATUS: dict[CeleryTaskState, str] = {
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


class CeleryTaskOut(Schema):
    """Output schema for a registered Celery task."""

    name: str
    description: str


class RunTaskIn(Schema):
    """Input schema for running a Celery task."""

    args: list = []
    kwargs: dict = {}


class RunTaskOut(Schema):
    """Output schema for a newly dispatched task."""

    tracker_id: str
    task_name: str


class TaskExecutionStateOut(Schema):
    """Output schema for an individual task execution state.

    Maps directly to :class:`ExecutionState` from the TrackerState model,
    keyed by Celery task ID in the ``tasks`` dict.
    """

    title: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    error_message: str
    result: dict | None


class TrackedTaskStepOut(Schema):
    """Output schema for a tracker step."""

    name: str
    label: str
    order: int
    status: str
    started_at: str | None
    finished_at: str | None
    progress_current: int
    progress_total: int
    progress_message: str
    progress_percent: int | None


class TrackedTaskListOut(Schema):
    """Output schema for the list endpoint."""

    id: str
    tracked_task_type: str
    name: str
    status: str

    progress_current: int
    progress_total: int
    progress_percent: int | None

    created_at: str
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None

    is_stale: bool
    error_message: str
    metadata: dict


class TrackedTaskDetailOut(Schema):
    """Output schema for the detail endpoint."""

    id: str
    tracked_task_type: str
    name: str
    celery_task_id: str | None
    status: str

    # Progress
    progress_current: int
    progress_total: int
    progress_percent: int | None
    progress_message: str

    # Per-task execution states keyed by Celery task ID
    tasks: dict[str, TaskExecutionStateOut]

    # Result
    result: dict | None
    error_message: str

    # Timestamps
    created_at: str
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None

    # Stale detection
    is_stale: bool

    # Metadata
    metadata: dict

    # Steps
    steps: list[TrackedTaskStepOut]

    # Parent tracked task
    parent_task_id: str | None


class CancellationOut(Schema):
    """Output schema for the cancel endpoint."""

    id: str
    status: str
    revoked_task_ids: list[str]


# =============================================================================
# Endpoints
# =============================================================================


# -- Celery task discovery & execution --------------------------------------


@router.get("/celery-tasks", response=list[CeleryTaskOut])
def list_celery_tasks(request):
    """List Celery task types registered with the current app.

    Reads ``current_app.tasks`` — the registry of task classes known to
    the application — and returns their names, excluding internal
    ``celery.*`` built-in tasks.
    """
    tasks = current_app.tasks  # type: ignore[attr-defined]
    return sorted(
        [
            CeleryTaskOut(name=name, description=getattr(task, "__doc__", "") or "")
            for name, task in tasks.items()
            if not name.startswith("celery.")
        ],
        key=lambda t: t.name,
    )


@router.post(
    "/celery-tasks/{task_name}/run",
    response={HTTPStatus.OK: RunTaskOut, HTTPStatus.NOT_FOUND: dict},
)
def run_celery_task(request, task_name: str, payload: RunTaskIn | None = None):
    """Run a registered Celery task by name and track it."""
    args = (payload.args if payload else []) or []
    kwargs = (payload.kwargs if payload else {}) or {}

    try:
        with track(task_name) as t:
            current_app.send_task(task_name, args=args, kwargs=kwargs)
    except Exception as exc:
        logger.exception("Failed to dispatch task %s", task_name)
        return HTTPStatus.NOT_FOUND, {"detail": str(exc)}

    return HTTPStatus.OK, RunTaskOut(tracker_id=t.tracker_id, task_name=task_name)


# -- Tracked-task CRUD ------------------------------------------------------


@router.get("/tracked-tasks", response=list[TrackedTaskListOut])
def list_tracked_tasks(request):
    """List all tracked tasks, merging live Celery state."""
    service = _get_service()
    results = []
    for t in service.list_trackers():
        try:
            live = service.get_tracker(t.id)
        except Exception:
            live = t
        results.append(_to_list_out(live))
    return results


@router.get(
    "/tracked-tasks/{tracker_id}",
    response={HTTPStatus.OK: TrackedTaskDetailOut, HTTPStatus.NOT_FOUND: dict},
)
def get_tracked_task(request, tracker_id: str):
    """Get tracked task details including live Celery state."""
    service = _get_service()
    try:
        tracker_state = service.get_tracker(tracker_id)
    except TrackerNotFoundError:
        return HTTPStatus.NOT_FOUND, {"detail": f"Tracker {tracker_id} not found"}
    return HTTPStatus.OK, _to_detail_out(tracker_state)


@router.get(
    "/tracked-tasks/by-celery-id/{celery_task_id}",
    response={HTTPStatus.OK: TrackedTaskDetailOut, HTTPStatus.NOT_FOUND: dict},
)
def get_tracked_task_by_celery_id(request, celery_task_id: str):
    """Get tracked task by Celery task ID (member task id or tracker id).

    Accepts either the tracker id or any registered member task id.
    """
    return get_tracked_task(request, tracker_id=celery_task_id)


@router.post(
    "/tracked-tasks/{tracker_id}/cancel",
    response={HTTPStatus.OK: CancellationOut, HTTPStatus.NOT_FOUND: dict},
)
def cancel_tracked_task(request, tracker_id: str):
    """Cancel a tracked task by revoking its Celery tasks."""
    service = _get_service()
    try:
        result = service.revoke_tracked_tasks(tracker_id)
    except TrackerNotFoundError:
        return HTTPStatus.NOT_FOUND, {"detail": f"Tracker {tracker_id} not found"}
    return HTTPStatus.OK, CancellationOut(
        id=tracker_id,
        status="cancelled",
        revoked_task_ids=result.revoked_task_ids,
    )


# =============================================================================
# Not implemented — stubs for API compatibility
# =============================================================================


@router.get(
    "/tracked-tasks/{tracker_id}/children",
    response={HTTPStatus.NOT_IMPLEMENTED: dict},
)
def list_child_tracked_tasks(request, tracker_id: str, status: str | None = None):
    """List child tracked tasks (subtasks) of a parent tracked task."""
    return HTTPStatus.NOT_IMPLEMENTED, {
        "detail": "Child task listing is not yet supported by celery-tracker.",
    }


@router.get(
    "/tracked-tasks/stats/by-type",
    response={HTTPStatus.NOT_IMPLEMENTED: dict},
)
def get_tracked_tasks_stats_by_type(request):
    """Get tracked task statistics grouped by type."""
    return HTTPStatus.NOT_IMPLEMENTED, {
        "detail": "Stats by type are not yet supported by celery-tracker.",
    }


@router.get(
    "/tracked-tasks/stats/recent",
    response={HTTPStatus.NOT_IMPLEMENTED: dict},
)
def get_recent_tracked_tasks_stats(request, hours: int = 24):
    """Get statistics for tracked tasks created in the last N hours."""
    return HTTPStatus.NOT_IMPLEMENTED, {
        "detail": "Recent stats are not yet supported by celery-tracker.",
    }


# =============================================================================
# Adapters — TrackerState → response schemas
# =============================================================================


def _get_service() -> TrackerService:
    return TrackerService()


def _progress_percent(current: float | None, total: float | None) -> int | None:
    if not total or not current:
        return None
    return int(current / total * 100)


def _duration_seconds(state: TrackerState) -> float | None:
    if state.started_on is None or state.completed_on is None:
        return None
    return (state.completed_on - state.started_on).total_seconds()


def _error_message(state: TrackerState) -> str:
    if state.info and state.info.error:
        return str(state.info.error)
    return ""


def _result_dict(state: TrackerState) -> dict | None:
    if state.info is None or state.info.result is None:
        return None
    r = state.info.result
    return r if isinstance(r, dict) else {"value": r}


def _execution_state_error(es: ExecutionState) -> str:
    if es.info and es.info.error:
        return str(es.info.error)
    return ""


def _execution_state_result(es: ExecutionState) -> dict | None:
    if es.info is None or es.info.result is None:
        return None
    r = es.info.result
    return r if isinstance(r, dict) else {"value": r}


def _task_execution_out(es: ExecutionState) -> TaskExecutionStateOut:
    """Convert an :class:`ExecutionState` to its API output schema."""
    return TaskExecutionStateOut(
        title=es.title,
        status=_STATE_TO_STATUS.get(es.state, es.state),
        started_at=es.started_on.isoformat() if es.started_on else None,
        finished_at=es.completed_on.isoformat() if es.completed_on else None,
        error_message=_execution_state_error(es),
        result=_execution_state_result(es),
    )


def _step_out(index: int, es: ExecutionState) -> TrackedTaskStepOut:
    name = es.title or f"step_{index}"
    return TrackedTaskStepOut(
        name=name,
        label=es.title or name,
        order=index,
        status=_STATE_TO_STATUS.get(es.state, es.state),
        started_at=es.started_on.isoformat() if es.started_on else None,
        finished_at=es.completed_on.isoformat() if es.completed_on else None,
        progress_current=0,
        progress_total=0,
        progress_message="",
        progress_percent=None,
    )


def _to_list_out(state: TrackerState) -> TrackedTaskListOut:
    return TrackedTaskListOut(
        id=state.id,
        tracked_task_type=state.result_type,
        name=state.title or "",
        status=_STATE_TO_STATUS.get(state.state, state.state),
        progress_current=int(state.progress_completed or 0),
        progress_total=int(state.progress_target or 0),
        progress_percent=_progress_percent(
            state.progress_completed, state.progress_target
        ),
        created_at=state.created_on.isoformat(),
        updated_at=None,
        started_at=state.started_on.isoformat() if state.started_on else None,
        finished_at=state.completed_on.isoformat() if state.completed_on else None,
        duration_seconds=_duration_seconds(state),
        is_stale=False,
        error_message=_error_message(state),
        metadata={},
    )


def _to_detail_out(state: TrackerState) -> TrackedTaskDetailOut:
    step_covered_ids = {
        s.celery_task_id for s in state.steps if s.celery_task_id
    }
    tasks_out = {
        task_id: _task_execution_out(es)
        for task_id, es in state.tasks.items()
        if task_id not in step_covered_ids
    }
    return TrackedTaskDetailOut(
        id=state.id,
        tracked_task_type=state.result_type,
        name=state.title or "",
        celery_task_id=primary_member_celery_task_id(state),
        status=_STATE_TO_STATUS.get(state.state, state.state),
        progress_current=int(state.progress_completed or 0),
        progress_total=int(state.progress_target or 0),
        progress_percent=_progress_percent(
            state.progress_completed, state.progress_target
        ),
        progress_message="",
        tasks=tasks_out,
        result=_result_dict(state),
        error_message=_error_message(state),
        created_at=state.created_on.isoformat(),
        updated_at=None,
        started_at=state.started_on.isoformat() if state.started_on else None,
        finished_at=state.completed_on.isoformat() if state.completed_on else None,
        duration_seconds=_duration_seconds(state),
        is_stale=False,
        metadata={},
        steps=[_step_out(i, s) for i, s in enumerate(state.steps)],
        parent_task_id=None,
    )
