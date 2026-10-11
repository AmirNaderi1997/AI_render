"""Persist a user's default approved plan style in PostgreSQL.

The small JSON fallback keeps local development without a database usable; all
Docker deployments use the PostgreSQL table.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal, DB_AVAILABLE
from app.models import PlanStyleSelection, PlanStyleVisibility
from brain.style_profile import LEARNED_PROFILES_DIR

_SAFE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SELECTIONS = LEARNED_PROFILES_DIR.parent / "plan-style-selections"


def _uid(user_id) -> str:
    value = str(user_id)
    if not value.isdecimal():
        raise ValueError("invalid user id")
    return value


def _path(user_id) -> Path:
    return _SELECTIONS / f"{_uid(user_id)}.json"


def _run(coro):
    from app.jobs import _await_db
    return _await_db(coro)


def get_selection(user_id) -> dict:
    uid = _uid(user_id)
    if DB_AVAILABLE:
        async def query():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(PlanStyleSelection).where(
                    PlanStyleSelection.user_id == int(uid)))).scalar_one_or_none()
                return {"style_id": row.style_id, "version": row.version, "selected": True} if row else {
                    "style_id": None, "version": None, "selected": False,
                }
        return _run(query())
    path = _path(uid)
    if not path.is_file():
        return {"style_id": None, "version": None, "selected": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"style_id": data.get("style_id"), "version": data.get("version"), "selected": True}


def set_selection(user_id, style_id: str | None, version: int | None) -> dict:
    uid = _uid(user_id)
    if style_id is not None and not _SAFE.fullmatch(style_id):
        raise ValueError("invalid style id")
    if DB_AVAILABLE:
        async def upsert():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(PlanStyleSelection).where(
                    PlanStyleSelection.user_id == int(uid)))).scalar_one_or_none()
                if row is None:
                    row = PlanStyleSelection(user_id=int(uid), style_id=style_id, version=version,
                                             updated_at=datetime.now(timezone.utc))
                    db.add(row)
                else:
                    row.style_id, row.version = style_id, version
                    row.updated_at = datetime.now(timezone.utc)
                await db.commit()
        _run(upsert())
    else:
        path = _path(uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"style_id": style_id, "version": version}), encoding="utf-8")
        temporary.replace(path)
    return {"style_id": style_id, "version": version, "selected": True}


def clear_selection(user_id) -> dict:
    uid = _uid(user_id)
    if DB_AVAILABLE:
        async def clear():
            async with AsyncSessionLocal() as db:
                await db.execute(delete(PlanStyleSelection).where(PlanStyleSelection.user_id == int(uid)))
                await db.commit()
        _run(clear())
    else:
        _path(uid).unlink(missing_ok=True)
    return {"style_id": None, "version": None, "selected": False}


def get_default_hidden(user_id) -> bool:
    uid = _uid(user_id)
    if DB_AVAILABLE:
        async def query():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(PlanStyleVisibility).where(
                    PlanStyleVisibility.user_id == int(uid)))).scalar_one_or_none()
                return bool(row and row.default_hidden)
        return _run(query())
    path = _SELECTIONS / f"{uid}-visibility.json"
    return bool(json.loads(path.read_text(encoding="utf-8")).get("default_hidden")) if path.is_file() else False


def set_default_hidden(user_id, hidden: bool) -> bool:
    uid = _uid(user_id)
    if DB_AVAILABLE:
        async def upsert():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(PlanStyleVisibility).where(
                    PlanStyleVisibility.user_id == int(uid)))).scalar_one_or_none()
                if row is None:
                    db.add(PlanStyleVisibility(user_id=int(uid), default_hidden=hidden))
                else:
                    row.default_hidden = hidden
                await db.commit()
        _run(upsert())
    else:
        path = _SELECTIONS / f"{uid}-visibility.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"default_hidden": hidden}), encoding="utf-8")
        temporary.replace(path)
    return hidden


def clear_removed_style(style_id: str, version: int) -> None:
    """Unset defaults that point to an approved version removed from the library."""
    if DB_AVAILABLE:
        async def clear():
            async with AsyncSessionLocal() as db:
                await db.execute(delete(PlanStyleSelection).where(
                    PlanStyleSelection.style_id == style_id,
                    PlanStyleSelection.version == version,
                ))
                await db.commit()
        _run(clear())
        return
    if not _SELECTIONS.is_dir():
        return
    for path in _SELECTIONS.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("style_id") == style_id and data.get("version") == version:
                path.unlink()
        except (OSError, ValueError):
            continue
