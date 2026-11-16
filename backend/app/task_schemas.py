"""Weekly task definitions are reusable context; assignments own weekly work."""
from datetime import date as Date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .schemas import DailySessionLimits, LocationAssignment, Model, Project, clock, sunday_of

SAFE_INTEGER = 9007199254740991


class TaskRecurrence(Model):
    kind: Literal["weekly"] = "weekly"
    start_week: Date | None = None
    end_week: Date | None = None
    stopped_from_week: Date | None = None
    interval_weeks: int = Field(default=1, ge=1, le=520, strict=True)

    @field_validator("start_week", "end_week", "stopped_from_week")
    @classmethod
    def normalize_week(cls, value):
        return sunday_of(value) if value else None

    @model_validator(mode="after")
    def bounds(self):
        if self.start_week and self.end_week and self.end_week < self.start_week:
            raise ValueError("Recurrence end must not precede its start")
        return self


class StopRepeating(Model):
    from_week: Date
    _sunday = field_validator("from_week")(sunday_of)


class AssociationSummary(Model):
    assigned_week_starts: list[str]
    stored_assignment_count: int
    history_week_starts: list[str]
    recurring: bool
    repeating_from_week: str | None
    repeating_through_week: str | None
    stopped_from_week: str | None


class TaskDefinition(LocationAssignment, DailySessionLimits):
    id: str | None = None
    association_summary: AssociationSummary | None = Field(default=None, exclude=True)
    title: str = Field(min_length=1, max_length=200)
    task_type: Literal["academic", "personal", "project_work", "administrative", "wellness", "other"] = "personal"
    session_minutes: int = Field(default=60, ge=1, le=SAFE_INTEGER, strict=True)
    min_sessions_per_week: int = Field(default=1, ge=0, le=SAFE_INTEGER, strict=True)
    importance: float = Field(default=5, ge=1, le=10, strict=True, allow_inf_nan=False)
    difficulty: float = Field(default=5, ge=0, le=10, strict=True, allow_inf_nan=False)
    allow_splitting: bool = False
    min_chunk_minutes: int = Field(default=15, ge=1, le=SAFE_INTEGER, strict=True)
    description: str = Field(default="", max_length=20000)
    status: Literal["active", "paused", "archived", "completed"] = "active"
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
    academic_subtype: Literal["studying", "assignment", "assessment_preparation", "reading", "other"] | None = None
    due_at: datetime | None = None
    assessment_at: datetime | None = None
    deadline_at: datetime | None = None
    course: str = Field(default="", max_length=200)
    hard_deadline: bool = True
    related_activity_id: str | None = Field(default=None, min_length=1, max_length=100)
    earliest_start: datetime | None = None
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    preferred_days: list[int] = Field(default_factory=list, max_length=7)
    preferred_time_of_day: Literal["any", "morning", "afternoon", "evening"] = "any"
    preferred_start: str | None = None
    preferred_end: str | None = None
    location_id: str | None = None
    recurrence: TaskRecurrence | None = None

    _half_steps = field_validator("importance", "difficulty")(Project.half_steps.__func__)

    @field_validator("due_at", "assessment_at", "deadline_at", "earliest_start", mode="before")
    @classmethod
    def date_requires_time(cls, value):
        if isinstance(value, str) and "T" not in value and " " not in value:
            raise ValueError("Use a date and time, not a date alone")
        return value

    @field_validator("preferred_start", "preferred_end")
    @classmethod
    def optional_clock(cls, value):
        return clock(value) if value else None

    @field_validator("title")
    @classmethod
    def name(cls, value):
        if not value.strip():
            raise ValueError("Task name cannot be blank")
        return value.strip()

    @field_validator("preferred_days")
    @classmethod
    def weekdays(cls, value):
        if any(isinstance(day, bool) or not 0 <= day <= 6 for day in value):
            raise ValueError("Preferred weekdays use Monday=0 through Sunday=6")
        return sorted(set(value))

    @model_validator(mode="after")
    def coherent(self):
        if self.allow_splitting and self.min_chunk_minutes > self.session_minutes:
            raise ValueError("Minimum chunk cannot exceed a logical session")
        if self.task_type != "academic" and self.academic_subtype:
            raise ValueError("Academic subtype is only available for academic tasks")
        if self.preferred_start and self.preferred_end and self.preferred_start >= self.preferred_end:
            raise ValueError("Preferred start must precede end")
        if self.recurrence and any((self.due_at, self.assessment_at, self.deadline_at, self.earliest_start)):
            raise ValueError("Every-week tasks cannot carry absolute one-time dates; clear those dates when converting")
        return self


class TaskWeek(Model):
    task_definition_id: str = Field(min_length=1, max_length=100)
    week_start: Date
    session_minutes: int | None = Field(default=None, ge=1, le=SAFE_INTEGER, strict=True)
    min_sessions_per_week: int | None = Field(default=None, ge=0, le=SAFE_INTEGER, strict=True)
    status: Literal["todo", "in_progress", "completed", "paused", "skipped"] = "todo"
    notes: str = Field(default="", max_length=10000)
    overrides: dict = Field(default_factory=dict)
    allow_inactive: bool | None = None
    _sunday = field_validator("week_start")(sunday_of)


class CopyTaskWeek(Model):
    source_week: Date
    target_week: Date
    deadline_policy: Literal["preserve", "shift"]
    definition_ids: list[str] | None = Field(default=None, max_length=10000)
    preview: bool = False
    _sunday = field_validator("source_week", "target_week")(sunday_of)


class SessionProgress(Model):
    completed_minutes: int | None = Field(default=None, ge=0, le=SAFE_INTEGER, strict=True)
    status: Literal["todo", "in_progress", "completed", "paused"] | None = None


class LogSession(Model):
    assignment_id: str = Field(min_length=1, max_length=100)
    completed_minutes: int | None = Field(default=None, ge=1, le=SAFE_INTEGER, strict=True)
