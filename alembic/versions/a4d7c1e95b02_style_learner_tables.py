"""move style learner references and learned profile from JSON files to PostgreSQL

Revision ID: a4d7c1e95b02
Revises: f3c8b52a91e4
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4d7c1e95b02"
down_revision: Union[str, Sequence[str], None] = "f3c8b52a91e4"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")
LEGACY_DIR = Path(__file__).resolve().parents[2] / "jobs" / "style-library" / "learned"


def upgrade() -> None:
    op.create_table(
        "style_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("digest", sa.String(length=32), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "digest", name="uq_style_references_user_digest"),
    )
    op.create_index("ix_style_references_user_id", "style_references", ["user_id"])
    op.create_table(
        "learned_style_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _import_legacy_files()


def _import_legacy_files() -> None:
    """Import unowned legacy files only when their owner is unambiguous."""
    bind = op.get_bind()
    users = bind.execute(sa.text("SELECT id FROM users ORDER BY id")).scalars().all()
    if len(users) != 1:
        if ((LEGACY_DIR.is_dir() and any(LEGACY_DIR.glob("references/ref-*.json")))
                or (LEGACY_DIR / "learned.json").is_file()):
            log.warning("legacy learned style data has no owner; leaving it untouched because the database has %s users", len(users))
        return
    owner = users[0]
    if not LEGACY_DIR.is_dir():
        return
    now = datetime.now(timezone.utc)
    refs = sa.table("style_references", sa.column("user_id"), sa.column("digest"),
                    sa.column("source_file"), sa.column("analysis", sa.JSON), sa.column("created_at"))
    for path in sorted((LEGACY_DIR / "references").glob("ref-*.json")):
        try:
            analysis = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("skipping unreadable legacy style reference %s", path.name)
            continue
        bind.execute(refs.insert().values(user_id=owner, digest=path.stem[len("ref-"):][:32],
                                          source_file=str(analysis.get("source_file", ""))[:500],
                                          analysis=analysis, created_at=now))
    profile_path = LEGACY_DIR / "learned.json"
    if profile_path.is_file():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("skipping unreadable legacy learned profile")
            return
        table = sa.table("learned_style_profiles", sa.column("user_id"),
                         sa.column("profile", sa.JSON), sa.column("updated_at"))
        bind.execute(table.insert().values(user_id=owner, profile=profile, updated_at=now))


def downgrade() -> None:
    op.drop_table("learned_style_profiles")
    op.drop_index("ix_style_references_user_id", table_name="style_references")
    op.drop_table("style_references")
