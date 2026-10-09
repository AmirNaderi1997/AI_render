"""Shared app JWT identity, ownership checks, and token encryption."""
import base64
import hashlib
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request

from app import auth as main_auth
from hermes.config import settings


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def cipher():
    secret = settings.HERMES_TOKEN_KEY or settings.JWT_SECRET or main_auth.jwt_secret()
    if not secret:
        raise HTTPException(503, detail={"code": "TOKEN_KEY_NOT_CONFIGURED"})
    key = base64.urlsafe_b64encode(hashlib.sha256(("hermes-fernet-v1:" + secret).encode()).digest())
    return Fernet(key)


def settings_cipher():
    """Cipher for UI-saved credentials; HERMES_ENCRYPTION_KEY, else the stable token key."""
    secret = settings.HERMES_ENCRYPTION_KEY or settings.HERMES_TOKEN_KEY
    if not secret:
        raise HTTPException(503, detail={"code": "ENCRYPTION_KEY_NOT_CONFIGURED"})
    key = base64.urlsafe_b64encode(hashlib.sha256(("hermes-settings-fernet-v1:" + secret).encode()).digest())
    return Fernet(key)


def encrypt_setting(value):
    return settings_cipher().encrypt(value.encode()).decode()


def decrypt_setting(value):
    try:
        return settings_cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(503, detail={"code": "SETTINGS_DECRYPT_FAILED"}) from exc


def encrypt_token(token):
    return cipher().encrypt(token.encode()).decode()


def decrypt_token(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(503, detail={"code": "TOKEN_DECRYPT_FAILED"}) from exc


async def current_user(request: Request):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED"})
    try:
        user = (await main_auth.db_get_current_user_from_token(token)
                if main_auth.USE_DB else main_auth.get_current_user_from_token(token))
        if not user.is_active:
            raise ValueError("disabled")
        return user
    except ValueError as exc:
        raise HTTPException(401, detail={"code": "AUTH_INVALID"}) from exc


async def owned_account(account_id, user):
    from hermes.database import get_row
    account = await get_row("accounts", account_id)
    if not account or str(account["user_id"]) != str(user.id):
        raise HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND"})
    return account


async def owned_post(post_id, user):
    from hermes.database import get_row
    post = await get_row("posts", post_id)
    if not post:
        raise HTTPException(404, detail={"code": "POST_NOT_FOUND"})
    await owned_account(post["account_id"], user)
    return post
