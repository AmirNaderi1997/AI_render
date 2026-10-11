"""persist each user's default plan style selection

Revision ID: c82d7410b9ef
Revises: a4d7c1e95b02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c82d7410b9ef"
down_revision: Union[str, Sequence[str], None] = "a4d7c1e95b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_style_selections",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("style_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plan_style_selections")
