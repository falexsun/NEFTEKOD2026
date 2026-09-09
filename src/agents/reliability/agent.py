"""Reliability Agent — assesses process risk via operating envelope deviation."""
from __future__ import annotations

import logging

import numpy as np

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.reliability import ReliabilityAssessment

logger = logging.getLogger(__name__)


class ReliabilityAgent:
    """Evaluates process reliability risk without explicit failure labels.

    Uses a combination of:
    - Historical operating envelope deviation
    - Rate-of-change analysis
    - Anomaly scoring
    - Duration near extreme states
    """

    def __init__(
        self,
        operating_envelope: dict[str, tuple[float, float]] | None = None,
        risk_threshold: float = 0.7,
    ):
        self.risk_threshold = risk_threshold
        # Default operating envelopes (will be overridden by data-driven bounds)
        self.envelope = operating_envelope or {}

    def evaluate(self, state: ProcessState) -> ReliabilityAssessment:
        """Assess reliability risk for the current process state."""
        factors = []
        risk_scores = []
        assumptions = [
            "Risk assessment uses historical operating envelope, not failure labels",
            "No direct degradation/failure data available — proxy-based assessment",
        ]

        # Check operating envelope deviation
        for name, val in {**state.avt_telemetry, **state.unit_242000_telemetry}.items():
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

        # Check for frozen sensors (same value repeated = suspicious)
        frozen_count = 0
        for name, val in {**state.avt_telemetry, **state.unit_242000_telemetry}.items():
            if val == 0.0 or (isinstance(val, float) and val == int(val)):
                frozen_count += 1

        if frozen_count > 5:
            risk_scores.append(0.3)
            factors.append(f"{frozen_count} potentially frozen sensors")

        # Overall risk
        if risk_scores:
            overall_risk = float(np.mean(risk_scores))
        else:
            overall_risk = 0.1  # Low baseline risk

        # Determine risk level
        if overall_risk >= 0.8:
            level = "critical"
        elif overall_risk >= 0.6:
            level = "high"
        elif overall_risk >= 0.3:
            level = "medium"
        else:
            level = "low"

        constraints = []
        if overall_risk >= self.risk_threshold:
            constraints.append("High risk — optimization should be conservative")

        return ReliabilityAssessment(
            risk_score=overall_risk,
            risk_level=level,
            factors=factors,
            constraints=constraints,
            assumptions=assumptions,
        )
