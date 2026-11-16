"""Bridge the authoritative calendar into the existing CP-SAT fixed intervals.

Definitions contain context, not occupied time. Only supplied occurrences reserve
time. This adapter does not infer preparation tasks or interpret descriptions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date as Date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def _instant(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Calendar occurrence times must include a timezone offset")
    if parsed.second or parsed.microsecond or parsed.minute % 5:
        raise ValueError("Calendar occurrence times must use exact five-minute intervals")
    return parsed.astimezone(UTC)


def fixed_blocks_for_day(date: str, settings: dict, activities: list[dict],
                         occurrences: list[dict]) -> list[dict]:
    """Join dated occurrences with typed activity context and clip to a local day.

    Local midnight boundaries are converted to UTC before intersection, so a DST
    transition day has its actual 23/25-hour length. Clipped overnight events still
    enter the solver; its existing waking-hours validator reports any conflict.
    Stable IDs allow regeneration to preserve started work without duplicating it.
    """
    day = Date.fromisoformat(date)
    zone = ZoneInfo(settings.get("timezone", "America/Toronto"))
    start_of_day = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end_of_day = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    activity_by_id = {item["id"]: item for item in activities}
    result, seen = [], {}
    for occurrence in occurrences:
        start, end = _instant(occurrence["start"]), _instant(occurrence["end"])
        if end <= start:
            raise ValueError("Calendar occurrence end must follow its start")
        if end <= start_of_day or start >= end_of_day:
            continue
        activity = activity_by_id.get(occurrence["activity_id"])
        if activity is None:
            raise ValueError(f"Calendar occurrence references a missing activity: {occurrence['activity_id']}")
        occurrence_id = occurrence["id"]
        identity = (occurrence["activity_id"], start, end)
        if occurrence_id in seen:
            if seen[occurrence_id] != identity:
                raise ValueError(f"Conflicting calendar occurrences share an ID: {occurrence_id}")
            continue
        seen[occurrence_id] = identity
        category = activity["category"]
        location = occurrence.get("location_override") or activity
        location_mode = location.get("location_mode") or ("required" if location.get("location_id") else "unspecified")
        result.append({
            "id": f"calendar:{occurrence_id}:{date}",
            "title": activity["title"],
            "kind": "class",
            "start": max(start, start_of_day).astimezone(zone).isoformat(),
            "end": min(end, end_of_day).astimezone(zone).isoformat(),
            "location_id": location.get("location_id"),
            "location_mode": location_mode,
            "allow_alternative_locations": location.get("allow_alternative_locations", False),
            "alternative_location_ids": list(location.get("alternative_location_ids", [])),
            **{key: deepcopy(location[key]) for key in ("location_requirements", "location_suitability") if key in location},
            "location_override": bool(occurrence.get("location_override")),
            "task_id": None,
            "class_id": f"occurrence:{occurrence_id}",
            "locked": True,
            "status": "todo",
            "rationale": f"Fixed {category}; its calendar time cannot move during optimization. Edit it in Classes, Commitments & Assessments.",
            "estimated": False,
            "activity_id": activity["id"],
            "occurrence_id": occurrence_id,
            "category": category,
            "subtype": activity.get("subtype"),
            "description": activity.get("description", ""),
            "related_entity": deepcopy(activity.get("related_entity")),
            "related_entity_context": deepcopy(activity.get("related_entity_context")),
            "course": activity.get("course"),
            "building": activity.get("building", ""),
            "room": location.get("room", ""),
            "actual_start": start.astimezone(zone).isoformat(),
            "actual_end": end.astimezone(zone).isoformat(),
            "calendar_source": occurrence.get("source", "manual"),
        })
    result.sort(key=lambda block: (_instant(block["start"]), block["id"]))
    return result
