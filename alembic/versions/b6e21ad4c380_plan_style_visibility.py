"""Persist per-user visibility of the built-in plan style card.

Revision ID: b6e21ad4c380
Revises: c82d7410b9ef
"""
from alembic import op
import sqlalchemy as sa

revision = "b6e21ad4c380"
down_revision = "c82d7410b9ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_style_visibility",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("default_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("plan_style_visibility")
