"""FastAPI backend for Rafiei AI Editor.

Run: .venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import importlib.util
import logging
import os
import re
import sys
import time
from pathlib import Path
import subprocess

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from logging_config import configure_structured_logging
from request_context import request_id_from_header, request_id_var
configure_structured_logging()

from . import auth, jobs as jobstore
from .auth_routes import router as auth_router
from .database import DB_AVAILABLE, close_db, engine, init_db
from .config import settings
from .routers import ai, content, denoise, effects, fonts, jobs, music, plans, premiere, qc, render, style
from .health import router as health_router

log = logging.getLogger(__name__)
# Keep structured request events visible even when the process manager leaves
# the root logger at its default WARNING level.
log.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "production" and (not settings.JWT_SECRET or not DB_AVAILABLE or not settings.REDIS_URL):
        raise RuntimeError("Production requires JWT_SECRET, DATABASE_URL, and REDIS_URL")
    if DB_AVAILABLE:
        # Schema ownership belongs to Alembic. Run it before serving so a new
        # app process cannot receive requests against an old schema. Gunicorn
        # runs this lifespan in every worker, so serialize migration runners
        # across workers and app replicas with a PostgreSQL advisory lock.
        if engine is None:
            raise RuntimeError("database engine is unavailable")
        async with engine.connect() as migration_lock:
            await migration_lock.execute(text("SELECT pg_advisory_lock(731904221)"))
            await migration_lock.commit()
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    check=True,
                    cwd=str(Path(__file__).resolve().parents[1]),
                )
            finally:
                await migration_lock.execute(text("SELECT pg_advisory_unlock(731904221)"))
                await migration_lock.commit()
        await init_db(create_schema=False)
        log.info("Database connected and migrations are current")
    else:
        log.info("Running in JSON fallback mode (no DATABASE_URL)")
    optional_runtimes = []
    if settings.WHISPER_ENABLED:
        optional_runtimes.append("faster_whisper")
    if settings.TTS_PROVIDER.strip().lower() == "elevenlabs":
        optional_runtimes.append("elevenlabs")
    missing = [name for name in optional_runtimes if importlib.util.find_spec(name) is None]
    if missing:
        log.warning(
            "Python runtime %s is missing %s; start the backend with "
            ".venv/bin/python -m uvicorn app.main:app --port 8000",
            sys.executable,
            ", ".join(missing),
        )
    else:
        log.info("Python runtime %s has configured optional audio runtimes available", sys.executable)
    n = jobstore.rescan()
    log.info("job registry rescan: loaded %d job(s) from %s", n, jobstore.JOBS_ROOT)
    yield
    await close_db()


production = settings.APP_ENV == "production"
if production:
    if len(settings.JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
    origins = [x.strip() for x in settings.CORS_ORIGINS.split(",") if x.strip()]
    if any(not x.startswith("https://") or "*" in x for x in origins):
        raise RuntimeError("CORS_ORIGINS must contain exact HTTPS origins in production")
else:
    origins = ["http://localhost:5173", "http://127.0.0.1:5173", "null"]
app = FastAPI(title="Rafiei AI Editor", version="0.1.0", lifespan=lifespan,
              docs_url=None if production else "/docs", redoc_url=None if production else "/redoc",
              openapi_url=None if production else "/openapi.json")

enforce_allowed_hosts = any(
    value.strip().lower() == "production"
    for value in (
        settings.APP_ENV,
        os.environ.get("APP_ENV", ""),
        os.environ.get("ENV", ""),
        os.environ.get("ENVIRONMENT", ""),
    )
)
if enforce_allowed_hosts:
    hosts = [x.strip() for x in settings.ALLOWED_HOSTS.split(",") if x.strip()]
    if not hosts or any("*" in host for host in hosts):
        raise RuntimeError("ALLOWED_HOSTS requires exact hostnames in production")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
elif settings.ALLOWED_HOSTS.strip():
    log.warning("ALLOWED_HOSTS is configured but ignored because APP_ENV/ENV/ENVIRONMENT is not production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=not production or bool(origins),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        request.state.exception_type = type(exc).__name__
        log.error("server_error status=%s path=%s", exc.status_code, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


app.include_router(auth_router)
app.include_router(health_router)
app.include_router(ai.router)
app.include_router(jobs.router)
app.include_router(plans.router)
app.include_router(render.router)
app.include_router(music.router)
app.include_router(music.legacy_router)
app.include_router(effects.router)
app.include_router(style.router)
app.include_router(style.legacy_router)
app.include_router(content.router)
app.include_router(content.legacy_router)
app.include_router(denoise.router)
app.include_router(premiere.router)
app.include_router(qc.router)
app.include_router(fonts.router)
app.include_router(fonts.legacy_router)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    def unauthorized():
        response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    path = request.url.path
    if request.method == "OPTIONS" or path in {"/", "/health", "/api/health/ready"} or path.startswith("/auth/"):
        return await call_next(request)
    # The CEP panel cannot hold the user's web-app JWT. These protocol routes
    # are protected by loopback checks, one-time pairing codes, and the
    # operation-scoped bearer token validated by premiere_bridge itself.
    if path in {
        "/integrations/premiere/bridge/pending",
        "/integrations/premiere/bridge/pair",
    } or re.fullmatch(r"/jobs/[0-9a-f]{12}/premiere/bridge/receipt", path):
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return unauthorized()
    try:
        user = (await auth.db_get_current_user_from_token(header[7:])
                if auth.USE_DB else auth.get_current_user_from_token(header[7:]))
        request.state.user = user
    except ValueError:
        return unauthorized()
    return await call_next(request)


@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = request_id_from_header(request.headers.get("X-Request-ID"))
    token = request_id_var.set(request_id)
    started = time.monotonic()
    exception_type = None
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            exception_type = type(exc).__name__
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        exception_type = exception_type or getattr(request.state, "exception_type", None)
        extra = {
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code >= 500:
            extra["exception_type"] = exception_type or "HTTPException"
            log.error("http_request", extra=extra)
        elif duration_ms > 2000:
            log.warning("http_request", extra=extra)
        else:
            log.info("http_request", extra=extra)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
    finally:
        request_id_var.reset(token)


@app.get("/")
def health():
    return {"ok": True, "service": "rafiei-ai-editor", "stage": 3}


@app.get("/health")
def health_check():
    return {"ok": True}
