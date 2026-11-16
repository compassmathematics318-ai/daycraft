"""Add independent archive and explicit completion snapshots; retain all live data."""
from alembic import op
import sqlalchemy as sa

revision = "0008_schedule_history"
down_revision = "0007_daily_session_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("schedule_archives",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source_schedule_id", sa.String(80), nullable=False),
        sa.Column("source_revision_id", sa.String(100), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("attached", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_schedule_id", "source_revision_id", name="uq_archive_revision"))
    op.create_index("ix_schedule_archives_date", "schedule_archives", ["date"])
    op.create_table("completed_work",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source_schedule_id", sa.String(80), nullable=False),
        sa.Column("source_block_id", sa.String(100), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=True),
        sa.Column("reopened_at", sa.String(40)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_schedule_id", "source_block_id", name="uq_completed_work_source"))
    op.create_index("ix_completed_work_date", "completed_work", ["date"])


def downgrade():
    op.drop_index("ix_completed_work_date", table_name="completed_work")
    op.drop_table("completed_work")
    op.drop_index("ix_schedule_archives_date", table_name="schedule_archives")
    op.drop_table("schedule_archives")
