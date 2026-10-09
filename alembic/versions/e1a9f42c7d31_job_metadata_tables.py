"""persist job metadata, plans, render results, and QC results

Revision ID: e1a9f42c7d31
Revises: d57cf7a0bea7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1a9f42c7d31"
down_revision: Union[str, Sequence[str], None] = "d57cf7a0bea7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("stage", sa.String(length=100), nullable=True))
    op.add_column("jobs", sa.Column("message", sa.Text(), nullable=False, server_default=""))
    op.add_column("jobs", sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("state", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    # Legacy columns stay in place so an existing production database can be
    # upgraded without destructive data loss. New code no longer reads them.
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenes", sa.JSON(), nullable=False),
        sa.Column("captions", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_plans_job_id", "plans", ["job_id"], unique=True)
    op.create_table(
        "render_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("output_path", sa.String(length=1000), nullable=False),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_render_results_job_id", "render_results", ["job_id"])
    op.create_table(
        "qc_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qc_results_job_id", "qc_results", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_qc_results_job_id", table_name="qc_results")
    op.drop_table("qc_results")
    op.drop_index("ix_render_results_job_id", table_name="render_results")
    op.drop_table("render_results")
    op.drop_index("ix_plans_job_id", table_name="plans")
    op.drop_table("plans")
    op.drop_column("jobs", "state")
    op.drop_column("jobs", "progress_pct")
    op.drop_column("jobs", "message")
    op.drop_column("jobs", "stage")
