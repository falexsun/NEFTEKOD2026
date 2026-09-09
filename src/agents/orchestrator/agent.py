"""Orchestrator Agent — coordinates the full decision pipeline.

Uses ProcessState.feature_vector as canonical runtime feature source.
Checks model_available before proceeding. ABSTAINs on any critical failure.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.recommendation import Recommendation, AbstainRecommendation
from src.shared.schemas.quality_prediction import QualityPrediction
from src.agents.data_quality.agent import DataQualityAgent
from src.agents.quality.agent import QualityAgent
from src.agents.reliability.agent import ReliabilityAgent
from src.agents.optimization.agent import OptimizationAgent
from src.agents.safety.agent import SafetyAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """Central MAS agent coordinating all other agents."""

    def __init__(
        self,
        data_quality_agent: DataQualityAgent,
        quality_agent: QualityAgent,
        reliability_agent: ReliabilityAgent,
        optimization_agent: OptimizationAgent,
        safety_agent: SafetyAgent,
        controls: dict[str, tuple[float, float]] | None = None,
    ):
        self.dq_agent = data_quality_agent
        self.quality_agent = quality_agent
        self.reliability_agent = reliability_agent
        self.optimization_agent = optimization_agent
        self.safety_agent = safety_agent
        self.controls = controls or {}

    def run_decision_cycle(self, state: ProcessState) -> Recommendation | AbstainRecommendation:
        """Execute full decision pipeline. Uses state.feature_vector."""
        decision_id = str(uuid.uuid4())
        state.decision_id = decision_id

        logger.info(f"[{decision_id}] Decision cycle at {state.timestamp}")

        # Step 1: Data Quality
        dq = self.dq_agent.evaluate(state)
        if not dq.allow_prediction:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason="Insufficient data quality",
                missing_data=dq.missing_signals, unsafe_scenarios=0, warnings=dq.warnings,
            )

        # Step 2: Quality Prediction — uses state.feature_vector
        quality_pred = self.quality_agent.predict(state, state.feature_vector)
        if not quality_pred.model_available:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason=f"Quality model unavailable: {quality_pred.unavailability_reason}",
                missing_data=[], unsafe_scenarios=0,
                warnings=[quality_pred.unavailability_reason or "Model unavailable"],
            )
        if quality_pred.prediction is None:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason="Quality prediction is None",
                missing_data=[], unsafe_scenarios=0, warnings=[],
            )

        # Step 3: Reliability
        reliability = self.reliability_agent.evaluate(state)

        # Step 4: Check allow_optimization
        if not dq.allow_optimization:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason="Data quality insufficient for optimization",
                missing_data=dq.missing_signals, unsafe_scenarios=0,
                warnings=dq.warnings + dq.stale_signals,
            )

        # Step 5: Generate & Evaluate Scenarios
        candidates = self.optimization_agent.generate_candidates(state, self.controls)
        evaluations, sim_available = self.optimization_agent.evaluate_scenarios(
            state, candidates, state.feature_vector, reliability
        )
        if not sim_available:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason="Surrogate unavailable — cannot evaluate scenarios",
                missing_data=[], unsafe_scenarios=0, warnings=[],
            )

        # Step 6: Safety Filtering
        safe, unsafe = self.safety_agent.filter_scenarios(evaluations, quality_pred, dq.score)
        if not safe:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason=f"No safe scenarios ({len(unsafe)} rejected)",
                missing_data=[], unsafe_scenarios=len(unsafe), warnings=[],
            )

        # Step 7: Ranking
        ranked = self.optimization_agent.rank_scenarios(safe)
        if not ranked:
            return AbstainRecommendation(
                decision_id=decision_id, timestamp=state.timestamp,
                reason="No valid scenarios after ranking",
                missing_data=[], unsafe_scenarios=0, warnings=[],
            )

        best = ranked[0]

        # Step 8: Build Recommendation
        problem = None
        if quality_pred.prediction > 8.0:
            problem = f"Sulfur approaching limit: {quality_pred.prediction:.1f} mg/kg"
        elif reliability.risk_level in ("high", "critical"):
            problem = f"High reliability risk: {reliability.risk_level}"

        changes = {}
        for param, value in best.action.items():
            current = state.avt_telemetry.get(param, state.unit_242000_telemetry.get(param))
            if current is not None and abs(value - current) > 0.01:
                changes[param] = {"current": current, "recommended": value, "change": value - current}

        explanation = self._explain(state, quality_pred, reliability, best, dq)

        return Recommendation(
            decision_id=decision_id,
            timestamp=state.timestamp,
            current_state={"sulfur_prediction": quality_pred.prediction, "reliability_risk": reliability.risk_score, "data_quality_score": dq.score},
            detected_problem=problem,
            recommended_changes=changes,
            expected_quality={"sulfur": best.predicted_sulfur},
            expected_production_effect=None,
            expected_energy_effect=None,
            reliability_effect=reliability.risk_score,
            checked_constraints=[f"sulfur<={self.safety_agent.sulfur_limit}", f"p_viol<={self.safety_agent.max_violation_prob}", f"risk<={self.safety_agent.max_risk_score}"],
            confidence=quality_pred.confidence,
            alternatives=[{"scenario_id": s.scenario_id, "predicted_sulfur": s.predicted_sulfur, "violation_prob": s.violation_probability} for s in ranked[1:4]],
            explanation=explanation,
            model_versions={"quality": quality_pred.model_version, "quality_type": quality_pred.model_type},
        )

    def _explain(self, state, quality_pred, reliability, best, dq) -> str:
        parts = [f"Состояние на {state.timestamp.strftime('%Y-%m-%d %H:%M')}."]
        if "sulfur" in state.quality:
            parts.append(f"Сера (ПАК): {state.quality['sulfur'].value:.1f} мг/кг.")
        if quality_pred.prediction is not None:
            parts.append(f"Прогноз ({quality_pred.model_type}): {quality_pred.prediction:.1f} мг/кг.")
        if quality_pred.violation_probability is not None:
            parts.append(f"P(нарушение): {quality_pred.violation_probability:.1%}.")
        parts.append(f"Надёжность: {reliability.risk_level} (риск={reliability.risk_score:.2f}).")
        return " ".join(parts)
