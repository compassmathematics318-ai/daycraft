"""Validated, versioned API entities. All persisted input passes these models."""
from datetime import date as Date, datetime, timedelta, timezone
from typing import Literal
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def sunday_of(value: Date) -> Date:
    """Group a local calendar date into its Sunday-through-Saturday week."""
    return value - timedelta(days=(value.weekday() + 1) % 7)


def clock(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("Use a valid HH:mm time") from exc
    if parsed.strftime("%H:%M") != value:
        raise ValueError("Use HH:mm time with leading zeroes")
    if parsed.minute % 5:
        raise ValueError("Times must use five-minute intervals")
    return value


def minutes(value: int) -> int:
    if value % 5:
        raise ValueError("Durations must use five-minute intervals")
    return value


class Meal(Model):
    id: str | None = Field(default=None, min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    time: str | None = None
    duration_minutes: int = Field(ge=5, le=180)
    enabled: bool = True
    location_id: str | None = None

    @field_validator("time")
    @classmethod
    def legacy_preference(cls, value):
        return clock(value) if value is not None else None

    _duration = field_validator("duration_minutes")(minutes)


class Settings(Model):
    timezone: str = "America/Toronto"
    wake_time: str = "07:00"
    sleep_time: str = "23:00"
    work_start: str = "08:00"
    work_end: str = "22:00"
    focus_minutes: int = Field(default=50, ge=5, le=240)
    break_minutes: int = Field(default=10, ge=0, le=120)
    travel_buffer_minutes: int = Field(default=5, ge=0, le=120)
    walking_speed_kmh: float = Field(default=4.5, ge=1, le=10)
    energy_preference: Literal["any", "morning", "afternoon", "evening"] = "any"
    default_location_id: str | None = None
    home_location_id: str | None = None
    start_at_home: bool = False
    end_at_home: bool = False
    map_center_lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    map_center_lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    map_default_region: str = Field(default="Waterloo, Ontario", min_length=1, max_length=200)
    theme: Literal["light", "dark", "midnight", "warm"] = "light"
    meals: list[Meal] = Field(default_factory=lambda: [Meal(id="breakfast", name="Breakfast", duration_minutes=30), Meal(id="lunch", name="Lunch", duration_minutes=45), Meal(id="dinner", name="Dinner", duration_minutes=30)], max_length=8)
    _times = field_validator("wake_time", "sleep_time", "work_start", "work_end")(clock)
    _minutes = field_validator("focus_minutes", "break_minutes", "travel_buffer_minutes")(minutes)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def ordered_hours(self):
        if (self.map_center_lat is None) != (self.map_center_lon is None):
            raise ValueError("Map center requires both latitude and longitude")
        if (self.start_at_home or self.end_at_home) and not self.home_location_id:
            raise ValueError("Choose a home location before enabling trips from or to home")
        # Midnight denotes the end of the selected day, as in the solver.
        sleep_boundary = "24:00" if self.sleep_time == "00:00" else self.sleep_time
        if not self.wake_time <= self.work_start < self.work_end <= sleep_boundary:
            raise ValueError("Working hours must fit between wake and sleep; sleep 00:00 means midnight at the end of the day")
        meal_ids = [meal.id for meal in self.meals if meal.id is not None]
        if len(meal_ids) != len(set(meal_ids)):
            raise ValueError("Meal IDs must be unique")
        return self


SAFE_INTEGER = 9007199254740991


def capability_tags(value):
    tags = [tag.strip().lower().replace(" ", "_").replace("-", "_") for tag in value]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", tag) for tag in tags):
        raise ValueError("Capability tags use letters, numbers and underscores, up to 80 characters")
    return list(dict.fromkeys(tags))


def location_edit(value, previous, fields):
    """Retain metadata for old clients; reset rooms on an explicit venue change."""
    value = dict(value)
    if "location_requirements" not in fields:
        value["location_requirements"] = previous.get("location_requirements", [])
    changed = any(field in fields and value.get(field) != previous.get(field) for field in ("location_id", "location_mode"))
    for field, default in (("allow_alternative_locations", False), ("alternative_location_ids", [])):
        if field not in fields:
            value[field] = default if changed else previous.get(field, default)
    if "room" not in fields:
        value["room"] = "" if changed else previous.get("room", "")
    if "building" in previous and "building" not in fields:
        value["building"] = previous["building"]
    return value


class DailySessionLimits(Model):
    min_sessions_per_day: int = Field(default=1, ge=0, le=SAFE_INTEGER, strict=True)
    max_sessions_per_day: int | None = Field(default=None, ge=1, le=SAFE_INTEGER, strict=True)

    @model_validator(mode="after")
    def coherent_daily_limits(self):
        if self.max_sessions_per_day is not None and self.max_sessions_per_day < self.min_sessions_per_day:
            raise ValueError("Maximum sessions per day cannot be less than minimum sessions per day")
        return self


class LocationAssignment(Model):
    """An explicit venue policy; legacy physical references retain their meaning."""
    location_id: str | None = None
    location_mode: Literal["unspecified", "remote", "preferred", "required"] = "unspecified"
    allow_alternative_locations: bool = Field(default=False, strict=True)
    alternative_location_ids: list[str] = Field(default_factory=list, max_length=100)
    location_requirements: list[str] = Field(default_factory=list, max_length=100)
    room: str = Field(default="", max_length=100)

    @field_validator("location_requirements")
    @classmethod
    def normalize_requirements(cls, value):
        return capability_tags(value)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_location(cls, value):
        if isinstance(value, dict) and "location_mode" not in value:
            return {**value, "location_mode": "required" if value.get("location_id") else "unspecified"}
        return value

    @model_validator(mode="after")
    def coherent_location(self):
        if self.location_mode in ("preferred", "required") and not self.location_id:
            raise ValueError("Choose a saved place for a preferred or required location")
        if self.location_mode in ("unspecified", "remote") and self.location_id:
            raise ValueError("Unspecified and remote activities cannot have a physical destination")
        object.__setattr__(self, "alternative_location_ids", list(dict.fromkeys(self.alternative_location_ids)))
        if any(not key.strip() for key in self.alternative_location_ids):
            raise ValueError("Alternative locations must reference saved places")
        if self.location_id in self.alternative_location_ids:
            raise ValueError("Alternative locations must differ from the selected place")
        if self.allow_alternative_locations and self.location_mode != "preferred":
            raise ValueError("Alternative locations are available only for preferred venues")
        if self.alternative_location_ids and not self.allow_alternative_locations:
            raise ValueError("Enable alternative locations before selecting other venues")
        if self.allow_alternative_locations and not self.alternative_location_ids:
            raise ValueError("Choose at least one acceptable alternative saved place")
        return self


class Location(Model):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    notes: str = Field(default="", max_length=5000)
    address: str = Field(default="", max_length=1000)
    building: str = Field(default="", max_length=200)
    room: str = Field(default="", max_length=100)
    floor: str = Field(default="", max_length=100)
    entrance: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    verified_capabilities: list[str] = Field(default_factory=list, max_length=100)
    access_confirmed: bool = Field(default=False, strict=True)
    verification_notes: str = Field(default="", max_length=5000)

    @field_validator("verified_capabilities")
    @classmethod
    def normalize_capabilities(cls, value):
        return capability_tags(value)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Place name cannot be blank")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value):
        if any(not alias.strip() or len(alias) > 200 for alias in value):
            raise ValueError("Aliases must contain 1?200 characters")
        return list(dict.fromkeys(alias.strip() for alias in value))

    travel_overrides: dict[str, int] = Field(default_factory=dict)

    @field_validator("travel_overrides")
    @classmethod
    def valid_overrides(cls, value):
        if any(not 0 <= x <= 1440 for x in value.values()):
            raise ValueError("Travel overrides must be between 0 and 1440 minutes")
        return value


class Class(LocationAssignment):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    class_type: str = Field(default="Lecture", max_length=80)
    date: Date | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    start_time: str
    end_time: str
    start_date: Date | None = None
    end_date: Date | None = None
    exceptions: list[Date] = Field(default_factory=list, max_length=366)
    location_id: str | None = None
    building: str = Field(default="", max_length=200)
    room: str = Field(default="", max_length=100)
    _times = field_validator("start_time", "end_time")(clock)

    @model_validator(mode="after")
    def valid_class(self):
        if self.start_time >= self.end_time:
            raise ValueError("Class end must follow start on the same day")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("Weekdays range from Monday=0 to Sunday=6")
        if not self.date and not self.weekdays:
            raise ValueError("Select a date or at least one recurring weekday")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Recurrence start cannot follow end")
        return self


class Project(Model):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    affiliations: list[str] = Field(default_factory=list, max_length=30)
    start_date: Date | None = None
    end_date: Date | None = None
    contributors: int = Field(default=1, ge=1, le=100000, strict=True)
    importance: float = Field(default=5, ge=1, le=10, allow_inf_nan=False, strict=True)
    difficulty: float = Field(default=5, ge=0, le=10, allow_inf_nan=False, strict=True)
    status: Literal["planning", "active", "paused", "completed", "archived"] = "active"
    category: Literal["academic", "software", "research", "extracurricular", "personal", "other"] = "personal"
    description: str = Field(default="", max_length=20000)
    goals: str = Field(default="", max_length=10000)
    links: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Project name cannot be blank")
        return value.strip()

    @field_validator("importance", "difficulty")
    @classmethod
    def half_steps(cls, value):
        if value * 2 != round(value * 2):
            raise ValueError("Use increments of 0.5")
        return value

    @field_validator("affiliations")
    @classmethod
    def clean_affiliations(cls, value):
        if any(not item.strip() or len(item) > 200 for item in value):
            raise ValueError("Each affiliation must contain 1–200 characters")
        return list(dict.fromkeys(item.strip() for item in value))

    @field_validator("links")
    @classmethod
    def valid_links(cls, value):
        for link in value:
            try:
                parsed = urlsplit(link.strip())
                valid = parsed.scheme in ("http", "https") and bool(parsed.hostname) and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid or len(link) > 2000 or any(char.isspace() for char in link.strip()):
                raise ValueError("Relevant links must be valid http:// or https:// URLs")
        return list(dict.fromkeys(link.strip() for link in value))

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Project end date cannot precede start date")
        return self


class Task(LocationAssignment, DailySessionLimits):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["academic", "project"] = "academic"
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
    duration_minutes: int = Field(default=60, ge=5, le=100000)
    remaining_minutes: int = Field(default=60, ge=0, le=100000)
    priority: int = Field(default=3, ge=1, le=5)
    deadline: datetime | None = None
    hard_deadline: bool = True
    splittable: bool = True
    min_session_minutes: int = Field(default=25, ge=5, le=1440)
    max_session_minutes: int = Field(default=90, ge=5, le=1440)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    location_id: str | None = None
    status: Literal["todo", "in_progress", "completed", "skipped"] = "todo"
    preferred_start: str | None = None
    preferred_end: str | None = None
    notes: str = Field(default="", max_length=10000)
    _minutes = field_validator("duration_minutes", "remaining_minutes", "min_session_minutes", "max_session_minutes")(minutes)

    @field_validator("preferred_start", "preferred_end")
    @classmethod
    def optional_clock(cls, value):
        return clock(value) if value else None

    @model_validator(mode="after")
    def coherent(self):
        if self.remaining_minutes > self.duration_minutes:
            raise ValueError("Remaining work cannot exceed estimated duration")
        if self.min_session_minutes > self.max_session_minutes:
            raise ValueError("Minimum session cannot exceed maximum")
        if self.preferred_start and self.preferred_end and self.preferred_start >= self.preferred_end:
            raise ValueError("Preferred start must precede end")
        return self


class RelatedEntity(Model):
    kind: Literal["activity", "project"]
    id: str = Field(min_length=1, max_length=100)


class Block(LocationAssignment):
    meal_id: str | None = None
    # Accepted for round trips only. The API always rebuilds this read-only data.
    location_suitability: dict | None = None
    related_entity: RelatedEntity | None = None
    related_entity_context: dict | None = None
    resolved_location_id: str | None = None
    location_override: bool = False
    id: str
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["class", "task", "project", "break", "meal", "travel", "personal"]
    start: datetime
    end: datetime
    location_id: str | None = None
    task_id: str | None = None
    project_id: str | None = None
    class_id: str | None = None
    locked: bool = False
    status: Literal["todo", "in_progress", "completed", "skipped"] = "todo"
    rationale: str = ""
    estimated: bool = False
    origin_id: str | None = None
    destination_id: str | None = None
    activity_id: str | None = None
    occurrence_id: str | None = None
    category: Literal["class", "assessment", "commitment"] | None = None
    subtype: str | None = None
    description: str = ""
    course: str | None = None
    building: str = ""
    room: str = ""
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    calendar_source: str | None = None
    task_definition_id: str | None = None
    task_assignment_id: str | None = None
    logical_session_id: str | None = None
    chunk_index: int | None = None
    completion_confirmed_at: datetime | None = None
    completion_previous_status: Literal["todo", "in_progress", "skipped"] | None = None
    completion_verified: bool = False
    completion_remaining_minutes_delta: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def positive_length(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Schedule block times must include timezone offsets")
        if self.end <= self.start:
            raise ValueError("Block end must follow start")
        if self.start.second or self.end.second or self.start.microsecond or self.end.microsecond:
            raise ValueError("Block boundaries must use whole-minute precision")
        return self


class Generate(Model):
    date: Date
    mode: Literal["balanced", "deadline", "deep"] = "balanced"
    reoptimize: bool = False
    include_inactive_projects: bool = False


class EditSchedule(Model):
    blocks: list[Block] = Field(max_length=1000)


class BlockCompletion(Model):
    completed: bool = Field(strict=True)


WorkloadLevel = Literal["very_low", "low", "medium", "high", "very_high"]


class DayPreferences(Model):
    workload_level: WorkloadLevel = "medium"


class Geocode(Model):
    query: str = Field(min_length=2, max_length=200)


class Route(Model):
    origin_id: str
    destination_id: str


def precise_instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Calendar timestamps must include a timezone offset")
    if value.minute % 5 or value.astimezone(timezone.utc).minute % 5 or value.second or value.microsecond:
        raise ValueError("Calendar times must use exact five-minute intervals")
    return value


class Activity(LocationAssignment):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    category: Literal["class", "assessment", "commitment"]
    subtype: Literal["Lecture", "Tutorial", "Lab", "Personal", "Groupwork"] | None = None
    description: str = Field(default="", max_length=10000)
    location_id: str | None = None
    building: str = Field(default="", max_length=200)
    room: str = Field(default="", max_length=100)
    course: str | None = Field(default=None, max_length=200)
    start_date: Date | None = None
    end_date: Date | None = None
    assessment_start: datetime | None = None
    assessment_end: datetime | None = None
    legacy_class_id: str | None = None
    related_entity: RelatedEntity | None = None

    @model_validator(mode="after")
    def coherent(self):
        if not self.title.strip():
            raise ValueError("Activity name cannot be blank")
        self.title = self.title.strip()
        if self.related_entity and self.category != "commitment":
            raise ValueError("Related entities are available for commitments")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Permitted start date cannot follow end date")
        if self.category == "assessment":
            if not self.assessment_start or not self.assessment_end:
                raise ValueError("Assessments require absolute start and end date/time")
            precise_instant(self.assessment_start)
            precise_instant(self.assessment_end)
            if self.assessment_end <= self.assessment_start:
                raise ValueError("Assessment end must be later than start")
            if self.subtype is not None:
                raise ValueError("Assessments do not have a class or commitment subtype")
        else:
            choices = {"Lecture", "Tutorial", "Lab"} if self.category == "class" else {"Personal", "Groupwork"}
            if self.subtype not in choices:
                raise ValueError("Select an appropriate subtype for this block category")
            if self.assessment_start or self.assessment_end:
                raise ValueError("Only assessments have predefined absolute times")
        return self


class OccurrenceInput(Model):
    location_override: LocationAssignment | None = None
    activity_id: str = Field(min_length=1, max_length=100)
    start: datetime
    end: datetime
    _times = field_validator("start", "end")(precise_instant)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Occurrence end must be later than start")
        return self


class CalendarOccurrence(OccurrenceInput):
    id: str
    source: Literal["manual", "assessment", "legacy"]


class CopyWeek(Model):
    week_start: Date

    @field_validator("week_start")
    @classmethod
    def containing_sunday(cls, value):
        return sunday_of(value)
