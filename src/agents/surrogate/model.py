"""Dynamics / Surrogate Model — data-driven predictive model.

NOT a digital twin. Predicts future state given current state + candidate action.
"""
from __future__ import annotations

import logging

import numpy as np

from src.shared.schemas.process_state import ProcessState

logger = logging.getLogger(__name__)


class SurrogateModel:
    """Data-driven surrogate model for predicting process dynamics.

    Given current state + candidate action → predicted future state/quality.
    Uses the trained ML model as the forward predictor.
    """

    def __init__(self, quality_model=None):
        self.quality_model = quality_model

    def simulate(
        self,
        state: ProcessState,
        action: dict[str, float],
        horizon_minutes: int = 60,
        feature_vector: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Simulate the effect of a candidate action.

        Returns predicted quality indicators.
        """
        if feature_vector is None:
            feature_vector = {}

        # Modify feature vector based on proposed action
        modified_features = dict(feature_vector)
        for param, value in action.items():
            # Apply action to corresponding feature
            for feat_name in modified_features:
                if param in feat_name:
                    modified_features[feat_name] = value

        # Predict using quality model
        predictions = {}

        if self.quality_model is not None:
            try:
                feature_names = sorted(modified_features.keys())
                X = np.array([[modified_features.get(k, 0.0) for k in feature_names]])
                X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

                pred = float(self.quality_model.predict(X.reshape(1, -1))[0])
                predictions["sulfur"] = pred
                predictions["sulfur_std"] = 1.5  # Estimated uncertainty

            except Exception as e:
                logger.warning(f"Surrogate prediction failed: {e}")
                # Fallback to current state
                if "sulfur" in state.quality:
                    predictions["sulfur"] = state.quality["sulfur"].value
                predictions["sulfur_std"] = 5.0  # High uncertainty
        else:
            # No model available — return current state values
            if "sulfur" in state.quality:
                predictions["sulfur"] = state.quality["sulfur"].value
            predictions["sulfur_std"] = 5.0

        return predictions
