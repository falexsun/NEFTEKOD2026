"""Process state schema — the central data structure passed between agents."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QualitySignal(BaseModel):
    """A single quality measurement with provenance."""
    value: float
    source: str  # LIMS | PAK | VAK
    measurement_timestamp: datetime
    age_minutes: float
    confidence: float = Field(ge=0.0, le=1.0)


class SourceFreshness(BaseModel):
    """How fresh each data source is."""
    avt_minutes: float | None = None
    unit_242000_minutes: float | None = None
    lims_minutes: float | None = None
    pak_sulfur_minutes: float | None = None
    pak_density_minutes: float | None = None


class ProcessState(BaseModel):
    """Unified state of the production process at a point in time."""
    timestamp: datetime

    # Raw telemetry from each unit
    avt_telemetry: dict[str, float] = Field(default_factory=dict)
    unit_242000_telemetry: dict[str, float] = Field(default_factory=dict)

    # Quality signals with source tracking
    quality: dict[str, QualitySignal] = Field(default_factory=dict)

    # Engineered feature vector
    feature_vector: dict[str, float] = Field(default_factory=dict)

    # Source freshness tracking
    source_freshness: SourceFreshness = Field(default_factory=SourceFreshness)

    # Data quality scores
    data_quality_score: float | None = None
    data_quality_flags: list[str] = Field(default_factory=list)

    # Metadata
    decision_id: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
