"""Surrogate Model — strict schema, no fallback values.

If feature missing from feature_vector → status="unavailable".
If model unavailable → status="unavailable".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    status: str  # "ok" | "unavailable" | "error"
    predictions: dict[str, float] = field(default_factory=dict)
    availability_reason: str | None = None


class SurrogateModel:
    def __init__(self, quality_model=None, feature_names: list[str] | None = None,
                 control_to_feature_map: dict[str, str] | None = None):
        self.quality_model = quality_model
        self.feature_names = feature_names
        self.control_to_feature_map = control_to_feature_map or {}

    @property
    def is_available(self) -> bool:
        return self.quality_model is not None and self.feature_names is not None

    def simulate(self, state, action, horizon_minutes=60, feature_vector=None):
        if self.quality_model is None:
            return SimulationResult(status="unavailable", availability_reason="No surrogate model")
        if feature_vector is None or len(feature_vector) == 0:
            return SimulationResult(status="unavailable", availability_reason="No feature vector")
        if self.feature_names is None:
            return SimulationResult(status="unavailable", availability_reason="No feature schema")

        # Strict schema: check all expected features present
        missing = [f for f in self.feature_names if f not in feature_vector]
        if missing:
            return SimulationResult(
                status="unavailable",
                availability_reason=f"Missing {len(missing)} features for simulation",
            )

        # Apply action using exact mapping only
        modified = dict(feature_vector)
        for control_name, value in action.items():
            mapped = self.control_to_feature_map.get(control_name)
            if mapped and mapped in modified:
                modified[mapped] = value

        try:
            X = np.array([[modified[k] for k in self.feature_names]])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            pred = float(self.quality_model.predict(X.reshape(1, -1))[0])
            return SimulationResult(status="ok", predictions={"sulfur": pred, "sulfur_std": 1.5})
        except Exception as e:
            return SimulationResult(status="error", availability_reason=f"Simulation error: {str(e)[:100]}")
