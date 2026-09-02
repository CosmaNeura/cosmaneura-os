from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os"
    redis_url: str = "redis://localhost:63799/0"
    cosmas_env: str = "synth_os"
    blob_root: str = "./data/blobs"
    cosmas_clock_now: str | None = None
    sync_worker: bool = True  # execute operations in-process when True (tests/demo)


settings = Settings()
