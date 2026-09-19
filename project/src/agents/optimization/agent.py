"""Optimization Agent — no magic prediction defaults.

If surrogate returns predictions without 'sulfur' or 'sulfur_std' → simulation_status="error".
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
    scenario_id: str
    action: dict[str, float]
    predicted_sulfur: float = 0.0
    sulfur_std: float = 0.0
    violation_probability: float = 1.0
    production_proxy: float | None = None
    energy_proxy: float | None = None
    reliability_risk: float = 0.0
    uncertainty: float = 0.0
    ood_score: float = 0.0
    simulation_status: str = "ok"


class OptimizationAgent:
    def __init__(self, surrogate: SurrogateModel, n_scenarios=10, sulfur_limit=10.0, seed=42):
        self.surrogate = surrogate
        self.n_scenarios = n_scenarios
        self.sulfur_limit = sulfur_limit
        self.seed = seed

    def generate_candidates(self, state: ProcessState, controls: dict[str, tuple[float, float]]) -> list[dict[str, float]]:
        rng = np.random.RandomState(self.seed)
        all_signals = {**state.avt_telemetry, **state.unit_242000_telemetry}

        baseline = {}
        for name in controls:
            if name in all_signals:
                baseline[name] = all_signals[name]

        if not baseline:
            return []

        candidates = [dict(baseline)]
        control_keys = list(baseline.keys())

        for _ in range(self.n_scenarios - 1):
            candidate = dict(baseline)
            n = rng.randint(1, max(2, len(control_keys)))
            params = rng.choice(control_keys, size=min(n, len(control_keys)), replace=False)
            for param in params:
                low, high = controls[param]
                current = baseline[param]
                delta = rng.uniform(-0.1, 0.1) * (high - low)
                candidate[param] = float(np.clip(current + delta, low, high))
            candidates.append(candidate)

        return candidates

    def evaluate_scenarios(self, state, candidates, feature_vector, reliability):
        if not self.surrogate.is_available:
            return [], False

        evaluations = []
        for i, action in enumerate(candidates):
            result: SimulationResult = self.surrogate.simulate(
                state=state, action=action, horizon_minutes=60, feature_vector=feature_vector,
            )
            if result.status != "ok":
                evaluations.append(ScenarioEvaluation(
                    scenario_id=f"scenario_{i}", action=action, simulation_status=result.status,
                ))
                continue

            # No magic defaults — if keys missing, mark as error
            if "sulfur" not in result.predictions or "sulfur_std" not in result.predictions:
                evaluations.append(ScenarioEvaluation(
                    scenario_id=f"scenario_{i}", action=action, simulation_status="error",
                ))
                continue

            pred = result.predictions["sulfur"]
            std = result.predictions["sulfur_std"]

            from scipy.stats import norm
            vprob = float(1 - norm.cdf(self.sulfur_limit, loc=pred, scale=std))

            evaluations.append(ScenarioEvaluation(
                scenario_id=f"scenario_{i}", action=action,
                predicted_sulfur=pred, sulfur_std=std,
                violation_probability=vprob,
                production_proxy=None, energy_proxy=None,
                reliability_risk=reliability.risk_score, uncertainty=std,
                simulation_status="ok",
            ))

        return evaluations, True

    def rank_scenarios(self, scenarios):
        valid = [s for s in scenarios if s.simulation_status == "ok"]
        return sorted(valid, key=lambda s: (s.violation_probability, s.reliability_risk))
