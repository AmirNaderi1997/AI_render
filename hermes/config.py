import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


log = logging.getLogger("uvicorn.error")


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""
    INSTAGRAM_ACCESS_TOKEN: str = ""
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = ""
    INSTAGRAM_REDIRECT_URI: str = ""
    JWT_SECRET: str = ""
    ALLOWED_HOSTS: str = ""
    HERMES_TOKEN_KEY: str = ""
    HERMES_ENCRYPTION_KEY: str = ""
    HERMES_DATA_DIR: str = "jobs/hermes"
    HERMES_PUBLIC_MEDIA_BASE_URL: str = ""
    APP_ENV: str = "development"
    INSTAGRAM_GRAPH_VERSION: str = "v25.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


def settings_row_id(user_id, provider="instagram"):
    return f"{provider}:{user_id}"


async def stored_instagram_credentials(user_id):
    """Decrypted credentials saved through the Hermes settings UI, or {} when none or unreadable."""
    from fastapi import HTTPException

    from hermes.database import get_row
    from hermes.security import decrypt_setting

    row = await get_row("settings", settings_row_id(user_id))
    stored = (row or {}).get("encrypted_credentials") or {}
    try:
        return {field: decrypt_setting(value) for field, value in stored.items() if value}
    except HTTPException:
        log.warning("hermes_settings credentials for user %s cannot be decrypted; falling back to environment", user_id)
        return {}


async def instagram_credentials(user_id):
    """Resolve Instagram credentials: this user's stored settings first, then .env values."""
    stored = await stored_instagram_credentials(user_id)
    return {
        "access_token": stored.get("access_token") or settings.INSTAGRAM_ACCESS_TOKEN.strip(),
        "app_id": settings.INSTAGRAM_APP_ID.strip(),
        "app_secret": stored.get("app_secret") or settings.INSTAGRAM_APP_SECRET.strip(),
        "business_account_id": stored.get("instagram_user_id") or settings.INSTAGRAM_BUSINESS_ACCOUNT_ID.strip(),
    }
