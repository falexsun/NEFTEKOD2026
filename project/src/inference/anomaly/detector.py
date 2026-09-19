"""Anomaly detection system for telemetry data."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect anomalies in telemetry data."""

    def __init__(self, contamination: float = 0.05):
        self.model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )
        self.is_fitted = False
        self.feature_names: list[str] = []
        self.normal_ranges: dict[str, tuple[float, float]] = {}

    def fit(self, historical_data: list[dict[str, Any]]):
        """Fit anomaly detector on historical normal data."""
        if len(historical_data) < 50:
            logger.warning("Not enough data for anomaly detection")
            return

        # Extract features
        features, feature_names = self._extract_features(historical_data)

        if features.shape[0] < 50:
            logger.warning("Not enough valid samples for training")
            return

        self.feature_names = feature_names
        self.model.fit(features)
        self.is_fitted = True

        # Calculate normal ranges (5th-95th percentile)
        for i, name in enumerate(feature_names):
            values = features[:, i]
            self.normal_ranges[name] = (
                float(np.percentile(values, 5)),
                float(np.percentile(values, 95)),
            )

        logger.info(f"Anomaly detector trained on {features.shape[0]} samples")

    def detect(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        """Detect anomalies in current telemetry."""
        if not self.is_fitted:
            return {
                "is_anomaly": False,
                "reason": "Detector not trained",
                "anomaly_score": 0.0,
                "suspicious_signals": [],
            }

        # Extract features
        features, _ = self._extract_features([telemetry])

        if features.shape[0] == 0:
            return {
                "is_anomaly": False,
                "reason": "Insufficient data",
                "anomaly_score": 0.0,
                "suspicious_signals": [],
            }

        # Predict
        prediction = self.model.predict(features)[0]
        score = self.model.score_samples(features)[0]

        is_anomaly = prediction == -1

        # Identify suspicious signals
        suspicious = []
        if is_anomaly:
            suspicious = self._identify_suspicious_signals(telemetry)

        return {
            "is_anomaly": is_anomaly,
            "anomaly_score": float(score),
            "suspicious_signals": suspicious,
            "confidence": abs(score) if is_anomaly else 1.0,
        }

    def _extract_features(
        self,
        data: list[dict[str, Any]]
    ) -> tuple[np.ndarray, list[str]]:
        """Extract numerical features from telemetry."""
        if not data:
            return np.array([]), []

        # Key features for anomaly detection
        feature_keys = [
            "Q21", "F30", "F31", "W70", "T33", "T55",
            "P21", "P22", "T21", "T22",
        ]

        features_list = []
        valid_keys = []

        for key in feature_keys:
            values = []
            for record in data:
                val = record.get(key)
                if val is not None and isinstance(val, (int, float)):
                    values.append(float(val))
                else:
                    values.append(np.nan)

            # Only include if at least 80% non-nan
            if np.sum(~np.isnan(values)) / len(values) >= 0.8:
                features_list.append(values)
                valid_keys.append(key)

        if not features_list:
            return np.array([]), []

        features = np.array(features_list).T

        # Remove rows with any NaN
        mask = ~np.isnan(features).any(axis=1)
        features = features[mask]

        return features, valid_keys

    def _identify_suspicious_signals(
        self,
        telemetry: dict[str, Any]
    ) -> list[str]:
        """Identify which signals are outside normal ranges."""
        suspicious = []

        for name, (low, high) in self.normal_ranges.items():
            value = telemetry.get(name)
            if value is None:
                continue

            if value < low:
                suspicious.append(
                    f"{name}: {value:.2f} (ниже нормы {low:.2f})"
                )
            elif value > high:
                suspicious.append(
                    f"{name}: {value:.2f} (выше нормы {high:.2f})"
                )

        # Check for unusual correlations
        if "T33" in telemetry and "T55" in telemetry:
            t33, t55 = telemetry["T33"], telemetry["T55"]
            # Normally T55 > T33 by 50-100°C
            if t55 <= t33:
                suspicious.append(f"T55 ({t55}°C) не превышает T33 ({t33}°C)")

        if "F31" in telemetry and "W70" in telemetry:
            f31, w70 = telemetry["F31"], telemetry["W70"]
            # Check F31/W70 ratio anomaly
            if f31 > 0 and w70 > 0:
                ratio = f31 / w70
                if ratio < 5 or ratio > 50:
                    suspicious.append(f"Необычное соотношение F31/W70: {ratio:.1f}")

        return suspicious


# Global detector instance
_detector = AnomalyDetector()


def get_anomaly_detector() -> AnomalyDetector:
    """Get global anomaly detector."""
    return _detector
