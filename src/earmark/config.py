from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./earmark.db"

    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24 * 7

    audiobookshelf_url: str = ""
    audiobookshelf_api_key: str = ""

    kosync_host: str = "0.0.0.0"
    kosync_port: int = 8080

    sync_interval_seconds: int = 300

    ebook_source: str = "abs"  # "abs" | "cwa" | "local"
    cwa_url: str = ""
    cwa_username: str = ""
    cwa_password: str = ""
    ebook_local_root: str = "."
    alignment_cache_dir: str = ".cache/earmark"
    whisper_model: str = "tiny.en"  # tiny.en | base.en | small.en | medium.en | large-v3
    whisper_device: str = "cpu"  # cpu | cuda | mps
    whisper_compute_type: str = "int8"  # int8 | float16 | float32
    whisper_batch_size: int = 4
    whisper_chunk_seconds: int = 600
    whisper_language: str = "en"

    timezone: str = "America/New_York"

    log_level: str = "INFO"
    log_pretty: bool = False


settings = Settings()
