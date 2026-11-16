"""Conservative contextual cues and independently tunable workload profiles."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.app.planning_intelligence import interpret_task_context, workload_profile


NOW = datetime(2026, 11, 12, 8, tzinfo=ZoneInfo("America/Toronto"))


def test_profiles_are_independent_soft_preferences_and_return_fresh_values():
    profiles = [workload_profile(level) for level in ("very_low", "low", "medium", "high", "very_high")]
    assert [item["preferred_utilization_ratio"] for item in profiles] == [.2, .4, .6, .8, .95]
    assert profiles[0]["opportunity_cost"] > profiles[-1]["opportunity_cost"]
    assert profiles[0]["fatigue_penalty"] > profiles[-1]["fatigue_penalty"]
    assert all("mode" not in item and "work_end" not in item for item in profiles)
    profiles[0]["opportunity_cost"] = -1
    assert workload_profile("very_low")["opportunity_cost"] == 450
    assert workload_profile("unknown")["level"] == "medium"


@pytest.mark.parametrize("fields,modality,preference", [
    ({"title": "Prove theorem"}, "focus", "longer"),
    ({"description": "Read and derive the result"}, "focus", "longer"),
    ({"academic_subtype": "assessment_preparation"}, "focus", "longer"),
    ({"task_type": "administrative", "title": "Email registration form"}, "administrative", "shorter"),
    ({"title": "Gym workout"}, "physical", "neutral"),
    ({"title": "Write gym membership comparison"}, "focus", "longer"),
])
def test_named_description_category_and_subtype_cues_are_explained(fields, modality, preference):
    original = deepcopy(fields)
    result = interpret_task_context(fields, NOW)
    assert result["modality"] == modality
    assert result["focus_preference"] == preference
    assert result["evidence"] and result["rationale"]
    assert fields == original
    assert all(field not in result for field in ("due_at", "location_id", "completed", "dependencies"))


def test_difficulty_changes_demand_without_priority_and_negated_or_quoted_dates_are_not_facts():
    task = {"title": "Read", "description": "Deadline tomorrow at PAC; not completed", "difficulty": 2}
    low = interpret_task_context(task, NOW)
    high = interpret_task_context({**task, "difficulty": 9}, NOW)
    assert high["cognitive_demand"] > low["cognitive_demand"]
    assert high["context_bonus"] == low["context_bonus"] == 0
    assert "deadline_at" not in high and "location_id" not in high


def test_explicit_class_link_supports_continuity_without_granting_completion():
    task = {"title": "Study MATH145", "related_activity": {"id": "class", "category": "class", "occurrences": [
        {"start": "2026-11-12T09:00:00-05:00", "end": "2026-11-12T10:00:00-05:00"}]}}
    result = interpret_task_context(task, NOW)
    assert result["context_bonus"] == 10
    assert "separate study" in " ".join(result["rationale"])
    assert "completed_minutes" not in result


def test_long_linked_commitment_changes_recovery_preference_without_creating_work():
    task = {"title": "Coding", "difficulty": 8, "related_activity": {"category": "commitment", "occurrences": [
        {"start": "2026-11-12T09:00:00-05:00", "end": "2026-11-12T12:00:00-05:00"}]}}
    result = interpret_task_context(task, NOW)
    assert result["focus_preference"] == "recovery"
    assert result["context_bonus"] == 0
    assert "duration_minutes" not in result


def test_project_context_is_evidenced_without_inheriting_dates_or_venue():
    task = {"title": "Study", "project": {"description": "Deadline tomorrow; use laboratory", "importance": 9, "status": "active"}}
    result = interpret_task_context(task, NOW)
    assert any(item["field"] == "project.description" for item in result["evidence"])
    assert "deadline_at" not in result and "location_id" not in result


def test_project_description_can_suggest_focus_only_for_ambiguous_task():
    context = {"project": {"description": "Programming and analysis"}, "title": "Continue"}
    assert interpret_task_context(context, NOW)["focus_preference"] == "longer"
    assert interpret_task_context({**context, "title": "Email invoice"}, NOW)["focus_preference"] == "shorter"
