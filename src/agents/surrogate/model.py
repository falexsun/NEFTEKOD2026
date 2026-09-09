"""Dynamics / Surrogate Model — data-driven predictive model.

NOT a digital twin. Predicts future state given current state + candidate action.

CRITICAL:
- If no model → status="unavailable", ABSTAIN
- Use exact feature mapping (control name → model feature name), NOT substring matching
- lag/rolling features are historical — action does NOT rewrite them
- Uncertainty is approximate, documented in assumptions.yaml
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from src.shared.schemas.process_state import ProcessState

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Result of a surrogate simulation — explicitly tracks availability."""
    status: str  # "ok" | "unavailable" | "error"
    predictions: dict[str, float] = field(default_factory=dict)
    availability_reason: str | None = None


class SurrogateModel:
    """Data-driven surrogate model for predicting process dynamics.

    If no quality_model is provided, simulate() returns status="unavailable".
    Uses exact control→feature mapping, NOT substring matching.
    """

    def __init__(
        self,
        quality_model=None,
        feature_names: list[str] | None = None,
        control_to_feature_map: dict[str, str] | None = None,
    ):
        self.quality_model = quality_model
        self.feature_names = feature_names
        # Exact mapping: canonical control name → model feature name
        # e.g. {"avt_T1": "avt_T1", "u24_T5": "u24_T5"}
        self.control_to_feature_map = control_to_feature_map or {}

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

        Only modifies exact mapped features — does NOT touch lag/rolling/delta features.
        """
        if self.quality_model is None:
            return SimulationResult(
                status="unavailable",
                availability_reason="No surrogate model loaded",
            )

        if feature_vector is None or len(feature_vector) == 0:
            return SimulationResult(
                status="unavailable",
                availability_reason="No feature vector provided",
            )

        if self.feature_names is None:
            return SimulationResult(
                status="unavailable",
                availability_reason="No feature schema (feature_names) available",
            )

        # Apply action using EXACT mapping only
        modified_features = dict(feature_vector)
        for control_name, value in action.items():
            mapped_feature = self.control_to_feature_map.get(control_name)
            if mapped_feature and mapped_feature in modified_features:
                modified_features[mapped_feature] = value
            # If no exact mapping exists, skip this control silently
            # (lag/rolling/delta features are NOT modified)

        try:
            # Use stored feature order — never sorted()
            X = np.array([[modified_features.get(k, 0.0) for k in self.feature_names]])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            pred = float(self.quality_model.predict(X.reshape(1, -1))[0])

            return SimulationResult(
                status="ok",
                predictions={
                    "sulfur": pred,
                    "sulfur_std": 1.5,  # APPROXIMATE — in assumptions.yaml
                },
            )

        except Exception as e:
            logger.warning(f"Surrogate prediction failed: {e}")
            return SimulationResult(
                status="error",
                availability_reason=f"Simulation error: {str(e)[:100]}",
            )
