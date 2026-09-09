"""Optimization Agent — generates and evaluates candidate actions."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
from src.shared.schemas.reliability import ReliabilityAssessment
from src.agents.surrogate.model import SurrogateModel

logger = logging.getLogger(__name__)


class ScenarioEvaluation(BaseModel):
    """Evaluation of a single candidate scenario."""
    scenario_id: str
    action: dict[str, float]
    predicted_sulfur: float
    sulfur_std: float
    violation_probability: float
    production_proxy: float = 0.0
    energy_proxy: float = 0.0
    reliability_risk: float = 0.0
    uncertainty: float = 0.0
    ood_score: float = 0.0


class OptimizationAgent:
    """Generates N candidate actions and evaluates them using surrogate model.

    Strategy: HARD FILTERING → PARETO / LEXICOGRAPHIC RANKING
    Priority: safety > quality > reliability > production > energy
    """

    def __init__(
        self,
        surrogate: SurrogateModel,
        n_scenarios: int = 10,
        sulfur_limit: float = 10.0,
    ):
        self.surrogate = surrogate
        self.n_scenarios = n_scenarios
        self.sulfur_limit = sulfur_limit

    def generate_candidates(
        self,
        state: ProcessState,
        controls: dict[str, tuple[float, float]],
    ) -> list[dict[str, float]]:
        """Generate N candidate control actions.

        Each candidate is a small perturbation of current state.
        """
        candidates = []

        # Current state as baseline (no change)
        baseline = {}
        for name, val in {**state.avt_telemetry, **state.unit_242000_telemetry}.items():
            if name in controls:
                baseline[name] = val
        candidates.append(baseline)

        # Generate perturbations
        for i in range(self.n_scenarios - 1):
            candidate = dict(baseline)
            # Randomly perturb a subset of controls
            n_perturb = np.random.randint(1, max(2, len(controls)))
            params_to_perturb = np.random.choice(
                list(controls.keys()), size=min(n_perturb, len(controls)), replace=False
            )

            for param in params_to_perturb:
                low, high = controls[param]
                current = baseline.get(param, (low + high) / 2)
                # Small perturbation (±10% of range)
                range_size = high - low
                delta = np.random.uniform(-0.1, 0.1) * range_size
                new_val = np.clip(current + delta, low, high)
                candidate[param] = float(new_val)

            candidates.append(candidate)

        return candidates

    def evaluate_scenarios(
        self,
        state: ProcessState,
        candidates: list[dict[str, float]],
        feature_vector: dict[str, float],
        reliability: ReliabilityAssessment,
    ) -> list[ScenarioEvaluation]:
        """Evaluate all candidate scenarios."""
        evaluations = []

        for i, action in enumerate(candidates):
            # Use surrogate to predict outcome
            predictions = self.surrogate.simulate(
                state=state,
                action=action,
                horizon_minutes=60,
                feature_vector=feature_vector,
            )

            pred_sulfur = predictions.get("sulfur", 7.0)
            sulfur_std = predictions.get("sulfur_std", 1.5)

            # Violation probability
            from scipy.stats import norm
            violation_prob = float(1 - norm.cdf(self.sulfur_limit, loc=pred_sulfur, scale=sulfur_std))

            # Production proxy: higher flow rates = higher production
            production = sum(v for k, v in action.items() if "F" in k) / max(len(action), 1)

            # Energy proxy: higher temperatures = higher energy
            energy = sum(v for k, v in action.items() if "T" in k) / max(len(action), 1)

            evaluations.append(ScenarioEvaluation(
                scenario_id=f"scenario_{i}",
                action=action,
                predicted_sulfur=pred_sulfur,
                sulfur_std=sulfur_std,
                violation_probability=violation_prob,
                production_proxy=production,
                energy_proxy=energy,
                reliability_risk=reliability.risk_score,
                uncertainty=sulfur_std,
                ood_score=0.0,
            ))

        return evaluations

    def rank_scenarios(
        self,
        scenarios: list[ScenarioEvaluation],
    ) -> list[ScenarioEvaluation]:
        """Rank scenarios using lexicographic ordering.

        Priority: violation_prob (asc) → reliability (asc) → production (desc)
        No weighted sum — quality safety cannot be compensated by production.
        """
        return sorted(
            scenarios,
            key=lambda s: (
                s.violation_probability,  # Lower violation prob first
                s.reliability_risk,       # Lower risk first
                -s.production_proxy,      # Higher production first
            ),
        )
