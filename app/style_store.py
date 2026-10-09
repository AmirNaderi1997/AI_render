"""Per-user storage for Style Learner reference analyses and the learned profile.

PostgreSQL when DATABASE_URL is set; otherwise per-user JSON files (dev/test fallback).
Reference video files always live on disk under the user's references directory.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal, DB_AVAILABLE
from app.models import LearnedStyleProfile, StyleReference
from brain.style_profile import LEARNED_PROFILES_DIR

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
_SAFE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _uid(user_id) -> str:
    uid = str(user_id)
    if not _SAFE.fullmatch(uid):
        raise ValueError("invalid user id")
    return uid


def user_dir(user_id) -> Path:
    return LEARNED_PROFILES_DIR / "users" / _uid(user_id)


def refs_dir(user_id) -> Path:
    path = user_dir(user_id) / "references"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(coro):
    from app.jobs import _await_db
    return _await_db(coro)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def list_references(user_id) -> list[dict]:
    if DB_AVAILABLE:
        async def query():
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(StyleReference).where(StyleReference.user_id == int(user_id))
                                         .order_by(StyleReference.id))).scalars().all()
                return [{**row.analysis, "_file": row.digest} for row in rows]
        return _run(query())
    items = []
    for path in sorted(refs_dir(user_id).glob("ref-*.json")):
        try:
            items.append({**json.loads(path.read_text(encoding="utf-8")), "_file": path.stem[len("ref-"):]})
        except Exception:
            continue
    return items


def add_reference(user_id, digest: str, analysis: dict) -> None:
    if DB_AVAILABLE:
        async def upsert():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(StyleReference).where(
                    StyleReference.user_id == int(user_id), StyleReference.digest == digest))).scalar_one_or_none()
                if row is None:
                    db.add(StyleReference(user_id=int(user_id), digest=digest,
                                          source_file=str(analysis.get("source_file", ""))[:500], analysis=analysis,
                                          created_at=datetime.now(timezone.utc)))
                else:
                    row.analysis, row.source_file = analysis, str(analysis.get("source_file", ""))[:500]
                await db.commit()
        _run(upsert())
        return
    _write_json(refs_dir(user_id) / f"ref-{digest}.json", analysis)


def delete_reference(user_id, digest: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{1,32}", digest):
        return False
    if DB_AVAILABLE:
        async def remove():
            async with AsyncSessionLocal() as db:
                result = await db.execute(delete(StyleReference).where(
                    StyleReference.user_id == int(user_id), StyleReference.digest == digest))
                await db.commit()
                return result.rowcount > 0
        found = _run(remove())
    else:
        path = refs_dir(user_id) / f"ref-{digest}.json"
        found = path.is_file()
        path.unlink(missing_ok=True)
    for video in refs_dir(user_id).glob(f"ref-{digest}.*"):
        if video.suffix in VIDEO_SUFFIXES:
            video.unlink(missing_ok=True)
    return found


def reference_video_path(user_id, digest: str) -> Optional[Path]:
    """Return a user's stored reference video, after confirming ownership."""
    if not re.fullmatch(r"[0-9a-f]{1,32}", digest):
        return None
    if not any(item.get("_file") == digest for item in list_references(user_id)):
        return None
    candidates = [*refs_dir(user_id).glob(f"ref-{digest}.*")]
    # Migrated analyses remain tied to the original global media directory.
    legacy_dir = LEARNED_PROFILES_DIR / "references"
    if legacy_dir.is_dir():
        candidates.extend(legacy_dir.glob(f"ref-{digest}.*"))
    return next((p for p in candidates if p.suffix.lower() in VIDEO_SUFFIXES and p.is_file()), None)


def load_profile(user_id) -> Optional[dict]:
    if user_id is None:
        return None
    if DB_AVAILABLE:
        async def query():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(LearnedStyleProfile).where(
                    LearnedStyleProfile.user_id == int(user_id)))).scalar_one_or_none()
                return row.profile if row else None
        return _run(query())
    path = user_dir(user_id) / "learned.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def save_profile(user_id, profile: dict) -> None:
    if DB_AVAILABLE:
        async def upsert():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(LearnedStyleProfile).where(
                    LearnedStyleProfile.user_id == int(user_id)))).scalar_one_or_none()
                if row is None:
                    db.add(LearnedStyleProfile(user_id=int(user_id), profile=profile,
                                               updated_at=datetime.now(timezone.utc)))
                else:
                    row.profile, row.updated_at = profile, datetime.now(timezone.utc)
                await db.commit()
        _run(upsert())
        return
    _write_json(user_dir(user_id) / "learned.json", profile)


def delete_profile(user_id) -> None:
    if DB_AVAILABLE:
        async def remove():
            async with AsyncSessionLocal() as db:
                await db.execute(delete(LearnedStyleProfile).where(LearnedStyleProfile.user_id == int(user_id)))
                await db.commit()
        _run(remove())
        return
    (user_dir(user_id) / "learned.json").unlink(missing_ok=True)
