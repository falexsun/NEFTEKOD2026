"""Safety Agent — deterministic, fail-closed. NO LLM.

Checks: model available, control ranges, max_step, reliability, OOD, data quality.
Any exception → REJECT.
"""
from __future__ import annotations

import logging

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.shared.schemas.safety import SafetyDecision

logger = logging.getLogger(__name__)


class SafetyAgent:
    def __init__(self, sulfur_limit=10.0, max_violation_prob=0.2, max_risk_score=0.8,
                 max_ood_score=0.8, min_data_quality=0.3, control_registry=None):
        self.sulfur_limit = sulfur_limit
        self.max_violation_prob = max_violation_prob
        self.max_risk_score = max_risk_score
        self.max_ood_score = max_ood_score
        self.min_data_quality = min_data_quality
        self.control_registry = control_registry

    def check_quality_prediction(self, quality_pred: QualityPrediction) -> SafetyDecision:
        violations = []
        if not quality_pred.model_available:
            violations.append(f"Quality model unavailable: {quality_pred.unavailability_reason}")
        if quality_pred.prediction is None:
            violations.append("Quality prediction is None")
        return SafetyDecision(allowed=len(violations) == 0, violations=violations)

    def check_scenario(self, scenario, quality_pred: QualityPrediction,
                       data_quality_score: float, state: ProcessState | None = None) -> SafetyDecision:
        """Run all safety checks. Pass state for max_step validation."""
        try:
            violations = []
            warnings = []

            if not quality_pred.model_available or quality_pred.prediction is None:
                violations.append("Quality prediction unavailable")
                return SafetyDecision(allowed=False, violations=violations)

            upper = scenario.predicted_sulfur + 1.96 * scenario.sulfur_std
            if upper > self.sulfur_limit:
                violations.append(f"Sulfur UCB {upper:.2f} > {self.sulfur_limit}")

            if scenario.violation_probability > self.max_violation_prob:
                violations.append(f"P(viol) {scenario.violation_probability:.3f} > {self.max_violation_prob}")

            if scenario.reliability_risk > self.max_risk_score:
                violations.append(f"Risk {scenario.reliability_risk:.3f} > {self.max_risk_score}")

            if scenario.ood_score > self.max_ood_score:
                violations.append(f"OOD {scenario.ood_score:.3f} > {self.max_ood_score}")

            if data_quality_score < self.min_data_quality:
                violations.append(f"DQ {data_quality_score:.3f} < {self.min_data_quality}")

            # Control range + max_step validation
            if self.control_registry and hasattr(scenario, 'action') and scenario.action:
                for param, value in scenario.action.items():
                    current = _get_current_value(state, param) if state else None
                    is_valid, ctrl_v = self.control_registry.validate_control_value(
                        param, value, current=current
                    )
                    if not is_valid:
                        violations.extend(ctrl_v)

            return SafetyDecision(allowed=len(violations) == 0, violations=violations, warnings=warnings)

        except Exception as e:
            logger.error(f"Safety error: {e}")
            return SafetyDecision(allowed=False, violations=[f"Safety error: {str(e)[:100]}"])

    def filter_scenarios(self, scenarios, quality_pred, data_quality_score, state=None):
        safe, unsafe = [], []
        for s in scenarios:
            if self.check_scenario(s, quality_pred, data_quality_score, state).allowed:
                safe.append(s)
            else:
                unsafe.append(s)
        return safe, unsafe


def _get_current_value(state: ProcessState, param: str) -> float | None:
    """Get current value for a control from state (canonical names)."""
    if param in state.avt_telemetry:
        return state.avt_telemetry[param]
    if param in state.unit_242000_telemetry:
        return state.unit_242000_telemetry[param]
    return None
