"""FastAPI backend for Rafiei AI Editor.

Run: .venv/bin/python -m uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import importlib.util
import json
import logging
import os
import re
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

from logging_config import configure_structured_logging
configure_structured_logging()

from . import auth, jobs as jobstore
from .auth_routes import router as auth_router
from .database import DB_AVAILABLE, init_db
from .config import settings
from .routers import content, denoise, effects, fonts, jobs, music, plans, premiere, qc, render, style

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "production" and (not settings.JWT_SECRET or not DB_AVAILABLE or not settings.REDIS_URL):
        raise RuntimeError("Production requires JWT_SECRET, DATABASE_URL, and REDIS_URL")
    if DB_AVAILABLE:
        await init_db(create_schema=not production)
        log.info("Database connected")
    else:
        log.info("Running in JSON fallback mode (no DATABASE_URL)")
    missing = [name for name in ("elevenlabs", "faster_whisper")
               if importlib.util.find_spec(name) is None]
    if missing:
        log.warning(
            "Python runtime %s is missing %s; start the backend with "
            ".venv/bin/python -m uvicorn app.main:app --port 8000",
            sys.executable,
            ", ".join(missing),
        )
    else:
        log.info("Python runtime %s has ElevenLabs and Whisper available", sys.executable)
    n = jobstore.rescan()
    log.info("job registry rescan: loaded %d job(s) from %s", n, jobstore.JOBS_ROOT)
    yield


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
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        log.error("server_error status=%s path=%s", exc.status_code, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        log.error("unhandled request error method=%s path=%s", request.method, request.url.path)
        raise
    log.info(json.dumps({"event": "http_request", "method": request.method,
                         "path": request.url.path, "status": response.status_code,
                         "duration_ms": round((time.monotonic() - started) * 1000)}))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

app.include_router(auth_router)
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
    if request.method == "OPTIONS" or path == "/" or path.startswith("/auth/"):
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


@app.get("/")
def health():
    return {"ok": True, "service": "rafiei-ai-editor", "stage": 3}


@app.get("/health")
def health_check():
    return {"ok": True, "service": "rafiei-ai-editor", "stage": 3}
