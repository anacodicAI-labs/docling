"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Paper Extract API"
    api_prefix: str = "/api/v1"
    debug: bool = False

    database_url: str = Field(
        default="sqlite:///./data/paper_extract.db",
        description="SQLAlchemy database URL",
    )
    redis_url: str = Field(default="redis://localhost:6379", description="Redis URL for ARQ")

    storage_root: Path = Field(default=Path("./data/storage"), description="Job uploads and outputs")

    max_files_per_job: int = 100
    max_pdf_bytes: int = 50 * 1024 * 1024
    max_batch_bytes: int = 500 * 1024 * 1024

    default_layout: str = "folder"
    copy_source_pdf: bool = True
    eta_seconds_per_page: float = 0.75
    eta_minimum_seconds: float = 15.0

    arq_queue_name: str = "paper_extract"


settings = Settings()
