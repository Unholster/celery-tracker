"""Global Celery signal handler for automatic member registration.

When the tracker package is imported, a ``before_task_publish`` handler
is connected that inspects every outgoing task message.  If the message
carries a ``tracker_id`` stamped header (injected by
:class:`~tracker.track.TrackingContext` on the client, or propagated by
Celery on workers), the handler registers the task ID as a member of
that tracker in the backend.

This fires on **both** the client and on **workers** (when Celery
dispatches chain callbacks, chord callbacks, etc. with propagated
stamps).  The result is an incrementally-built set of member task IDs
per tracker — no canvas introspection required.
"""

from __future__ import annotations

import logging

from celery.signals import before_task_publish

from .stamping import TRACKER_ID_HEADER

logger = logging.getLogger(__name__)


def _extract_tracker_id_from_headers(headers: dict) -> str | None:
    """Read ``tracker_id`` from ``headers['stamps']``.

    Both client-side publishes (:class:`~tracker.track.TrackingContext`)
    and worker-side publishes (pre-stamped canvas signatures) place the
    value in ``headers['stamps']``.

    The value may be a bare string or wrapped in a list (canvas
    propagation).
    """
    raw = (headers.get("stamps") or {}).get(TRACKER_ID_HEADER)
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw


@before_task_publish.connect
def _on_task_publish(sender, headers, **kwargs):  # noqa: ANN001, ANN003
    """Register a stamped task as a member of its tracker."""
    tracker_id = _extract_tracker_id_from_headers(headers)
    if not tracker_id:
        return

    task_id = headers.get("id")
    if not task_id:
        return

    try:
        from .backend import get_backend

        backend = get_backend()
        backend.add_member(tracker_id, task_id)
    except Exception:
        logger.debug(
            "Could not register task %s for tracker %s",
            task_id,
            tracker_id,
            exc_info=True,
        )
