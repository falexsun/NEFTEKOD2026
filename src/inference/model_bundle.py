"""
Model bundle for Q21 advisory system.
Loads trained models with metadata, feature order, and imputation values.
"""
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, CatBoostClassifier


@dataclass
class ModelMetadata:
    """Metadata for deployed model."""
    model_sha256: str
    model_path: str
    feature_set: str
    horizon_hours: float
    training_timestamp: str
    training_domain_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    feature_order: List[str] = field(default_factory=list)
    imputation_medians: Dict[str, float] = field(default_factory=dict)
    lambda_penalty: int = 25
    threshold: float = 0.5
    tag_version: str = "v1"


class Q21ModelBundle:
    """Bundle containing Q21 regression and classification models with inference logic."""

    EXPECTED_CHECKSUMS = {
        "regression": "95469b40d8b550fa1dbf16e7faba4ed400c0a9398fe015f8042c00259d478eee",
        "risk": "a0ef98b61af8ba439260e546da13e787c171f0ec90ebd5c300d6b89d18f3e496",
        "multi_0.5": "8f071c76994a866a04229305d5125b273914d5369250aaee3b1feaadfa8a7247",
        "multi_1.0": "5f67c37b51e30f50d5ffa1f83c0844b9aa84c09813df7eff9b84098a8a8b022a",
        "multi_2.0": "234d5abf491e3d81b72016fa59996db1e72d0f89578f1f0f7574e2933a1cc748",
        "multi_3.0": "3c16b884ea7e2bdff743a17d4a30d5d26f124c128bf192d3d7affdb31b966a0d",
        "multi_6.0": "b15dc12264547975d3b87fb43104903dfe777a052cf7bc9dd4ef1613928b9367",
        "quantile_0.1": "24b8ccadcfcb2193a241648d3ed531e3e31ed463930eca3345aff86556c9b7a0",
        "quantile_0.9": "dcde4d7e9a08b0170b6988586cbba150ebff518909f279b4ae629189ebaa1dad",
    }

    def __init__(self, models_dir: Path):
        """
        Initialize model bundle.

        Args:
            models_dir: Directory containing .cbm model files
        """
        self.models_dir = Path(models_dir)
        self.regression_model: Optional[CatBoostRegressor] = None
        self.risk_model: Optional[CatBoostClassifier] = None
        self.regression_meta: Optional[ModelMetadata] = None
        self.risk_meta: Optional[ModelMetadata] = None
        self.multi_models: Dict[float, CatBoostRegressor] = {}
        self.quantile_models: Dict[float, CatBoostRegressor] = {}

    def load_models(self) -> None:
        """Load both regression and risk models from disk."""
        # Load regression model (q50)
        reg_path = self.models_dir / "reg_h1_all_plus_q21_history_q50.cbm"
        if not reg_path.exists():
            raise FileNotFoundError(f"Regression model not found: {reg_path}")

        self.regression_model = CatBoostRegressor()
        self.regression_model.load_model(str(reg_path))

        # Load risk classification model
        risk_path = self.models_dir / "risk_h1_controls_plus_q21_history_s42.cbm"
        if not risk_path.exists():
            raise FileNotFoundError(f"Risk model not found: {risk_path}")

        self.risk_model = CatBoostClassifier()
        self.risk_model.load_model(str(risk_path))

        # Initialize metadata
        self.regression_meta = ModelMetadata(
            model_sha256=self.EXPECTED_CHECKSUMS["regression"],
            model_path=str(reg_path),
            feature_set="all_plus_q21_history",
            horizon_hours=1,
            training_timestamp="2026-09-15T16:28:45+00:00"
        )

        self.risk_meta = ModelMetadata(
            model_sha256=self.EXPECTED_CHECKSUMS["risk"],
            model_path=str(risk_path),
            feature_set="controls_plus_q21_history",
            horizon_hours=1,
            training_timestamp="2026-09-15T16:28:45+00:00",
            lambda_penalty=25,
            threshold=0.248
        )

        for kind, path in (("regression", reg_path), ("risk", risk_path)):
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != self.EXPECTED_CHECKSUMS[kind]:
                raise RuntimeError(f"{kind} model checksum mismatch: {actual}")

        for horizon in (0.5, 1.0, 2.0, 3.0, 6.0):
            path = self.models_dir / f"reg_h{horizon}_residual.cbm"
            self._verify(path, f"multi_{horizon}")
            model = CatBoostRegressor()
            model.load_model(str(path))
            self.multi_models[horizon] = model
        for quantile, filename in ((0.1, "quantile_h1_q10.cbm"), (0.9, "quantile_h1_q90.cbm")):
            path = self.models_dir / filename
            self._verify(path, f"quantile_{quantile}")
            model = CatBoostRegressor()
            model.load_model(str(path))
            self.quantile_models[quantile] = model

    def _verify(self, path: Path, kind: str) -> None:
        if not path.exists():
            raise FileNotFoundError(f"{kind} model not found: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != self.EXPECTED_CHECKSUMS[kind]:
            raise RuntimeError(f"{kind} model checksum mismatch: {actual}")

    def predict_q21(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict Q21 value (median/q50).

        Args:
            features: DataFrame with features in correct order

        Returns:
            Array of Q21 predictions in ppm
        """
        if self.regression_model is None:
            raise RuntimeError("Models not loaded. Call load_models() first.")

        ordered = features.loc[:, self.get_feature_names("regression")]
        return self.regression_model.predict(ordered)

    def predict_risk(self, features: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Predict risk of Q21 exceeding 10 ppm.

        Args:
            features: DataFrame with features in correct order

        Returns:
            Tuple of (class predictions, probabilities of exceedance)
        """
        if self.risk_model is None:
            raise RuntimeError("Models not loaded. Call load_models() first.")

        ordered = features.loc[:, self.get_feature_names("risk")]
        proba = self.risk_model.predict_proba(ordered)
        # Assuming class 1 is Q21 > 10
        exceedance_proba = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
        predictions = (exceedance_proba > self.risk_meta.threshold).astype(int)

        return predictions, exceedance_proba

    def get_feature_names(self, model_type: str = "risk") -> List[str]:
        """Get feature names from specified model."""
        if model_type == "risk" and self.risk_model:
            return self.risk_model.feature_names_
        elif model_type == "regression" and self.regression_model:
            return self.regression_model.feature_names_
        return []

    def predict_multihorizon(self, features: Dict[float, pd.DataFrame], current_q21: float) -> Dict[float, float]:
        return {h: float(current_q21 + model.predict(features[h].loc[:, model.feature_names_])[0])
                for h, model in self.multi_models.items()}

    def predict_h1_interval(self, features: pd.DataFrame, current_q21: float) -> Tuple[float, float]:
        lower = current_q21 + float(self.quantile_models[0.1].predict(features.loc[:, self.quantile_models[0.1].feature_names_])[0])
        upper = current_q21 + float(self.quantile_models[0.9].predict(features.loc[:, self.quantile_models[0.9].feature_names_])[0])
        return lower, upper

    def export_metadata(self, output_path: Path) -> None:
        """Export model metadata to JSON file."""
        metadata = {
            "regression": {
                "sha256": self.regression_meta.model_sha256,
                "feature_set": self.regression_meta.feature_set,
                "horizon_hours": self.regression_meta.horizon_hours,
                "features_count": len(self.get_feature_names("regression"))
            },
            "risk": {
                "sha256": self.risk_meta.model_sha256,
                "feature_set": self.risk_meta.feature_set,
                "horizon_hours": self.risk_meta.horizon_hours,
                "lambda": self.risk_meta.lambda_penalty,
                "threshold": self.risk_meta.threshold,
                "features_count": len(self.get_feature_names("risk"))
            },
            "exported_at": datetime.utcnow().isoformat()
        }

        with open(output_path, "w") as f:
            json.dump(metadata, f, indent=2)
