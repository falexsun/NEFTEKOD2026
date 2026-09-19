"""Reliability assessment schema."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReliabilityAssessment(BaseModel):
    """Equipment/process reliability risk assessment."""
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str  # low | medium | high | critical
    factors: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    model_version: str | None = None
    assumptions: list[str] = Field(default_factory=list)
