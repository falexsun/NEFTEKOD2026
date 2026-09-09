"""Optimization Agent — generates and evaluates candidate actions.

IMPROVEMENTS:
- Deterministic seed for reproducibility
- Baseline scenario 'NO CHANGE' always included
- Only allowed controls from ControlRegistry
- Production/energy proxy uses semantic tag metadata, not tag name letters
- Handles surrogate unavailable → returns empty evaluations
"""
from __future__ import annotations

import logging

import numpy as np
from pydantic import BaseModel, Field

from src.shared.schemas.process_state import ProcessState
from src.shared.schemas.quality_prediction import QualityPrediction
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
    production_proxy: float = 0.0
    energy_proxy: float = 0.0
    reliability_risk: float = 0.0
    uncertainty: float = 0.0
    ood_score: float = 0.0
    simulation_status: str = "ok"  # "ok" | "unavailable" | "error"


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
        seed: int = 42,
        # Semantic proxy configs: lists of tag names for each proxy
        flow_tags: list[str] | None = None,
        temperature_tags: list[str] | None = None,
    ):
        self.surrogate = surrogate
        self.n_scenarios = n_scenarios
        self.sulfur_limit = sulfur_limit
        self.seed = seed
        # Semantic proxy tag lists from config (not tag name letters)
        self.flow_tags = set(flow_tags or [])
        self.temperature_tags = set(temperature_tags or [])

    def generate_candidates(
        self,
        state: ProcessState,
        controls: dict[str, tuple[float, float]],
    ) -> list[dict[str, float]]:
        """Generate N candidate control actions.

        First candidate is always the baseline (NO CHANGE).
        Deterministic with fixed seed.
        """
        rng = np.random.RandomState(self.seed)

        candidates = []

        # Current state as baseline (no change) — always first
        baseline = {}
        for name, val in {**state.avt_telemetry, **state.unit_242000_telemetry}.items():
            if name in controls:
                baseline[name] = val
        candidates.append(dict(baseline))  # NO CHANGE scenario

        # Generate perturbations
        control_keys = list(controls.keys())
        if not control_keys:
            return candidates

        for i in range(self.n_scenarios - 1):
            candidate = dict(baseline)
            # Randomly perturb a subset of controls
            n_perturb = rng.randint(1, max(2, len(control_keys)))
            params_to_perturb = rng.choice(
                control_keys, size=min(n_perturb, len(control_keys)), replace=False
            )

            for param in params_to_perturb:
                low, high = controls[param]
                current = baseline.get(param, (low + high) / 2)
                # Small perturbation (±10% of range)
                range_size = high - low
                delta = rng.uniform(-0.1, 0.1) * range_size
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
    ) -> tuple[list[ScenarioEvaluation], bool]:
        """Evaluate all candidate scenarios.

        Returns (evaluations, simulation_available).
        If surrogate is unavailable, returns empty list with simulation_available=False.
        """
        # Check if surrogate can simulate
        if not self.surrogate.is_available:
            logger.warning("Optimization Agent: surrogate unavailable — cannot evaluate scenarios")
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
                logger.warning(f"Scenario {i}: simulation {result.status}")
                evaluations.append(ScenarioEvaluation(
                    scenario_id=f"scenario_{i}",
                    action=action,
                    predicted_sulfur=0.0,
                    sulfur_std=0.0,
                    violation_probability=1.0,  # Pessimistic
                    simulation_status=result.status,
                ))
                continue

            pred_sulfur = result.predictions.get("sulfur", 0.0)
            sulfur_std = result.predictions.get("sulfur_std", 5.0)

            # Violation probability
            from scipy.stats import norm
            violation_prob = float(1 - norm.cdf(self.sulfur_limit, loc=pred_sulfur, scale=sulfur_std))

            # Production proxy: use semantic tag registry, NOT tag name letters
            production = self._compute_production_proxy(action)
            energy = self._compute_energy_proxy(action)

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
                simulation_status="ok",
            ))

        return evaluations, True

    def _compute_production_proxy(self, action: dict[str, float]) -> float:
        """Compute production proxy using semantic tag registry.

        Uses configured flow_tags, NOT tag name letters.
        """
        if not self.flow_tags:
            return 0.0  # No flow tags configured — honest zero
        flow_vals = [v for k, v in action.items() if k in self.flow_tags]
        return sum(flow_vals) / len(flow_vals) if flow_vals else 0.0

    def _compute_energy_proxy(self, action: dict[str, float]) -> float:
        """Compute energy severity proxy using semantic tag registry.

        Uses configured temperature_tags, NOT tag name letters.
        """
        if not self.temperature_tags:
            return 0.0  # No temp tags configured — honest zero
        temp_vals = [v for k, v in action.items() if k in self.temperature_tags]
        return sum(temp_vals) / len(temp_vals) if temp_vals else 0.0

    def rank_scenarios(
        self,
        scenarios: list[ScenarioEvaluation],
    ) -> list[ScenarioEvaluation]:
        """Rank scenarios using lexicographic ordering.

        Priority: violation_prob (asc) → reliability (asc) → production (desc)
        No weighted sum — quality safety cannot be compensated by production.
        """
        # Only rank scenarios with successful simulation
        valid = [s for s in scenarios if s.simulation_status == "ok"]
        return sorted(
            valid,
            key=lambda s: (
                s.violation_probability,
                s.reliability_risk,
                -s.production_proxy,
            ),
        )
