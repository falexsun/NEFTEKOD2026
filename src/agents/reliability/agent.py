"""Reliability Agent — assesses process risk via operating envelope deviation.

Uses canonical tags (avt_T6, u24_T6 are SEPARATE signals).
No failure labels → proxy-based assessment.
Baseline risk is a documented assumption, not a statistical calculation.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.reliability import ReliabilityAssessment

logger = logging.getLogger(__name__)


class ReliabilityAgent:
    """Evaluates process reliability risk without failure labels."""

    def __init__(
        self,
        operating_envelope: dict[str, tuple[float, float]] | None = None,
        risk_threshold: float = 0.7,
        frozen_window: int = 6,
        frozen_std_threshold: float = 0.001,
        baseline_risk: float = 0.1,
    ):
        self.risk_threshold = risk_threshold
        self.envelope = operating_envelope or {}
        self.frozen_window = frozen_window
        self.frozen_std_threshold = frozen_std_threshold
        self.baseline_risk = baseline_risk  # DOCUMENTED assumption in assumptions.yaml
        self._history: dict[str, list[float]] = defaultdict(list)

    def evaluate(self, state: ProcessState) -> ReliabilityAssessment:
        factors = []
        risk_scores = []
        assumptions = [
            "Risk assessment uses historical operating envelope, not failure labels",
            "Operating envelope derived from historical data, not industrial limits",
            f"Baseline risk={self.baseline_risk} is an assumption (documented in assumptions.yaml)",
        ]

        # Use canonical tags — avt_T6 and u24_T6 are SEPARATE
        all_signals = {}
        for k, v in state.avt_telemetry.items():
            all_signals[f"avt_{k}" if not k.startswith("avt_") else k] = v
        for k, v in state.unit_242000_telemetry.items():
            all_signals[f"u24_{k}" if not k.startswith("u24_") else k] = v

        # 1. Operating envelope deviation
        for name, val in all_signals.items():
            if name in self.envelope:
                low, high = self.envelope[name]
                if val < low:
                    deviation = (low - val) / max(abs(low), 1.0)
                    risk_scores.append(min(1.0, deviation))
                    factors.append(f"{name}={val:.1f} below envelope [{low:.1f}, {high:.1f}]")
                elif val > high:
                    deviation = (val - high) / max(abs(high), 1.0)
                    risk_scores.append(min(1.0, deviation))
                    factors.append(f"{name}={val:.1f} above envelope [{low:.1f}, {high:.1f}]")

        # 2. Frozen sensor detection (canonical names prevent collision)
        frozen = self._detect_frozen(all_signals)
        if frozen:
            risk_scores.append(min(0.5, len(frozen) * 0.1))
            factors.append(f"Frozen sensors: {frozen}")

        # 3. Extreme values
        for name, val in all_signals.items():
            if abs(val) > 1e6:
                risk_scores.append(0.3)
                factors.append(f"{name}={val:.1f} extreme")

        overall_risk = float(np.mean(risk_scores)) if risk_scores else self.baseline_risk

        level = "critical" if overall_risk >= 0.8 else "high" if overall_risk >= 0.6 else "medium" if overall_risk >= 0.3 else "low"
        constraints = ["High risk — optimization should be conservative"] if overall_risk >= self.risk_threshold else []

        return ReliabilityAssessment(
            risk_score=overall_risk, risk_level=level, factors=factors,
            constraints=constraints, assumptions=assumptions,
        )

    def _detect_frozen(self, signals: dict[str, float]) -> list[str]:
        frozen = []
        for name, val in signals.items():
            history = self._history[name]
            history.append(val)
            if len(history) > self.frozen_window:
                history[:] = history[-self.frozen_window:]
            if len(history) >= self.frozen_window and np.std(history) < self.frozen_std_threshold:
                frozen.append(name)
        return frozen

    def reset_history(self):
        self._history.clear()
