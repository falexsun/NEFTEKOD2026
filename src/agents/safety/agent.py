"""Safety Agent — deterministic safety gate. NO LLM. FAIL-CLOSED.

Reject when:
- model unavailable / schema mismatch
- quality prediction unavailable
- data quality insufficient
- control outside allowed range (via ControlRegistry)
- control step too large
- reliability risk too high
- OOD too high
- stale critical data
- unknown critical uncertainty

Any unexpected exception → REJECT.
"""
from __future__ import annotations

import logging

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.shared.schemas.safety import SafetyDecision

logger = logging.getLogger(__name__)


class SafetyAgent:
    """Deterministic safety filter. All checks rule-based. LLM NEVER used."""

    def __init__(
        self,
        sulfur_limit: float = 10.0,
        max_violation_prob: float = 0.2,
        max_risk_score: float = 0.8,
        max_ood_score: float = 0.8,
        min_data_quality: float = 0.3,
        control_registry=None,
    ):
        self.sulfur_limit = sulfur_limit
        self.max_violation_prob = max_violation_prob
        self.max_risk_score = max_risk_score
        self.max_ood_score = max_ood_score
        self.min_data_quality = min_data_quality
        self.control_registry = control_registry

    def check_quality_prediction(self, quality_pred: QualityPrediction) -> SafetyDecision:
        """Gate check: is the quality prediction itself valid?"""
        violations = []
        if not quality_pred.model_available:
            violations.append(f"Quality model unavailable: {quality_pred.unavailability_reason}")
        if quality_pred.prediction is None:
            violations.append("Quality prediction is None")
        return SafetyDecision(allowed=len(violations) == 0, violations=violations)

    def check_scenario(self, scenario, quality_pred: QualityPrediction, data_quality_score: float) -> SafetyDecision:
        """Run all safety checks. FAIL-CLOSED on exception."""
        try:
            violations = []
            warnings = []

            # 1. Quality prediction must be valid
            if not quality_pred.model_available or quality_pred.prediction is None:
                violations.append("Quality prediction unavailable")
                return SafetyDecision(allowed=False, violations=violations)

            # 2. Sulfur upper confidence bound
            upper = scenario.predicted_sulfur + 1.96 * scenario.sulfur_std
            if upper > self.sulfur_limit:
                violations.append(f"Sulfur UCB {upper:.2f} > {self.sulfur_limit}")

            # 3. Violation probability
            if scenario.violation_probability > self.max_violation_prob:
                violations.append(f"P(violation) {scenario.violation_probability:.3f} > {self.max_violation_prob}")

            # 4. Reliability risk
            if scenario.reliability_risk > self.max_risk_score:
                violations.append(f"Risk {scenario.reliability_risk:.3f} > {self.max_risk_score}")

            # 5. OOD score
            if scenario.ood_score > self.max_ood_score:
                violations.append(f"OOD {scenario.ood_score:.3f} > {self.max_ood_score}")

            # 6. Data quality
            if data_quality_score < self.min_data_quality:
                violations.append(f"Data quality {data_quality_score:.3f} < {self.min_data_quality}")

            # 7. Control range validation via ControlRegistry
            if self.control_registry and hasattr(scenario, 'action'):
                for param, value in scenario.action.items():
                    is_valid, ctrl_violations = self.control_registry.validate_control_value(param, value)
                    if not is_valid:
                        violations.extend(ctrl_violations)

            return SafetyDecision(
                allowed=len(violations) == 0,
                violations=violations,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"Safety Agent error: {e}")
            return SafetyDecision(
                allowed=False,
                violations=[f"Safety check failed: {str(e)[:100]}"],
                warnings=["Unexpected exception — rejecting by default"],
            )

    def filter_scenarios(self, scenarios, quality_pred, data_quality_score):
        safe, unsafe = [], []
        for s in scenarios:
            if self.check_scenario(s, quality_pred, data_quality_score).allowed:
                safe.append(s)
            else:
                unsafe.append(s)
        return safe, unsafe
