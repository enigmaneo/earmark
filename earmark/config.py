from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./earmark.db"

    audiobookshelf_url: str = ""
    audiobookshelf_api_key: str = ""

    kosync_host: str = "0.0.0.0"
    kosync_port: int = 8080

    sync_interval_minutes: int = 5


settings = Settings()
