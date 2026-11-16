"""Validated entities, preferences and one saved schedule per selected day."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("entities", sa.Column("collection", sa.String(20), primary_key=True), sa.Column("id", sa.String(80), primary_key=True), sa.Column("payload", sa.JSON(), nullable=False))
    op.create_table("configuration", sa.Column("id", sa.String(20), primary_key=True), sa.Column("payload", sa.JSON(), nullable=False))
    op.create_table("schedules", sa.Column("id", sa.String(80), primary_key=True), sa.Column("date", sa.String(10), nullable=False, unique=True), sa.Column("payload", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("schedules")
    op.drop_table("configuration")
    op.drop_table("entities")
