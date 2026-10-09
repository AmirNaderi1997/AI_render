"""SMTP email delivery helpers."""
from __future__ import annotations

from email.message import EmailMessage
import smtplib
import ssl

from .config import settings


def smtp_is_configured() -> bool:
    """Return whether the SMTP host and authentication credentials are set."""
    return bool(settings.SMTP_HOST.strip() and settings.SMTP_USER.strip() and settings.SMTP_PASSWORD)


def send_email(to_address: str, subject: str, text_body: str) -> None:
    """Send a plain-text email through the configured SMTP server.

    Port 465 uses implicit TLS. Other ports use STARTTLS before authenticating.
    """
    if not smtp_is_configured():
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_USER
    message["To"] = to_address
    message.set_content(text_body)

    context = ssl.create_default_context()
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=20) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
