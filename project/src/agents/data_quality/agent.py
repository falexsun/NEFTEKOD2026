"""Data Quality Agent — checks data sufficiency and reliability.

Checks:
- missing signals
- stale signals (AVT, 24-2000, PAK, LIMS)
- frozen sensors (via history, not single values)
- impossible jumps
- too many missing features
- absent sulfur source
"""
from __future__ import annotations

import logging
from collections import defaultdict
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
    frozen_signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DataQualityAgent:
    """Checks data sufficiency, freshness, and anomaly state."""

    def __init__(
        self,
        max_stale_minutes: float = 120,
        min_avt_signals: int = 10,
        min_u24_signals: int = 5,
        min_data_quality_score: float = 0.3,
        frozen_window: int = 6,
        frozen_std_threshold: float = 0.001,
        max_jump_threshold: float = 100.0,  # Max allowed jump per 10-min step
    ):
        self.max_stale_minutes = max_stale_minutes
        self.min_avt_signals = min_avt_signals
        self.min_u24_signals = min_u24_signals
        self.min_data_quality_score = min_data_quality_score
        self.frozen_window = frozen_window
        self.frozen_std_threshold = frozen_std_threshold
        self.max_jump_threshold = max_jump_threshold
        # History for frozen/jump detection
        self._history: dict[str, list[float]] = defaultdict(list)
        self._last_values: dict[str, float] = {}

    def evaluate(self, state: ProcessState) -> DataQualityAssessment:
        """Evaluate data quality for a given process state."""
        warnings = []
        missing = []
        stale = []
        anomalous = []
        frozen = []

        all_signals = {**state.avt_telemetry, **state.unit_242000_telemetry}

        # ── 1. Telemetry signal counts ───────────────────────
        n_avt = len(state.avt_telemetry)
        n_u24 = len(state.unit_242000_telemetry)

        if n_avt < self.min_avt_signals:
            missing.append(f"AVT: only {n_avt}/{self.min_avt_signals} signals available")
        if n_u24 < self.min_u24_signals:
            missing.append(f"24-2000: only {n_u24}/{self.min_u24_signals} signals available")

        # ── 2. Source freshness ──────────────────────────────
        freshness = state.source_freshness
        if freshness.avt_minutes is not None and freshness.avt_minutes > self.max_stale_minutes:
            stale.append(f"AVT data is {freshness.avt_minutes:.0f} min old (max {self.max_stale_minutes})")
        if freshness.unit_242000_minutes is not None and freshness.unit_242000_minutes > self.max_stale_minutes:
            stale.append(f"24-2000 data is {freshness.unit_242000_minutes:.0f} min old")
        if freshness.pak_sulfur_minutes is not None and freshness.pak_sulfur_minutes > self.max_stale_minutes * 3:
            stale.append(f"PAK sulfur is {freshness.pak_sulfur_minutes:.0f} min old")
        if freshness.lims_minutes is not None and freshness.lims_minutes > 1440 * 3:  # 3 days
            stale.append(f"LIMS is {freshness.lims_minutes:.0f} min old (>3 days)")

        # ── 3. Quality signals ───────────────────────────────
        if "sulfur" not in state.quality:
            missing.append("No sulfur quality signal available")
        elif state.quality["sulfur"].age_minutes > self.max_stale_minutes * 6:
            stale.append(f"Quality sulfur is {state.quality['sulfur'].age_minutes:.0f} min old")

        # ── 4. Frozen sensor detection (via history) ─────────
        for name, val in all_signals.items():
            history = self._history[name]
            history.append(val)
            if len(history) > self.frozen_window:
                history[:] = history[-self.frozen_window:]

            if len(history) >= self.frozen_window:
                import numpy as np
                std = np.std(history)
                if std < self.frozen_std_threshold:
                    frozen.append(name)

        # ── 5. Jump detection ────────────────────────────────
        for name, val in all_signals.items():
            if name in self._last_values:
                prev = self._last_values[name]
                jump = abs(val - prev)
                if jump > self.max_jump_threshold:
                    anomalous.append(f"{name}: jump {prev:.1f}→{val:.1f} (Δ={jump:.1f})")
            self._last_values[name] = val

        # ── 6. Extreme values ────────────────────────────────
        for name, val in all_signals.items():
            if abs(val) > 1e6:
                anomalous.append(f"{name}={val:.1f} extreme value")

        # ── Compute score ────────────────────────────────────
        n_issues = len(missing) + len(stale) + len(anomalous) + len(frozen)
        score = max(0.0, 1.0 - n_issues * 0.08)

        # ── Decision ─────────────────────────────────────────
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
            warnings.append("Insufficient data for reliable prediction — system will ABSTAIN")
        if frozen:
            warnings.append(f"Frozen sensors detected: {frozen}")
        if anomalous:
            warnings.append(f"Anomalous signals: {len(anomalous)} detected")

        assessment = DataQualityAssessment(
            score=score,
            allow_prediction=allow_prediction,
            allow_optimization=allow_optimization,
            missing_signals=missing,
            stale_signals=stale,
            anomalous_signals=anomalous,
            frozen_signals=frozen,
            warnings=warnings,
        )

        logger.info(
            f"DataQuality: score={score:.2f}, predict={allow_prediction}, "
            f"optimize={allow_optimization}, issues={n_issues}"
        )
        return assessment

    def reset_history(self):
        """Reset sensor history."""
        self._history.clear()
        self._last_values.clear()
