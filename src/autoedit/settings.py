"""AutoEdit AI settings using pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    OPENROUTER_API_KEY: str = ""

    # Storage
    DATA_DIR: str = "./data"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"

    # GPU
    GPU_VRAM_BUDGET_MB: int = 7000

    # Defaults LLM
    DIRECTOR_MODEL: str = "deepseek/deepseek-chat-v3"
    TRIAGE_MODEL: str = "google/gemini-2.5-flash"

    # Transcription
    TRANSCRIPTION_PROVIDER: str = "local"  # "local" | "remote"
    TRANSCRIPTION_LOCAL_MODEL: str = "large-v3"
    TRANSCRIPTION_REMOTE_MODEL: str = "openai/whisper-large-v3"
    TRANSCRIPTION_REMOTE_BASE_URL: str = "https://openrouter.ai/api/v1"
    TRANSCRIPTION_REMOTE_API_KEY: str = ""  # falls back to OPENROUTER_API_KEY

    # Assets
    ASSET_RETRIEVAL_TOP_K: int = 3
    FREESOUND_API_KEY: str = ""   # https://freesound.org/apiv2/apply/
    PIXABAY_API_KEY: str = ""     # https://pixabay.com/api/docs/#api_key

    # Observability
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # FFmpeg
    FFMPEG_BIN: str = "ffmpeg"
    NVENC_PRESET: str = "p4"
    NVENC_CQ: int = 22

    # Twitch (poller)
    TWITCH_CHANNEL_NAME: str | None = None
    TWITCH_CLIENT_ID: str | None = None
    TWITCH_CLIENT_SECRET: str | None = None

    @property
    def data_dir(self) -> Path:
        return Path(self.DATA_DIR).resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "autoedit.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


settings = Settings()
