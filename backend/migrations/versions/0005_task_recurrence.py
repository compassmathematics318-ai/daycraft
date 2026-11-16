"""Weekly recurrence and copy metadata use existing validated JSON columns.

No preexisting task is made recurring and no assignment, progress, session,
schedule, or original payload is rewritten. Missing recurrence means finite
explicit-only work. Recurring assignments are materialized lazily by writes.
"""

revision = "0005_task_recurrence"
down_revision = "0004_weekly_tasks"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
