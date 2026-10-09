"""Central configuration for local and database-backed deployments."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    JWT_SECRET: str = ""
    JWT_ACCESS_HOURS: int = 24
    JWT_REFRESH_DAYS: int = 30
    AI_PROVIDER: str = "jarvis"
    AI_PROVIDER_TIMEOUT_SECONDS: int = 300
    AI_CORRECTION_TIMEOUT_SECONDS: int = 45
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-5-5"
    VISION_PROVIDER: str = ""
    VISION_MODEL: str = "gpt-5-5-image"
    CONTENT_VOICE_PROVIDER: str = "edge"
    SAROVI_API_KEY: str = ""
    SAROVI_TTS_MODEL: str = ""
    SAROVI_TTS_VOICE: str = ""
    TTS_VOICE_ID: str = ""
    # TTS_PROVIDER is deliberately independent of optional image/text providers.
    # Edge TTS works without an API key and is the default in restricted networks.
    TTS_PROVIDER: str = "edge-tts"
    TTS_VOICE: str = "en-US-GuyNeural"
    TTS_RATE: str = "+0%"
    JARVIS_API_KEY: str = ""
    JARVIS_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    OPENAI_BASE_URL: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    WHISPER_ENABLED: bool = True
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_TIMEOUT_SECONDS: int = 120
    # Media artifacts only: uploads, rendered outputs and editable exports.
    # Job metadata/status is persisted in PostgreSQL.
    JOBS_DIR: str = "/app/job_data"
    ASSETS_DIR: str = "assets"
    PRESETS_DIR: str = "presets"
    APP_ENV: str = "development"
    CORS_ORIGINS: str = ""
    ALLOWED_HOSTS: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
