"""Auth API routes."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import auth
from . import email as email_sender

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


async def get_current_user(request: Request) -> auth.User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = header[7:]
    try:
        if auth.USE_DB:
            return await auth.db_get_current_user_from_token(token)
        return auth.get_current_user_from_token(token)
    except ValueError:
        raise HTTPException(401, "Not authenticated")


class SignupBody(BaseModel):
    email: str
    name: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str


class LogoutBody(BaseModel):
    refresh_token: str | None = None


REFRESH_COOKIE = "ai_render_refresh_token"


def _cookie_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return forwarded_proto == "https" or request.url.scheme == "https"


def _set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=auth.REFRESH_TOKEN_EXPIRES,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _token_response(
    result: dict,
    request: Request,
    *,
    status_code: int = 200,
) -> JSONResponse:
    response = JSONResponse(result, status_code=status_code)
    _set_refresh_cookie(response, request, result["refresh_token"])
    return response


@router.post("/signup", status_code=201)
async def signup(body: SignupBody, request: Request):
    try:
        user = (await auth.db_register(body.email, body.name, body.password)
                if auth.USE_DB else auth.register(body.email, body.name, body.password))
    except ValueError as e:
        msg = str(e)
        if msg == "DUPLICATE_EMAIL":
            raise HTTPException(409, "An account with this email already exists")
        raise HTTPException(422, msg)
    result = (await auth.db_login(user.email, body.password)
              if auth.USE_DB else auth.login(user.email, body.password))
    return _token_response(result, request, status_code=201)


@router.post("/login")
async def login(body: LoginBody, request: Request):
    try:
        result = (await auth.db_login(body.email, body.password)
                  if auth.USE_DB else auth.login(body.email, body.password))
        return _token_response(result, request)
    except ValueError as e:
        msg = str(e)
        if msg in ("INVALID_CREDENTIALS", "ACCOUNT_DISABLED"):
            raise HTTPException(401, "Invalid email or password")
        raise HTTPException(401, str(e))


@router.post("/refresh")
async def refresh_token(request: Request, body: RefreshBody | None = None):
    refresh_value = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    if not refresh_value:
        raise HTTPException(401, "Invalid or expired refresh token")
    try:
        return (await auth.db_refresh(refresh_value)
                if auth.USE_DB else auth.refresh(refresh_value))
    except ValueError:
        raise HTTPException(401, "Invalid or expired refresh token")


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody, request: Request):
    token = (await auth.db_request_reset(body.email)
             if auth.USE_DB else auth.request_reset(body.email))
    if not email_sender.smtp_is_configured():
        if token:
            log.warning("SMTP is not configured; password reset token for %s: %s", body.email, token)
        return JSONResponse(
            status_code=503,
            content={"detail": "Password reset email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD."},
        )

    if token:
        reset_url = f"{str(request.base_url).rstrip('/')}/reset-password?{urlencode({'token': token})}"
        try:
            await asyncio.to_thread(
                email_sender.send_email,
                body.email.strip(),
                "Reset your AI Render password",
                "We received a request to reset your AI Render password.\n\n"
                f"Open this link within one hour to choose a new password:\n{reset_url}\n\n"
                "If you did not request this, you can ignore this email.",
            )
        except Exception:
            log.exception("Password reset email delivery failed")
            return JSONResponse(
                status_code=503,
                content={"detail": "Password reset email could not be sent. Check the SMTP settings and try again."},
            )
    return {"ok": True, "message": "If this email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody):
    try:
        if auth.USE_DB:
            await auth.db_reset_password(body.token, body.new_password)
        else:
            auth.reset_password(body.token, body.new_password)
    except ValueError as e:
        msg = str(e)
        if "EXPIRED" in msg:
            raise HTTPException(400, "Reset token has expired")
        if "INVALID" in msg:
            raise HTTPException(400, "Invalid reset token")
        raise HTTPException(422, msg)
    return {"ok": True}


@router.get("/me")
def me(user: auth.User = Depends(get_current_user)):
    return user.public_dict()


@router.post("/logout")
async def logout(request: Request, body: LogoutBody | None = None):
    refresh_value = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    if refresh_value:
        if auth.USE_DB:
            await auth.db_logout(refresh_value)
        else:
            auth.logout(refresh_value)
    response = JSONResponse({"ok": True})
    response.delete_cookie(REFRESH_COOKIE, path="/", samesite="lax")
    return response
