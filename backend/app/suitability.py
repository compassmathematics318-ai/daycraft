"""Conservative local requirement inference and evidence-backed venue choices.

Place names, geocoder results and proximity are never evidence of capabilities
or access. Only explicit user confirmations populate those facts.
"""
import re

INTELLIGENCE_VERSION = 1

CAPABILITIES = (
    "fitness_training", "quiet_workspace", "desk", "wifi", "computer", "printer",
    "weights", "cardio_equipment", "swimming_pool", "outdoor_space", "kitchen",
    "music_practice_space", "collaboration_space", "laboratory", "workshop",
)


def infer_requirements(value):
    explicit = value.get("location_requirements", [])
    if explicit:
        return list(explicit), "explicit", "User declared the complete activity requirements."
    text = " ".join(str(value.get(key) or "") for key in ("title", "description", "notes", "academic_subtype", "class_type", "subtype")).casefold()
    project = value.get("project") or {}
    context = " ".join(str(project.get(key) or "") for key in ("title", "name", "description", "notes", "goals")).casefold()
    # Specialized, negative and unresolved conditions make a generic match unsafe.
    if re.search(r"\b(no|not|without|only|except|special|specific|accessible|accessibility|medical|rehab|therapy|lab|laboratory|workshop|equipment|microscope|microscopy|instrument|instruments|chemicals|reagents|soldering|pottery|climbing|bouldering|court|courts|treadmill|rowing|appointment|exam|lecture|tutorial|class|in.person|reservation|booking)\b", text + " " + context):
        return [], "unknown", "Specialized or conditional needs require explicit activity requirements."
    if re.search(r"\b(plan|planning|membership|research|compare|purchase|buy|write|design|review)\b", text) and re.search(r"\b(gym|workout|fitness|exercise|swim|swimming|cook|cooking)\b", text):
        return [], "unknown", "Planning or writing about an activity does not establish its physical venue needs."
    families = []
    physical_exercise = value.get("task_type") == "wellness" and re.search(r"\bexercise\b", text)
    if re.search(r"\b(gym|workout|fitness)\b", text) or physical_exercise:
        families.append(["fitness_training"])
    if re.search(r"\b(weightlifting|weights|strength training)\b", text):
        families.append(["fitness_training", "weights"])
    if re.search(r"\b(swim|swimming)\b", text):
        families.append(["swimming_pool"])
    if re.search(r"\b(study|studying|reading|read|homework|assignment|writing|revision)\b|assessment_preparation", text):
        families.append(["quiet_workspace", "desk"])
    if re.search(r"\b(print|printing)\b", text):
        families.append(["printer"])
    if re.search(r"\b(cook|cooking|meal prep|baking)\b", text):
        families.append(["kitchen"])
    if re.search(r"\b(groupwork|group work|collaboration|team meeting)\b", text):
        families.append(["collaboration_space"])
    # Multiple distinct activities could require several unmentioned constraints.
    unique = {tuple(family) for family in families}
    if len(unique) > 1 and unique != {("fitness_training",), ("fitness_training", "weights")}:
        return [], "unknown", "Multiple activity types need explicit complete requirements."
    if not families:
        return [], "unknown", "Activity needs are ambiguous; confirm requirements or acceptable alternatives."
    requirements = list(dict.fromkeys(tag for family in families for tag in family))
    if re.search(r"\b(online|internet|wifi|wi-fi)\b", text):
        requirements.append("wifi")
    return requirements, "inferred", "Deterministic activity-text rule; no place facts were inferred."


def enrich(value, places):
    """Rebuild all derived candidate evidence from current trusted source data."""
    places = places if isinstance(places, dict) else {place["id"]: place for place in places}
    requirements, source, explanation = infer_requirements(value)
    mode = value.get("location_mode") or ("required" if value.get("location_id") else "unspecified")
    primary = value.get("location_id")
    candidates = []
    limitations = []

    def add(key, origin, evidence):
        if key in places and key not in {candidate["location_id"] for candidate in candidates}:
            candidates.append({"location_id": key, "source": origin, "confidence": "high", "evidence": evidence})

    if mode in {"required", "preferred"}:
        add(primary, "selected", "User selected this saved place.")
    if mode == "preferred":
        if value.get("allow_alternative_locations"):
            for key in value.get("alternative_location_ids", []):
                place = places.get(key, {})
                known = set(place.get("verified_capabilities", []))
                if known and requirements and not set(requirements).issubset(known):
                    limitations.append("A confirmed alternative lacks verification for the activity's known requirements.")
                    continue
                add(key, "user_confirmed", "User explicitly confirmed this saved place as an acceptable alternative.")
        if requirements:
            for key, place in sorted(places.items()):
                if place.get("access_confirmed") is True and set(requirements).issubset(place.get("verified_capabilities", [])):
                    add(key, "verified_capabilities", "User verified capabilities: " + ", ".join(requirements) + "; user confirmed access." + (" " + place["verification_notes"] if place.get("verification_notes") else ""))
            if len(candidates) <= 1:
                limitations.append("No alternative has all required capabilities and confirmed access.")
        else:
            limitations.append(explanation)
    return {**value, "location_suitability": {"requirements": requirements, "source": source,
            "confidence": "high" if requirements else "unknown", "candidates": candidates,
            "limitation": " ".join(dict.fromkeys(limitations))}}


def candidate_ids(value):
    return [candidate["location_id"] for candidate in (value.get("location_suitability") or {}).get("candidates", [])]


def saved_places(db):
    from sqlalchemy import select
    from .database import Entity
    return {row.id: row.payload for row in db.scalars(select(Entity).where(Entity.collection == "locations"))}
