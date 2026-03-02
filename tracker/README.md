# Tracker

Lightweight, framework-agnostic Celery task tracking library. State is **derived** from Celery's own result backend at query time — no mutation, no signals, no Django ORM required.

## Architecture

Tracker stores a minimal registration snapshot in Redis when a task is dispatched, then merges it with live Celery state on every read. The result backend is the single source of truth; tracker never writes state transitions itself.

```
dispatch ──► track() ──► save snapshot to Redis
                             │
query ──► state() ──► load snapshot + poll AsyncResult/GroupResult ──► derive TrackerState
```

## Public API

The top-level `tracker` module exposes five symbols:

```python
import tracker

tracker.track(target, *, title=None, backend=None)  # register a tracker
tracker.state(tracker_id)                            # query derived state
tracker.step(title)                                  # track a named step (context manager / decorator)
tracker.configure(backend)                           # set the default backend explicitly
tracker.RedisTrackerBackend                          # built-in Redis backend
```

## Tracking a task

`track()` accepts either an undispatched **Signature** or an already-dispatched **AsyncResult** / **GroupResult**.

### Signature (preferred)

When given a `Signature` (including `group`, `chain`, `chord`, …), `track()` will:

1. Generate a tracker ID (UUID).
2. **Stamp** every leaf task in the canvas with a `tracker_id` header via `TrackerStampingVisitor`.
3. Dispatch the signature with `apply_async()`.
4. Persist a `TrackerState` snapshot to the backend.

```python
from celery import shared_task
import tracker

@shared_task
def add(x, y):
    return x + y

result = tracker.track(add.s(2, 3), title="Quick addition")
result.get()  # normal Celery result, track() is a pass-through
```

### Already-dispatched result

When given an `AsyncResult` or `GroupResult` the tracker is saved but **no stamping occurs** (the tasks are already in flight, so `tracker.step()` won't work inside them).

```python
result = add.delay(2, 3)
tracker.track(result, title="Late-tracked addition")
```

### Groups and complex canvases

Groups, chains, and chords all work. For groups, child task states are discovered automatically from `GroupResult.results`:

```python
from celery import group
import tracker

result = tracker.track(
    group(add.s(i, i) for i in range(10)),
    title="Parallel additions",
)
```

## Querying state

`tracker.state(tracker_id)` returns a `TrackerState` with live data merged from Celery:

```python
s = tracker.state(result.id)
s.state              # "STARTED", "SUCCESS", "FAILURE", etc.
s.tasks              # dict[str, ExecutionState] — child task states (for groups)
s.progress_completed # count of terminal tasks
s.progress_target    # total task count
s.steps              # list[ExecutionState] — named steps recorded inside the task
s.info               # TrackerResult with .result / .error
```

### State reduction

For groups, the parent state is **reduced** from child states:

| Condition | Reduced state |
|---|---|
| At least one child is `FAILURE` | `FAILURE` |
| At least one child is `STARTED` or `RETRY` | `STARTED` |
| All children are `SUCCESS` or `REVOKED` | `SUCCESS` |
| Otherwise | `PENDING` |

## Steps

`tracker.step()` tracks named stages within a task. It works as a **context manager** or a **decorator** and requires the task to have been dispatched via `tracker.track(signature)` (so the `tracker_id` stamp is available on the worker).

### Context manager

```python
@shared_task
def etl_pipeline():
    with tracker.step("Extract"):
        data = extract()
    with tracker.step("Transform"):
        data = transform(data)
    with tracker.step("Load"):
        load(data)

tracker.track(etl_pipeline.s(), title="ETL run")
```

### Decorator

```python
@shared_task
@tracker.step("Process")
def process_item(item_id):
    do_work(item_id)
```

Steps are persisted to the backend as `ExecutionState` entries (with their own `state`, `started_on`, `completed_on`, and `info` on failure) and appear in `TrackerState.steps` on query.

## Revocation

`TrackerService.revoke_tracked_tasks(tracker_id)` revokes all Celery tasks associated with a tracker (individual task or all group members) via Celery's native `revoke(terminate=True)`. The revoked state will be reflected on the next query through normal state derivation.

## Backend configuration

### Automatic (from Celery config)

If the Celery app's `result_backend` is a `redis://` or `rediss://` URL, a `RedisTrackerBackend` is created automatically on first use.

### Explicit

```python
from redis import StrictRedis
import tracker

client = StrictRedis.from_url("redis://localhost:6379/0")
tracker.configure(tracker.RedisTrackerBackend(client))
```

### Custom backend

Subclass `tracker.TrackerBackend` and implement `save`, `load`, `list_all`, `add_step`, `update_step`, and `get_steps`.

## Django Ninja API

The `tracker.api` module provides a Django Ninja `Router` with endpoints compatible with the `celery_task_tracking` app interface:

| Method | Route | Status |
|---|---|---|
| `GET` | `/tracked-tasks` | ✅ Supported |
| `GET` | `/tracked-tasks/{tracker_id}` | ✅ Supported |
| `GET` | `/tracked-tasks/by-celery-id/{celery_task_id}` | ✅ Supported |
| `POST` | `/tracked-tasks/{tracker_id}/cancel` | ✅ Supported |
| `GET` | `/tracked-tasks/{tracker_id}/children` | 501 — Not yet implemented |
| `GET` | `/tracked-tasks/stats/by-type` | 501 — Not yet implemented |
| `GET` | `/tracked-tasks/stats/recent` | 501 — Not yet implemented |

Mount the router in your Django project:

```python
from ninja import NinjaAPI
from tracker.api import router

api = NinjaAPI()
api.add_router("/tracker/", router)
```

Response schemas translate Celery states to lowercase domain statuses (`pending`, `running`, `completed`, `failed`, `cancelled`, `retrying`) for frontend compatibility.

## Models

```python
class TrackerResult(BaseModel):
    result: Any = None
    error: Any = None

class ExecutionState(BaseModel):
    title: str | None = None
    state: CeleryTaskState = "PENDING"
    info: TrackerResult | None = None
    created_on: datetime
    started_on: datetime | None = None
    completed_on: datetime | None = None

class TrackerState(ExecutionState):
    id: str
    result_type: "task" | "group"
    retries: int = 0
    retryable: bool = True
    progress_completed: float | None = None
    progress_target: float | None = None
    tasks: dict[str, ExecutionState] = {}
    steps: list[ExecutionState] = []
```

## Module structure

```
tracker/
├── __init__.py       # Public API re-exports
├── track.py          # track() and state() — dispatch and query entry points
├── step.py           # step — context manager / decorator for named stages
├── service.py        # TrackerService — list, get (with Celery merge), revoke
├── backend.py        # TrackerBackend ABC, RedisTrackerBackend, configuration
├── models.py         # Pydantic models (TrackerState, ExecutionState, TrackerResult)
├── stamping.py       # TrackerStampingVisitor — stamps canvas with tracker_id
└── api.py            # Django Ninja router with celery_task_tracking-compatible endpoints
```

## Requirements

- Python ≥ 3.11
- Celery ≥ 5.6 (uses the stamping / `StampingVisitor` API)
- Redis (for the built-in backend)
- Tasks **must** return serializable values (tracker reads `AsyncResult.info`)