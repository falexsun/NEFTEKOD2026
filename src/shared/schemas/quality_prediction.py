"""Quality prediction schema."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QualityPrediction(BaseModel):
    """ML prediction for a quality indicator.

    When model_available=False, prediction/lower_bound/upper_bound/violation_probability
    will be None. Orchestrator MUST check model_available before using.
    """
    indicator: str  # e.g. "sulfur", "density", "t95"

    # Prediction values — None when model is unavailable
    prediction: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    violation_probability: float | None = None

    # confidence is None when no calibrated confidence is available
    confidence: float | None = Field(ge=0.0, le=1.0, default=None)
    model_version: str = "unknown"
    model_type: str = "unknown"

    # Availability tracking
    model_available: bool = True
    unavailability_reason: str | None = None

    # Uncertainty tracking — separate from confidence
    uncertainty_method: str | None = None  # "approximate_std_1.5", "conformal", etc.
    uncertainty_value: float | None = None  # The actual std estimate used
