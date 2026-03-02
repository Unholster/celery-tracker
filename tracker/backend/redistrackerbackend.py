from __future__ import annotations

import logging

from redis import StrictRedis

from ..models import ExecutionState, TrackerState
from .trackerbackend import TrackerBackend, TrackerNotFoundError

logger = logging.getLogger(__name__)


class RedisTrackerBackend(TrackerBackend):
    """Redis-based tracker backend."""

    STATE_PREFIX = "celery-tracker:state"
    MEMBERS_PREFIX = "celery-tracker:members"
    STEPS_PREFIX = "celery-tracker:steps"

    def __init__(self, client: StrictRedis) -> None:
        self._client = client

    # -- tracker state -------------------------------------------------------

    def save(self, state: TrackerState) -> None:
        key = self._state_key(state.id)
        self._client.set(key, state.model_dump_json())
        logger.debug("Saved tracker state %s", state.id)

    def load(self, tracker_id: str) -> TrackerState:
        key = self._state_key(tracker_id)
        data: bytes | None = self._client.get(key)  # type: ignore[assignment]
        if data is None:
            raise TrackerNotFoundError(f"Tracker {tracker_id} not found")
        return TrackerState.model_validate_json(data)

    def list_all(self) -> list[TrackerState]:
        pattern = f"{self.STATE_PREFIX}:*"
        return [
            TrackerState.model_validate_json(data)
            for key in self._client.scan_iter(match=pattern)
            if (data := self._client.get(key)) is not None
        ]

    # -- members -------------------------------------------------------------

    def add_member(self, tracker_id: str, task_id: str) -> None:
        key = self._members_key(tracker_id)
        self._client.sadd(key, task_id)

    def get_members(self, tracker_id: str) -> list[str]:
        key = self._members_key(tracker_id)
        raw: set[bytes] = self._client.smembers(key)  # type: ignore[assignment]
        return sorted(m.decode() for m in raw)

    # -- steps ---------------------------------------------------------------

    def add_step(self, tracker_id: str, step: ExecutionState) -> int:
        key = self._steps_key(tracker_id)
        length: int = self._client.rpush(key, step.model_dump_json())  # type: ignore[assignment]
        return length - 1

    def update_step(
        self, tracker_id: str, step_index: int, step: ExecutionState
    ) -> None:
        key = self._steps_key(tracker_id)
        self._client.lset(key, step_index, step.model_dump_json())

    def get_steps(self, tracker_id: str) -> list[ExecutionState]:
        key = self._steps_key(tracker_id)
        items: list[bytes] = self._client.lrange(key, 0, -1)  # type: ignore[assignment]
        return [ExecutionState.model_validate_json(item) for item in items]

    # -- key helpers ---------------------------------------------------------

    def _state_key(self, tracker_id: str) -> str:
        return f"{self.STATE_PREFIX}:{tracker_id}"

    def _members_key(self, tracker_id: str) -> str:
        return f"{self.MEMBERS_PREFIX}:{tracker_id}"

    def _steps_key(self, tracker_id: str) -> str:
        return f"{self.STEPS_PREFIX}:{tracker_id}"
