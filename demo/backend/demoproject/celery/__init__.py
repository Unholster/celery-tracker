import logging
import os

from celery import Celery
from celery.signals import after_setup_logger
from redis import StrictRedis

from ..log_handler import RedisLogHandler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demoproject.settings")

logger = logging.getLogger(__name__)

app = Celery("demo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.set_default()


@after_setup_logger.connect
def _install_redis_log_handler(logger: logging.Logger, **kwargs) -> None:  # type: ignore[type-arg]
    """Push worker log records to Redis so the UI can display them.

    Attaches to the *root* logger (not just the ``celery`` logger passed
    by the signal) so that task loggers like ``demoproject.celery`` are
    also captured.
    """
    root = logging.getLogger()
    if any(isinstance(h, RedisLogHandler) for h in root.handlers):
        return
    url = app.conf.result_backend
    if url and url.startswith(("redis://", "rediss://")):
        client = StrictRedis.from_url(url)
        handler = RedisLogHandler(client, level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)


# Import task modules so Celery registers them on app startup.
from . import (  # noqa: E402, F401
    report_basic,
    report_chained,
    report_fanout,
    report_stepped,
)
