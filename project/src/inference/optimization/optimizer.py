"""Scenario optimization - find best control actions."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ScenarioOptimizer:
    """Optimize control actions to minimize Q21 while maintaining production."""

    def __init__(self):
        self.n_scenarios = 10
        self.mutation_rate = 0.3

    def optimize_scenarios(
        self,
        current_state: dict[str, float],
        controls: list[dict[str, Any]],
        surrogate_model,
        safety_agent,
        max_iterations: int = 50,
    ) -> list[dict[str, Any]]:
        """Find optimal scenarios using evolutionary algorithm."""

        # Extract control bounds
        control_bounds = {
            c["id"]: {"min": c["min"], "max": c["max"], "current": c.get("current")}
            for c in controls
            if c.get("available")
        }

        if not control_bounds:
            logger.warning("No available controls for optimization")
            return []

        # Initialize population with random scenarios
        population = self._generate_initial_population(control_bounds)

        best_scenarios = []

        for iteration in range(max_iterations):
            # Evaluate all scenarios
            evaluated = []
            for scenario in population:
                result = self._evaluate_scenario(
                    scenario,
                    current_state,
                    surrogate_model,
                    safety_agent,
                )
                evaluated.append((scenario, result))

            # Sort by fitness (lower Q21 is better)
            evaluated.sort(key=lambda x: self._fitness(x[1]))

            # Keep top scenarios
            best_scenarios = [
                {
                    "scenario_id": f"opt_{i}",
                    "action": scenario,
                    "predicted_q21": result["predicted_sulfur"],
                    "violation_probability": result["violation_probability"],
                    "production_impact": result.get("production_effect", 0),
                    "fitness_score": self._fitness(result),
                    "safe": result["status"] == "safe",
                }
                for i, (scenario, result) in enumerate(evaluated[:5])
            ]

            # Check convergence
            if iteration > 10:
                top_fitness = [self._fitness(r) for _, r in evaluated[:3]]
                if max(top_fitness) - min(top_fitness) < 0.1:
                    logger.info(f"Converged at iteration {iteration}")
                    break

            # Evolve population
            population = self._evolve_population(evaluated, control_bounds)

        return best_scenarios

    def _generate_initial_population(
        self,
        control_bounds: dict[str, dict],
    ) -> list[dict[str, float]]:
        """Generate initial random population."""
        population = []

        for _ in range(self.n_scenarios):
            scenario = {}
            for control_id, bounds in control_bounds.items():
                current = bounds.get("current", (bounds["min"] + bounds["max"]) / 2)
                # Random change within ±20% of range
                range_size = bounds["max"] - bounds["min"]
                delta = np.random.uniform(-0.2, 0.2) * range_size
                new_value = np.clip(
                    current + delta,
                    bounds["min"],
                    bounds["max"]
                )
                scenario[control_id] = float(new_value)

            population.append(scenario)

        return population

    def _evaluate_scenario(
        self,
        scenario: dict[str, float],
        current_state: dict[str, float],
        surrogate_model,
        safety_agent,
    ) -> dict[str, Any]:
        """Evaluate a scenario using surrogate model and safety checks."""
        try:
            # Simulate scenario
            simulation = surrogate_model.simulate(
                current_state,
                scenario,
                horizon_minutes=60,
            )

            if simulation.status != "ok":
                return {
                    "status": "rejected",
                    "predicted_sulfur": 999.0,
                    "violation_probability": 1.0,
                }

            # Safety check
            safety_result = safety_agent.evaluate_scenario(
                predicted_sulfur=simulation.predictions["sulfur"],
                sulfur_std=simulation.predictions.get("sulfur_std", 0),
                action=scenario,
            )

            return {
                "status": "safe" if safety_result["allowed"] else "rejected",
                "predicted_sulfur": simulation.predictions["sulfur"],
                "violation_probability": simulation.predictions.get("violation_probability", 0),
                "production_effect": simulation.predictions.get("production_effect", 0),
            }

        except Exception as e:
            logger.error(f"Failed to evaluate scenario: {e}")
            return {
                "status": "rejected",
                "predicted_sulfur": 999.0,
                "violation_probability": 1.0,
            }

    def _fitness(self, result: dict[str, Any]) -> float:
        """Calculate fitness score (lower is better)."""
        if result["status"] != "safe":
            return 1000.0

        # Multi-objective fitness:
        # 1. Minimize Q21
        # 2. Minimize violation probability
        # 3. Maximize production

        q21_penalty = result["predicted_sulfur"]
        violation_penalty = result["violation_probability"] * 10
        production_bonus = -result.get("production_effect", 0) * 0.1

        return q21_penalty + violation_penalty + production_bonus

    def _evolve_population(
        self,
        evaluated: list[tuple[dict, dict]],
        control_bounds: dict[str, dict],
    ) -> list[dict[str, float]]:
        """Evolve population using crossover and mutation."""
        # Keep top 30%
        elite_size = max(1, len(evaluated) // 3)
        elite = [scenario for scenario, _ in evaluated[:elite_size]]

        new_population = elite.copy()

        # Generate offspring
        while len(new_population) < self.n_scenarios:
            # Select two parents from elite
            parent1, parent2 = np.random.choice(elite, size=2, replace=False)

            # Crossover
            child = {}
            for key in parent1.keys():
                child[key] = parent1[key] if np.random.random() < 0.5 else parent2[key]

            # Mutation
            if np.random.random() < self.mutation_rate:
                mutate_key = np.random.choice(list(child.keys()))
                bounds = control_bounds[mutate_key]
                range_size = bounds["max"] - bounds["min"]
                delta = np.random.uniform(-0.1, 0.1) * range_size
                child[mutate_key] = float(np.clip(
                    child[mutate_key] + delta,
                    bounds["min"],
                    bounds["max"]
                ))

            new_population.append(child)

        return new_population


# Global optimizer instance
_optimizer = ScenarioOptimizer()


def get_scenario_optimizer() -> ScenarioOptimizer:
    """Get global scenario optimizer."""
    return _optimizer
