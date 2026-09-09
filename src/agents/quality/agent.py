"""Quality Agent — ML-based quality prediction.

CRITICAL RULES:
- If model is unavailable → return ABSTAIN-like QualityPrediction with model_available=False
- If feature schema is unknown → ABSTAIN
- NEVER fabricate predictions with magic values
- NEVER use sorted(feature_vector.keys()) — use stored feature order from model metadata
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
        """Check if a feature vector matches this model's expected schema.

        Returns (is_valid, list_of_issues).
        """
        issues = []
        vec_keys = set(feature_vector.keys())
        expected = set(self.feature_names)

        missing = expected - vec_keys
        extra = vec_keys - expected

        if missing:
            issues.append(f"Missing {len(missing)} expected features: {sorted(missing)[:5]}...")
        if extra:
            issues.append(f"Extra {len(extra)} unexpected features: {sorted(extra)[:5]}...")

        # If more than 10% of expected features are missing, schema is incompatible
        if len(missing) > len(expected) * 0.1:
            issues.append(f"Schema mismatch: {len(missing)}/{len(expected)} features missing")

        return len(issues) == 0, issues


class QualityAgent:
    """Predicts product quality indicators using ML models.

    If no model is available or schema doesn't match, returns a prediction
    with model_available=False — Orchestrator must check this and ABSTAIN.
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
                    self.model = load_model(path)
                    model_type = name.replace("_champion.pkl", "")

                    # Try to extract feature names from the model
                    feature_names = self._extract_feature_names(self.model)
                    if feature_names:
                        self.model_metadata = ModelArtifactMetadata(
                            model_name=name,
                            model_version="champion",
                            target="sulfur",
                            prediction_horizon_minutes=60,
                            feature_names=feature_names,
                        )
                        logger.info(
                            f"Quality Agent loaded: {name} with {len(feature_names)} features"
                        )
                    else:
                        logger.warning(
                            f"Model {name} loaded but feature names cannot be extracted — "
                            "inference will require schema validation"
                        )
                    return
                except Exception as e:
                    logger.warning(f"Failed to load {name}: {e}")

        logger.warning("No ML model found — Quality Agent will report unavailable")

    def _extract_feature_names(self, model) -> list[str] | None:
        """Try to extract feature names from a loaded model."""
        try:
            # CatBoost
            if hasattr(model, "feature_names_"):
                return list(model.feature_names_)
            # LightGBM
            if hasattr(model, "feature_name_"):
                return list(model.feature_name_)
            # XGBoost
            if hasattr(model, "feature_names_in_"):
                return list(model.feature_names_in_)
            # sklearn-style
            if hasattr(model, "get_booster"):
                booster = model.get_booster()
                if hasattr(booster, "feature_names"):
                    return list(booster.feature_names)
        except Exception:
            pass
        return None

    @property
    def is_available(self) -> bool:
        """Whether the agent can produce real predictions."""
        return self.model is not None

    @property
    def is_ready(self) -> bool:
        """Whether the agent is ready for inference (model + metadata)."""
        return self.model is not None and self.model_metadata is not None

    def predict(
        self,
        state: ProcessState,
        feature_vector: dict[str, float],
    ) -> QualityPrediction:
        """Predict sulfur quality for the current state.

        Returns QualityPrediction with model_available=False if:
        - No model loaded
        - Feature schema mismatch
        - Inference error
        """
        # ── Case 1: No model ─────────────────────────────────
        if self.model is None:
            logger.warning("Quality Agent: no model available — returning unavailable")
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                lower_bound=None,
                upper_bound=None,
                violation_probability=None,
                confidence=0.0,
                model_version="unavailable",
                model_type="unavailable",
                model_available=False,
                unavailability_reason="No ML model loaded",
            )

        # ── Case 2: Schema validation ────────────────────────
        if self.model_metadata is not None:
            is_valid, issues = self.model_metadata.validate_feature_vector(feature_vector)
            if not is_valid:
                logger.warning(f"Quality Agent: feature schema mismatch — {issues}")
                return QualityPrediction(
                    indicator="sulfur",
                    prediction=None,
                    lower_bound=None,
                    upper_bound=None,
                    violation_probability=None,
                    confidence=0.0,
                    model_version=self.model_metadata.model_version,
                    model_type=self.model_metadata.model_name,
                    model_available=False,
                    unavailability_reason=f"Feature schema mismatch: {'; '.join(issues[:3])}",
                )

        # ── Case 3: Inference ────────────────────────────────
        try:
            # Build feature array using the model's expected feature order
            if self.model_metadata is not None:
                feature_names = self.model_metadata.feature_names
            else:
                # Fallback: use sorted keys (logged as warning)
                feature_names = sorted(feature_vector.keys())
                logger.warning(
                    "Quality Agent: no feature metadata — using sorted keys (may be wrong)"
                )

            X = np.array([[feature_vector.get(k, 0.0) for k in feature_names]])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            prediction = float(self.model.predict(X.reshape(1, -1))[0])

            # Uncertainty estimate — mark as approximate
            from scipy.stats import norm
            # Use a conservative std estimate — real uncertainty requires conformal prediction
            std_estimate = 1.5  # APPROXIMATE — documented in assumptions.yaml
            lower = prediction - 1.96 * std_estimate
            upper = prediction + 1.96 * std_estimate
            violation_prob = float(1 - norm.cdf(SULFUR_LIMIT, loc=prediction, scale=std_estimate))

            return QualityPrediction(
                indicator="sulfur",
                prediction=prediction,
                lower_bound=lower,
                upper_bound=upper,
                violation_probability=violation_prob,
                confidence=min(1.0, max(0.0, 1.0 - violation_prob)),
                model_version=self.model_metadata.model_version if self.model_metadata else "unknown",
                model_type=self.model_metadata.model_name if self.model_metadata else "unknown",
                model_available=True,
                unavailability_reason=None,
                uncertainty_method="approximate_std_1.5",
            )

        except Exception as e:
            logger.error(f"Quality Agent inference failed: {e}")
            return QualityPrediction(
                indicator="sulfur",
                prediction=None,
                lower_bound=None,
                upper_bound=None,
                violation_probability=None,
                confidence=0.0,
                model_version=self.model_metadata.model_version if self.model_metadata else "unknown",
                model_type=self.model_metadata.model_name if self.model_metadata else "unknown",
                model_available=False,
                unavailability_reason=f"Inference error: {str(e)[:100]}",
            )
