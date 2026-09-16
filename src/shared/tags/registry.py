"""Control Registry — reads configs/controls.yaml and provides ControlSpec objects.

Optimizer works ONLY through ControlRegistry.
Only tags with role=control_candidate or role=both can be modified by optimizer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ControlSpec:
    """Specification for a single controllable variable."""
    name: str  # canonical name, e.g. "avt_T1"
    semantic_name: str  # human-readable, e.g. "Температура верха К1"
    unit: str  # e.g. "°C", "m3/h"
    stage: str  # "AVT" | "Hydrofining"
    role: str  # "state" | "control_candidate" | "both"
    model_range: tuple[float, float] | None  # plausible range from domain
    max_step: float | None  # max allowed change per step
    max_rate_of_change: float | None  # max rate per 10-min
    source: str  # "expert" | "data" | "standard"
    confidence: str  # "high" | "medium" | "low"


class ControlRegistry:
    """Registry of all controllable variables, loaded from YAML config."""

    def __init__(self, config_path: str | Path = "configs/controls.yaml"):
        self.controls: dict[str, ControlSpec] = {}
        self._load(config_path)

    def _load(self, config_path: str | Path):
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Controls config not found: {path}")
            return

        with open(path) as f:
            config = yaml.safe_load(f)

        for name, spec in config.get("variables", {}).items():
            pr = spec.get("plausible_range")
            model_range = (pr[0], pr[1]) if pr and len(pr) == 2 else None

            self.controls[name] = ControlSpec(
                name=name,
                semantic_name=spec.get("description", name),
                unit=spec.get("unit", ""),
                stage=spec.get("stage", ""),
                role=spec.get("role", ["state"])[0] if isinstance(spec.get("role"), list) else spec.get("role", "state"),
                model_range=model_range,
                max_step=spec.get("max_step"),
                max_rate_of_change=spec.get("max_rate_of_change"),
                source=spec.get("source", "expert"),
                confidence=spec.get("confidence", "low"),
            )

        n_controls = sum(1 for c in self.controls.values() if c.role in ("control_candidate", "both"))
        logger.info(f"ControlRegistry loaded {len(self.controls)} variables, {n_controls} control candidates")

    def get_control_candidates(self) -> dict[str, ControlSpec]:
        """Return only variables that are control candidates."""
        return {k: v for k, v in self.controls.items() if v.role in ("control_candidate", "both")}

    def get_optimization_bounds(self) -> dict[str, tuple[float, float]]:
        """Return bounds for optimizer: only control_candidates with ranges."""
        bounds = {}
        for name, spec in self.get_control_candidates().items():
            if spec.model_range is not None:
                bounds[name] = spec.model_range
        return bounds

    def is_control(self, name: str) -> bool:
        """Check if a tag is a control candidate."""
        spec = self.controls.get(name)
        return spec is not None and spec.role in ("control_candidate", "both")

    def get_spec(self, name: str) -> ControlSpec | None:
        return self.controls.get(name)

    def validate_control_value(self, name: str, value: float, current: float | None = None) -> tuple[bool, list[str]]:
        """Validate a proposed control value against registry constraints.

        Returns (is_valid, list_of_violations).
        """
        violations = []
        spec = self.controls.get(name)

        if spec is None:
            violations.append(f"Unknown control: {name}")
            return False, violations

        if spec.role not in ("control_candidate", "both"):
            violations.append(f"{name} is not a control candidate (role={spec.role})")

        if spec.model_range is not None:
            low, high = spec.model_range
            if value < low or value > high:
                violations.append(f"{name}={value:.1f} outside model range [{low:.1f}, {high:.1f}]")

        if spec.max_step is not None and current is not None:
            if abs(value - current) > spec.max_step:
                violations.append(
                    f"{name}: change {abs(value-current):.1f} > max_step {spec.max_step:.1f}"
                )

        return len(violations) == 0, violations

    def build_control_to_feature_map(self) -> dict[str, str]:
        """Build mapping from control canonical name to model feature name.

        For controls registered as avt_T1, the model feature is avt_T1 (same).
        This mapping is used by the surrogate model for exact feature modification.
        """
        return {name: name for name in self.get_control_candidates()}
