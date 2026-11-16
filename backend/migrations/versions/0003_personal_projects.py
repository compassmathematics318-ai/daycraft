"""Separate contextual projects from existing, explicitly entered task work.

Every legacy project work item keeps its ID and full original work data. A
container is added for it, with an immutable pre-migration snapshot. No new
task, duration, recurrence, or calendar block is invented.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0003_personal_projects"
down_revision = "0002_activity_calendar"
branch_labels = None
depends_on = None


def upgrade():
    projects = op.create_table("projects", sa.Column("id", sa.String(100), primary_key=True), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("legacy_snapshot", sa.JSON()))
    links = op.create_table("task_projects", sa.Column("task_collection", sa.String(20), primary_key=True), sa.Column("task_id", sa.String(80), primary_key=True), sa.Column("project_id", sa.String(100), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False), sa.ForeignKeyConstraint(["task_collection", "task_id"], ["entities.collection", "entities.id"], ondelete="CASCADE"), sa.CheckConstraint("task_collection = 'tasks'", name="ck_task_projects_collection"))
    op.create_index("ix_task_projects_project_id", "task_projects", ["project_id"])
    connection = op.get_bind()
    entities = sa.table("entities", sa.column("collection", sa.String()), sa.column("id", sa.String()), sa.column("payload", sa.JSON()))
    for row in connection.execute(sa.select(entities.c.id, entities.c.payload).where(entities.c.collection == "tasks")):
        old = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
        if old.get("kind") != "project":
            continue
        value = {"id": row.id, "name": old.get("title") or "Imported project", "affiliations": [], "start_date": None, "end_date": None, "contributors": 1, "importance": max(1, min(10, old.get("priority", 3) * 2)), "difficulty": 5, "status": "completed" if old.get("status") == "completed" else "active", "category": "personal", "description": old.get("notes", ""), "goals": "", "links": []}
        connection.execute(projects.insert().values(id=row.id, payload=value, legacy_snapshot=old))
        connection.execute(links.insert().values(task_collection="tasks", task_id=row.id, project_id=row.id))
        connection.execute(entities.update().where(entities.c.collection == "tasks", entities.c.id == row.id).values(payload={**old, "project_id": row.id}))


def downgrade():
    # Preserve task work and user edits; only remove now-invalid association keys.
    connection = op.get_bind()
    entities = sa.table("entities", sa.column("collection", sa.String()), sa.column("id", sa.String()), sa.column("payload", sa.JSON()))
    for row in connection.execute(sa.select(entities.c.id, entities.c.payload).where(entities.c.collection == "tasks")):
        value = dict(json.loads(row.payload) if isinstance(row.payload, str) else row.payload)
        value.pop("project_id", None)
        connection.execute(entities.update().where(entities.c.collection == "tasks", entities.c.id == row.id).values(payload=value))
    op.drop_index("ix_task_projects_project_id", table_name="task_projects")
    op.drop_table("task_projects")
    op.drop_table("projects")
