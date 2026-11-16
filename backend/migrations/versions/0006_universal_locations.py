"""Persist optional per-occurrence location overrides without rewriting history."""
from alembic import op
import sqlalchemy as sa

revision = "0006_universal_locations"
down_revision = "0005_task_recurrence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("occurrences", sa.Column("location_override", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("occurrences", "location_override")
