"""Quality Agent — ML-based quality prediction."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.training.models import load_model

logger = logging.getLogger(__name__)

SULFUR_LIMIT = 10.0  # mg/kg per GOST


class QualityAgent:
    """Predicts product quality indicators using ML models."""

    def __init__(self, model_dir: str | Path = "models"):
        self.model_dir = Path(model_dir)
        self.model = None
        self.model_version = "unknown"
        self.model_type = "unknown"
        self._load_model()

    def _load_model(self):
        """Try to load the best available model."""
        for name in ["catboost_champion.pkl", "lightgbm_champion.pkl", "xgboost_champion.pkl"]:
            path = self.model_dir / name
            if path.exists():
                try:
                    self.model = load_model(path)
                    self.model_type = name.replace("_champion.pkl", "")
                    self.model_version = "champion"
                    logger.info(f"Quality Agent loaded model: {name}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load {name}: {e}")

        logger.warning("No ML model found — Quality Agent will use fallback")

    def predict(
        self,
        state: ProcessState,
        feature_vector: dict[str, float],
    ) -> QualityPrediction:
        """Predict sulfur quality for the current state."""
        if self.model is None:
            return self._fallback_predict(state)

        try:
            # Build feature array from feature_vector
            # Sort keys for consistent ordering
            feature_names = sorted(feature_vector.keys())
            X = np.array([[feature_vector.get(k, 0.0) for k in feature_names]])

            # Replace NaN/inf
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            prediction = float(self.model.predict(X.reshape(1, -1))[0])

            # Estimate bounds using historical residual std (simple approach)
            # In production, this would use conformal prediction or quantile regression
            std_estimate = 1.5  # Approximate from training
            lower = prediction - 1.96 * std_estimate
            upper = prediction + 1.96 * std_estimate

            # Violation probability (simplified)
            from scipy.stats import norm
            violation_prob = float(1 - norm.cdf(SULFUR_LIMIT, loc=prediction, scale=std_estimate))

            return QualityPrediction(
                indicator="sulfur",
                prediction=prediction,
                lower_bound=lower,
                upper_bound=upper,
                violation_probability=violation_prob,
                confidence=min(1.0, max(0.1, 1.0 - violation_prob)),
                model_version=self.model_version,
                model_type=self.model_type,
            )
        except Exception as e:
            logger.error(f"Quality prediction failed: {e}")
            return self._fallback_predict(state)

    def _fallback_predict(self, state: ProcessState) -> QualityPrediction:
        """Fallback prediction using PAK reading or conservative estimate."""
        if "sulfur" in state.quality:
            val = state.quality["sulfur"].value
            return QualityPrediction(
                indicator="sulfur",
                prediction=val,
                lower_bound=val - 3.0,
                upper_bound=val + 3.0,
                violation_probability=0.5,  # Unknown
                confidence=0.3,
                model_version="fallback_pak",
                model_type="fallback",
            )

        return QualityPrediction(
            indicator="sulfur",
            prediction=7.0,  # Conservative mid-range
            lower_bound=2.0,
            upper_bound=12.0,
            violation_probability=0.3,
            confidence=0.1,
            model_version="fallback_default",
            model_type="fallback",
        )
