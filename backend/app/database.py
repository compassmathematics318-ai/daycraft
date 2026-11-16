"""Local persistence. JSON documents are validated by API schemas before storage."""
import os
from pathlib import Path

from sqlalchemy import JSON, BigInteger, Integer, String, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[2]


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"
    collection: Mapped[str] = mapped_column(String(20), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    legacy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TaskProject(Base):
    __tablename__ = "task_projects"
    task_collection: Mapped[str] = mapped_column(String(20), primary_key=True, default="tasks")
    task_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True)
    __table_args__ = (ForeignKeyConstraint(["task_collection", "task_id"], ["entities.collection", "entities.id"], ondelete="CASCADE"), CheckConstraint("task_collection = 'tasks'", name="ck_task_projects_collection"))


class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True)
    related_activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    legacy_task_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    scheduling_model: Mapped[str] = mapped_column(String(20), nullable=False, default="weekly")
    legacy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class TaskWeek(Base):
    __tablename__ = "task_weeks"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_definition_id: Mapped[str] = mapped_column(ForeignKey("task_definitions.id", ondelete="RESTRICT"), nullable=False)
    week_start: Mapped[str] = mapped_column(String(10), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("task_definition_id", "week_start", name="uq_task_week"),)


class LogicalSession(Base):
    __tablename__ = "logical_sessions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("task_weeks.id", ondelete="CASCADE"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_minutes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_minutes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    baseline_completed_minutes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    __table_args__ = (UniqueConstraint("assignment_id", "index", name="uq_logical_session_index"),)


class TaskChunk(Base):
    __tablename__ = "task_chunks"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    logical_session_id: Mapped[str] = mapped_column(ForeignKey("logical_sessions.id", ondelete="RESTRICT"), nullable=False, index=True)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    start: Mapped[str] = mapped_column(String(40), nullable=False)
    end: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    credited_minutes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class Configuration(Base):
    __tablename__ = "configuration"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class ScheduleArchive(Base):
    """Independent snapshots: source identifiers deliberately have no foreign keys."""
    __tablename__ = "schedule_archives"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_schedule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    attached: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("source_schedule_id", "source_revision_id", name="uq_archive_revision"),)


class CompletedWork(Base):
    """Explicit work evidence independent of archives and task lifetimes."""
    __tablename__ = "completed_work"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_schedule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_block_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    confirmed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reopened_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("source_schedule_id", "source_block_id", name="uq_completed_work_source"),)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    legacy_class_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    legacy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Occurrence(Base):
    __tablename__ = "occurrences"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    start: Mapped[str] = mapped_column(String(40), nullable=False)
    end: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    location_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("activity_id", "start", "end", name="uq_occurrence_identity"), Index("ix_occurrence_bounds", "start", "end"))


def database_path(path=None):
    return Path(path or os.getenv("SCHEDULE_BUILDER_DB", str(ROOT / "data" / "schedule_builder.db"))).resolve()


def build_database(path=None):
    path = database_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def sqlite_options(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine, sessionmaker(engine, expire_on_commit=False)

