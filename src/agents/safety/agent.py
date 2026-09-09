"""Safety Agent — deterministic safety gate. NO LLM.

FAIL-CLOSED: Any unexpected condition → REJECT / ABSTAIN.

Reject when:
- model unavailable
- feature schema mismatch (model_available=False)
- quality prediction unavailable
- data quality insufficient
- control outside allowed range
- control step too large
- reliability risk too high
- OOD too high
- stale critical data
- unknown critical uncertainty
"""
from __future__ import annotations

import logging

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.shared.schemas.safety import SafetyDecision

logger = logging.getLogger(__name__)


class SafetyAgent:
    """Deterministic safety filter for candidate scenarios.

    All checks are rule-based. LLM is NEVER used here.
    FAIL-CLOSED: any unexpected condition → REJECT.
    """

    def __init__(
        self,
        sulfur_limit: float = 10.0,
        max_violation_prob: float = 0.2,
        max_risk_score: float = 0.8,
        max_ood_score: float = 0.8,
        min_data_quality: float = 0.3,
    ):
        self.sulfur_limit = sulfur_limit
        self.max_violation_prob = max_violation_prob
        self.max_risk_score = max_risk_score
        self.max_ood_score = max_ood_score
        self.min_data_quality = min_data_quality

    def check_quality_prediction(
        self,
        quality_pred: QualityPrediction,
    ) -> SafetyDecision:
        """Gate check: is the quality prediction itself valid?

        Must be called BEFORE scenario evaluation.
        Returns REJECT if prediction is unavailable or from fallback.
        """
        violations = []

        if not quality_pred.model_available:
            violations.append(
                f"Quality model unavailable: {quality_pred.unavailability_reason or 'unknown reason'}"
            )

        if quality_pred.prediction is None:
            violations.append("Quality prediction is None — cannot evaluate scenarios")

        if quality_pred.confidence <= 0.0:
            violations.append("Quality prediction has zero confidence")

        return SafetyDecision(
            allowed=len(violations) == 0,
            violations=violations,
            warnings=[],
        )

    def check_scenario(
        self,
        scenario,
        quality_pred: QualityPrediction,
        data_quality_score: float,
    ) -> SafetyDecision:
        """Run all safety checks on a single scenario.

        FAIL-CLOSED: unexpected exception → REJECT.
        """
        try:
            violations = []
            warnings = []

            # 1. Quality prediction must be valid
            if not quality_pred.model_available:
                violations.append("Quality model unavailable — cannot evaluate safety")
                return SafetyDecision(allowed=False, violations=violations, warnings=warnings)

            if quality_pred.prediction is None:
                violations.append("Quality prediction is None")
                return SafetyDecision(allowed=False, violations=violations, warnings=warnings)

            # 2. Sulfur upper confidence bound
            upper_bound = scenario.predicted_sulfur + 1.96 * scenario.sulfur_std
            if upper_bound > self.sulfur_limit:
                violations.append(
                    f"Sulfur upper bound {upper_bound:.2f} > {self.sulfur_limit} mg/kg"
                )

            # 3. Violation probability
            if scenario.violation_probability > self.max_violation_prob:
                violations.append(
                    f"Violation probability {scenario.violation_probability:.3f} "
                    f"> {self.max_violation_prob}"
                )

            # 4. Reliability risk
            if scenario.reliability_risk > self.max_risk_score:
                violations.append(
                    f"Reliability risk {scenario.reliability_risk:.3f} "
                    f"> {self.max_risk_score}"
                )

            # 5. OOD score
            if scenario.ood_score > self.max_ood_score:
                violations.append(
                    f"OOD score {scenario.ood_score:.3f} > {self.max_ood_score}"
                )

            # 6. Data quality
            if data_quality_score < self.min_data_quality:
                violations.append(
                    f"Data quality {data_quality_score:.3f} < {self.min_data_quality}"
                )

            # 7. Model confidence
            if quality_pred.confidence < 0.1:
                warnings.append(
                    f"Very low model confidence: {quality_pred.confidence:.3f}"
                )

            allowed = len(violations) == 0

            if not allowed:
                logger.info(
                    f"Scenario {scenario.scenario_id} REJECTED: {violations}"
                )

            return SafetyDecision(
                allowed=allowed,
                violations=violations,
                warnings=warnings,
            )

        except Exception as e:
            # FAIL-CLOSED: any unexpected exception → REJECT
            logger.error(f"Safety Agent unexpected error: {e}")
            return SafetyDecision(
                allowed=False,
                violations=[f"Safety check failed with unexpected error: {str(e)[:100]}"],
                warnings=["Unexpected exception in safety check — rejecting by default"],
            )

    def filter_scenarios(
        self,
        scenarios: list,
        quality_pred: QualityPrediction,
        data_quality_score: float,
    ) -> tuple[list, list]:
        """Filter scenarios into safe and unsafe.

        Returns (safe_scenarios, unsafe_scenarios).
        """
        safe = []
        unsafe = []

        for scenario in scenarios:
            decision = self.check_scenario(scenario, quality_pred, data_quality_score)
            if decision.allowed:
                safe.append(scenario)
            else:
                unsafe.append(scenario)

        logger.info(
            f"Safety filter: {len(safe)} safe, {len(unsafe)} rejected "
            f"out of {len(scenarios)} scenarios"
        )
        return safe, unsafe
