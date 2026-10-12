import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


log = logging.getLogger("uvicorn.error")


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
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
        log.warning("hermes_settings credentials for user %s cannot be decrypted", user_id)
        return {}


async def instagram_credentials(user_id):
    """Resolve Instagram credentials only from this user's encrypted settings."""
    stored = await stored_instagram_credentials(user_id)
    return {
        "access_token": stored.get("access_token", ""),
        "app_id": stored.get("app_id", ""),
        "app_secret": stored.get("app_secret", ""),
        "business_account_id": stored.get("instagram_user_id", ""),
    }
