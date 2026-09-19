"""Quality Agent — ML-based quality prediction.

CRITICAL RULES:
- If model is unavailable → model_available=False → Orchestrator ABSTAINs
- If feature metadata missing → model_available=False → ABSTAIN
- NEVER use sorted(feature_vector.keys()) — use stored feature order from model
- Extract feature names from inner estimator (wrapper.model), not wrapper itself
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction

logger = logging.getLogger(__name__)

SULFUR_LIMIT = 10.0  # mg/kg per GOST


class ModelArtifactMetadata:
    """Metadata about a loaded model artifact — required for correct inference."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        target: str,
        prediction_horizon_minutes: int,
        feature_names: list[str],
        feature_pipeline_version: str = "1.0",
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.target = target
        self.prediction_horizon_minutes = prediction_horizon_minutes
        self.feature_names = feature_names
        self.feature_pipeline_version = feature_pipeline_version

    def validate_feature_vector(self, feature_vector: dict[str, float]) -> tuple[bool, list[str]]:
        """Check if feature vector matches this model's expected schema.

        STRICT policy: any missing expected feature → schema mismatch → ABSTAIN.
        """
        issues = []
        vec_keys = set(feature_vector.keys())
        expected = set(self.feature_names)

        missing = expected - vec_keys
        extra = vec_keys - expected

        if missing:
            issues.append(f"Missing {len(missing)} expected features")
        if extra:
            issues.append(f"Extra {len(extra)} unexpected features")
        if len(feature_vector) != len(self.feature_names):
            issues.append(
                f"Feature count mismatch: got {len(feature_vector)}, "
                f"expected {len(self.feature_names)}"
            )

        return len(issues) == 0, issues


def _extract_feature_names_from_model(model) -> list[str] | None:
    """Extract feature names from a model, handling wrapper classes.

    Checks the inner estimator (model.model) first, then the model itself.
    Supports CatBoostRegressor, LGBMRegressor, XGBRegressor, sklearn-compatible.
    """
    # Get the actual estimator — unwrap wrapper classes
    estimator = getattr(model, "model", model)

    # Try various attributes in priority order
    for attr in ["feature_names_", "feature_name_", "feature_names_in_"]:
        if hasattr(estimator, attr):
            val = getattr(estimator, attr)
            if val is not None and len(val) > 0:
                return list(val)

    # Fallback: check the wrapper itself
    for attr in ["feature_names_", "feature_name_", "feature_names_in_"]:
        if hasattr(model, attr):
            val = getattr(model, attr)
            if val is not None and len(val) > 0:
                return list(val)

    return None


class QualityAgent:
    """Predicts product quality indicators using ML models.

    If no model is available or schema doesn't match, returns
    model_available=False — Orchestrator must check and ABSTAIN.
    """

    def __init__(self, model_dir: str | Path = "models"):
        self.model_dir = Path(model_dir)
        self.model = None
        self.model_metadata: ModelArtifactMetadata | None = None
        self._load_model()

    def _load_model(self):
        """Try to load the best available model with its metadata."""
        from src.training.models import load_model

        for name in ["catboost_champion.pkl", "lightgbm_champion.pkl", "xgboost_champion.pkl"]:
            path = self.model_dir / name
            if path.exists():
                try:
                    loaded = load_model(path)
                    feature_names = _extract_feature_names_from_model(loaded)

                    if not feature_names:
                        logger.error(
                            f"Model {name} loaded but feature names cannot be extracted — "
                            "cannot use for inference"
                        )
                        continue

                    self.model = loaded
                    self.model_metadata = ModelArtifactMetadata(
                        model_name=name,
                        model_version="champion",
                        target="sulfur",
                        prediction_horizon_minutes=60,
                        feature_names=feature_names,
                    )
                    logger.info(
                        f"Quality Agent loaded: {name}, "
                        f"{len(feature_names)} features, "
                        f"first5={feature_names[:5]}"
                    )
                    return
                except Exception as e:
                    logger.warning(f"Failed to load {name}: {e}")

        logger.warning("No ML model found — Quality Agent will report unavailable")

    @property
    def is_available(self) -> bool:
        return self.model is not None

    @property
    def is_ready(self) -> bool:
        return self.model is not None and self.model_metadata is not None

    def predict(
        self,
        state: ProcessState,
        feature_vector: dict[str, float],
    ) -> QualityPrediction:
        """Predict sulfur quality. Returns model_available=False if cannot predict."""
        # Case 1: No model
        if self.model is None:
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                model_available=False,
                unavailability_reason="No ML model loaded",
            )

        # Case 2: No metadata (shouldn't happen if model loaded, but safety check)
        if self.model_metadata is None:
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                model_available=False,
                unavailability_reason="Model metadata unavailable",
            )

        # Case 3: Schema validation
        is_valid, issues = self.model_metadata.validate_feature_vector(feature_vector)
        if not is_valid:
            logger.warning(f"Quality Agent: schema mismatch — {issues}")
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                model_available=False,
                unavailability_reason=f"Feature schema mismatch: {'; '.join(issues[:3])}",
            )

        # Case 4: Inference — use model's stored feature order
        try:
            feature_names = self.model_metadata.feature_names
            X = np.array([[feature_vector[k] for k in feature_names]])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            prediction = float(self.model.predict(X.reshape(1, -1))[0])

            # Uncertainty: approximate — documented in assumptions.yaml
            # NOT a calibrated confidence interval
            std_estimate = 1.5
            from scipy.stats import norm
            lower = prediction - 1.96 * std_estimate
            upper = prediction + 1.96 * std_estimate
            violation_prob = float(1 - norm.cdf(SULFUR_LIMIT, loc=prediction, scale=std_estimate))

            return QualityPrediction(
                indicator="sulfur",
                prediction=prediction,
                lower_bound=lower,
                upper_bound=upper,
                violation_probability=violation_prob,
                confidence=None,  # No calibrated confidence available
                model_version=self.model_metadata.model_version,
                model_type=self.model_metadata.model_name,
                model_available=True,
                uncertainty_method="approximate_std_1.5",
                uncertainty_value=std_estimate,
            )

        except Exception as e:
            logger.error(f"Quality Agent inference failed: {e}")
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                model_available=False,
                unavailability_reason=f"Inference error: {str(e)[:100]}",
            )

    def get_model_info(self) -> dict:
        """Return model artifact information for /model/info endpoint."""
        return {
            "model_available": self.is_available,
            "model_ready": self.is_ready,
            "model_name": self.model_metadata.model_name if self.model_metadata else None,
            "model_version": self.model_metadata.model_version if self.model_metadata else None,
            "target": self.model_metadata.target if self.model_metadata else None,
            "horizon_minutes": self.model_metadata.prediction_horizon_minutes if self.model_metadata else None,
            "feature_count": len(self.model_metadata.feature_names) if self.model_metadata else 0,
            "feature_schema_available": self.model_metadata is not None,
        }
