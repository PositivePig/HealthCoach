"""Pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch, tmp_path):
    """Don't let real .env leak into tests.

    Also clear cached singletons (settings/router/langfuse) so each test
    sees the cleaned env.
    """
    keys = [
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_VL_BASE_URL",
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_BASE_URL",
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)

    # Critical: stop pydantic-settings from reading the real .env in tests
    monkeypatch.chdir(tmp_path)  # cwd without .env (cross-platform)

    # Clear cached singletons
    from backend.app.core import config as cfg
    from backend.app.core import langfuse_client as lfc
    from backend.app.llm import router as rt

    cfg.get_settings.cache_clear()
    rt.get_router.cache_clear()
    lfc._langfuse_client = None  # type: ignore[attr-defined]
    lfc._init_attempted = False  # type: ignore[attr-defined]

    yield

    cfg.get_settings.cache_clear()
    rt.get_router.cache_clear()
