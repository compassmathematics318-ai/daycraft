"""Reusable definitions, explicit Sunday assignments, logical sessions/chunks.

Legacy work remains finite. Import its original estimate and completion once;
never infer recurrence, extra sessions, or new time from a description.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision = "0004_weekly_tasks"
down_revision = "0003_personal_projects"
branch_labels = None
depends_on = None


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def upgrade():
    definitions = op.create_table("task_definitions", sa.Column("id", sa.String(100), primary_key=True), sa.Column("project_id", sa.String(100), sa.ForeignKey("projects.id", ondelete="RESTRICT")), sa.Column("related_activity_id", sa.String(100), sa.ForeignKey("activities.id", ondelete="SET NULL")), sa.Column("legacy_task_id", sa.String(80), unique=True), sa.Column("scheduling_model", sa.String(20), nullable=False), sa.Column("legacy_snapshot", sa.JSON()), sa.Column("payload", sa.JSON(), nullable=False))
    assignments = op.create_table("task_weeks", sa.Column("id", sa.String(100), primary_key=True), sa.Column("task_definition_id", sa.String(100), sa.ForeignKey("task_definitions.id", ondelete="RESTRICT"), nullable=False), sa.Column("week_start", sa.String(10), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("task_definition_id", "week_start", name="uq_task_week"))
    sessions = op.create_table("logical_sessions", sa.Column("id", sa.String(100), primary_key=True), sa.Column("assignment_id", sa.String(100), sa.ForeignKey("task_weeks.id", ondelete="CASCADE"), nullable=False), sa.Column("index", sa.Integer(), nullable=False), sa.Column("target_minutes", sa.BigInteger(), nullable=False), sa.Column("completed_minutes", sa.BigInteger(), nullable=False), sa.Column("baseline_completed_minutes", sa.BigInteger(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.UniqueConstraint("assignment_id", "index", name="uq_logical_session_index"))
    op.create_index("ix_logical_sessions_assignment_id", "logical_sessions", ["assignment_id"])
    chunks = op.create_table("task_chunks", sa.Column("id", sa.String(100), primary_key=True), sa.Column("logical_session_id", sa.String(100), sa.ForeignKey("logical_sessions.id", ondelete="RESTRICT"), nullable=False), sa.Column("schedule_id", sa.String(80), sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False), sa.Column("start", sa.String(40), nullable=False), sa.Column("end", sa.String(40), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("credited_minutes", sa.BigInteger(), nullable=False))
    op.create_index("ix_task_chunks_logical_session_id", "task_chunks", ["logical_session_id"])
    connection = op.get_bind()
    settings = unpack(connection.execute(sa.text("SELECT payload FROM configuration WHERE id='settings'")).scalar()) or {}
    today = datetime.now(ZoneInfo(settings.get("timezone", "America/Toronto"))).date()
    week = (today - timedelta(days=(today.weekday() + 1) % 7)).isoformat()
    project_links = dict(connection.execute(sa.text("SELECT task_id,project_id FROM task_projects")).all())
    legacy_sessions, baselines = {}, {}
    for row in connection.execute(sa.text("SELECT id,payload FROM entities WHERE collection='tasks'")):
        old = unpack(row.payload)
        duration = old.get("duration_minutes", 60)
        remaining = old.get("remaining_minutes", duration)
        status = old.get("status", "todo")
        completed = duration if status == "completed" else max(0, min(duration, duration - remaining))
        project_id = project_links.get(row.id)
        value = {"id": row.id, "title": old.get("title", "Imported task"), "task_type": "project_work" if project_id or old.get("kind") == "project" else "academic", "session_minutes": duration, "min_sessions_per_week": 0 if status in ("completed", "skipped") else 1, "importance": max(1, min(10, old.get("priority", 3) * 2)), "difficulty": 5, "allow_splitting": old.get("splittable", True), "min_chunk_minutes": min(duration, old.get("min_session_minutes", 25)), "description": old.get("notes", ""), "status": "paused" if status == "skipped" else "active", "project_id": project_id, "academic_subtype": None, "due_at": old.get("deadline") if old.get("kind", "academic") == "academic" else None, "assessment_at": None, "deadline_at": old.get("deadline") if old.get("kind") == "project" else None, "hard_deadline": old.get("hard_deadline", True), "related_activity_id": None, "course": "", "earliest_start": None, "dependencies": old.get("dependencies", []), "preferred_days": [], "preferred_time_of_day": "any", "preferred_start": old.get("preferred_start"), "preferred_end": old.get("preferred_end"), "location_id": old.get("location_id")}
        connection.execute(definitions.insert().values(id=row.id, project_id=project_id, legacy_task_id=row.id, scheduling_model="weekly", legacy_snapshot=old, payload=value))
        assignment_id, session_id = f"legacy-week:{row.id}", f"legacy-session:{row.id}"
        assignment = {"session_minutes": duration, "min_sessions_per_week": value["min_sessions_per_week"], "status": "completed" if status == "completed" else "paused" if status == "skipped" else status, "notes": "Imported finite work. No future weekly repetition is assumed.", "legacy_finite": True}
        connection.execute(assignments.insert().values(id=assignment_id, task_definition_id=row.id, week_start=week, payload=assignment))
        connection.execute(sessions.insert().values(id=session_id, assignment_id=assignment_id, index=0, target_minutes=duration, completed_minutes=completed, baseline_completed_minutes=completed, status="completed" if completed == duration else "paused" if status == "skipped" else "in_progress" if completed else "todo"))
        legacy_sessions[row.id] = session_id
        baselines[session_id] = completed
    seen = set()
    for row in connection.execute(sa.text("SELECT id,payload FROM schedules")):
        for block in unpack(row.payload).get("blocks", []):
            if block.get("task_id") in legacy_sessions and block.get("id") not in seen:
                seen.add(block["id"])
                sid = legacy_sessions[block["task_id"]]
                amount = round((datetime.fromisoformat(block["end"].replace("Z", "+00:00")) - datetime.fromisoformat(block["start"].replace("Z", "+00:00"))).total_seconds() / 60)
                credited = min(baselines[sid], amount) if block.get("status") == "completed" else 0
                baselines[sid] -= credited
                connection.execute(chunks.insert().values(id=block["id"], logical_session_id=sid, schedule_id=row.id, start=block["start"], end=block["end"], status=block.get("status", "todo"), credited_minutes=credited))
    for sid, baseline in baselines.items():
        connection.execute(sessions.update().where(sessions.c.id == sid).values(baseline_completed_minutes=baseline))


def downgrade():
    op.drop_index("ix_task_chunks_logical_session_id", table_name="task_chunks")
    op.drop_table("task_chunks")
    op.drop_index("ix_logical_sessions_assignment_id", table_name="logical_sessions")
    op.drop_table("logical_sessions")
    op.drop_table("task_weeks")
    op.drop_table("task_definitions")
