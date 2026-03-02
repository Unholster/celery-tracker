"""Tracker backend package.

Re-exports the public API that was previously in the single
``tracker.backend`` module so that every existing import such as
``from tracker.backend import TrackerBackend`` keeps working.
"""

from __future__ import annotations

import logging
from typing import Union

from celery import current_app, current_task
from celery.result import AsyncResult, GroupResult
from redis import StrictRedis

from .djangotrackerbackend import DjangoTrackerBackend
from .redistrackerbackend import RedisTrackerBackend
from .trackerbackend import TrackerBackend, TrackerNotFoundError

__all__ = [
    "TrackerBackend",
    "TrackerNotFoundError",
    "RedisTrackerBackend",
    "DjangoTrackerBackend",
    "configure",
    "get_backend",
    "resolve_backend",
    "resolve_backend_for_task",
]

logger = logging.getLogger(__name__)

CeleryResult = Union[AsyncResult, GroupResult]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Module-level default backend, lazily resolved and cached.
_default_backend: TrackerBackend | None = None


def configure(backend: TrackerBackend) -> None:
    """Set the default tracker backend explicitly."""
    global _default_backend
    _default_backend = backend


def get_backend() -> TrackerBackend:
    """Return the current default backend, auto-resolving if needed.

    If no backend has been explicitly configured yet, attempts to derive
    one from the current Celery app's configuration (e.g. a Redis
    ``result_backend``).  Raises :class:`RuntimeError` only when
    auto-resolution also fails.
    """
    if _default_backend is None:
        return _resolve_from_app(current_app)
    return _default_backend


def resolve_backend(result: CeleryResult) -> TrackerBackend:
    """Resolve the tracker backend from configuration.

    Resolution order:
      1. Module-level default set via ``configure()``.
      2. ``tracker_backend`` attribute on the Celery app config.
      3. Auto-build a ``RedisTrackerBackend`` from ``result_backend``
         when the URL scheme is ``redis://`` or ``rediss://``.

    The resolved backend is cached as the module-level default so that
    subsequent calls don't recreate clients.
    """
    if _default_backend is not None:
        return _default_backend
    return _resolve_from_app(result.app)


def resolve_backend_for_task() -> TrackerBackend:
    """Resolve the tracker backend from within a running Celery task.

    Tries the module-level default first, then falls back to resolving
    from the current Celery task's app configuration.
    """
    if _default_backend is not None:
        return _default_backend

    task = current_task
    if task is None or task.request.id is None:  # type: ignore[union-attr]
        raise RuntimeError(
            "resolve_backend_for_task() called outside a Celery task context."
        )
    return _resolve_from_app(task.app)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_from_app(app) -> TrackerBackend:  # type: ignore[type-arg]
    """Resolve and cache a backend from a Celery app instance."""
    global _default_backend

    if app is not None:
        # 1) Explicit TrackerBackend instance on the Celery config
        configured = getattr(app.conf, "tracker_backend", None)
        if isinstance(configured, TrackerBackend):
            _default_backend = configured
            return _default_backend

        # 2) Fall back: derive a Redis backend from the result backend URL
        backend_url: str | None = app.conf.result_backend
        if backend_url and backend_url.startswith(("redis://", "rediss://")):
            client = StrictRedis.from_url(backend_url)
            _default_backend = RedisTrackerBackend(client)
            return _default_backend

    raise RuntimeError(
        "No tracker backend configured. "
        "Either call tracker.backend.configure(), set 'tracker_backend' on "
        "your Celery app config, or ensure 'result_backend' points to Redis."
    )
