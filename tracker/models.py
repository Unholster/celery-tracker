import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

CeleryResultType = Literal["task", "group", "chain"]
CeleryTaskState = Literal[
    "PENDING",
    "RECEIVED",
    "STARTED",
    "SUCCESS",
    "FAILURE",
    "REVOKED",
    "REJECTED",
    "RETRY",
    "IGNORED",
]


class TrackerResult(BaseModel):
    result: Any = None
    error: Any = None

    @model_validator(mode="before")
    @classmethod
    def build(cls, celery_info: Any) -> dict:
        logger.debug(f"Serializing info: {celery_info}")
        match celery_info:
            case Exception():
                return {"error": f"{celery_info.__class__.__name__}: {celery_info}"}
            case None:
                return {"result": None, "error": None}
            case _:
                return {"result": celery_info, "error": None}


class ExecutionState(BaseModel):
    title: str | None = None
    state: CeleryTaskState = "PENDING"
    info: TrackerResult | None = None
    created_on: datetime = Field(default_factory=datetime.now)
    started_on: datetime | None = None
    completed_on: datetime | None = None


class TrackerState(ExecutionState):
    id: str
    result_type: CeleryResultType = "task"
    retries: int = 0
    retryable: bool = True
    progress_completed: float | None = None
    progress_target: float | None = None
    tasks: dict[str, ExecutionState] = {}
    steps: list[ExecutionState] = []
