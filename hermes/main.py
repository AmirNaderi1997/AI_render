"""Run locally: python -m uvicorn hermes.main:app --port 8001."""
import asyncio
import logging
import os
import secrets
import string
import time
from contextlib import asynccontextmanager

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from logging_config import configure_structured_logging
from request_context import request_id_from_header, request_id_var
configure_structured_logging()

from hermes.config import settings
from hermes.database import init_db
from hermes.routers import advisor, analytics, auth, posts, scheduler, settings as settings_router
from hermes.security import current_user
from hermes.services.scheduler_service import local_schedule_loop

log = logging.getLogger("uvicorn.error")

def _is_production():
    # APP_ENV is also read from the configured settings file by pydantic,
    # while ENV and ENVIRONMENT may be supplied directly by the process.
    return any(
        value.strip().lower() == "production"
        for value in (
            settings.APP_ENV,
            os.environ.get("APP_ENV", ""),
            os.environ.get("ENV", ""),
            os.environ.get("ENVIRONMENT", ""),
        )
    )


enforce_production_config = _is_production()


def _ensure_token_key():
    if len(settings.HERMES_TOKEN_KEY) >= 32:
        return
    if enforce_production_config:
        raise RuntimeError("HERMES_TOKEN_KEY must be at least 32 characters in production")
    log.warning(
        "HERMES_TOKEN_KEY is unset or shorter than 32 characters; "
        "using a random session-only development key"
    )
    alphabet = string.ascii_letters + string.digits
    settings.HERMES_TOKEN_KEY = "".join(secrets.choice(alphabet) for _ in range(32))


def _ensure_encryption_key():
    """Credentials saved in the UI use HERMES_ENCRYPTION_KEY, then HERMES_TOKEN_KEY, then a dev-only random key."""
    if settings.HERMES_ENCRYPTION_KEY or len(settings.HERMES_TOKEN_KEY) >= 32:
        return
    if enforce_production_config:
        raise RuntimeError("HERMES_ENCRYPTION_KEY (or HERMES_TOKEN_KEY) must be set in production")
    log.warning(
        "HERMES_ENCRYPTION_KEY is unset; using a random session-only development key, "
        "so credentials saved in Hermes settings cannot be read after a restart"
    )
    settings.HERMES_ENCRYPTION_KEY = Fernet.generate_key().decode()


@asynccontextmanager
async def lifespan(app):
    _ensure_encryption_key()
    _ensure_token_key()
    await init_db(create_schema=not production)
    task = asyncio.create_task(local_schedule_loop()) if not settings.REDIS_URL else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


production = settings.APP_ENV == "production"
app = FastAPI(title="Hermes Agent", version="0.1.0", lifespan=lifespan,
              docs_url=None if production else "/docs", redoc_url=None if production else "/redoc",
              openapi_url=None if production else "/openapi.json")
if enforce_production_config:
    hosts = [host.strip() for host in settings.ALLOWED_HOSTS.split(",") if host.strip()]
    if not hosts or any("*" in host for host in hosts):
        raise RuntimeError("ALLOWED_HOSTS requires exact hostnames in production")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
elif settings.ALLOWED_HOSTS.strip():
    log.warning("ALLOWED_HOSTS is configured but ignored because APP_ENV/ENV/ENVIRONMENT is not production")
app.add_middleware(CORSMiddleware, allow_origins=[] if production else ["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=not production, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                   expose_headers=["X-Request-ID"])


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        request.state.exception_type = type(exc).__name__
        log.error("server_error status=%s path=%s", exc.status_code, request.url.path)
        return JSONResponse({"detail": {"code": "INTERNAL_ERROR"}}, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


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
            response = JSONResponse({"detail": {"code": "INTERNAL_ERROR"}}, status_code=500)
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        exception_type = exception_type or getattr(request.state, "exception_type", None)
        extra = {"event": "http_request", "service": "hermes", "request_id": request_id,
                 "method": request.method, "path": request.url.path,
                 "status_code": response.status_code, "duration_ms": duration_ms}
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
for router in (auth.router, posts.router, scheduler.router, analytics.router, advisor.router, settings_router.router):
    app.include_router(router)


@app.get("/health")
async def health_public():
    return {"status": "ok"}


@app.get("/api/hermes/health")
async def health(user=Depends(current_user)):
    return {"status": "ok", "storage": "postgresql" if settings.DATABASE_URL else "json"}
