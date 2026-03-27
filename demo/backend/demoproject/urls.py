from http import HTTPStatus

from celery import current_app
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI, Router, Schema
from redis import StrictRedis

from tracker.api import (
    CancellationOut,
    CeleryTaskOut,
    RunTaskIn,
    RunTaskOut,
    TrackedTaskDetailOut,
    TrackedTaskListOut,
)
from tracker.api import (
    cancel_tracked_task as _cancel_tracked_task,
)
from tracker.api import (
    get_tracked_task as _get_tracked_task,
)
from tracker.api import (
    get_tracked_task_by_celery_id as _get_tracked_task_by_celery_id,
)
from tracker.api import (
    list_tracked_tasks as _list_tracked_tasks,
)
from tracker.stamping import TRACKER_ID_HEADER
from tracker.track import track

from .celery.report_chained import CANVAS_RECIPES as CHAINED_RECIPES
from .celery.report_fanout import CANVAS_RECIPES as FANOUT_RECIPES
from .log_handler import REDIS_KEY

CANVAS_RECIPES: dict = {**CHAINED_RECIPES, **FANOUT_RECIPES}

api = NinjaAPI()


# =============================================================================
# Celery task discovery & execution (custom — supports canvas recipes)
# =============================================================================

tasks_router = Router(tags=["Celery Tasks"])


@tasks_router.get("/celery-tasks", response=list[CeleryTaskOut])
def list_celery_tasks(request):
    """List registered Celery tasks *and* canvas recipes.

    Merges auto-discovered ``current_app.tasks`` (excluding internal
    ``celery.*`` built-ins) with the canvas recipes defined in
    ``report_chained`` and ``report_fanout``.
    """
    tasks = current_app.tasks  # type: ignore[attr-defined]
    items = [
        CeleryTaskOut(name=name, description=getattr(task, "__doc__", "") or "")
        for name, task in tasks.items()
        if not name.startswith("celery.")
    ]
    for recipe_name, (title, _builder) in CANVAS_RECIPES.items():
        items.append(CeleryTaskOut(name=recipe_name, description=title))
    return sorted(items, key=lambda t: t.name)


@tasks_router.post(
    "/celery-tasks/{task_name}/run",
    response={HTTPStatus.OK: RunTaskOut, HTTPStatus.NOT_FOUND: dict},
)
def run_task_or_canvas(request, task_name: str, payload: RunTaskIn | None = None):
    """Run a Celery task or canvas recipe by name and track it.

    If *task_name* matches a key in :data:`CANVAS_RECIPES`, the
    corresponding canvas builder is called and the resulting signature
    is tracked.  Otherwise falls back to the standard single-task
    dispatch.
    """
    args = (payload.args if payload else []) or []
    kwargs = (payload.kwargs if payload else {}) or {}

    if task_name in CANVAS_RECIPES:
        title, builder = CANVAS_RECIPES[task_name]
    else:
        title = task_name
        builder = None

    try:
        with track(title) as t:
            if builder is not None:
                sig = builder()
                # Stamp the whole canvas so every link/chord child carries
                # tracker_id when the worker publishes — track() alone only
                # stamps the first client-side publish.
                sig.stamp(**{TRACKER_ID_HEADER: t.tracker_id})
                sig.apply_async()
            else:
                current_app.send_task(task_name, args=args, kwargs=kwargs)
    except Exception:
        return HTTPStatus.NOT_FOUND, {"detail": f"Task '{task_name}' not found"}

    return HTTPStatus.OK, RunTaskOut(tracker_id=t.tracker_id, task_name=task_name)


api.add_router("/", tasks_router)


# =============================================================================
# Tracked-task endpoints (thin wrappers delegating to tracker library)
# =============================================================================

tracker_router = Router(tags=["Tracked Tasks"])


@tracker_router.get("/tracked-tasks", response=list[TrackedTaskListOut])
def list_tracked_tasks(request):
    return _list_tracked_tasks(request)


@tracker_router.get(
    "/tracked-tasks/{tracker_id}",
    response={HTTPStatus.OK: TrackedTaskDetailOut, HTTPStatus.NOT_FOUND: dict},
)
def get_tracked_task(request, tracker_id: str):
    return _get_tracked_task(request, tracker_id)


@tracker_router.get(
    "/tracked-tasks/by-celery-id/{celery_task_id}",
    response={HTTPStatus.OK: TrackedTaskDetailOut, HTTPStatus.NOT_FOUND: dict},
)
def get_tracked_task_by_celery_id(request, celery_task_id: str):
    return _get_tracked_task_by_celery_id(request, celery_task_id)


@tracker_router.post(
    "/tracked-tasks/{tracker_id}/cancel",
    response={HTTPStatus.OK: CancellationOut, HTTPStatus.NOT_FOUND: dict},
)
def cancel_tracked_task(request, tracker_id: str):
    return _cancel_tracked_task(request, tracker_id)


api.add_router("/", tracker_router)


# =============================================================================
# Worker logs endpoint (demo-only)
# =============================================================================

logs_router = Router(tags=["Worker Logs"])


class LogEntryOut(Schema):
    timestamp: str
    level: str
    logger: str
    message: str


@logs_router.get("/worker", response=list[LogEntryOut])
def get_worker_logs(request, limit: int = 100):
    """Return the most recent worker log entries from Redis."""
    import json

    from django.conf import settings

    url = getattr(settings, "CELERY_RESULT_BACKEND", None)
    if not url:
        return []

    client = StrictRedis.from_url(url)
    raw_entries = client.lrange(REDIS_KEY, 0, min(limit, 500) - 1)
    return [json.loads(entry) for entry in raw_entries]


api.add_router("/logs", logs_router)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/tracker/", api.urls),
]
