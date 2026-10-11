"""Central configuration for local and database-backed deployments."""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    JWT_SECRET: str = ""
    JWT_ACCESS_HOURS: int = 24
    JWT_REFRESH_DAYS: int = 30
    AI_PROVIDER: str = "jarvis"
    AI_PROVIDER_TIMEOUT_SECONDS: int = 300
    AI_TIMEOUT_SECONDS: int = 60
    AI_CORRECTION_TIMEOUT_SECONDS: int = 45
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "CLAUDE_SONNET_5_5"
    SAROVI_LLM_MODEL: str = "anthropic/claude-sonnet-5.5"
    # Content Creator can use a dedicated text provider without changing the
    # upload/edit planner used elsewhere in the application.
    CONTENT_LLM_PROVIDER: str = ""
    CORRECTION_PROVIDER: str = ""
    CORRECTION_MODEL: str = ""
    VISION_PROVIDER: str = ""
    VISION_MODEL: str = "gpt-5-5-image"
    CONTENT_VOICE_PROVIDER: str = "edge"
    # Per-call Content Creator narration provider. When empty, the legacy
    # CONTENT_VOICE_PROVIDER/TTS_PROVIDER compatibility rules remain active.
    CONTENT_TTS_PROVIDER: str = ""
    SAROVI_API_KEY: str = ""
    SAROVI_TTS_MODEL: str = ""
    SAROVI_TTS_VOICE: str = ""
    TTS_VOICE_ID: str = ""
    # TTS_PROVIDER is deliberately independent of optional image/text providers.
    # Edge TTS works without an API key and is the default in restricted networks.
    TTS_PROVIDER: str = "edge-tts"
    TTS_VOICE: str = "en-US-GuyNeural"
    TTS_RATE: str = "+0%"
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = ""
    JARVIS_API_KEY: str = ""
    JARVIS_API_URL: str = ""
    JARVIS_MODEL: str = ""
    JARVIS_BASE_URL: str = ""
    SAROVI_API_URL: str = ""
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
    HEALTH_MIN_DISK_FREE_GB: float = 2.0
    PRESETS_DIR: str = "presets"
    APP_ENV: str = "development"
    CORS_ORIGINS: str = ""
    ALLOWED_HOSTS: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    @model_validator(mode="after")
    def validate_production_hosts(self):
        if self.APP_ENV.strip().lower() == "production":
            hosts = [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]
            if not hosts:
                raise ValueError("ALLOWED_HOSTS must contain at least one hostname in production")
            for host in hosts:
                # TrustedHostMiddleware expects hostnames, without URL or port syntax.
                if (
                    host == "*"
                    or "*" in host
                    or ":" in host
                    or "/" in host
                    or "@" in host
                    or host.startswith(".")
                    or host.endswith(".")
                ):
                    raise ValueError("ALLOWED_HOSTS must contain exact hostnames without ports in production")
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
