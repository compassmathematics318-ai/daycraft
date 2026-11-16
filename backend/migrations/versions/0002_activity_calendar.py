"""Reusable activity definitions and FK-linked dated calendar occurrences.

Legacy class documents remain untouched, including recurrence and exceptions.
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision = "0002_activity_calendar"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    activities = op.create_table("activities", sa.Column("id", sa.String(100), primary_key=True), sa.Column("legacy_class_id", sa.String(80), unique=True), sa.Column("legacy_snapshot", sa.JSON()), sa.Column("payload", sa.JSON(), nullable=False))
    occurrences = op.create_table("occurrences", sa.Column("id", sa.String(160), primary_key=True), sa.Column("activity_id", sa.String(100), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False), sa.Column("start", sa.String(40), nullable=False), sa.Column("end", sa.String(40), nullable=False), sa.Column("source", sa.String(20), nullable=False), sa.UniqueConstraint("activity_id", "start", "end", name="uq_occurrence_identity"))
    op.create_index("ix_occurrence_bounds", "occurrences", ["start", "end"])
    connection = op.get_bind()
    settings_row = connection.execute(sa.text("SELECT payload FROM configuration WHERE id='settings'")).scalar()
    settings = json.loads(settings_row) if isinstance(settings_row, str) else settings_row or {}
    zone = ZoneInfo(settings.get("timezone", "America/Toronto"))
    for row in connection.execute(sa.text("SELECT id,payload FROM entities WHERE collection='classes'")):
        old = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
        subtype = old.get("class_type", "Lecture")
        assessment = subtype.casefold() in {"exam", "quiz", "assessment", "midterm", "final"} and bool(old.get("date"))
        category = "assessment" if assessment else "class" if subtype in {"Lecture", "Tutorial", "Lab"} else "commitment"
        start = datetime.fromisoformat(f"{old['date']}T{old['start_time']}").replace(tzinfo=zone).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if assessment else None
        end = datetime.fromisoformat(f"{old['date']}T{old['end_time']}").replace(tzinfo=zone).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if assessment else None
        value = {"id": row.id, "title": old["title"], "category": category, "subtype": None if assessment else subtype if category == "class" else "Personal", "description": "" if category == "class" or assessment else f"Imported {subtype} commitment.", "location_id": old.get("location_id"), "building": old.get("building", ""), "room": old.get("room", ""), "course": None, "start_date": old.get("start_date"), "end_date": old.get("end_date"), "assessment_start": start, "assessment_end": end, "legacy_class_id": row.id}
        connection.execute(activities.insert().values(id=row.id, legacy_class_id=row.id, legacy_snapshot=old, payload=value))
        if assessment and old["date"] not in old.get("exceptions", []):
            connection.execute(occurrences.insert().values(id=f"assessment:{row.id}", activity_id=row.id, start=start, end=end, source="assessment"))


def downgrade():
    op.drop_index("ix_occurrence_bounds", table_name="occurrences")
    op.drop_table("occurrences")
    op.drop_table("activities")
