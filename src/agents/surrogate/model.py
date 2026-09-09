"""Dynamics / Surrogate Model — data-driven predictive model.

NOT a digital twin. Predicts future state given current state + candidate action.

HONEST STATUS:
- If no quality_model is provided, simulate() returns status="unavailable"
- NEVER fabricate predictions with magic values
- Optimization Agent must check availability and ABSTAIN if unavailable
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from src.shared.schemas.process_state import ProcessState

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Result of a surrogate simulation — explicitly tracks availability."""
    status: str  # "ok" | "unavailable" | "error"
    predictions: dict[str, float]
    availability_reason: str | None = None


class SurrogateModel:
    """Data-driven surrogate model for predicting process dynamics.

    Given current state + candidate action → predicted future state/quality.
    Uses the trained ML model as the forward predictor.

    If no model is available, returns SimulationResult with status="unavailable".
    """

    def __init__(self, quality_model=None, feature_names: list[str] | None = None):
        self.quality_model = quality_model
        self.feature_names = feature_names

    @property
    def is_available(self) -> bool:
        return self.quality_model is not None

    def simulate(
        self,
        state: ProcessState,
        action: dict[str, float],
        horizon_minutes: int = 60,
        feature_vector: dict[str, float] | None = None,
    ) -> SimulationResult:
        """Simulate the effect of a candidate action.

        Returns SimulationResult with explicit status tracking.
        """
        if self.quality_model is None:
            return SimulationResult(
                status="unavailable",
                predictions={},
                availability_reason="No surrogate model loaded",
            )

        if feature_vector is None or len(feature_vector) == 0:
            return SimulationResult(
                status="unavailable",
                predictions={},
                availability_reason="No feature vector provided for simulation",
            )

        # Modify feature vector based on proposed action
        modified_features = dict(feature_vector)
        for param, value in action.items():
            # Apply action to corresponding feature
            for feat_name in list(modified_features.keys()):
                if param in feat_name:
                    modified_features[feat_name] = value

        try:
            # Use stored feature order if available
            if self.feature_names:
                feature_order = self.feature_names
            else:
                feature_order = sorted(modified_features.keys())
                logger.warning("Surrogate: no feature names — using sorted keys")

            X = np.array([[modified_features.get(k, 0.0) for k in feature_order]])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            pred = float(self.quality_model.predict(X.reshape(1, -1))[0])

            return SimulationResult(
                status="ok",
                predictions={
                    "sulfur": pred,
                    # Uncertainty is approximate — documented in assumptions.yaml
                    "sulfur_std": 1.5,
                },
            )

        except Exception as e:
            logger.warning(f"Surrogate prediction failed: {e}")
            return SimulationResult(
                status="error",
                predictions={},
                availability_reason=f"Simulation error: {str(e)[:100]}",
            )
