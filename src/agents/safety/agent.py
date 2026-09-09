"""Safety Agent — deterministic safety gate. NO LLM."""
from __future__ import annotations

import logging

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.shared.schemas.safety import SafetyDecision
from src.agents.optimization.agent import ScenarioEvaluation

logger = logging.getLogger(__name__)


class SafetyAgent:
    """Deterministic safety filter for candidate scenarios.

    All checks are rule-based. LLM is NEVER used here.
    """

    def __init__(
        self,
        sulfur_limit: float = 10.0,
        max_violation_prob: float = 0.2,
        max_risk_score: float = 0.8,
        max_ood_score: float = 0.8,
        min_data_quality: float = 0.3,
        max_rate_of_change: float = 10.0,
    ):
        self.sulfur_limit = sulfur_limit
        self.max_violation_prob = max_violation_prob
        self.max_risk_score = max_risk_score
        self.max_ood_score = max_ood_score
        self.min_data_quality = min_data_quality
        self.max_rate_of_change = max_rate_of_change

    def check_scenario(
        self,
        scenario: ScenarioEvaluation,
        quality_pred: QualityPrediction,
        data_quality_score: float,
    ) -> SafetyDecision:
        """Run all safety checks on a single scenario."""
        violations = []
        warnings = []

        # 1. Sulfur upper confidence bound
        upper_bound = scenario.predicted_sulfur + 1.96 * scenario.sulfur_std
        if upper_bound > self.sulfur_limit:
            violations.append(
                f"Sulfur upper bound {upper_bound:.2f} > {self.sulfur_limit} mg/kg"
            )

        # 2. Violation probability
        if scenario.violation_probability > self.max_violation_prob:
            violations.append(
                f"Violation probability {scenario.violation_probability:.3f} "
                f"> {self.max_violation_prob}"
            )

        # 3. Reliability risk
        if scenario.reliability_risk > self.max_risk_score:
            violations.append(
                f"Reliability risk {scenario.reliability_risk:.3f} "
                f"> {self.max_risk_score}"
            )

        # 4. OOD score
        if scenario.ood_score > self.max_ood_score:
            violations.append(
                f"OOD score {scenario.ood_score:.3f} > {self.max_ood_score}"
            )

        # 5. Data quality
        if data_quality_score < self.min_data_quality:
            violations.append(
                f"Data quality {data_quality_score:.3f} < {self.min_data_quality}"
            )

        # 6. Rate-of-change check on action
        for param, value in scenario.action.items():
            # Check if value is within reasonable bounds
            # (In production, compare with previous state and check rate limits)
            if abs(value) > 1e5:
                warnings.append(f"Extreme control value: {param}={value:.1f}")

        # 7. Model confidence check
        if quality_pred.confidence < 0.2:
            warnings.append(
                f"Low model confidence: {quality_pred.confidence:.3f}"
            )

        allowed = len(violations) == 0

        if not allowed:
            logger.debug(
                f"Scenario {scenario.scenario_id} REJECTED: {violations}"
            )

        return SafetyDecision(
            allowed=allowed,
            violations=violations,
            warnings=warnings,
        )

    def filter_scenarios(
        self,
        scenarios: list[ScenarioEvaluation],
        quality_pred: QualityPrediction,
        data_quality_score: float,
    ) -> tuple[list[ScenarioEvaluation], list[ScenarioEvaluation]]:
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
