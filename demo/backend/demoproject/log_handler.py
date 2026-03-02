"""
Redis-backed logging handler for streaming worker logs to the UI.

Pushes JSON-serialised log records to a Redis list (capped via LTRIM)
so that the Django API can read them back for display.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis import StrictRedis

REDIS_KEY = "celery-tracker:worker-logs"
MAX_ENTRIES = 500


class RedisLogHandler(logging.Handler):
    """Logging handler that writes JSON log entries to a capped Redis list."""

    def __init__(
        self,
        redis_client: StrictRedis,
        key: str = REDIS_KEY,
        max_entries: int = MAX_ENTRIES,
        level: int = logging.DEBUG,
    ) -> None:
        super().__init__(level)
        self._redis = redis_client
        self._key = key
        self._max_entries = max_entries

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.dumps(
                {
                    "timestamp": datetime.fromtimestamp(
                        record.created, tz=timezone.utc
                    ).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": self.format(record),
                },
                default=str,
            )
            pipe = self._redis.pipeline()
            pipe.lpush(self._key, entry)
            pipe.ltrim(self._key, 0, self._max_entries - 1)
            pipe.execute()
        except Exception:
            self.handleError(record)
