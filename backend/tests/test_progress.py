"""Daily accounting remains available without loading the optional solver runtime."""
from copy import deepcopy

from backend.app.progress import daily_session_progress


def test_shared_logical_sessions_count_chunks_on_toronto_dates_including_completed_history():
    policies = [{"id": "session:first", "task_definition_id": "d", "title": "Task",
                 "min_sessions_per_day": 3, "max_sessions_per_day": 4},
                {"id": "session:second", "task_definition_id": "d", "title": "Task",
                 "min_sessions_per_day": 3, "max_sessions_per_day": 4}]
    blocks = [{"kind": "task", "task_id": "session:first", "start": "2026-11-15T02:00:00Z", "status": "completed"},
              {"kind": "task", "task_id": "session:second", "start": "2026-11-14T22:00:00-05:00", "status": "todo"},
              {"kind": "project", "task_id": "d", "task_definition_id": "d", "start": "2026-11-15T08:00:00-05:00"},
              {"kind": "task", "task_id": "session:first", "start": "2026-11-14T23:00:00-05:00", "status": "skipped"},
              {"kind": "break", "task_id": "d", "task_definition_id": "d", "start": "2026-11-14T21:30:00-05:00"}]
    original = deepcopy((blocks, policies))
    result = daily_session_progress(blocks, policies, {"timezone": "America/Toronto"})
    assert result == [{"task_definition_id": "d", "title": "Task", "date": "2026-11-14", "minimum_sessions": 3,
                       "maximum_sessions": 4, "scheduled_sessions": 2, "expected_shortfall": 1},
                      {"task_definition_id": "d", "title": "Task", "date": "2026-11-15", "minimum_sessions": 3,
                       "maximum_sessions": 4, "scheduled_sessions": 1, "expected_shortfall": 2}]
    assert (blocks, policies) == original


def test_missing_policy_and_invalid_or_nonexistent_local_times_do_not_invent_daily_counts():
    blocks = [{"kind": "task", "task_id": "d", "start": "2026-03-08T02:30:00"},
              {"kind": "task", "task_id": "d", "start": "invalid"},
              {"kind": "task", "task_id": "d"},
              {"kind": "task", "task_id": "unrelated", "start": "2026-03-08T08:00:00"}]
    assert daily_session_progress(blocks, [{"id": "d", "title": "Task"}], {}) == []
