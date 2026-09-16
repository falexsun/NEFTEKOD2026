"""
Q21 Advisory System - Production-like inference pipeline.
Coordinates state detection, quality gates, model inference, and recommendations.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import numpy as np
import pandas as pd

from .model_bundle import Q21ModelBundle
from .state_detector import PlantState, StateDetector
from .quality_gates import QualityGates, ValidationResult
from .feature_builder import FeatureContractError, Q21FeatureBuilder
from .extended_feature_builder import build_multihorizon_features, build_quantile_features


@dataclass
class AdvisoryRecommendation:
    """Advisory system output."""
    timestamp: pd.Timestamp
    plant_state: PlantState
    q21_current: Optional[float]
    q21_forecast_1h: Optional[float]
    exceedance_probability: Optional[float]
    exceedance_risk: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    action: str  # "MONITOR", "NO_ACTION", "INVESTIGATE", "ADJUST"
    reason_code: str
    message: str
    confidence: str  # "HIGH", "MEDIUM", "LOW", "NO_CONFIDENCE"
    details: Dict = None
    validation_failures: List[ValidationResult] = None
    multi_horizon_forecasts: Dict[float, float] = None
    q21_interval_80: Tuple[float, float] = None
    extended_warnings: List[str] = None


class Q21AdvisorySystem:
    """
    Production-like advisory system for Q21 sulfur monitoring.

    This is an observational prediction system, NOT a causal control system.
    It forecasts quality based on historical patterns, not proven operator actions.
    """

    def __init__(
        self,
        models_dir: Path,
        lambda_penalty: int = 25,
        risk_threshold: Optional[float] = None
    ):
        """
        Initialize advisory system.

        Args:
            models_dir: Directory containing trained models
            lambda_penalty: Asymmetric penalty (10 or 25 for demo)
            risk_threshold: Classification threshold for exceedance
        """
        self.model_bundle = Q21ModelBundle(models_dir)
        self.state_detector = StateDetector()
        self.quality_gates = QualityGates()
        self.lambda_penalty = lambda_penalty
        if lambda_penalty not in self.CALIBRATED_THRESHOLDS:
            raise ValueError("lambda_penalty must be one of 5, 10, 25, 50")
        self.risk_threshold = risk_threshold if risk_threshold is not None else self.CALIBRATED_THRESHOLDS[lambda_penalty]
        self.feature_builder = Q21FeatureBuilder()

        # Load models at initialization
        self.model_bundle.load_models()
        # The calibrated λ=25 threshold is 0.248. An override must be explicit.
        self.model_bundle.risk_meta.threshold = self.risk_threshold
        self.model_bundle.risk_meta.lambda_penalty = lambda_penalty

    def generate_advisory(
        self,
        telemetry: pd.DataFrame,
        current_q21: Optional[float] = None,
        declared_state: Optional[PlantState] = None,
        reference_time: Optional[pd.Timestamp] = None,
    ) -> AdvisoryRecommendation:
        """
        Generate advisory recommendation from current telemetry.

        Args:
            telemetry: Recent telemetry window with all required tags
            current_q21: Current Q21 value if available

        Returns:
            AdvisoryRecommendation with forecast and action
        """
        timestamp = pd.Timestamp.now()

        if "Q21" in telemetry and not telemetry.empty:
            history_q21 = float(telemetry["Q21"].iloc[-1])
            if current_q21 is not None and not np.isclose(current_q21, history_q21, equal_nan=True):
                return AdvisoryRecommendation(
                    timestamp=timestamp, plant_state=PlantState.UNKNOWN, q21_current=current_q21,
                    q21_forecast_1h=None, exceedance_probability=None, exceedance_risk="UNKNOWN",
                    action="NO_ACTION", reason_code="Q21_SNAPSHOT_MISMATCH",
                    message="Current Q21 does not match the latest history point.", confidence="NO_CONFIDENCE",
                )
            current_q21 = history_q21

        # Step 1: Detect plant state
        if declared_state is None:
            plant_state, state_confidence = PlantState.UNKNOWN, {"source": "missing_declaration"}
        else:
            plant_state, state_confidence = declared_state, {"source": "ingestion_declaration"}

        # Step 2: Check if we're in normal operating mode
        if plant_state != PlantState.NORMAL:
            return AdvisoryRecommendation(
                timestamp=timestamp,
                plant_state=plant_state,
                q21_current=current_q21,
                q21_forecast_1h=None,
                exceedance_probability=None,
                exceedance_risk="UNKNOWN",
                action="NO_ACTION",
                reason_code=f"PLANT_STATE_{plant_state.value.upper()}",
                message=f"Plant in {plant_state.value} mode. No advisory available.",
                confidence="NO_CONFIDENCE",
                details=state_confidence
            )

        # Step 3: Run quality gates
        validation_results = self.quality_gates.run_all_gates(
            telemetry,
            q21_value=current_q21,
            reference_time=reference_time,
        )

        # Check for any validation failures
        failures = [r for r in validation_results if not r.passed]
        if failures:
            return AdvisoryRecommendation(
                timestamp=timestamp,
                plant_state=plant_state,
                q21_current=current_q21,
                q21_forecast_1h=None,
                exceedance_probability=None,
                exceedance_risk="UNKNOWN",
                action="NO_ACTION",
                reason_code=failures[0].reason_code,
                message=failures[0].message,
                confidence="NO_CONFIDENCE",
                validation_failures=failures
            )

        # Step 4: Prepare features for inference
        try:
            built = self.feature_builder.build(
                telemetry,
                self.model_bundle.get_feature_names("regression"),
                self.model_bundle.get_feature_names("risk"),
            )
            current_q21 = built.current_q21
        except FeatureContractError as e:
            return AdvisoryRecommendation(
                timestamp=timestamp,
                plant_state=plant_state,
                q21_current=current_q21,
                q21_forecast_1h=None,
                exceedance_probability=None,
                exceedance_risk="UNKNOWN",
                action="NO_ACTION",
                reason_code="FEATURE_PREPARATION_ERROR",
                message=f"Failed to prepare features: {str(e)}",
                confidence="NO_CONFIDENCE"
            )

        # Step 5: Generate predictions
        try:
            q21_forecast = self.model_bundle.predict_q21(built.regression)[0]
            _, exceedance_proba = self.model_bundle.predict_risk(built.risk)
            exceedance_prob = float(exceedance_proba[0])
        except Exception as e:
            return AdvisoryRecommendation(
                timestamp=timestamp,
                plant_state=plant_state,
                q21_current=current_q21,
                q21_forecast_1h=None,
                exceedance_probability=None,
                exceedance_risk="UNKNOWN",
                action="NO_ACTION",
                reason_code="INFERENCE_ERROR",
                message=f"Model inference failed: {str(e)}",
                confidence="NO_CONFIDENCE"
            )

        # Step 6: Determine risk level and action
        risk_level, action, message = self._assess_risk(
            q21_forecast,
            exceedance_prob,
            current_q21
        )

        # Step 7: Assess confidence
        confidence = self._assess_confidence(exceedance_prob, q21_forecast)

        extended_warnings = []
        multi_forecasts = None
        interval = None
        try:
            multi_features = {h: build_multihorizon_features(telemetry, model.feature_names_)
                              for h, model in self.model_bundle.multi_models.items()}
            multi_forecasts = self.model_bundle.predict_multihorizon(multi_features, current_q21)
            # Preserve the specialized 0.725 ppm h=1 result as the primary value.
            multi_forecasts[1.0] = float(q21_forecast)
        except FeatureContractError as exc:
            extended_warnings.append(f"MULTI_HORIZON_UNAVAILABLE: {exc}")
        try:
            quantile_features = build_quantile_features(
                telemetry, self.model_bundle.quantile_models[0.1].feature_names_)
            lower, upper = self.model_bundle.predict_h1_interval(quantile_features, current_q21)
            if lower <= upper:
                interval = (lower, upper)
            else:
                extended_warnings.append("QUANTILE_CROSSING: q10 exceeded q90")
        except FeatureContractError as exc:
            extended_warnings.append(f"UNCERTAINTY_UNAVAILABLE: {exc}")

        return AdvisoryRecommendation(
            timestamp=timestamp,
            plant_state=plant_state,
            q21_current=current_q21,
            q21_forecast_1h=float(q21_forecast),
            exceedance_probability=exceedance_prob,
            exceedance_risk=risk_level,
            action=action,
            reason_code="OK",
            message=message,
            confidence=confidence,
            multi_horizon_forecasts=multi_forecasts,
            q21_interval_80=interval,
            extended_warnings=extended_warnings,
            details={
                "lambda": self.lambda_penalty,
                "threshold": self.risk_threshold,
                "model_horizon_hours": 1
                ,"history_points": built.points
                ,"source_timestamp": built.timestamp.isoformat()
                ,"regression_sha256": self.model_bundle.regression_meta.model_sha256
                ,"risk_sha256": self.model_bundle.risk_meta.model_sha256
            }
        )

    def _assess_risk(
        self,
        q21_forecast: float,
        exceedance_prob: float,
        current_q21: Optional[float]
    ) -> Tuple[str, str, str]:
        """Assess risk level and recommend action."""
        # Risk thresholds based on λ=25 calibration
        if exceedance_prob < 0.1:
            risk = "LOW"
            action = "MONITOR"
            msg = f"Q21 forecast: {q21_forecast:.1f} ppm. Low risk of exceeding 10 ppm limit."
        elif exceedance_prob < 0.3:
            risk = "MEDIUM"
            action = "MONITOR"
            msg = f"Q21 forecast: {q21_forecast:.1f} ppm. Moderate risk ({exceedance_prob:.1%}). Continue monitoring."
        elif exceedance_prob < 0.6:
            risk = "HIGH"
            action = "INVESTIGATE"
            msg = f"Q21 forecast: {q21_forecast:.1f} ppm. High risk ({exceedance_prob:.1%}). Investigate operating conditions."
        else:
            risk = "CRITICAL"
            action = "INVESTIGATE"
            msg = f"Q21 forecast: {q21_forecast:.1f} ppm. Critical risk ({exceedance_prob:.1%}). Immediate attention recommended."

        return risk, action, msg

    def _assess_confidence(self, exceedance_prob: float, q21_forecast: float) -> str:
        """Assess confidence in prediction based on calibration metrics."""
        # Based on evaluation results: h1 has good calibration
        # AP=0.906, AUC=0.959 for λ=25
        if 0.1 < exceedance_prob < 0.9 and 5 < q21_forecast < 15:
            return "HIGH"
        elif 0.05 < exceedance_prob < 0.95 and 2 < q21_forecast < 20:
            return "MEDIUM"
        else:
            return "LOW"

    def generate_scenario_recommendation(
        self,
        advisory: AdvisoryRecommendation,
        scenario_controls: Dict[str, float]
    ) -> Dict:
        """
        Generate scenario-based recommendation.

        WARNING: This is model-based what-if analysis.
        Causal effect NOT validated. Not safe for automated control.

        Args:
            advisory: Current advisory recommendation
            scenario_controls: Proposed control adjustments

        Returns:
            Scenario analysis with clear warnings
        """
        return {
            "warning": "MODEL-BASED WHAT-IF SCENARIO",
            "disclaimer": "Causal effect not validated. Historical correlation only.",
            "not_for": "Automated control or operator instruction",
            "current_advisory": advisory,
            "proposed_changes": scenario_controls,
            "scenario_type": "DEMONSTRATION_ONLY",
            "requires": "Expert review and validation before any action"
        }
    CALIBRATED_THRESHOLDS = {5: 0.533, 10: 0.397, 25: 0.248, 50: 0.147}
