"""Optimization Agent — generates and evaluates candidate actions.

IMPROVEMENTS:
- Deterministic seed for reproducibility
- Baseline scenario 'NO CHANGE' always first, contains actual current values
- Only uses controls from ControlRegistry
- Skips controls with no current value (no midpoint guessing)
- Uses exact control→feature mapping for surrogate
- Production/energy proxy returns None if semantic tags not configured
"""
from __future__ import annotations

import logging

import numpy as np
from pydantic import BaseModel, Field

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.reliability import ReliabilityAssessment
from src.agents.surrogate.model import SurrogateModel, SimulationResult

logger = logging.getLogger(__name__)


class ScenarioEvaluation(BaseModel):
    """Evaluation of a single candidate scenario."""
    scenario_id: str
    action: dict[str, float]
    predicted_sulfur: float
    sulfur_std: float
    violation_probability: float
    production_proxy: float | None = None
    energy_proxy: float | None = None
    reliability_risk: float = 0.0
    uncertainty: float = 0.0
    ood_score: float = 0.0
    simulation_status: str = "ok"


class OptimizationAgent:
    """Generates N candidate actions using ControlRegistry.

    Strategy: HARD FILTERING → LEXICOGRAPHIC RANKING
    Priority: safety > quality > reliability > production > energy
    """

    def __init__(
        self,
        surrogate: SurrogateModel,
        n_scenarios: int = 10,
        sulfur_limit: float = 10.0,
        seed: int = 42,
    ):
        self.surrogate = surrogate
        self.n_scenarios = n_scenarios
        self.sulfur_limit = sulfur_limit
        self.seed = seed

    def generate_candidates(
        self,
        state: ProcessState,
        controls: dict[str, tuple[float, float]],
    ) -> list[dict[str, float]]:
        """Generate candidate control actions.

        First candidate is always NO CHANGE (current values).
        Only includes controls that have current values in state.
        Skips controls with no current value (no midpoint guessing).
        """
        rng = np.random.RandomState(self.seed)
        all_signals = {**state.avt_telemetry, **state.unit_242000_telemetry}

        # Build baseline: only controls that have current values
        baseline = {}
        for name in controls:
            if name in all_signals:
                baseline[name] = all_signals[name]
            # If control not in current state → skip (don't guess midpoint)

        if not baseline:
            return [{}]  # Empty baseline — no controls available

        candidates = [dict(baseline)]  # NO CHANGE

        control_keys = list(baseline.keys())

        for i in range(self.n_scenarios - 1):
            candidate = dict(baseline)
            n_perturb = rng.randint(1, max(2, len(control_keys)))
            params = rng.choice(control_keys, size=min(n_perturb, len(control_keys)), replace=False)

            for param in params:
                low, high = controls[param]
                current = baseline[param]
                range_size = high - low
                if range_size <= 0:
                    continue
                delta = rng.uniform(-0.1, 0.1) * range_size
                candidate[param] = float(np.clip(current + delta, low, high))

            candidates.append(candidate)

        return candidates

    def evaluate_scenarios(
        self,
        state: ProcessState,
        candidates: list[dict[str, float]],
        feature_vector: dict[str, float],
        reliability: ReliabilityAssessment,
    ) -> tuple[list[ScenarioEvaluation], bool]:
        """Evaluate all candidate scenarios.

        Returns (evaluations, simulation_available).
        """
        if not self.surrogate.is_available:
            logger.warning("Optimization Agent: surrogate unavailable")
            return [], False

        evaluations = []
        for i, action in enumerate(candidates):
            result: SimulationResult = self.surrogate.simulate(
                state=state,
                action=action,
                horizon_minutes=60,
                feature_vector=feature_vector,
            )

            if result.status != "ok":
                evaluations.append(ScenarioEvaluation(
                    scenario_id=f"scenario_{i}",
                    action=action,
                    predicted_sulfur=0.0,
                    sulfur_std=0.0,
                    violation_probability=1.0,
                    simulation_status=result.status,
                ))
                continue

            pred_sulfur = result.predictions.get("sulfur", 0.0)
            sulfur_std = result.predictions.get("sulfur_std", 5.0)

            from scipy.stats import norm
            violation_prob = float(1 - norm.cdf(self.sulfur_limit, loc=pred_sulfur, scale=sulfur_std))

            evaluations.append(ScenarioEvaluation(
                scenario_id=f"scenario_{i}",
                action=action,
                predicted_sulfur=pred_sulfur,
                sulfur_std=sulfur_std,
                violation_probability=violation_prob,
                production_proxy=None,  # No semantic proxy configured
                energy_proxy=None,       # No semantic proxy configured
                reliability_risk=reliability.risk_score,
                uncertainty=sulfur_std,
                ood_score=0.0,
                simulation_status="ok",
            ))

        return evaluations, True

    def rank_scenarios(self, scenarios: list[ScenarioEvaluation]) -> list[ScenarioEvaluation]:
        """Rank using lexicographic ordering. No weighted sum."""
        valid = [s for s in scenarios if s.simulation_status == "ok"]
        return sorted(
            valid,
            key=lambda s: (s.violation_probability, s.reliability_risk),
        )
