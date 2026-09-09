"""Orchestrator Agent — coordinates the full decision pipeline.

CRITICAL FLOW:
    ProcessState
        → Data Quality Agent
        → allow_prediction? NO → ABSTAIN
        → Quality Agent (check model_available!)
        → model_available? NO → ABSTAIN
        → Reliability Agent
        → allow_optimization? NO → forecast-only / ABSTAIN
        → Optimization Agent (check simulation_available!)
        → simulation_available? NO → ABSTAIN
        → Safety Agent (check quality prediction valid!)
        → safe scenarios? NO → ABSTAIN
        → Ranking → Recommendation
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
    """Central MAS agent that coordinates all other agents."""

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

    def run_decision_cycle(
        self,
        state: ProcessState,
        feature_vector: dict[str, float] | None = None,
    ) -> Recommendation | AbstainRecommendation:
        """Execute the full decision pipeline with proper ABSTAIN gates."""
        decision_id = str(uuid.uuid4())
        state.decision_id = decision_id
        feature_vector = feature_vector or {}

        logger.info(f"[{decision_id}] Decision cycle started at {state.timestamp}")

        # ── Step 1: Data Quality Check ───────────────────────────
        dq = self.dq_agent.evaluate(state)

        if not dq.allow_prediction:
            logger.warning(f"[{decision_id}] ABSTAIN — insufficient data quality")
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="Insufficient data quality for reliable prediction",
                missing_data=dq.missing_signals,
                unsafe_scenarios=0,
                warnings=dq.warnings,
            )

        # ── Step 2: Quality Prediction ───────────────────────────
        quality_pred = self.quality_agent.predict(state, feature_vector)

        # Check if quality prediction is actually available
        if not quality_pred.model_available:
            logger.warning(
                f"[{decision_id}] ABSTAIN — quality model unavailable: "
                f"{quality_pred.unavailability_reason}"
            )
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason=f"Quality model unavailable: {quality_pred.unavailability_reason}",
                missing_data=[],
                unsafe_scenarios=0,
                warnings=[quality_pred.unavailability_reason or "Model unavailable"],
            )

        if quality_pred.prediction is None:
            logger.warning(f"[{decision_id}] ABSTAIN — quality prediction is None")
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="Quality prediction returned None",
                missing_data=[],
                unsafe_scenarios=0,
                warnings=["Quality agent could not produce prediction"],
            )

        # ── Step 3: Reliability Assessment ───────────────────────
        reliability = self.reliability_agent.evaluate(state)

        logger.info(
            f"[{decision_id}] Quality: sulfur={quality_pred.prediction:.2f}, "
            f"Reliability: risk={reliability.risk_score:.2f} ({reliability.risk_level})"
        )

        # ── Step 4: Check allow_optimization ─────────────────────
        if not dq.allow_optimization:
            logger.warning(
                f"[{decision_id}] ABSTAIN — optimization not allowed "
                f"(missing sulfur source or stale data)"
            )
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="Data quality insufficient for optimization (stale or missing quality sources)",
                missing_data=dq.missing_signals,
                unsafe_scenarios=0,
                warnings=dq.warnings + dq.stale_signals,
            )

        # ── Step 5: Generate and Evaluate Candidate Scenarios ────
        candidates = self.optimization_agent.generate_candidates(state, self.controls)
        evaluations, simulation_available = self.optimization_agent.evaluate_scenarios(
            state, candidates, feature_vector, reliability
        )

        if not simulation_available:
            logger.warning(f"[{decision_id}] ABSTAIN — surrogate simulation unavailable")
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="Surrogate model unavailable — cannot evaluate candidate scenarios",
                missing_data=[],
                unsafe_scenarios=0,
                warnings=["Surrogate model not loaded or simulation failed"],
            )

        # ── Step 6: Safety Filtering ─────────────────────────────
        safe_scenarios, unsafe_scenarios = self.safety_agent.filter_scenarios(
            evaluations, quality_pred, dq.score
        )

        if not safe_scenarios:
            logger.warning(
                f"[{decision_id}] ABSTAIN — no safe scenarios "
                f"({len(unsafe_scenarios)} rejected)"
            )
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="No safe scenarios found — all candidates violate safety constraints",
                missing_data=[],
                unsafe_scenarios=len(unsafe_scenarios),
                warnings=[f"{len(unsafe_scenarios)} scenarios rejected by safety gate"],
            )

        # ── Step 7: Ranking ──────────────────────────────────────
        ranked = self.optimization_agent.rank_scenarios(safe_scenarios)
        if not ranked:
            logger.warning(f"[{decision_id}] ABSTAIN — no valid scenarios after ranking")
            return AbstainRecommendation(
                decision_id=decision_id,
                timestamp=state.timestamp,
                reason="No valid scenarios after ranking (all simulations failed)",
                missing_data=[],
                unsafe_scenarios=0,
                warnings=["All scenario simulations returned non-ok status"],
            )

        best = ranked[0]

        # ── Step 8: Build Recommendation ─────────────────────────
        problem = None
        if quality_pred.prediction > 8.0:
            problem = f"Sulfur approaching limit: predicted {quality_pred.prediction:.1f} mg/kg"
        elif reliability.risk_level in ("high", "critical"):
            problem = f"High reliability risk: {reliability.risk_level}"

        recommended_changes = {}
        for param, value in best.action.items():
            current = state.avt_telemetry.get(param, state.unit_242000_telemetry.get(param))
            if current is not None and abs(value - current) > 0.01:
                recommended_changes[param] = {
                    "current": current,
                    "recommended": value,
                    "change": value - current,
                }

        explanation = _generate_explanation(
            state, quality_pred, reliability, best, dq
        )

        recommendation = Recommendation(
            decision_id=decision_id,
            timestamp=state.timestamp,
            current_state={
                "sulfur_prediction": quality_pred.prediction,
                "reliability_risk": reliability.risk_score,
                "data_quality_score": dq.score,
            },
            detected_problem=problem,
            recommended_changes=recommended_changes,
            expected_quality={"sulfur": best.predicted_sulfur},
            expected_production_effect=best.production_proxy,
            expected_energy_effect=best.energy_proxy,
            reliability_effect=reliability.risk_score,
            checked_constraints=[
                f"sulfur_upper_bound <= {self.safety_agent.sulfur_limit}",
                f"violation_prob <= {self.safety_agent.max_violation_prob}",
                f"risk <= {self.safety_agent.max_risk_score}",
            ],
            confidence=quality_pred.confidence,
            alternatives=[
                {
                    "scenario_id": s.scenario_id,
                    "predicted_sulfur": s.predicted_sulfur,
                    "violation_prob": s.violation_probability,
                }
                for s in ranked[1:4]
            ],
            explanation=explanation,
            model_versions={
                "quality": quality_pred.model_version,
                "quality_type": quality_pred.model_type,
                "reliability": reliability.model_version or "proxy",
                "surrogate": "available" if self.optimization_agent.surrogate.is_available else "unavailable",
            },
        )

        logger.info(
            f"[{decision_id}] RECOMMENDATION issued, "
            f"conf={recommendation.confidence:.2f}, "
            f"sulfur_pred={quality_pred.prediction:.2f}, "
            f"candidates={len(candidates)}, safe={len(safe_scenarios)}, "
            f"rejected={len(unsafe_scenarios)}"
        )
        return recommendation


def _generate_explanation(
    state: ProcessState,
    quality_pred: QualityPrediction,
    reliability,
    best_scenario,
    dq,
) -> str:
    """Generate a deterministic template explanation (no LLM)."""
    parts = []

    parts.append(f"Состояние на {state.timestamp.strftime('%Y-%m-%d %H:%M')}.")

    if "sulfur" in state.quality:
        parts.append(
            f"Текущее значение серы (ПАК): {state.quality['sulfur'].value:.1f} мг/кг."
        )

    if quality_pred.prediction is not None:
        parts.append(
            f"Прогноз серы ({quality_pred.model_type}): {quality_pred.prediction:.1f} мг/кг"
        )
        if quality_pred.lower_bound is not None and quality_pred.upper_bound is not None:
            parts[-1] += f" (границы: {quality_pred.lower_bound:.1f}–{quality_pred.upper_bound:.1f})."
        else:
            parts[-1] += "."
    else:
        parts.append("Прогноз серы: недоступен.")

    if quality_pred.violation_probability is not None:
        parts.append(f"Вероятность нарушения: {quality_pred.violation_probability:.1%}.")

    parts.append(f"Оценка надёжности: {reliability.risk_level} (риск={reliability.risk_score:.2f}).")

    if best_scenario.violation_probability < 0.05:
        parts.append("Прогноз благоприятный — критических отклонений не ожидается.")
    elif best_scenario.violation_probability < 0.2:
        parts.append("Прогноз осторожно оптимистичный — рекомендуется мониторинг.")
    else:
        parts.append("ВНИМАНИЕ: Высокая вероятность нарушения качества.")

    return " ".join(parts)
