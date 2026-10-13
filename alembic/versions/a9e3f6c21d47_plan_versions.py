"""Plan version history for undo and operation audit.

Revision ID: a9e3f6c21d47
Revises: b6e21ad4c380
"""
from alembic import op
import sqlalchemy as sa

revision = "a9e3f6c21d47"
down_revision = "b6e21ad4c380"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "version", name="uq_plan_versions_job_version"),
    )
    op.create_index("ix_plan_versions_job_id", "plan_versions", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_versions_job_id", table_name="plan_versions")
    op.drop_table("plan_versions")
