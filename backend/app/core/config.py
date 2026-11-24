"""Centralized application configuration via pydantic-settings.

Loads from .env in project root.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app config in one place. Read from env vars / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- App ----------
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # ---------- DeepSeek ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_main_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"

    # ---------- DashScope (Qwen) ----------
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_vl_model: str = "qwen-vl-plus"
    dashscope_text_model: str = "qwen-plus"

    # ---------- Anthropic ----------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # ---------- OpenAI ----------
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_vl_model: str = "gpt-4o"

    # ---------- Local LLM (vLLM compatible) ----------
    local_llm_base_url: str = ""
    local_llm_model: str = "Qwen/Qwen3-14B-Instruct-AWQ"
    local_vl_base_url: str = ""
    local_vl_model: str = "Qwen/Qwen3-VL-7B"

    # ---------- Storage ----------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "healthcoach"
    postgres_password: str = "healthcoach_dev"
    postgres_db: str = "healthcoach"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # ---------- Langfuse ----------
    # Either LANGFUSE_HOST or LANGFUSE_BASE_URL is accepted.
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_base_url: str = ""  # if set, overrides langfuse_host
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_enabled: bool = Field(default=False)

    # ---------- Storage backend ----------
    # "sqlite" (no-docker dev profile) or "postgres" (production)
    storage_backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = "./data/healthcoach.db"

    # ---------- Derived ----------
    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def langfuse_resolved_host(self) -> str:
        """Prefer LANGFUSE_BASE_URL if explicitly set, else LANGFUSE_HOST."""
        return self.langfuse_base_url or self.langfuse_host

    @property
    def db_url(self) -> str:
        """SQLAlchemy URL based on storage_backend."""
        if self.storage_backend == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton."""
    return Settings()
