"""RuntimeConfig — loads from configs/runtime.yaml, applies to all agents."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class RuntimeConfig:
    """Centralized runtime configuration loaded from YAML."""

    def __init__(self, config_path: str | Path = "configs/runtime.yaml"):
        self._config = {}
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"RuntimeConfig loaded from {path}")
        else:
            logger.warning(f"RuntimeConfig not found: {path} — using defaults")

    @property
    def data_quality(self) -> dict:
        return self._config.get("data_quality", {})

    @property
    def safety(self) -> dict:
        return self._config.get("safety", {})

    @property
    def reliability(self) -> dict:
        return self._config.get("reliability", {})

    @property
    def quality_uncertainty(self) -> dict:
        return self._config.get("quality_uncertainty", {})

    @property
    def sulfur_std(self) -> float:
        return self.quality_uncertainty.get("sulfur_std", 1.5)

    def apply_to_data_quality_agent(self, agent):
        dq = self.data_quality
        if "max_stale_minutes" in dq:
            agent.max_stale_minutes = dq["max_stale_minutes"]
        if "min_avt_signals" in dq:
            agent.min_avt_signals = dq["min_avt_signals"]
        if "min_u24_signals" in dq:
            agent.min_u24_signals = dq["min_u24_signals"]
        if "min_data_quality_score" in dq:
            agent.min_data_quality_score = dq["min_data_quality_score"]
        if "frozen_window" in dq:
            agent.frozen_window = dq["frozen_window"]
        if "frozen_std_threshold" in dq:
            agent.frozen_std_threshold = dq["frozen_std_threshold"]
        if "jump_threshold" in dq:
            agent.max_jump_threshold = dq["jump_threshold"]

    def apply_to_safety_agent(self, agent):
        s = self.safety
        if "sulfur_limit" in s:
            agent.sulfur_limit = s["sulfur_limit"]
        if "max_violation_prob" in s:
            agent.max_violation_prob = s["max_violation_prob"]
        if "max_risk_score" in s:
            agent.max_risk_score = s["max_risk_score"]
        if "max_ood_score" in s:
            agent.max_ood_score = s["max_ood_score"]
        if "min_data_quality" in s:
            agent.min_data_quality = s["min_data_quality"]

    def apply_to_reliability_agent(self, agent):
        r = self.reliability
        if "baseline_risk" in r:
            agent.baseline_risk = r["baseline_risk"]
