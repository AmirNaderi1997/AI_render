"""add_hermes_settings

Revision ID: f3c8b52a91e4
Revises: e1a9f42c7d31
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3c8b52a91e4'
down_revision: Union[str, Sequence[str], None] = 'e1a9f42c7d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'hermes_settings' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table('hermes_settings',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('encrypted_credentials', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'provider')
    )
    op.create_index(op.f('ix_hermes_settings_user_id'), 'hermes_settings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hermes_settings_user_id'), table_name='hermes_settings')
    op.drop_table('hermes_settings')
