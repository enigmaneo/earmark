import logging
import os
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # extra="ignore": the .env is shared with Docker (PORT) and SvelteKit (ORIGIN),
    # so tolerate env keys this backend doesn't define instead of failing to start.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./earmark.db"

    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24 * 7

    # Origins allowed by CORS. Comma-separated in the env (e.g. "https://app.example.com").
    # NoDecode disables pydantic-settings' JSON parsing so the validator below can split it.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    audiobookshelf_url: str = ""
    audiobookshelf_api_key: str = ""

    kosync_host: str = "0.0.0.0"
    kosync_port: int = 8080

    sync_interval_seconds: int = 300
    # Min seconds since ABS lastUpdate before an ABS→KOSync write is allowed. While an
    # audiobook is actively playing, lastUpdate keeps advancing; deferring until it has
    # been idle this long collapses a listening session into a single KOSync entry.
    sync_abs_idle_seconds: int = 360

    cwa_url: str = ""
    cwa_username: str = ""
    cwa_password: str = ""
    ebook_local_root: str = "."
    alignment_cache_dir: str = ".cache/earmark"
    whisper_model: str = "tiny.en"  # tiny.en | base.en | small.en | medium.en | large-v3
    whisper_device: str = "cpu"  # cpu | cuda | mps
    whisper_compute_type: str = "int8"  # int8 | float16 | float32
    whisper_chunk_seconds: int = 600
    whisper_cpu_threads: int = 4
    whisper_language: str = "en"

    timezone: str = "America/New_York"

    log_level: str = "INFO"
    log_pretty: bool = False
    log_requests: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()

if os.getenv("EBOOK_SOURCE"):
    logger.warning(
        "EBOOK_SOURCE is set but no longer read. Source is now chosen per mapping; "
        "see docs/CalibreWebIntegration.md."
    )
