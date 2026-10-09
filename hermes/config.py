from pydantic_settings import BaseSettings, SettingsConfigDict


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
    HERMES_DATA_DIR: str = "jobs/hermes"
    HERMES_PUBLIC_MEDIA_BASE_URL: str = ""
    APP_ENV: str = "development"
    INSTAGRAM_GRAPH_VERSION: str = "v25.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


async def instagram_credentials(user_id):
    """Resolve each Instagram value from env, then this user's encrypted settings."""
    from hermes.database import get_row
    from hermes.security import decrypt_token

    row = await get_row("settings", str(user_id))
    values = {}
    for field, env_name in (
        ("access_token", "INSTAGRAM_ACCESS_TOKEN"),
        ("app_id", "INSTAGRAM_APP_ID"),
        ("app_secret", "INSTAGRAM_APP_SECRET"),
        ("business_account_id", "INSTAGRAM_BUSINESS_ACCOUNT_ID"),
    ):
        env_value = getattr(settings, env_name).strip()
        values[field] = env_value or (decrypt_token(row[field]) if row and row.get(field) else "")
    return values
