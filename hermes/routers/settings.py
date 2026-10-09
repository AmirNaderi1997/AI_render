"""Per-user Instagram credentials; API responses never contain secret values."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from hermes.config import instagram_credentials
from hermes.database import get_row, save_row
from hermes.security import current_user, encrypt_token, utcnow
from hermes.services.instagram_api import InstagramAPI, InstagramError

router = APIRouter(prefix="/api/hermes/settings", tags=["hermes-settings"])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(default="", max_length=4096)
    app_id: str = Field(default="", max_length=512)
    app_secret: str = Field(default="", max_length=4096)
    business_account_id: str = Field(default="", max_length=512)


class SettingsOutput(BaseModel):
    access_token: str
    app_id: str
    app_secret: str
    business_account_id: str
    connection_status: Literal["connected", "disconnected", "expired"]


def _mask(value: str) -> str:
    return f"{value[:3]}...***{value[-3:]}" if len(value) >= 8 else "***" if value else ""


async def _output(user_id: str) -> SettingsOutput:
    values = await instagram_credentials(user_id)
    row = await get_row("settings", user_id)
    return SettingsOutput(**{field: _mask(value) for field, value in values.items()},
                          connection_status=row.get("connection_status", "disconnected") if row else "disconnected")


@router.get("", response_model=SettingsOutput)
async def get_settings(user=Depends(current_user)):
    return await _output(str(user.id))


@router.post("", response_model=SettingsOutput)
async def save_settings(body: SettingsInput, user=Depends(current_user)):
    user_id = str(user.id)
    existing = await get_row("settings", user_id)
    row = dict(existing) if existing else {"id": user_id, "user_id": int(user_id) if str(user_id).isdigit() else user_id}
    changed = False
    for field, value in body.model_dump().items():
        value = value.strip()
        if value:
            row[field] = encrypt_token(value)
            changed = True
    if not changed:
        raise HTTPException(422, detail={"code": "CREDENTIALS_REQUIRED"})
    row["connection_status"] = "disconnected"
    row["updated_at"] = utcnow()
    await save_row("settings", row)
    return await _output(user_id)


@router.post("/test", response_model=SettingsOutput)
async def test_connection(user=Depends(current_user)):
    user_id = str(user.id)
    values = await instagram_credentials(user_id)
    if not values["access_token"] or not values["business_account_id"]:
        raise HTTPException(422, detail={"code": "TOKEN_AND_BUSINESS_ACCOUNT_REQUIRED"})
    row = await get_row("settings", user_id)
    if not row:
        row = {"id": user_id, "user_id": int(user_id) if user_id.isdigit() else user_id}
    try:
        profile = await InstagramAPI(user_id, values["access_token"]).profile()
        status = "connected" if str(profile.get("id", "")) == values["business_account_id"] else "disconnected"
    except InstagramError as exc:
        if exc.code == "INSTAGRAM_AUTH_ERROR":
            status = "expired"
        else:
            raise HTTPException(exc.status, detail={"code": exc.code}) from exc
    row["connection_status"] = status
    row["updated_at"] = utcnow()
    await save_row("settings", row)
    return await _output(user_id)
