"""Deterministic flexible-meal identity and wake-relative timing preferences.

Saved clock times are retained as preferences. They never create appointments.
Standard meals have broad wake-relative plausibility bounds, while custom meals
can use the whole awake interval. Actual availability and travel stay in CP-SAT.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5


def identified_meals(meals):
    """Supply stable identities on reads; callers may persist them on editing."""
    result, name_counts = [], {}
    for meal in meals:
        if not meal.get("id"):
            name = meal["name"].strip().casefold()
            ordinal = name_counts.get(name, 0)
            name_counts[name] = ordinal + 1
            meal = {**meal, "id": str(uuid5(NAMESPACE_URL, f"daycraft:legacy-meal:{name}:{ordinal}"))}
        result.append(dict(meal))
    return result


def meal_requirements(settings, preserved):
    """Match each enabled definition to at most one preserved meal record.

    Configured IDs win. Older definitions receive a stable derived ID from their
    normalized name and duplicate ordinal, independent from duration, preferred
    time, venue, or enabled state. Existing no-ID records still match by title.
    Confirmed/started meals retain historical durations; never rewrite them.
    """
    saved = [block for block in preserved if block.get("kind") == "meal"]
    used, result = set(), []
    for index, meal in enumerate(identified_meals(settings.get("meals", []))):
        if not meal.get("enabled", True):
            continue
        match = next((i for i, block in enumerate(saved) if i not in used and
                      ((meal.get("id") and block.get("meal_id") == meal["id"])
                       or (not block.get("meal_id") and block.get("title") == meal["name"]))), None)
        if match is not None:
            used.add(match)
        result.append({"definition": meal, "index": index,
                       "preserved": saved[match] if match is not None else None})
    return result


def meal_timing(meal, index, count, awake_start, awake_end):
    """Return a preferred center and very broad sensible placement boundaries.

Only exact standard names infer meal type; descriptions never invent a venue,
completion, or a compulsory clock time. Night-shift profiles follow awake hours.
"""
    span = max(0, awake_end - awake_start)
    name = meal["name"].strip().casefold()
    ratio = {"breakfast": .035, "lunch": .33, "dinner": .70}.get(name, (index + 1) / (count + 1))
    earliest, latest = awake_start, awake_end
    if name == "breakfast":
        latest = min(awake_end, awake_start + round(min(300, span * .45)))
    elif name == "lunch":
        earliest = awake_start + round(min(180, span * .20))
        latest = awake_start + round(span * .78)
    elif name == "dinner":
        earliest = awake_start + round(span * .45)
    preferred = awake_start + (min(30, span * ratio) if name == "breakfast" else span * ratio)
    return round(preferred), earliest, latest


def validate_required_meals(blocks, requirements):
    """Generation-only essential-meal audit, independent from solver variables."""
    errors = []
    matched = meal_requirements({"meals": [item["definition"] for item in requirements]}, blocks)
    for item, original in zip(matched, requirements, strict=True):
        meal, block = item["definition"], item["preserved"]
        if block is None:
            errors.append(f"Required meal {meal['name']} is missing. Adjust its duration or the day's commitments.")
        elif original["preserved"] is None:
            start = datetime.fromisoformat(block["start"].replace("Z", "+00:00")).astimezone(timezone.utc)
            end = datetime.fromisoformat(block["end"].replace("Z", "+00:00")).astimezone(timezone.utc)
            if round((end - start).total_seconds() / 60) != int(meal["duration_minutes"]):
                errors.append(f"Required meal {meal['name']} does not retain its configured duration.")
            if meal.get("location_id") and block.get("resolved_location_id", block.get("location_id")) != meal["location_id"]:
                errors.append(f"Required meal {meal['name']} does not retain its configured venue.")
    errors.extend(validate_meal_order(blocks, requirements))
    return errors


def validate_meal_order(blocks, requirements):
    """Audit configured enabled order independently of CP-SAT and display order.

    Match by stable identity just as generation does. Missing definitions are
    audited separately; the records that do exist must still respect the
    transitive order, including locked and completed historical meals.
    """
    matched = meal_requirements({"meals": [item["definition"] for item in requirements]}, blocks)
    present = [item for item in matched if item["preserved"] is not None]
    errors = []
    for left, right in zip(present, present[1:]):
        try:
            end = datetime.fromisoformat(left["preserved"]["end"].replace("Z", "+00:00")).astimezone(timezone.utc)
            start = datetime.fromisoformat(right["preserved"]["start"].replace("Z", "+00:00")).astimezone(timezone.utc)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue  # The ordinary block validator reports invalid timestamps.
        if end > start:
            errors.append(
                f"Configured meal order requires {left['definition']['name']} to finish before "
                f"{right['definition']['name']} starts. Review the meal order in Preferences or adjust "
                "editable meal durations or commitments; locked and completed meals are preserved."
            )
    return errors
