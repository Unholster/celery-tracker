"""Public tracking API.

Track Celery work by wrapping dispatch calls in a context manager::

    with track("Q4 Report") as t:
        report_task.delay(report_id=1)
    print(t.tracker_id)

Every ``.delay()`` / ``.apply_async()`` inside the block is stamped
with the tracker ID automatically.  A ``before_task_publish`` signal
handler (global in :mod:`tracker.signals`, plus a context-local one)
registers every stamped task ID as a member of the tracker.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

from celery.signals import before_task_publish

from .backend import TrackerBackend, get_backend
from .models import TrackerState
from .service import TrackerService
from .stamping import TRACKER_ID_HEADER

logger = logging.getLogger(__name__)

_current_tracking: ContextVar[TrackingContext | None] = ContextVar(
    "current_tracking", default=None
)


# ── Public API ──────────────────────────────────────────────────────────────


def track(
    title: str,
    *,
    backend: TrackerBackend | None = None,
) -> TrackingContext:
    """Return a :class:`TrackingContext` for use as a context manager.

    Every task published inside the ``with`` block is stamped with a
    shared tracker ID and registered as a member of the tracker::

        with track("Nightly ETL") as t:
            extract.delay()
            transform.delay()
            load.delay()

        print(t.tracker_id)   # single ID covering all three tasks
    """
    return TrackingContext(title=title, backend=backend)


def state(tracker_id: str) -> TrackerState:
    """Load a :class:`TrackerState` by ID from the backend."""
    return TrackerService().get_tracker(tracker_id)


# ── TrackingContext ─────────────────────────────────────────────────────────


class TrackingContext:
    """Stamps every task published within the ``with`` block.

    Created by ``track("title")``.  Attributes available after entering
    the context:

    * ``tracker_id`` — the UUID assigned to this tracker.
    """

    def __init__(
        self,
        title: str,
        *,
        backend: TrackerBackend | None = None,
    ) -> None:
        self.title = title
        self.tracker_id = str(uuid4())
        self._backend_override = backend

    # -- context manager protocol --------------------------------------------

    def __enter__(self) -> TrackingContext:
        self._token = _current_tracking.set(self)
        before_task_publish.connect(self._on_publish)

        # Persist the tracker *before* any tasks are dispatched so that
        # add_member() can find the row in every backend flavour.
        self._resolve_backend().save(TrackerState(id=self.tracker_id, title=self.title))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        before_task_publish.disconnect(self._on_publish)
        _current_tracking.reset(self._token)
        return False  # never suppress exceptions

    # -- signal handler (scoped to this context via contextvar) ---------------

    def _on_publish(self, sender, headers, **kwargs):  # noqa: ANN001, ANN003
        if _current_tracking.get(None) is not self:
            return  # different thread / async task — not ours

        # Inject the tracker stamp into the outgoing message headers.
        headers[TRACKER_ID_HEADER] = self.tracker_id
        headers.setdefault("stamped_headers", []).append(TRACKER_ID_HEADER)

        # Register the member directly — the global handler in
        # tracker.signals connected *before* us so it already ran and
        # saw no stamp.  We handle client-side registration here;
        # worker-side callbacks get picked up by the global handler
        # because they carry the propagated stamp.
        task_id = headers.get("id")
        if task_id:
            try:
                self._resolve_backend().add_member(self.tracker_id, task_id)
            except Exception:
                logger.debug(
                    "Could not register task %s for tracker %s",
                    task_id,
                    self.tracker_id,
                    exc_info=True,
                )

    # -- helpers -------------------------------------------------------------

    def _resolve_backend(self) -> TrackerBackend:
        return self._backend_override or get_backend()
