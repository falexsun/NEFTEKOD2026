"""QualitySourceResolver — selects best quality source based on priority + freshness.

Reads policy from configs/quality_source_policy.yaml.
Priority: LIMS > PAK > VAK (but freshness matters).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class QualitySourceCandidate:
    """A candidate quality source with metadata."""
    name: str  # "LIMS" | "PAK" | "VAK"
    value: float
    timestamp: datetime
    age_minutes: float
    confidence: float


@dataclass
class ResolvedQuality:
    """Result of quality source resolution."""
    indicator: str
    value: float
    source: str  # "LIMS" | "PAK" | "VAK"
    age_minutes: float
    confidence: float
    resolution_reason: str


class QualitySourceResolver:
    """Resolves which quality source to use for each indicator.

    Policy: configured priority + freshness check.
    If all sources stale → returns None (caller should ABSTAIN).
    """

    def __init__(self, config_path: str | Path = "configs/quality_source_policy.yaml"):
        self.policies: dict[str, list[dict]] = {}
        self._load(config_path)

    def _load(self, config_path: str | Path):
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Quality source policy not found: {path}")
            return
        with open(path) as f:
            config = yaml.safe_load(f)
        for indicator, spec in config.get("policy", {}).items():
            # Sort sources by explicit priority field (1=highest)
            sources = spec.get("sources", [])
            for i, s in enumerate(sources):
                if "priority" not in s:
                    s["priority"] = i + 1
            sources.sort(key=lambda s: s.get("priority", 99))
            self.policies[indicator] = sources
        logger.info(f"QualitySourceResolver loaded policies for: {list(self.policies.keys())}")

    def resolve(
        self,
        indicator: str,
        candidates: list[QualitySourceCandidate],
        now: datetime | None = None,
    ) -> ResolvedQuality | None:
        """Resolve the best source for an indicator.

        Returns None if all sources are stale or unavailable.
        """
        if indicator not in self.policies:
            logger.warning(f"No policy for indicator: {indicator}")
            return None

        now = now or datetime.utcnow()
        policy_sources = self.policies[indicator]

        # Try each source in priority order
        for policy in policy_sources:
            source_name = policy["name"]
            max_age = policy.get("max_age_minutes", 999999)
            default_confidence = policy.get("confidence", 0.5)

            # Find matching candidate
            for cand in candidates:
                if cand.name == source_name and cand.age_minutes <= max_age:
                    return ResolvedQuality(
                        indicator=indicator,
                        value=cand.value,
                        source=cand.name,
                        age_minutes=cand.age_minutes,
                        confidence=min(cand.confidence, default_confidence),
                        resolution_reason=f"Selected {cand.name} (priority {policy.get('priority')}, age={cand.age_minutes:.0f}min)",
                    )

        # All sources stale or unavailable
        return None
