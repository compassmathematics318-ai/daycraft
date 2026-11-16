"""Pure daily work-block accounting shared by planning and confirmation APIs."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _daily_policies(tasks):
    """Logical sessions share the reusable task's daily block policy."""
    return {task.get("task_definition_id") or task["id"]: task for task in tasks or []}


def daily_session_progress(blocks, tasks, settings):
    """Count saved work chunks on local dates without treating them as credit.

    Completed chunks still consume a daily slot. Skipped chunks do not. Logical
    session IDs never create independent allowances for one reusable task.
    """
    tz = ZoneInfo(settings.get("timezone", "America/Toronto"))
    task_map = {task["id"]: task for task in tasks or []}
    policies = _daily_policies(tasks)
    counts = {}
    for block in blocks:
        if block.get("kind") not in {"task", "project"} or block.get("status") == "skipped":
            continue
        task = task_map.get(block.get("task_id"), {})
        definition_id = block.get("task_definition_id") or task.get("task_definition_id") or block.get("task_id")
        if definition_id not in policies:
            continue
        try:
            start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
                if start.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != start.replace(tzinfo=None):
                    continue  # Match the planner's rejection of nonexistent local times.
            date = start.astimezone(tz).date().isoformat()
        except (ValueError, KeyError, TypeError):
            continue  # The ordinary time validator reports malformed blocks.
        key = (definition_id, date)
        counts[key] = counts.get(key, 0) + 1
    return [{"task_definition_id": definition_id, "title": policies[definition_id]["title"],
             "date": date, "minimum_sessions": policies[definition_id].get("min_sessions_per_day", 1),
             "maximum_sessions": policies[definition_id].get("max_sessions_per_day"),
             "scheduled_sessions": count,
             "expected_shortfall": max(0, policies[definition_id].get("min_sessions_per_day", 1) - count)}
            for (definition_id, date), count in sorted(counts.items())]
