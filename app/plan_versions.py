"""Append-only plan history per job, backing operation audit and undo.

PostgreSQL stores versions in ``plan_versions``. Without a database (local
development and tests) the same records live as JSON files under
``<job dir>/plan_versions/v<N>.json``.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Optional

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import PlanVersion

if TYPE_CHECKING:
    from app.jobs import Job

VersionSource = Literal["ai_generate", "user_ui", "chat", "qc", "undo", "legacy"]
_file_lock = threading.Lock()
# Default parent: the latest version. ``None`` explicitly means "no parent".
LATEST = object()


def _use_db() -> bool:
    # Versions live wherever the job store keeps jobs.
    from app import jobs
    return jobs.DB_AVAILABLE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(record: PlanVersion | dict, include_plan: bool) -> dict:
    if isinstance(record, dict):
        data = dict(record)
    else:
        data = {"version": record.version, "parent_version": record.parent_version,
                "source": record.source, "operations": record.operations or [],
                "plan": record.plan, "created_at": record.created_at.isoformat() if record.created_at else None}
    if not include_plan:
        data.pop("plan", None)
    return data


# --- file fallback ---------------------------------------------------------

def _dir(job: "Job"):
    return job.dir / "plan_versions"


def _file_versions(job: "Job") -> list[dict]:
    d = _dir(job)
    if not d.is_dir():
        return []
    rows = [json.loads(p.read_text()) for p in d.glob("v*.json")]
    return sorted(rows, key=lambda r: r["version"])


def _file_record(job: "Job", row: dict) -> dict:
    with _file_lock:
        d = _dir(job)
        d.mkdir(parents=True, exist_ok=True)
        existing = [int(p.stem[1:]) for p in d.glob("v*.json") if p.stem[1:].isdigit()]
        row["version"] = max(existing, default=0) + 1
        if row["parent_version"] is LATEST:
            row["parent_version"] = max(existing, default=None)
        (d / f"v{row['version']}.json").write_text(json.dumps(row, ensure_ascii=False))
    return row


# --- public API --------------------------------------------------------------

def record_version(
    job: "Job",
    plan: dict,
    source: VersionSource,
    operations: Optional[list] = None,
    parent_version: Optional[int] | object = LATEST,
) -> int:
    """Append a version and return its number.

    ``parent_version`` defaults to the latest version (a linear edit). Undo
    passes an older parent (or ``None``) so repeated undos walk back along
    the chain.
    """
    row = {"version": 0, "parent_version": parent_version, "source": source,
           "operations": operations or [], "plan": plan, "created_at": _now().isoformat()}
    if not _use_db():
        return _file_record(job, row)["version"]

    from app.jobs import _await_db

    async def insert() -> int:
        assert AsyncSessionLocal is not None
        async with AsyncSessionLocal() as db:
            latest = (await db.execute(select(func.max(PlanVersion.version))
                                       .where(PlanVersion.job_id == job.id))).scalar()
            version = (latest or 0) + 1
            parent = latest if parent_version is LATEST else parent_version
            db.add(PlanVersion(job_id=job.id, version=version, parent_version=parent, source=source,
                               operations=row["operations"], plan=plan, created_at=_now()))
            await db.commit()
            return version
    return _await_db(insert())


def list_versions(job: "Job", include_plan: bool = False) -> list[dict]:
    if not _use_db():
        return [_row(r, include_plan) for r in _file_versions(job)]

    from app.jobs import _await_db

    async def load() -> list[dict]:
        assert AsyncSessionLocal is not None
        async with AsyncSessionLocal() as db:
            records = (await db.execute(select(PlanVersion).where(PlanVersion.job_id == job.id)
                                        .order_by(PlanVersion.version))).scalars().all()
            return [_row(r, include_plan) for r in records]
    return _await_db(load())


def get_version(job: "Job", version: int) -> Optional[dict]:
    return next((r for r in list_versions(job, include_plan=True) if r["version"] == version), None)


def latest_version(job: "Job") -> Optional[dict]:
    rows = list_versions(job, include_plan=True)
    return rows[-1] if rows else None
