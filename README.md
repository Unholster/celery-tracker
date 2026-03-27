# celery-tracker

Track groups of Celery tasks under a single umbrella ID — without introspecting canvases.

`celery-tracker` gives you a lightweight context manager that stamps every task dispatched inside it with a shared tracker ID. A global signal handler picks up those stamps on both the client and worker side, building an incrementally-updated set of member tasks per tracker. Query the tracker at any time to get an aggregate state, per-task breakdown, and optional step-level progress.

## Features

- **Zero canvas introspection** — works with `delay()`, `apply_async()`, chains, chords, and groups out of the box.
- **Automatic stamp propagation** — Celery's built-in stamp mechanism carries the tracker ID through callbacks and errbacks.
- **Step tracking** — report fine-grained progress within a single task using `tracker.step()`.
- **Pluggable backends** — ships with `RedisTrackerBackend` (default) and `DjangoTrackerBackend` (ORM-based).
- **Django Ninja API** — drop-in router for listing, inspecting, and cancelling tracked work.

## Quick Start

### Install

```
pip install celery-tracker
```

Or, with [uv](https://docs.astral.sh/uv/):

```
uv add celery-tracker
```

### Basic usage

Wrap any block of Celery dispatches in `tracker.track()`:

```python
import tracker

with tracker.track("Nightly ETL") as t:
    extract.delay()
    transform.delay()
    load.delay()

print(t.tracker_id)  # single UUID covering all three tasks
```

Every `.delay()` or `.apply_async()` call inside the `with` block is stamped automatically. Later, retrieve the live aggregate state:

```python
state = tracker.state(t.tracker_id)

print(state.state)               # "STARTED", "SUCCESS", "FAILURE", …
print(state.progress_completed)  # 2.0
print(state.progress_target)     # 3.0
print(state.tasks)               # per-task ExecutionState keyed by task ID
```

### Step tracking

Inside a Celery task, break work into named steps:

```python
import tracker

@app.task
def generate_report():
    with tracker.step("Fetch data"):
        fetch()
    with tracker.step("Transform"):
        transform()
    with tracker.step("Render PDF"):
        render()
```

Steps appear in the tracker's `steps` list in real time, each with its own state and timing.

`tracker.step` also works as a decorator:

```python
@app.task
@tracker.step("Process")
def my_task():
    process()
```

## Django Integration

### 1. Configure the backend

The simplest setup auto-resolves a `RedisTrackerBackend` from your existing Celery `result_backend` — no extra configuration needed:

```python
# settings.py
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
```

For explicit control, call `tracker.configure()` in your app's `ready()` method or Celery init:

```python
from redis import StrictRedis
from tracker import configure, RedisTrackerBackend

client = StrictRedis.from_url("redis://localhost:6379/0")
configure(RedisTrackerBackend(client))
```

To use the Django ORM backend instead (requires a `TrackedTask` and `TrackedTaskStep` model):

```python
from tracker import configure, DjangoTrackerBackend
from myapp.models import TrackedTask, TrackedTaskStep

configure(DjangoTrackerBackend(
    task_model=TrackedTask,
    step_model=TrackedTaskStep,
))
```

### 2. Mount the API

`celery-tracker` ships a Django Ninja `Router` you can mount on any `NinjaAPI` instance:

```python
# urls.py
from ninja import NinjaAPI
from tracker.api import router as tracker_router

api = NinjaAPI()
api.add_router("/", tracker_router)

urlpatterns = [
    path("api/tracker/", api.urls),
]
```

This exposes:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/tracked-tasks` | List all trackers |
| `GET` | `/tracked-tasks/{id}` | Tracker detail with live Celery state |
| `GET` | `/tracked-tasks/by-celery-id/{id}` | Look up tracker by tracker id or member Celery task id |
| `POST` | `/tracked-tasks/{id}/cancel` | Revoke all member tasks |
| `GET` | `/celery-tasks` | List registered Celery task types |
| `POST` | `/celery-tasks/{name}/run` | Dispatch a task by name and track it |

## Running the Demo

The repository includes a full demo with a Django backend, Celery worker, and React frontend.

### Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose

### Launch

From the repository root:

```sh
cd demo
docker compose up -d
```

This starts four services:

| Service | Port | Description |
|---------|------|-------------|
| **django** | [localhost:8000](http://localhost:8000) | Django dev server with the tracker API |
| **worker** | — | Celery worker processing tasks |
| **frontend** | [localhost:5173](http://localhost:5173) | React UI for dispatching and monitoring tasks |
| **redis** | 6379 | Broker and result backend |

Once everything is up:

1. Open **http://localhost:5173** in your browser.
2. Pick a task from the list (basic, stepped, chained, or fan-out).
3. Click **Run** and watch progress update in real time.

### Tear down

```sh
docker compose down
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Your Code                                      │
│                                                 │
│  with tracker.track("My Job") as t:             │
│      task_a.delay()  ──► stamped with tracker_id│
│      task_b.delay()  ──► stamped with tracker_id│
└──────────────────┬──────────────────────────────┘
                   │
       ┌───────────▼───────────┐
       │  before_task_publish  │  (signal handler)
       │  register member IDs  │
       └───────────┬───────────┘
                   │
       ┌───────────▼───────────┐
       │   TrackerBackend      │
       │   (Redis or Django)   │
       │                       │
       │  • tracker state      │
       │  • member task IDs    │
       │  • step progress      │
       └───────────┬───────────┘
                   │
       ┌───────────▼───────────┐
       │   tracker.state(id)   │  (query anytime)
       │   or GET /tracked-tasks/id │
       └──────────────────────-┘
```

## License

See [LICENSE](LICENSE) for details.