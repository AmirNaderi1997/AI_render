"""Request correlation context shared by HTTP handlers and Celery workers."""
from __future__ import annotations

import contextvars
import logging
import re
import uuid


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def request_id_from_header(value: str | None) -> str:
    """Keep a bounded, log-safe caller ID or create a UUID4 correlation ID."""
    candidate = (value or "").strip()
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else str(uuid.uuid4())


def current_request_id() -> str | None:
    return request_id_var.get()


def celery_request_headers() -> dict[str, str]:
    """Return trace headers without changing any Celery task signature."""
    request_id = current_request_id()
    return {"request_id": request_id} if request_id else {}


class RequestContextFilter(logging.Filter):
    """Attach the active request ID to every structured application record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = current_request_id()
        return True
