from __future__ import annotations

import functools
import logging
from datetime import UTC, datetime

from celery import current_task

from .backend import resolve_backend_for_task
from .models import ExecutionState
from .stamping import TRACKER_ID_HEADER

logger = logging.getLogger(__name__)


class step:
    """Track a named step within a Celery task.

    Works as a **context manager** or a **decorator**.

    Context manager::

        @app.task
        def my_task():
            with tracker.step("Fetch data"):
                fetch()
            with tracker.step("Transform"):
                transform()

    Decorator (wraps the entire function body as a single step)::

        @app.task
        @tracker.step("Process")
        def my_task():
            process()

    The tracker ID is read from the ``tracker_id`` stamped header that
    :func:`tracker.track` embeds into every dispatched signature.  No
    backend lookup is required.
    """

    def __init__(self, title: str) -> None:
        self.title = title

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> step:
        task = current_task
        if task is None or task.request.id is None:  # type: ignore[union-attr]
            logger.warning(
                "tracker.step('%s') used outside a Celery task – skipping",
                self.title,
            )
            self._noop = True
            return self

        self._noop = False
        tracker_id = _extract_tracker_id(task.request)

        if tracker_id is None:
            logger.warning(
                "No tracker_id stamp on task %s – step '%s' will not be tracked",
                task.request.id,  # type: ignore[union-attr]
                self.title,
            )
            self._noop = True
            return self

        self._tracker_id = tracker_id
        self._celery_task_id = task.request.id
        self._started_on = datetime.now(UTC)

        backend = resolve_backend_for_task()
        step_state = ExecutionState(
            title=self.title,
            state="STARTED",
            celery_task_id=task.request.id,
            started_on=self._started_on,
        )
        self._step_index = backend.add_step(tracker_id, step_state)
        logger.debug(
            "Started step '%s' (index=%d) for tracker %s",
            self.title,
            self._step_index,
            tracker_id,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: ANN001
        if self._noop:
            return False

        now = datetime.now(UTC)
        backend = resolve_backend_for_task()

        if exc_type is not None:
            completed = ExecutionState(
                title=self.title,
                state="FAILURE",
                info=exc_val,
                celery_task_id=self._celery_task_id,
                started_on=self._started_on,
                completed_on=now,
            )
        else:
            completed = ExecutionState(
                title=self.title,
                state="SUCCESS",
                celery_task_id=self._celery_task_id,
                started_on=self._started_on,
                completed_on=now,
            )

        backend.update_step(self._tracker_id, self._step_index, completed)
        logger.debug(
            "Completed step '%s' (index=%d) with state %s",
            self.title,
            self._step_index,
            completed.state,
        )
        return False  # never suppress exceptions

    # -- decorator -----------------------------------------------------------

    def __call__(self, func):  # noqa: ANN001, ANN202
        title = self.title

        @functools.wraps(func)
        def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            with step(title):
                return func(*args, **kwargs)

        return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_tracker_id(request) -> str | None:  # noqa: ANN001
    """Read the ``tracker_id`` stamp from a Celery task request.

    The value lives in ``request.stamps['tracker_id']`` — both
    client-side publishes and pre-stamped canvas signatures place it in
    ``headers['stamps']``, which Celery copies to the request.

    The value may be a bare string or wrapped in a list (canvas
    propagation).
    """
    stamps = getattr(request, "stamps", None) or {}
    raw = stamps.get(TRACKER_ID_HEADER)
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw  # type: ignore[return-value]
