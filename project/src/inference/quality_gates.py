"""
Quality gates and data validation for inference.
Implements freshness checks, frozen sensor detection, and OOD checks.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd


@dataclass
class ValidationResult:
    """Result of quality gate validation."""
    passed: bool
    reason_code: str
    message: str
    details: Dict = None


class QualityGates:
    """Quality and freshness validation for inference inputs."""

    # Q21 special codes
    Q21_UNRELIABLE_CODE = 307.0

    def __init__(
        self,
        max_staleness_minutes: int = 30,
        freeze_detection_hours: int = 2,
        ood_quantile_threshold: float = 0.001
    ):
        """
        Initialize quality gates.

        Args:
            max_staleness_minutes: Maximum age of input data
            freeze_detection_hours: Window for frozen sensor detection
            ood_quantile_threshold: Threshold for out-of-distribution detection
        """
        self.max_staleness_minutes = max_staleness_minutes
        self.freeze_detection_hours = freeze_detection_hours
        self.ood_quantile_threshold = ood_quantile_threshold

        # Training domain statistics (to be loaded from model metadata)
        self.training_quantiles = {}

    def check_freshness(
        self,
        data: pd.DataFrame,
        timestamp_col: str = "timestamp",
        reference_time: Optional[pd.Timestamp] = None,
    ) -> ValidationResult:
        """Check if data is fresh enough for inference."""
        if data.empty:
            return ValidationResult(
                passed=False,
                reason_code="NO_DATA",
                message="No input data provided"
            )

        if timestamp_col not in data.columns:
            return ValidationResult(
                passed=False,
                reason_code="NO_TIMESTAMP",
                message=f"Timestamp column '{timestamp_col}' not found"
            )

        latest = pd.to_datetime(data[timestamp_col].max())
        now = pd.Timestamp(reference_time) if reference_time is not None else (
            pd.Timestamp.now(tz="UTC") if latest.tzinfo is not None else pd.Timestamp.now())
        if latest.tzinfo is None and now.tzinfo is not None:
            now = now.tz_localize(None)
        elif latest.tzinfo is not None and now.tzinfo is None:
            now = now.tz_localize("UTC")
        age_minutes = (now - latest).total_seconds() / 60

        if age_minutes > self.max_staleness_minutes:
            return ValidationResult(
                passed=False,
                reason_code="STALE_DATA",
                message=f"Data is {age_minutes:.1f} minutes old (max: {self.max_staleness_minutes})",
                details={"age_minutes": age_minutes}
            )

        return ValidationResult(
            passed=True,
            reason_code="OK",
            message="Data freshness OK",
            details={"age_minutes": age_minutes}
        )

    def check_q21_reliability(self, q21_value: float) -> ValidationResult:
        """Check if Q21 value is reliable (not error code 307)."""
        if np.isnan(q21_value):
            return ValidationResult(
                passed=False,
                reason_code="Q21_MISSING",
                message="Q21 value is missing"
            )

        if abs(q21_value - self.Q21_UNRELIABLE_CODE) < 0.1:
            return ValidationResult(
                passed=False,
                reason_code="Q21_CODE_307",
                message="Q21 ≈ 307 ppm: confirmed known outlier; investigate analyzer and process conditions",
                details={"q21": q21_value}
            )

        return ValidationResult(
            passed=True,
            reason_code="OK",
            message="Q21 value reliable",
            details={"q21": q21_value}
        )

    def check_frozen_sensors(
        self,
        data: pd.DataFrame,
        columns: Optional[List[str]] = None
    ) -> ValidationResult:
        """Detect frozen sensors (constant values for extended period)."""
        if data.empty or len(data) < 12:  # Need at least 2 hours of 10-min data
            return ValidationResult(
                passed=True,
                reason_code="INSUFFICIENT_HISTORY",
                message="Not enough history to check for frozen sensors"
            )

        check_cols = columns or data.select_dtypes(include=[np.number]).columns
        frozen = []

        for col in check_cols:
            if col not in data.columns:
                continue

            values = data[col].dropna()
            if len(values) < 12:
                continue

            # Check if all recent values are identical
            recent = values.tail(12)
            if recent.nunique() == 1:
                frozen.append(col)

        if frozen:
            return ValidationResult(
                passed=False,
                reason_code="FROZEN_SENSOR",
                message=f"Frozen sensors detected: {', '.join(frozen[:3])}",
                details={"frozen_tags": frozen}
            )

        return ValidationResult(
            passed=True,
            reason_code="OK",
            message="No frozen sensors detected"
        )

    def check_ood(
        self,
        features: pd.DataFrame,
        feature_ranges: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> ValidationResult:
        """Check for out-of-distribution inputs."""
        if feature_ranges is None:
            return ValidationResult(
                passed=True,
                reason_code="NO_TRAINING_RANGES",
                message="No training ranges available for OOD check"
            )

        ood_features = []

        for col in features.columns:
            if col not in feature_ranges:
                continue

            min_train, max_train = feature_ranges[col]
            values = features[col].dropna()

            if len(values) == 0:
                continue

            # Check if current value is outside training range
            current = values.iloc[-1]
            if current < min_train or current > max_train:
                ood_features.append({
                    "feature": col,
                    "value": float(current),
                    "training_range": [float(min_train), float(max_train)]
                })

        if ood_features:
            return ValidationResult(
                passed=False,
                reason_code="OUT_OF_DISTRIBUTION",
                message=f"{len(ood_features)} features outside training domain",
                details={"ood_features": ood_features[:5]}  # Limit to first 5
            )

        return ValidationResult(
            passed=True,
            reason_code="OK",
            message="All features within training domain"
        )

    def check_zero_denominators(self, data: pd.DataFrame) -> ValidationResult:
        """Check for zero values in denominator positions (e.g., F30 for W70/F30 ratio)."""
        critical_denominators = ["F30"]  # Add more as needed

        zero_denoms = []
        for col in critical_denominators:
            if col not in data.columns:
                continue

            value = data[col].iloc[-1] if not data[col].empty else np.nan
            if pd.notna(value) and abs(value) < 1e-6:
                zero_denoms.append(col)

        if zero_denoms:
            return ValidationResult(
                passed=False,
                reason_code="ZERO_DENOMINATOR",
                message=f"Zero denominator detected: {', '.join(zero_denoms)}",
                details={"tags": zero_denoms}
            )

        return ValidationResult(
            passed=True,
            reason_code="OK",
            message="No zero denominator issues"
        )

    def run_all_gates(
        self,
        data: pd.DataFrame,
        q21_value: Optional[float] = None,
        feature_ranges: Optional[Dict[str, Tuple[float, float]]] = None,
        reference_time: Optional[pd.Timestamp] = None,
    ) -> List[ValidationResult]:
        """Run all quality gates and return results."""
        results = []

        # Freshness
        results.append(self.check_freshness(data, reference_time=reference_time))

        # Q21 reliability
        if q21_value is not None:
            results.append(self.check_q21_reliability(q21_value))

        # Frozen sensors
        results.append(self.check_frozen_sensors(data))

        # Zero denominators
        results.append(self.check_zero_denominators(data))

        # OOD check
        if feature_ranges:
            results.append(self.check_ood(data, feature_ranges))

        return results
