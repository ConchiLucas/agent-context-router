from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str | None = None
    frontend_origin: str = "http://127.0.0.1:49211"
    embedding_provider: str = "local"
    embedding_dimensions: int = Field(default=1024, ge=128, le=4096)
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = Field(default=90, ge=10, le=600)
    llm_max_retries: int = Field(default=3, ge=1, le=10)
    seed_demo: bool = False
    search_candidate_limit: int = Field(default=80, ge=10, le=500)
    search_session_ttl_days: int = Field(default=7, ge=1, le=90)
    search_session_cache_size: int = Field(default=1000, ge=10, le=10000)

    model_config = SettingsConfigDict(
        env_prefix="API_NAVIGATOR_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
