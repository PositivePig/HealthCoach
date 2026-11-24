"""Food recognizer: turns an image into a structured nutrition result.

Three modes (auto-selected by configuration):
  - "qwen-vl"  : real API call via the shared OpenAICompatibleProvider
  - "mock"     : deterministic offline result, used in tests / when no API key
  - "fallback" : Qwen-VL succeeded but JSON parse failed → return a degraded
                 placeholder so the agent still gets *something* to show
                 (with low confidence + notes pointing to the parse error).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from pydantic import ValidationError

from ...core.config import get_settings
from ...core.logging import get_logger
from ...llm.providers.openai_compatible import OpenAICompatibleProvider
from ...llm.types import ChatMessage, ProviderError
from .prompts import SYSTEM_PROMPT, build_user_text
from .schema import FoodItem, RecognizeFoodResult

log = get_logger(__name__)


# ----------------------- helpers -----------------------


def _to_data_url(image: str) -> str:
    """Accept a path, raw base64, or already-formed data URL.

    Returns: data:image/jpeg;base64,<...>
    """
    if image.startswith("data:image/"):
        return image
    if image.startswith(("http://", "https://")):
        return image
    p = Path(image)
    if p.exists() and p.is_file():
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        # Best-effort mime guess
        ext = p.suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(
            ext, "jpeg"
        )
        return f"data:image/{mime};base64,{b64}"
    # Treat as raw base64
    return f"data:image/jpeg;base64,{image}"


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_recognition_json(raw: str) -> RecognizeFoodResult:
    """Robustly parse VLM output into RecognizeFoodResult.

    Strategy:
      1. Try direct json.loads
      2. Try extracting first {...} block (in case model wrapped in markdown)
      3. Re-validate against pydantic schema
      4. On failure → raise ValueError (caller decides fallback)
    """
    text = raw.strip()
    # Strip common markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    candidates: list[str] = [text]
    m = _JSON_BLOCK.search(text)
    if m:
        candidates.append(m.group(0))

    last_err: Exception | None = None
    for c in candidates:
        try:
            data = json.loads(c)
            return RecognizeFoodResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            continue
    raise ValueError(f"VLM output not parseable as RecognizeFoodResult: {last_err}")


# ----------------------- mock -----------------------


def _mock_result(hint: str | None) -> RecognizeFoodResult:
    """Deterministic mock result. Useful for tests / no-key environments.

    The hint can steer the mock to keep flexible test cases reasonable.
    """
    if hint and "salad" in hint.lower():
        items = [
            FoodItem(
                name="蔬菜沙拉",
                estimated_grams=200,
                kcal=120,
                protein_g=3,
                carbs_g=12,
                fat_g=7,
                fiber_g=4,
                confidence=0.8,
            )
        ]
        notes = "[mock] 沙拉 hint 触发"
    else:
        items = [
            FoodItem(
                name="番茄炒蛋",
                estimated_grams=280,
                kcal=290,
                protein_g=17,
                carbs_g=8,
                fat_g=21,
                fiber_g=1.5,
                confidence=0.7,
            ),
            FoodItem(
                name="米饭",
                estimated_grams=150,
                kcal=195,
                protein_g=4,
                carbs_g=43,
                fat_g=0.5,
                fiber_g=0.6,
                confidence=0.85,
            ),
        ]
        notes = "[mock] 默认假数据，用于离线测试"
    res = RecognizeFoodResult(
        items=items,
        overall_confidence=0.75,
        notes=notes,
        image_quality="good",
        mode="mock",
    )
    res.recompute_totals()
    return res


# ----------------------- main entry -----------------------


class FoodRecognizer:
    """The thing that does the work. Stateless, safe to call concurrently."""

    def __init__(self, *, force_mock: bool = False) -> None:
        self._force_mock = force_mock
        self._provider: OpenAICompatibleProvider | None = None

    @property
    def provider(self) -> OpenAICompatibleProvider:
        if self._provider is None:
            s = get_settings()
            self._provider = OpenAICompatibleProvider(
                name="qwen-vl",
                role="vision",
                api_key=s.dashscope_api_key,
                base_url=s.dashscope_base_url,
                default_model=s.dashscope_vl_model,
            )
        return self._provider

    def _should_mock(self) -> bool:
        return self._force_mock or not self.provider.available

    async def recognize(
        self, image: str, hint: str | None = None
    ) -> RecognizeFoodResult:
        """Identify food in `image` and return structured nutrition."""
        if self._should_mock():
            log.info("food_vlm_mock", reason="no_api_key" if not self._force_mock else "forced")
            return _mock_result(hint)

        data_url = _to_data_url(image)
        messages = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=build_user_text(hint),
                image_urls=[data_url],
            ),
        ]
        try:
            resp = await self.provider.chat(
                messages, temperature=0.1, max_tokens=1500
            )
        except ProviderError as e:
            log.warning("food_vlm_provider_error", error=str(e))
            # Degraded result so downstream UI still works
            return RecognizeFoodResult(
                notes=f"[fallback] VLM 调用失败: {e}",
                overall_confidence=0.0,
                image_quality="poor",
                mode="fallback",
            )

        try:
            result = _parse_recognition_json(resp.content)
            result.mode = "qwen-vl"
            # Defensive: model sometimes forgets to fill totals
            result.recompute_totals()
            log.info(
                "food_vlm_ok",
                items=len(result.items),
                kcal=result.total_kcal,
                conf=result.overall_confidence,
            )
            return result
        except ValueError as e:
            log.warning("food_vlm_parse_error", raw=resp.content[:200], error=str(e))
            return RecognizeFoodResult(
                notes=f"[fallback] VLM 输出无法解析为 JSON: {e}",
                overall_confidence=0.0,
                image_quality="poor",
                mode="fallback",
            )
