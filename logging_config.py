"""Shared structured logging and sensitive-value redaction."""
from __future__ import annotations

import ipaddress
import logging
import re
import traceback
from typing import Any

from pythonjsonlogger import jsonlogger
from request_context import RequestContextFilter


_REDACTED = "[REDACTED]"
_EMAIL_RE = re.compile(
    r"(?i)(?<![\w.+-])[\w.+-]+(?:@|%40)[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
_JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])")
_CREDENTIAL_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|token|password|passwd|pwd|"
    r"api[_-]?key|secret|client[_-]?secret|authorization|auth[_-]?key)\b['\"]?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_RE = re.compile(r"\b(?:sk|pk|rk|key)-[A-Za-z0-9_-]{12,}\b")
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_IPV6_CANDIDATE_RE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f:.]{0,39}(?![\w:])")
_SENSITIVE_FIELD_RE = re.compile(
    r"(?i)(?:token|password|passwd|pwd|api[_-]?key|secret|authorization|auth[_-]?key)"
)


def redact_sensitive(value: str) -> str:
    """Mask credential-like values, email addresses, and IP addresses."""
    value = _CREDENTIAL_RE.sub(lambda match: match.group(1) + _REDACTED, value)
    value = _BEARER_RE.sub("Bearer " + _REDACTED, value)
    value = _JWT_RE.sub(_REDACTED, value)
    value = _KEY_RE.sub(_REDACTED, value)
    value = _EMAIL_RE.sub(_REDACTED, value)
    value = _IPV4_RE.sub(lambda match: _REDACTED if _is_ip(match.group(0)) else match.group(0), value)
    value = _IPV6_CANDIDATE_RE.sub(lambda match: _REDACTED if _is_ip(match.group(0)) else match.group(0), value)
    return value


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _redact_value(value: Any, field_name: str = "") -> Any:
    if _SENSITIVE_FIELD_RE.search(field_name):
        return _REDACTED
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, dict):
        return {key: _redact_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, field_name) for item in value)
    return value


class SensitiveDataFilter(logging.Filter):
    """Redact rendered log content before it reaches any configured handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact_sensitive(rendered)
        record.args = ()

        if record.exc_info:
            record.exception = redact_sensitive("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
            record.exc_text = None
        if record.stack_info:
            record.stack_info = redact_sensitive(record.stack_info)

        # Extra fields are serialized by JsonFormatter too, so redact their values.
        standard = logging.makeLogRecord({}).__dict__
        for key, value in tuple(record.__dict__.items()):
            if key not in standard and key != "exception":
                record.__dict__[key] = _redact_value(value, key)
        return True


def configure_structured_logging() -> None:
    """Install one JSON stderr handler for application, server, and worker logs."""
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RequestContextFilter())
    handler.addFilter(SensitiveDataFilter())

    # Uvicorn and Celery configure named handlers during startup. Route their
    # records through the shared root handler without changing any logger level.
    root.handlers[:] = [handler]
    for logger_name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            logger.handlers.clear()
            logger.propagate = True
