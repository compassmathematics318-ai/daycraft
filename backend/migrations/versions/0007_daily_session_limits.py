"""Daily block limits and room metadata use existing JSON with read defaults.

No payloads, session progress, occurrence overrides or saved plans are rewritten.
"""
revision = "0007_daily_session_limits"
down_revision = "0006_universal_locations"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
