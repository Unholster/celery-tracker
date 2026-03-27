from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from conftest import TASK_ID, TRACKER_ID, InMemoryTrackerBackend

from tracker.models import ExecutionState, TrackerState
from tracker.backend import TrackerNotFoundError
from tracker.service import TrackerService, primary_member_celery_task_id
from tracker.signals import _on_task_publish
from tracker.stamping import TRACKER_ID_HEADER
from tracker.step import step
from tracker.track import TrackingContext, track

# ---------------------------------------------------------------------------
# step as context manager
# ---------------------------------------------------------------------------


class TestStepContextManager:
    def test_success(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with step("Fetch data"):
            pass

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 1
        assert steps[0].title == "Fetch data"
        assert steps[0].state == "SUCCESS"
        assert steps[0].started_on is not None
        assert steps[0].completed_on is not None
        assert steps[0].completed_on >= steps[0].started_on

    def test_failure_records_error(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with pytest.raises(ValueError, match="boom"):
            with step("Validate"):
                raise ValueError("boom")

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 1
        assert steps[0].title == "Validate"
        assert steps[0].state == "FAILURE"
        assert steps[0].info is not None
        assert "boom" in steps[0].info.error
        assert steps[0].completed_on is not None

    def test_exception_propagates(self, fake_task_context):
        with pytest.raises(RuntimeError, match="not swallowed"):
            with step("Risky"):
                raise RuntimeError("not swallowed")

    def test_body_return_value_accessible(self, fake_task_context):
        """The context manager doesn't interfere with control flow."""
        result = None
        with step("Compute"):
            result = 1 + 1

        assert result == 2

    def test_multiple_sequential_steps(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with step("Step A"):
            pass
        with step("Step B"):
            pass
        with step("Step C"):
            pass

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 3
        assert [s.title for s in steps] == ["Step A", "Step B", "Step C"]
        assert all(s.state == "SUCCESS" for s in steps)

    def test_step_started_state_persisted_during_body(self, fake_task_context):
        """While the body is running the step should already be STARTED."""
        backend: InMemoryTrackerBackend = fake_task_context["backend"]
        observed_state: str | None = None

        with step("In-flight"):
            observed_state = backend.get_steps(TRACKER_ID)[0].state

        assert observed_state == "STARTED"

    def test_timestamps_ordered(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with step("Timed"):
            pass

        s = backend.get_steps(TRACKER_ID)[0]
        assert s.started_on is not None
        assert s.completed_on is not None
        assert s.started_on <= s.completed_on

    def test_failure_after_success_keeps_both(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with step("Good"):
            pass

        with pytest.raises(ZeroDivisionError):
            with step("Bad"):
                1 / 0

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 2
        assert steps[0].state == "SUCCESS"
        assert steps[1].state == "FAILURE"


# ---------------------------------------------------------------------------
# step as decorator
# ---------------------------------------------------------------------------


class TestStepDecorator:
    def test_success(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        @step("Process")
        def do_work():
            return 42

        result = do_work()

        assert result == 42
        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 1
        assert steps[0].title == "Process"
        assert steps[0].state == "SUCCESS"

    def test_failure(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        @step("Explode")
        def blow_up():
            raise TypeError("kaboom")

        with pytest.raises(TypeError, match="kaboom"):
            blow_up()

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 1
        assert steps[0].state == "FAILURE"

    def test_preserves_function_metadata(self, fake_task_context):
        @step("Named")
        def my_function():
            """Docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "Docstring."

    def test_passes_arguments_through(self, fake_task_context):
        @step("Add")
        def add(a, b, *, extra=0):
            return a + b + extra

        assert add(1, 2, extra=10) == 13

    def test_decorator_creates_fresh_step_per_call(self, fake_task_context):
        """Each invocation must create an independent step instance."""
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        @step("Reusable")
        def repeatable():
            pass

        repeatable()
        repeatable()

        steps = backend.get_steps(TRACKER_ID)
        assert len(steps) == 2
        assert all(s.title == "Reusable" and s.state == "SUCCESS" for s in steps)


# ---------------------------------------------------------------------------
# Noop / graceful degradation
# ---------------------------------------------------------------------------


class TestStepNoop:
    def test_noop_outside_celery_task(self, backend):
        """step should silently skip when there is no current Celery task."""
        with patch("tracker.step.current_task", None):
            with step("Ghost"):
                result = "still runs"

        assert result == "still runs"
        assert backend.get_steps(TRACKER_ID) == []

    def test_noop_when_task_request_id_is_none(self, backend):
        mock_task = MagicMock()
        mock_task.request.id = None

        with patch("tracker.step.current_task", mock_task):
            with step("No ID"):
                pass

        assert backend.get_steps(TRACKER_ID) == []

    def test_noop_when_no_tracker_id_stamp(self, backend):
        """Task exists but was not stamped with a tracker_id — step is skipped."""
        mock_task = MagicMock()
        mock_task.request.id = "unstamped-task"
        mock_task.request.stamps = {}
        mock_task.request.tracker_id = None

        with patch("tracker.step.current_task", mock_task):
            with step("Orphan"):
                pass

        assert backend._steps == {}

    def test_noop_decorator_still_runs_function(self, backend):
        with patch("tracker.step.current_task", None):

            @step("Invisible")
            def compute():
                return 99

            assert compute() == 99


# ---------------------------------------------------------------------------
# TrackerService.get_tracker includes steps
# ---------------------------------------------------------------------------


class TestGetTrackerStateWithSteps:
    def test_steps_attached_to_tracker_state(self, fake_task_context):
        backend: InMemoryTrackerBackend = fake_task_context["backend"]

        with step("Alpha"):
            pass
        with step("Beta"):
            pass

        service = TrackerService(backend)
        state = service.get_tracker(TRACKER_ID)
        assert len(state.steps) == 2
        assert state.steps[0].title == "Alpha"
        assert state.steps[1].title == "Beta"

    def test_tracker_state_with_no_steps(self, backend):
        backend.save(TrackerState(id="empty-tracker"))
        service = TrackerService(backend)
        state = service.get_tracker("empty-tracker")
        assert state.steps == []


# ---------------------------------------------------------------------------
# Signal-based member registration
# ---------------------------------------------------------------------------


class TestSignalMemberRegistration:
    """Verify the before_task_publish signal handler registers members."""

    def test_stamped_task_is_registered(self, backend):
        """A published task with a tracker_id stamp is added as a member."""
        backend.save(TrackerState(id="trk-1"))

        headers = {
            "id": "task-aaa",
            "stamps": {TRACKER_ID_HEADER: "trk-1"},
            "stamped_headers": [TRACKER_ID_HEADER],
        }
        _on_task_publish(sender="my_app.tasks.do_work", headers=headers)

        assert "task-aaa" in backend.get_members("trk-1")

    def test_unstamped_task_is_ignored(self, backend):
        """A published task without a tracker_id stamp is not registered."""
        backend.save(TrackerState(id="trk-2"))

        headers = {"id": "task-bbb"}
        _on_task_publish(sender="my_app.tasks.other", headers=headers)

        assert backend.get_members("trk-2") == []

    def test_multiple_tasks_registered_under_same_tracker(self, backend):
        """Several tasks stamped with the same tracker_id all appear as members."""
        backend.save(TrackerState(id="trk-3"))

        for task_id in ("t1", "t2", "t3"):
            headers = {
                "id": task_id,
                "stamps": {TRACKER_ID_HEADER: "trk-3"},
                "stamped_headers": [TRACKER_ID_HEADER],
            }
            _on_task_publish(sender="some.task", headers=headers)

        members = backend.get_members("trk-3")
        assert sorted(members) == ["t1", "t2", "t3"]

    def test_duplicate_publish_is_idempotent(self, backend):
        """Publishing the same task ID twice does not create duplicates."""
        backend.save(TrackerState(id="trk-4"))

        headers = {
            "id": "task-dup",
            "stamps": {TRACKER_ID_HEADER: "trk-4"},
            "stamped_headers": [TRACKER_ID_HEADER],
        }
        _on_task_publish(sender="task", headers=headers)
        _on_task_publish(sender="task", headers=headers)

        assert backend.get_members("trk-4") == ["task-dup"]

    def test_list_wrapped_tracker_id(self, backend):
        """Celery may wrap propagated stamps in a list — handler normalises."""
        backend.save(TrackerState(id="trk-5"))

        headers = {
            "id": "task-list",
            "stamps": {TRACKER_ID_HEADER: ["trk-5"]},
            "stamped_headers": [TRACKER_ID_HEADER],
        }
        _on_task_publish(sender="task", headers=headers)

        assert "task-list" in backend.get_members("trk-5")

    def test_missing_task_id_is_ignored(self, backend):
        """If the headers have no 'id' the handler silently skips."""
        backend.save(TrackerState(id="trk-6"))

        headers = {
            "stamps": {TRACKER_ID_HEADER: "trk-6"},
            "stamped_headers": [TRACKER_ID_HEADER],
        }
        _on_task_publish(sender="task", headers=headers)

        assert backend.get_members("trk-6") == []

    def test_backend_error_does_not_propagate(self, backend):
        """If the backend raises, the signal handler catches and logs."""
        headers = {
            "id": "task-err",
            "stamps": {TRACKER_ID_HEADER: "no-such-tracker"},
            "stamped_headers": [TRACKER_ID_HEADER],
        }
        # Should not raise even though the tracker doesn't exist
        _on_task_publish(sender="task", headers=headers)

    def test_stamp_in_stamps_dict_is_registered(self, backend):
        """Worker-published tasks carry tracker_id inside headers['stamps']."""
        backend.save(TrackerState(id="trk-stamps"))

        headers = {
            "id": "task-worker",
            "stamped_headers": [TRACKER_ID_HEADER],
            "stamps": {TRACKER_ID_HEADER: "trk-stamps"},
        }
        _on_task_publish(sender="some.chain.callback", headers=headers)

        assert "task-worker" in backend.get_members("trk-stamps")

    def test_stamp_in_stamps_dict_list_wrapped(self, backend):
        """Canvas propagation may wrap the stamp value in a list."""
        backend.save(TrackerState(id="trk-wrap"))

        headers = {
            "id": "task-wrap",
            "stamped_headers": [TRACKER_ID_HEADER],
            "stamps": {TRACKER_ID_HEADER: ["trk-wrap"]},
        }
        _on_task_publish(sender="task", headers=headers)

        assert "task-wrap" in backend.get_members("trk-wrap")


# ---------------------------------------------------------------------------
# Service with members
# ---------------------------------------------------------------------------


class TestGetTrackerWithMembers:
    """Verify get_tracker merges Celery state from registered members."""

    def test_members_appear_in_tasks_dict(self, backend):
        backend.save(TrackerState(id="trk-m"))
        backend.add_member("trk-m", "celery-task-1")
        backend.add_member("trk-m", "celery-task-2")

        def fake_async_result(tid):
            r = MagicMock()
            r.id = tid
            r.state = "SUCCESS"
            r.info = None
            return r

        with patch("tracker.service.AsyncResult", side_effect=fake_async_result):
            service = TrackerService(backend)
            state = service.get_tracker("trk-m")

        assert set(state.tasks.keys()) == {"celery-task-1", "celery-task-2"}

    def test_progress_reflects_member_states(self, backend):
        backend.save(TrackerState(id="trk-p"))
        backend.add_member("trk-p", "done-1")
        backend.add_member("trk-p", "done-2")
        backend.add_member("trk-p", "pending-1")

        def fake_async_result(tid):
            r = MagicMock()
            r.id = tid
            r.info = None
            r.state = "SUCCESS" if tid.startswith("done") else "PENDING"
            return r

        with patch("tracker.service.AsyncResult", side_effect=fake_async_result):
            service = TrackerService(backend)
            state = service.get_tracker("trk-p")

        assert state.progress_target == 3.0
        assert state.progress_completed == 2.0
        assert state.state == "PENDING"

    def test_no_members_returns_base_state(self, backend):
        backend.save(TrackerState(id="trk-empty", title="Lonely"))

        service = TrackerService(backend)
        state = service.get_tracker("trk-empty")

        assert state.tasks == {}
        assert state.title == "Lonely"
        assert state.steps == []

    def test_get_tracker_by_member_task_id(self, backend):
        backend.save(TrackerState(id="trk-m"))
        backend.add_member("trk-m", "celery-task-1")

        def fake_async_result(tid):
            r = MagicMock()
            r.id = tid
            r.state = "SUCCESS"
            r.info = None
            return r

        with patch("tracker.service.AsyncResult", side_effect=fake_async_result):
            service = TrackerService(backend)
            state = service.get_tracker("celery-task-1")

        assert state.id == "trk-m"
        assert "celery-task-1" in state.tasks

    def test_get_tracker_unknown_raises(self, backend):
        service = TrackerService(backend)
        with pytest.raises(TrackerNotFoundError):
            service.get_tracker("not-a-tracker")

    def test_member_tasks_get_title_from_async_result_name(self, backend):
        """UI subtask list uses ExecutionState.title; Celery exposes it via AsyncResult.name."""
        backend.save(TrackerState(id="trk-t"))
        backend.add_member("trk-t", "tid-1")

        def fake_async_result(tid):
            r = MagicMock()
            r.id = tid
            r.state = "SUCCESS"
            r.info = None
            r.name = "demoproject.celery.report_chained.fetch_data"
            return r

        with patch("tracker.service.AsyncResult", side_effect=fake_async_result):
            state = TrackerService(backend).get_tracker("trk-t")

        assert state.tasks["tid-1"].title == "Fetch Data"


# ---------------------------------------------------------------------------
# API detail — celery_task_id field
# ---------------------------------------------------------------------------


class TestDetailCeleryTaskId:
    """``primary_member_celery_task_id`` feeds API ``celery_task_id`` for single-task trackers."""

    def test_single_member_uses_that_task_id(self):
        state = TrackerState(
            id="trk",
            title="x",
            state="SUCCESS",
            tasks={
                "real-celery-uuid": ExecutionState(state="SUCCESS", info=None),
            },
        )
        assert primary_member_celery_task_id(state) == "real-celery-uuid"

    def test_multi_member_omits_celery_task_id(self):
        state = TrackerState(
            id="trk",
            title="x",
            state="SUCCESS",
            tasks={
                "a": ExecutionState(state="SUCCESS", info=None),
                "b": ExecutionState(state="SUCCESS", info=None),
            },
        )
        assert primary_member_celery_task_id(state) is None

    def test_zero_members_omits_celery_task_id(self):
        state = TrackerState(id="trk", title="x", state="PENDING", tasks={})
        assert primary_member_celery_task_id(state) is None


# ---------------------------------------------------------------------------
# TrackingContext — context-manager mode of track()
# ---------------------------------------------------------------------------


class TestTrackingContext:
    """Verify the ``with track("title"):`` context manager."""

    def test_returns_tracking_context_for_string(self, backend):
        ctx = track("My title")
        assert isinstance(ctx, TrackingContext)

    def test_tracker_id_available(self, backend):
        with track("Job") as t:
            assert t.tracker_id is not None
            assert isinstance(t.tracker_id, str)

    def test_tracker_state_saved_on_enter(self, backend):
        with track("Saved early") as t:
            state = backend.load(t.tracker_id)
            assert state.title == "Saved early"

    def test_stamps_injected_into_published_task(self, backend):
        """Headers of a task published inside the block get the stamp."""
        captured_headers: list[dict] = []

        def fake_handler(sender, headers, **kwargs):
            captured_headers.append(dict(headers))

        from celery.signals import before_task_publish

        # Connect an observer AFTER the context manager's handler
        headers: dict = {"id": "task-123"}
        with track("Stamp test") as t:
            before_task_publish.connect(fake_handler)
            try:
                before_task_publish.send(
                    sender="my.task",
                    headers=headers,
                )
            finally:
                before_task_publish.disconnect(fake_handler)

        # The context manager should have injected the stamp into headers['stamps']
        assert headers.get("stamps", {}).get(TRACKER_ID_HEADER) == t.tracker_id
        assert TRACKER_ID_HEADER in headers.get("stamped_headers", [])

    def test_member_registered_on_publish(self, backend):
        """Tasks published inside the block are registered as members."""
        with track("Member test") as t:
            # Simulate a task publish by calling the handler directly
            t._on_publish(
                sender="my.task",
                headers={
                    "id": "task-abc",
                    TRACKER_ID_HEADER: t.tracker_id,
                    "stamped_headers": [TRACKER_ID_HEADER],
                },
            )

        assert "task-abc" in backend.get_members(t.tracker_id)

    def test_multiple_tasks_registered(self, backend):
        """Several tasks dispatched inside one block all become members."""
        with track("Multi") as t:
            for tid in ("t1", "t2", "t3"):
                t._on_publish(
                    sender="my.task",
                    headers={"id": tid},
                )

        assert sorted(backend.get_members(t.tracker_id)) == ["t1", "t2", "t3"]

    def test_stamped_headers_none_still_registers_member(self, backend):
        """Celery can send ``stamped_headers: None``; member registration must still run."""
        with track("Celery None stamped_headers") as t:
            t._on_publish(
                sender="my.task",
                headers={"id": "task-xyz", "stamped_headers": None},
            )

        assert "task-xyz" in backend.get_members(t.tracker_id)

    def test_handler_disconnected_after_exit(self, backend):
        """The signal handler must not fire after the block exits."""
        with track("Scoped") as t:
            pass

        # Simulate a publish after the block — should NOT get stamped
        headers: dict = {"id": "late-task"}
        from celery.signals import before_task_publish

        before_task_publish.send(sender="my.task", headers=headers)

        assert TRACKER_ID_HEADER not in headers
        assert "late-task" not in backend.get_members(t.tracker_id)

    def test_does_not_stamp_other_contexts(self, backend):
        """Nested or concurrent contexts only stamp their own tasks."""
        inner_tracker_id: str = ""
        with track("Outer") as outer:
            with track("Inner") as inner:
                inner_tracker_id = inner.tracker_id
                headers_inner: dict = {"id": "inner-task"}
                inner._on_publish(sender="t", headers=headers_inner)

            headers_outer: dict = {"id": "outer-task"}
            outer._on_publish(sender="t", headers=headers_outer)

        assert "inner-task" in backend.get_members(inner_tracker_id)
        assert "outer-task" in backend.get_members(outer.tracker_id)
        assert "inner-task" not in backend.get_members(outer.tracker_id)
        assert "outer-task" not in backend.get_members(inner_tracker_id)

    def test_exception_in_body_still_cleans_up(self, backend):
        """Signal handler is disconnected even if the body raises."""
        tracker_id: str = ""
        with pytest.raises(RuntimeError, match="boom"):
            with track("Boom") as t:
                tracker_id = t.tracker_id
                raise RuntimeError("boom")

        # Tracker state was saved on enter
        assert tracker_id != ""
        assert backend.load(tracker_id).title == "Boom"

        # Handler should be disconnected — publish should not stamp
        headers: dict = {"id": "after-boom"}
        from celery.signals import before_task_publish

        before_task_publish.send(sender="my.task", headers=headers)
        assert TRACKER_ID_HEADER not in headers

    def test_explicit_backend(self, backend):
        other = InMemoryTrackerBackend()
        with track("Explicit", backend=other) as t:
            t._on_publish(sender="t", headers={"id": "x"})

        assert other.load(t.tracker_id).title == "Explicit"
        assert "x" in other.get_members(t.tracker_id)
        assert backend.get_members(t.tracker_id) == []


# ---------------------------------------------------------------------------
# InMemoryTrackerBackend members
# ---------------------------------------------------------------------------


class TestInMemoryBackendMembers:
    """Verify the in-memory backend honours the member contract."""

    def test_add_and_get_members(self, backend):
        backend.add_member("t", "a")
        backend.add_member("t", "b")
        assert sorted(backend.get_members("t")) == ["a", "b"]

    def test_add_member_is_idempotent(self, backend):
        backend.add_member("t", "a")
        backend.add_member("t", "a")
        assert backend.get_members("t") == ["a"]

    def test_get_members_empty_for_unknown_tracker(self, backend):
        assert backend.get_members("nonexistent") == []

    def test_members_isolated_between_trackers(self, backend):
        backend.add_member("t1", "a")
        backend.add_member("t2", "b")
        assert backend.get_members("t1") == ["a"]
        assert backend.get_members("t2") == ["b"]


# ---------------------------------------------------------------------------
# _extract_tracker_id
# ---------------------------------------------------------------------------


class TestExtractTrackerId:
    """Verify the helper that reads tracker_id from the Celery request."""

    def test_string_value_in_stamps(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock()
        request.stamps = {"tracker_id": "plain-string"}
        assert _extract_tracker_id(request) == "plain-string"

    def test_list_value_in_stamps(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock()
        request.stamps = {"tracker_id": ["from-list"]}
        assert _extract_tracker_id(request) == "from-list"

    def test_empty_list_returns_none(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock()
        request.stamps = {"tracker_id": []}
        assert _extract_tracker_id(request) is None

    def test_empty_stamps_returns_none(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock()
        request.stamps = {}
        assert _extract_tracker_id(request) is None

    def test_missing_stamps_attr_returns_none(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock(spec=[])
        assert _extract_tracker_id(request) is None

    def test_stamps_is_none_returns_none(self):
        from tracker.step import _extract_tracker_id

        request = MagicMock()
        request.stamps = None
        assert _extract_tracker_id(request) is None


# ---------------------------------------------------------------------------
# InMemoryTrackerBackend itself
# ---------------------------------------------------------------------------


class TestInMemoryBackendSteps:
    """Verify the in-memory backend honours the step contract."""

    def test_add_returns_incrementing_indices(self, backend):
        s0 = ExecutionState(title="s0", state="STARTED")
        s1 = ExecutionState(title="s1", state="STARTED")

        assert backend.add_step("t", s0) == 0
        assert backend.add_step("t", s1) == 1

    def test_update_replaces_at_index(self, backend):
        original = ExecutionState(title="orig", state="STARTED")
        idx = backend.add_step("t", original)

        replacement = ExecutionState(title="orig", state="SUCCESS")
        backend.update_step("t", idx, replacement)

        steps = backend.get_steps("t")
        assert steps[idx].state == "SUCCESS"

    def test_get_steps_returns_copy(self, backend):
        backend.add_step("t", ExecutionState(title="x", state="STARTED"))
        first = backend.get_steps("t")
        second = backend.get_steps("t")
        assert first is not second

    def test_get_steps_empty_for_unknown_tracker(self, backend):
        assert backend.get_steps("nonexistent") == []
