"""Public liveness-adjacent readiness checks with bounded dependency probes."""
from __future__ import annotations

import asyncio
import shutil
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import database
from app.celery_app import CELERY_AVAILABLE, celery
from app.config import settings


router = APIRouter()
CHECK_TIMEOUT_SECONDS = 2.0
CELERY_CACHE_SECONDS = 15.0
_celery_cache_lock = threading.Lock()
_celery_cache: tuple[float, bool] | None = None


async def _check_database() -> bool:
    if database.engine is None:
        return False
    async with database.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    if not settings.REDIS_URL:
        return False
    import redis.asyncio as redis

    client = redis.from_url(settings.REDIS_URL)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


def _celery_ping_cached() -> bool:
    global _celery_cache
    now = time.monotonic()
    with _celery_cache_lock:
        if _celery_cache is not None and now - _celery_cache[0] < CELERY_CACHE_SECONDS:
            return _celery_cache[1]
        passed = False
        if CELERY_AVAILABLE and celery is not None:
            replies = celery.control.inspect(timeout=CHECK_TIMEOUT_SECONDS / 2).ping()
            passed = bool(replies) and all(value.get("ok") == "pong" for value in replies.values())
        _celery_cache = (time.monotonic(), passed)
        return passed


async def _check_celery() -> bool:
    return await asyncio.to_thread(_celery_ping_cached)


def _disk_has_capacity() -> bool:
    minimum = int(settings.HEALTH_MIN_DISK_FREE_GB * 1024 ** 3)
    paths = (Path(settings.JOBS_DIR).expanduser(), Path(settings.ASSETS_DIR).expanduser())
    checked_devices: set[int] = set()
    for path in paths:
        if not path.exists():
            return False
        device = path.stat().st_dev
        if device in checked_devices:
            continue
        checked_devices.add(device)
        if shutil.disk_usage(path).free < minimum:
            return False
    return True


async def _check_disk() -> bool:
    return await asyncio.to_thread(_disk_has_capacity)


async def _check_ffmpeg() -> bool:
    return await asyncio.to_thread(lambda: shutil.which("ffmpeg") is not None)


async def _timed_check(check: Callable[[], Awaitable[bool]]) -> dict[str, object]:
    started = time.monotonic()
    try:
        passed = bool(await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS))
    except Exception:
        passed = False
    return {
        "status": "pass" if passed else "fail",
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }


@router.get("/api/health/ready")
async def readiness():
    names = ("database", "redis", "celery", "disk", "ffmpeg")
    results = await asyncio.gather(*(
        _timed_check(check)
        for check in (_check_database, _check_redis, _check_celery, _check_disk, _check_ffmpeg)
    ))
    checks = dict(zip(names, results))
    critical_failed = any(checks[name]["status"] == "fail" for name in ("database", "redis"))
    noncritical_failed = any(checks[name]["status"] == "fail" for name in ("celery", "disk", "ffmpeg"))
    body = {
        "ok": not critical_failed,
        "degraded": not critical_failed and noncritical_failed,
        "checks": checks,
    }
    return JSONResponse(body, status_code=503 if critical_failed else 200)
