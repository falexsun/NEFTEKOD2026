"""Data Quality Agent — checks data sufficiency and reliability."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from src.shared.schemas.process_state import ProcessState

logger = logging.getLogger(__name__)


class DataQualityAssessment(BaseModel):
    """Output of the Data Quality Agent."""
    score: float = Field(ge=0.0, le=1.0)
    allow_prediction: bool
    allow_optimization: bool
    missing_signals: list[str] = Field(default_factory=list)
    stale_signals: list[str] = Field(default_factory=list)
    anomalous_signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DataQualityAgent:
    """Checks data sufficiency, freshness, and anomaly state."""

    def __init__(
        self,
        max_stale_minutes: float = 120,
        min_avt_signals: int = 10,
        min_u24_signals: int = 5,
        min_data_quality_score: float = 0.3,
    ):
        self.max_stale_minutes = max_stale_minutes
        self.min_avt_signals = min_avt_signals
        self.min_u24_signals = min_u24_signals
        self.min_data_quality_score = min_data_quality_score

    def evaluate(self, state: ProcessState) -> DataQualityAssessment:
        """Evaluate data quality for a given process state."""
        warnings = []
        missing = []
        stale = []
        anomalous = []

        # Check telemetry signal counts
        n_avt = len(state.avt_telemetry)
        n_u24 = len(state.unit_242000_telemetry)

        if n_avt < self.min_avt_signals:
            missing.append(f"AVT: only {n_avt}/{self.min_avt_signals} signals available")

        if n_u24 < self.min_u24_signals:
            missing.append(f"24-2000: only {n_u24}/{self.min_u24_signals} signals available")

        # Check source freshness
        freshness = state.source_freshness
        if freshness.avt_minutes is not None and freshness.avt_minutes > self.max_stale_minutes:
            stale.append(f"AVT data is {freshness.avt_minutes:.0f} minutes old")

        if freshness.unit_242000_minutes is not None and freshness.unit_242000_minutes > self.max_stale_minutes:
            stale.append(f"24-2000 data is {freshness.unit_242000_minutes:.0f} minutes old")

        if freshness.pak_sulfur_minutes is not None and freshness.pak_sulfur_minutes > self.max_stale_minutes * 3:
            stale.append(f"PAK sulfur is {freshness.pak_sulfur_minutes:.0f} minutes old")

        # Check for anomalous values (extreme outliers)
        for name, val in state.avt_telemetry.items():
            if abs(val) > 1e6:
                anomalous.append(f"AVT {name} = {val:.1f} (extreme value)")

        for name, val in state.unit_242000_telemetry.items():
            if abs(val) > 1e6:
                anomalous.append(f"24-2000 {name} = {val:.1f} (extreme value)")

        # Check quality signals
        if "sulfur" not in state.quality:
            missing.append("No sulfur quality signal available")
        elif state.quality["sulfur"].age_minutes > self.max_stale_minutes * 6:
            stale.append(f"Quality sulfur is {state.quality['sulfur'].age_minutes:.0f} minutes old")

        # Compute score
        n_issues = len(missing) + len(stale) + len(anomalous)
        score = max(0.0, 1.0 - n_issues * 0.1)

        # Decision
        allow_prediction = (
            n_avt >= self.min_avt_signals
            and n_u24 >= self.min_u24_signals
            and score >= self.min_data_quality_score
        )

        allow_optimization = (
            allow_prediction
            and "sulfur" in state.quality
            and len(stale) == 0
        )

        if not allow_prediction:
            warnings.append("Insufficient data for reliable prediction — system may ABSTAIN")

        assessment = DataQualityAssessment(
            score=score,
            allow_prediction=allow_prediction,
            allow_optimization=allow_optimization,
            missing_signals=missing,
            stale_signals=stale,
            anomalous_signals=anomalous,
            warnings=warnings,
        )

        logger.info(
            f"DataQuality: score={score:.2f}, predict={allow_prediction}, "
            f"optimize={allow_optimization}, issues={n_issues}"
        )
        return assessment
