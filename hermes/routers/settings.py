"""Per-user Instagram credentials saved from the browser; responses never contain secret values."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hermes.config import instagram_credentials, settings_row_id, stored_instagram_credentials
from hermes.database import delete_row, get_row, save_row
from hermes.security import current_user, encrypt_setting, utcnow
from hermes.services.instagram_api import InstagramAPI, InstagramError

router = APIRouter(prefix="/api/hermes/settings/instagram", tags=["hermes-settings"])


class InstagramCredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(max_length=4096)
    instagram_user_id: str = Field(max_length=512)
    app_id: str = Field(max_length=512)
    app_secret: str = Field(max_length=4096)

    @field_validator("*")
    @classmethod
    def not_blank(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class InstagramStatus(BaseModel):
    configured: bool
    instagram_user_id: str | None = None


class InstagramConnection(InstagramStatus):
    connection_status: Literal["connected", "disconnected", "expired"]


async def _status(user_id) -> InstagramStatus:
    stored = await stored_instagram_credentials(user_id)
    configured = all(stored.get(field) for field in ("access_token", "instagram_user_id", "app_id", "app_secret"))
    return InstagramStatus(configured=configured, instagram_user_id=stored.get("instagram_user_id") if configured else None)


@router.get("", response_model=InstagramStatus)
async def get_instagram_settings(user=Depends(current_user)):
    return await _status(str(user.id))


@router.post("", response_model=InstagramStatus)
async def save_instagram_settings(body: InstagramCredentialsInput, user=Depends(current_user)):
    user_id = str(user.id)
    row_id = settings_row_id(user_id)
    existing = await get_row("settings", row_id)
    now = utcnow()
    await save_row("settings", {
        "id": row_id,
        "user_id": int(user_id) if user_id.isdigit() else user_id,
        "provider": "instagram",
        "encrypted_credentials": {field: encrypt_setting(value) for field, value in body.model_dump().items()},
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    })
    return await _status(user_id)


@router.delete("", response_model=InstagramStatus)
async def delete_instagram_settings(user=Depends(current_user)):
    await delete_row("settings", settings_row_id(str(user.id)))
    return await _status(str(user.id))


@router.post("/test", response_model=InstagramConnection)
async def test_instagram_connection(user=Depends(current_user)):
    """Checks this user's saved credentials against the Graph API."""
    user_id = str(user.id)
    values = await instagram_credentials(user_id)
    if not values["access_token"] or not values["business_account_id"]:
        raise HTTPException(422, detail={"code": "TOKEN_AND_BUSINESS_ACCOUNT_REQUIRED"})
    try:
        profile = await InstagramAPI(user_id, values["access_token"]).profile()
        connection = "connected" if str(profile.get("id", "")) == values["business_account_id"] else "disconnected"
    except InstagramError as exc:
        if exc.code != "INSTAGRAM_AUTH_ERROR":
            raise HTTPException(exc.status, detail={"code": exc.code}) from exc
        connection = "expired"
    status = await _status(user_id)
    return InstagramConnection(**status.model_dump(), connection_status=connection)
