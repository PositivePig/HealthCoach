"""Tests for data_analyst node (W4 D2)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.agents.nodes.data_analyst import (
    _generate_calorie_chart,
    _generate_sleep_chart,
    _generate_weight_chart,
    _generate_activity_chart,
    data_analyst_node,
)


# ---- fixtures ----

def _make_vital(ts: datetime, weight_kg=None, sleep_min=None, hrv_ms=None):
    v = MagicMock()
    v.ts = ts
    v.weight_kg = weight_kg
    v.sleep_min = sleep_min
    v.hrv_ms = hrv_ms
    return v


def _make_meal(ts: datetime, total_kcal: float):
    m = MagicMock()
    m.ts = ts
    m.total_kcal = total_kcal
    return m


def _make_activity(ts: datetime, typ: str, duration_min: float):
    a = MagicMock()
    a.type = typ
    a.duration_min = duration_min
    return a


# ---- chart generation ----

class TestGenerateWeightChart:
    def test_returns_none_when_no_vitals(self):
        assert _generate_weight_chart("u1", []) is None

    def test_returns_none_when_single_entry(self):
        v = _make_vital(datetime.now(), weight_kg=70.0)
        assert _generate_weight_chart("u1", [v]) is None

    def test_generates_chart_when_enough_data(self):
        base = datetime.now() - timedelta(days=5)
        vitals = [
            _make_vital(base + timedelta(days=i), weight_kg=70.0 + i * 0.2)
            for i in range(6)
        ]
        path = _generate_weight_chart("u1", vitals)
        assert path is not None
        assert os.path.basename(path).startswith("u1_weight_")
        assert path.endswith(".png")
        # Cleanup
        if os.path.exists(path):
            os.remove(path)


class TestGenerateCalorieChart:
    def test_returns_none_when_no_meals(self):
        assert _generate_calorie_chart("u1", []) is None

    def test_generates_chart_with_meals(self):
        base = datetime.now() - timedelta(days=3)
        meals = [
            _make_meal(base + timedelta(days=i), total_kcal=500.0 * (i + 1))
            for i in range(4)
        ]
        path = _generate_calorie_chart("u1", meals)
        assert path is not None
        assert "calories" in os.path.basename(path)
        if os.path.exists(path):
            os.remove(path)


class TestGenerateSleepChart:
    def test_returns_none_when_insufficient_data(self):
        v = _make_vital(datetime.now(), sleep_min=420)
        assert _generate_sleep_chart("u1", [v]) is None

    def test_generates_chart_with_sleep_data(self):
        base = datetime.now() - timedelta(days=5)
        vitals = [
            _make_vital(base + timedelta(days=i), sleep_min=360 + i * 30)
            for i in range(5)
        ]
        path = _generate_sleep_chart("u1", vitals)
        assert path is not None
        assert "sleep" in os.path.basename(path)
        if os.path.exists(path):
            os.remove(path)


class TestGenerateActivityChart:
    def test_returns_none_when_no_activities(self):
        assert _generate_activity_chart("u1", []) is None

    def test_generates_chart_with_activities(self):
        activities = [
            _make_activity(datetime.now(), "running", 30),
            _make_activity(datetime.now(), "running", 40),
            _make_activity(datetime.now(), "yoga", 60),
        ]
        path = _generate_activity_chart("u1", activities)
        assert path is not None
        assert "activity" in os.path.basename(path)
        if os.path.exists(path):
            os.remove(path)


# ---- data_analyst_node ----

@pytest.mark.asyncio
async def test_data_analyst_node_returns_command(monkeypatch):
    """Test that data_analyst_node returns a Command with correct structure."""
    # Mock LLM router
    mock_resp = MagicMock()
    mock_resp.content = "这是数据分析结果。（基于最近 30 天数据）"
    mock_resp.provider = "mock"
    mock_resp.model = "mock-v1"

    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_router", lambda: mock_router)
    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_langfuse", lambda: None)

    # Mock session_scope
    mock_session = AsyncMock()
    mock_user = MagicMock()
    mock_user.goal = "cut"
    mock_user.target_kcal = 1700
    mock_user.weight_kg = 70.0
    mock_user.target_weight = 65.0

    mock_repo = AsyncMock()
    mock_repo.get_user = AsyncMock(return_value=mock_user)
    mock_repo.query_meals = AsyncMock(return_value=[])
    mock_repo.query_activities = AsyncMock(return_value=[])
    mock_repo.query_vitals = AsyncMock(return_value=[])

    with patch("backend.app.agents.nodes.data_analyst.session_scope") as mock_scope:
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("backend.app.agents.nodes.data_analyst.repo", mock_repo)

        state = {"user_id": "test_user", "user_message": "分析我的数据"}
        result = await data_analyst_node(state)

        assert hasattr(result, "update")
        assert "coach_answers" in result.update
        assert result.update["visited_coaches"] == ["data"]
        assert result.goto == "supervisor"


@pytest.mark.asyncio
async def test_data_analyst_node_handoff_nutrition(monkeypatch):
    """Test handoff to nutrition when user asks about diet."""
    mock_resp = MagicMock()
    mock_resp.content = "建议调整饮食。HANDOFF: nutrition"
    mock_resp.provider = "mock"
    mock_resp.model = "mock-v1"

    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_router", lambda: mock_router)
    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_langfuse", lambda: None)

    with patch("backend.app.agents.nodes.data_analyst.session_scope") as mock_scope:
        mock_scope.return_value.__aenter__ = AsyncMock()
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        state = {"user_id": "test_user", "user_message": "我的营养摄入怎么改善？"}
        result = await data_analyst_node(state)

        assert result.update.get("handoff_to") == "nutrition"


@pytest.mark.asyncio
async def test_data_analyst_node_handoff_fitness(monkeypatch):
    """Test handoff to fitness when user asks about exercise."""
    mock_resp = MagicMock()
    mock_resp.content = "建议增加运动。HANDOFF: fitness"
    mock_resp.provider = "mock"
    mock_resp.model = "mock-v1"

    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_router", lambda: mock_router)
    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_langfuse", lambda: None)

    with patch("backend.app.agents.nodes.data_analyst.session_scope") as mock_scope:
        mock_scope.return_value.__aenter__ = AsyncMock()
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        state = {"user_id": "test_user", "user_message": "我的运动计划怎么制定？"}
        result = await data_analyst_node(state)

        assert result.update.get("handoff_to") == "fitness"


@pytest.mark.asyncio
async def test_data_analyst_self_handoff_prevented(monkeypatch):
    """Test that self-handoff (HANDOFF: data) is prevented."""
    mock_resp = MagicMock()
    mock_resp.content = "数据分析完成。HANDOFF: data"  # Self-handoff attempt
    mock_resp.provider = "mock"
    mock_resp.model = "mock-v1"

    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_router", lambda: mock_router)
    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_langfuse", lambda: None)

    with patch("backend.app.agents.nodes.data_analyst.session_scope") as mock_scope:
        mock_scope.return_value.__aenter__ = AsyncMock()
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        state = {"user_id": "test_user", "user_message": "分析数据"}
        result = await data_analyst_node(state)

        # Self-handoff should be prevented
        assert result.update.get("handoff_to") is None


@pytest.mark.asyncio
async def test_data_analyst_node_no_handoff_for_pure_query(monkeypatch):
    """Test no handoff when user only asks for data query."""
    mock_resp = MagicMock()
    mock_resp.content = "根据最近 30 天数据，你的体重呈下降趋势。"
    mock_resp.provider = "mock"
    mock_resp.model = "mock-v1"

    mock_router = MagicMock()
    mock_router.chat = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_router", lambda: mock_router)
    monkeypatch.setattr("backend.app.agents.nodes.data_analyst.get_langfuse", lambda: None)

    with patch("backend.app.agents.nodes.data_analyst.session_scope") as mock_scope:
        mock_scope.return_value.__aenter__ = AsyncMock()
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        state = {"user_id": "test_user", "user_message": "最近体重趋势如何？"}
        result = await data_analyst_node(state)

        assert result.update.get("handoff_to") is None
