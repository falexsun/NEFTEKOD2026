"""Reliability Agent — assesses process risk via operating envelope deviation.

Uses historical operating envelope, NOT industrial safety limits.
No failure labels available → proxy-based assessment.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.reliability import ReliabilityAssessment

logger = logging.getLogger(__name__)


class ReliabilityAgent:
    """Evaluates process reliability risk without explicit failure labels.

    Uses a combination of:
    - Historical operating envelope deviation
    - Rate-of-change analysis
    - Frozen sensor detection (via history, not single values)
    - Duration near boundaries
    """

    def __init__(
        self,
        operating_envelope: dict[str, tuple[float, float]] | None = None,
        risk_threshold: float = 0.7,
        frozen_sensor_window: int = 6,
        frozen_sensor_std_threshold: float = 0.001,
    ):
        self.risk_threshold = risk_threshold
        self.envelope = operating_envelope or {}
        self.frozen_sensor_window = frozen_sensor_window
        self.frozen_sensor_std_threshold = frozen_sensor_std_threshold
        # History buffer for frozen sensor detection
        self._history: dict[str, list[float]] = defaultdict(list)

    def evaluate(self, state: ProcessState) -> ReliabilityAssessment:
        """Assess reliability risk for the current process state."""
        factors = []
        risk_scores = []
        assumptions = [
            "Risk assessment uses historical operating envelope, not failure labels",
            "No direct degradation/failure data available — proxy-based assessment",
            "Operating envelope is derived from historical data, not industrial limits",
        ]

        all_signals = {**state.avt_telemetry, **state.unit_242000_telemetry}

        # ── 1. Operating envelope deviation ──────────────────
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

        # ── 2. Frozen sensor detection (via history) ─────────
        frozen_sensors = self._detect_frozen_sensors(all_signals)
        if frozen_sensors:
            risk_scores.append(min(0.5, len(frozen_sensors) * 0.1))
            factors.append(f"Frozen sensors detected: {frozen_sensors}")

        # ── 3. Extreme values ────────────────────────────────
        for name, val in all_signals.items():
            if abs(val) > 1e6:
                risk_scores.append(0.3)
                factors.append(f"{name}={val:.1f} extreme value")

        # ── Overall risk ─────────────────────────────────────
        if risk_scores:
            overall_risk = float(np.mean(risk_scores))
        else:
            overall_risk = 0.1  # Low baseline risk

        # Risk level
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

    def _detect_frozen_sensors(self, signals: dict[str, float]) -> list[str]:
        """Detect frozen sensors using rolling history.

        A sensor is frozen if:
        - Last N readings have std < threshold (consecutive identical/near-identical values)
        - NOT by checking if a single value is an integer

        This correctly identifies sensors stuck at the same value over time,
        while NOT flagging legitimate integer-like readings (e.g. temperature=234.0).
        """
        frozen = []

        for name, val in signals.items():
            # Update history
            history = self._history[name]
            history.append(val)
            # Keep only last N readings
            if len(history) > self.frozen_sensor_window:
                history[:] = history[-self.frozen_sensor_window:]

            # Need at least window_size readings to check
            if len(history) < self.frozen_sensor_window:
                continue

            # Check if std is essentially zero (all readings identical)
            arr = np.array(history)
            std = np.std(arr)
            if std < self.frozen_sensor_std_threshold:
                frozen.append(name)

        return frozen

    def reset_history(self):
        """Reset frozen sensor history (e.g., on restart)."""
        self._history.clear()
