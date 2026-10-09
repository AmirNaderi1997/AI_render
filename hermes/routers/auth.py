"""Instagram Login OAuth; callback uses a single-use state issued to a JWT user."""
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hermes.config import instagram_credentials, settings
from hermes.database import list_rows, save_row
from hermes.security import current_user, encrypt_token, owned_account, utcnow
from hermes.services.instagram_api import InstagramAPI, InstagramError

router = APIRouter(prefix="/api/hermes/auth", tags=["hermes-auth"])
_states = {}


async def _store_state(state, user_id):
    if settings.REDIS_URL:
        import redis.asyncio as redis
        try:
            client = redis.from_url(settings.REDIS_URL)
            await client.set("hermes:oauth:" + state, user_id, ex=600, nx=True)
            await client.aclose()
        except Exception as exc:
            raise HTTPException(503, detail={"code": "OAUTH_STATE_STORE_UNAVAILABLE"}) from exc
    else:
        for key, (_, expires) in list(_states.items()):
            if expires < time.time():
                _states.pop(key, None)
        _states[state] = (user_id, time.time() + 600)


async def _consume_state(state):
    if settings.REDIS_URL:
        import redis.asyncio as redis
        try:
            client = redis.from_url(settings.REDIS_URL)
            value = await client.getdel("hermes:oauth:" + state)
            await client.aclose()
            return value.decode() if value else None
        except Exception as exc:
            raise HTTPException(503, detail={"code": "OAUTH_STATE_STORE_UNAVAILABLE"}) from exc
    record = _states.pop(state, None)
    return record[0] if record and record[1] >= time.time() else None


def error(exc):
    raise HTTPException(exc.status, detail={"code": exc.code}) from exc


@router.post("/connect")
async def connect(user=Depends(current_user)):
    credentials = await instagram_credentials(user.id)
    if not all((credentials["app_id"], credentials["app_secret"], settings.INSTAGRAM_REDIRECT_URI)):
        raise HTTPException(503, detail={"code": "INSTAGRAM_NOT_CONFIGURED"})
    state = secrets.token_urlsafe(32)
    await _store_state(state, str(user.id))
    url = "https://www.instagram.com/oauth/authorize?" + urlencode({
        "client_id": credentials["app_id"], "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
        "response_type": "code", "scope": "instagram_business_basic,instagram_business_content_publish",
        "state": state,
    })
    return {"authorization_url": url, "expires_in": 600}


@router.get("/callback")
async def callback(code: str, state: str):
    user_id = await _consume_state(state)
    if not user_id:
        raise HTTPException(400, detail={"code": "OAUTH_STATE_INVALID"})
    api = InstagramAPI(user_id)
    try:
        short = await api.exchange_code(code)
        if "data" in short:
            data = short["data"]
            if not isinstance(data, list) or len(data) != 1 or "access_token" in short:
                raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
            short = data[0]
        short_token = short.get("access_token")
        if not short_token:
            raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
        long = await api.long_lived_token(short_token)
        token = long.get("access_token")
        if not token:
            raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
        api.token = token
        profile = await api.profile()
    except InstagramError as exc:
        error(exc)
    ig_id = str(profile.get("id") or short.get("user_id") or "")
    if not ig_id or not profile.get("username"):
        raise HTTPException(502, detail={"code": "INSTAGRAM_INVALID_RESPONSE"})
    existing = next((row for row in await list_rows("accounts") if str(row["user_id"]) == user_id and row["ig_user_id"] == ig_id), None)
    now = utcnow()
    account = {
        "id": existing["id"] if existing else uuid4().hex,
        "user_id": int(user_id) if settings.DATABASE_URL else user_id,
        "ig_user_id": ig_id, "username": profile["username"],
        "access_token": encrypt_token(token),
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(long.get("expires_in", 5184000)))).isoformat(),
        "created_at": existing["created_at"] if existing else now, "updated_at": now,
    }
    await save_row("accounts", account)
    return {key: value for key, value in account.items() if key != "access_token"}


class RefreshRequest(BaseModel):
    account_id: str


@router.post("/refresh")
async def refresh(body: RefreshRequest, user=Depends(current_user)):
    from hermes.security import decrypt_token
    account = await owned_account(body.account_id, user)
    api = InstagramAPI(account["ig_user_id"])
    try:
        result = await api.refresh_token(decrypt_token(account["access_token"]))
    except InstagramError as exc:
        error(exc)
    if not result.get("access_token"):
        raise HTTPException(502, detail={"code": "INSTAGRAM_INVALID_RESPONSE"})
    account.update(access_token=encrypt_token(result["access_token"]),
                   token_expires_at=(datetime.now(timezone.utc) + timedelta(seconds=int(result.get("expires_in", 5184000)))).isoformat(),
                   updated_at=utcnow())
    await save_row("accounts", account)
    return {"account_id": account["id"], "token_expires_at": account["token_expires_at"]}


@router.get("/accounts")
async def accounts(user=Depends(current_user)):
    return [{key: value for key, value in row.items() if key != "access_token"}
            for row in await list_rows("accounts") if str(row["user_id"]) == str(user.id)]
