"""Quality prediction schema."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QualityPrediction(BaseModel):
    """ML prediction for a quality indicator."""
    indicator: str  # e.g. "sulfur", "density", "t95"
    prediction: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    violation_probability: float | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    model_version: str = "unknown"
    model_type: str = "unknown"
