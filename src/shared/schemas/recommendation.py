"""Recommendation and abstain schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .quality_prediction import QualityPrediction
from .reliability import ReliabilityAssessment


class Recommendation(BaseModel):
    """Final recommendation for the operator."""
    decision_id: str
    timestamp: datetime
    current_state: dict[str, Any] = Field(default_factory=dict)
    detected_problem: str | None = None
    recommended_changes: dict[str, Any] = Field(default_factory=dict)
    expected_quality: dict[str, float] = Field(default_factory=dict)
    expected_production_effect: float | None = None
    expected_energy_effect: float | None = None
    reliability_effect: float | None = None
    checked_constraints: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    model_versions: dict[str, str] = Field(default_factory=dict)


class AbstainRecommendation(BaseModel):
    """System abstains from giving a recommendation."""
    decision_id: str
    timestamp: datetime
    reason: str
    missing_data: list[str] = Field(default_factory=list)
    unsafe_scenarios: int = 0
    warnings: list[str] = Field(default_factory=list)
