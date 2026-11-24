"""Food recognition output schema.

Used by both the Qwen-VL recognizer and the LangGraph nutrition coach.
Keep this schema stable—it's the contract between vision model and downstream agents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FoodItem(BaseModel):
    """One identified dish / ingredient on the plate."""

    name: str = Field(..., description="食物名称（中文，如：番茄炒蛋）")
    estimated_grams: float = Field(
        ..., ge=0, description="估算重量（克）。看不准时给出区间中值，并把不确定性写进 confidence。"
    )
    kcal: float = Field(..., ge=0, description="热量（千卡）")
    protein_g: float = Field(..., ge=0, description="蛋白质（克）")
    carbs_g: float = Field(..., ge=0, description="碳水化合物（克）")
    fat_g: float = Field(..., ge=0, description="脂肪（克）")
    fiber_g: float = Field(default=0.0, ge=0, description="膳食纤维（克）")
    confidence: float = Field(
        default=0.6,
        ge=0,
        le=1,
        description="该项识别置信度 0~1，<0.5 时下游应触发人工确认",
    )


class RecognizeFoodResult(BaseModel):
    """Top-level recognition result returned by the food_vlm tool."""

    items: list[FoodItem] = Field(default_factory=list)
    total_kcal: float = 0.0
    total_protein_g: float = 0.0
    total_carbs_g: float = 0.0
    total_fat_g: float = 0.0
    overall_confidence: float = Field(
        default=0.6, ge=0, le=1, description="整张图的总体置信度"
    )
    notes: str = Field(
        default="",
        description="给营养教练的额外提示（如：图像模糊/拍摄角度差/份量难判定）",
    )
    image_quality: Literal["good", "fair", "poor"] = "good"
    mode: Literal["qwen-vl", "mock", "fallback"] = "qwen-vl"

    def recompute_totals(self) -> None:
        """Re-derive totals from items (defensive: model may forget)."""
        self.total_kcal = round(sum(i.kcal for i in self.items), 1)
        self.total_protein_g = round(sum(i.protein_g for i in self.items), 1)
        self.total_carbs_g = round(sum(i.carbs_g for i in self.items), 1)
        self.total_fat_g = round(sum(i.fat_g for i in self.items), 1)
