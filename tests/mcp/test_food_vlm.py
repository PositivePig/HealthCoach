"""Unit tests for food_vlm: schema + recognizer (mock + parse logic).

Real Qwen-VL calls are NOT made here (they'd need a key + cost money).
A separate `test_food_vlm_live.py` (skipped by default) exercises the real API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.mcp_servers.food_vlm.recognizer import (
    FoodRecognizer,
    _parse_recognition_json,
    _to_data_url,
)
from backend.app.mcp_servers.food_vlm.schema import (
    FoodItem,
    RecognizeFoodResult,
)


# ----------------------- schema -----------------------


def test_schema_recompute_totals():
    r = RecognizeFoodResult(
        items=[
            FoodItem(name="A", estimated_grams=100, kcal=100, protein_g=10,
                     carbs_g=10, fat_g=2, confidence=0.8),
            FoodItem(name="B", estimated_grams=50, kcal=50, protein_g=5,
                     carbs_g=5, fat_g=1, confidence=0.7),
        ]
    )
    r.recompute_totals()
    assert r.total_kcal == 150
    assert r.total_protein_g == 15
    assert r.total_carbs_g == 15
    assert r.total_fat_g == 3


def test_schema_rejects_negative():
    with pytest.raises(Exception):
        FoodItem(name="bad", estimated_grams=-1, kcal=0, protein_g=0,
                 carbs_g=0, fat_g=0)


# ----------------------- parser -----------------------


def test_parse_clean_json():
    raw = json.dumps({
        "items": [{"name": "rice", "estimated_grams": 100, "kcal": 130,
                   "protein_g": 3, "carbs_g": 28, "fat_g": 0.3,
                   "confidence": 0.9}],
        "total_kcal": 130, "total_protein_g": 3, "total_carbs_g": 28,
        "total_fat_g": 0.3, "overall_confidence": 0.9, "notes": "",
        "image_quality": "good"
    })
    r = _parse_recognition_json(raw)
    assert len(r.items) == 1
    assert r.items[0].name == "rice"


def test_parse_strips_markdown_fences():
    raw = """```json
{"items": [], "total_kcal": 0, "total_protein_g": 0, "total_carbs_g": 0,
 "total_fat_g": 0, "overall_confidence": 0.5, "notes": "empty",
 "image_quality": "fair"}
```"""
    r = _parse_recognition_json(raw)
    assert r.notes == "empty"


def test_parse_extracts_first_json_block_in_prose():
    raw = (
        "Sure, here is what I see:\n"
        '{"items": [], "total_kcal": 0, "total_protein_g": 0, "total_carbs_g": 0,'
        ' "total_fat_g": 0, "overall_confidence": 0.5, "notes": "ok",'
        ' "image_quality": "good"}\n'
        "Hope this helps!"
    )
    r = _parse_recognition_json(raw)
    assert r.notes == "ok"


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        _parse_recognition_json("totally not json")


# ----------------------- data URL helper -----------------------


def test_to_data_url_passthrough_data_url():
    s = "data:image/png;base64,abcd"
    assert _to_data_url(s) == s


def test_to_data_url_passthrough_http():
    assert _to_data_url("https://example.com/x.jpg") == "https://example.com/x.jpg"


def test_to_data_url_local_path(tmp_path: Path):
    # 1x1 JPEG (smallest valid). We just need *some* bytes.
    f = tmp_path / "tiny.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")  # placeholder bytes
    out = _to_data_url(str(f))
    assert out.startswith("data:image/jpeg;base64,")


# ----------------------- mock recognizer -----------------------


@pytest.mark.asyncio
async def test_mock_recognizer_default():
    rec = FoodRecognizer(force_mock=True)
    res = await rec.recognize("/nonexistent/path.jpg")
    assert res.mode == "mock"
    assert len(res.items) > 0
    assert res.total_kcal > 0
    # totals consistent
    assert abs(res.total_kcal - sum(i.kcal for i in res.items)) < 1e-3


@pytest.mark.asyncio
async def test_mock_recognizer_with_salad_hint():
    rec = FoodRecognizer(force_mock=True)
    res = await rec.recognize("anything", hint="this is a salad")
    assert any("沙拉" in i.name or "salad" in i.name.lower() for i in res.items)


@pytest.mark.asyncio
async def test_recognizer_falls_back_to_mock_when_no_key():
    """If no DASHSCOPE_API_KEY in env, recognizer should auto-mock."""
    rec = FoodRecognizer(force_mock=False)
    # provider.available is False because conftest cleared the key
    res = await rec.recognize("/tmp/x.jpg")
    assert res.mode == "mock"
