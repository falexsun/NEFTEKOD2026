"""Feature parity with ``eda/train_q21_target_a100.py`` for online inference."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class FeatureContractError(ValueError):
    """Input history cannot reproduce the training feature contract."""


@dataclass(frozen=True)
class FeatureBuildResult:
    regression: pd.DataFrame
    risk: pd.DataFrame
    current_q21: float
    timestamp: pd.Timestamp
    points: int


class Q21FeatureBuilder:
    """Build the exact rolling features used by the selected h=1 models."""

    HISTORY_HOURS = 24
    CADENCE = pd.Timedelta(minutes=10)
    MIN_POINTS = HISTORY_HOURS * 6 + 1

    def build(self, telemetry: pd.DataFrame, regression_features: list[str], risk_features: list[str]) -> FeatureBuildResult:
        if telemetry.empty or "timestamp" not in telemetry or "Q21" not in telemetry:
            raise FeatureContractError("Required columns: timestamp and Q21")
        frame = telemetry.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        if frame["timestamp"].isna().any():
            raise FeatureContractError("Invalid timestamp in Q21 history")
        frame = frame.sort_values("timestamp")
        if frame["timestamp"].duplicated().any():
            raise FeatureContractError("Duplicate timestamps in Q21 history")
        if len(frame) < self.MIN_POINTS:
            raise FeatureContractError(f"Need at least {self.MIN_POINTS} points (24 hours at 10-minute cadence)")
        frame = frame.tail(self.MIN_POINTS).set_index("timestamp")
        gaps = frame.index.to_series().diff().dropna()
        if not (gaps == self.CADENCE).all():
            raise FeatureContractError("Q21 history must have uninterrupted 10-minute cadence")

        expected = set(regression_features) | set(risk_features)
        raw_tags = sorted({name.split("_", 1)[0] for name in expected if not name.startswith("Q21_")})
        missing = [tag for tag in raw_tags if tag not in frame]
        if missing:
            raise FeatureContractError("Missing process tags: " + ", ".join(missing))
        numeric = raw_tags + ["Q21"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(frame[raw_tags].to_numpy(dtype=float)).all():
            raise FeatureContractError("Process history contains missing or non-finite values")

        target = frame["Q21"]
        process = frame[raw_tags]
        features = process.add_suffix("_now")
        for hours in (1, 3, 6, 12, 24):
            shift = hours * 6
            roll = process.rolling(f"{hours}h", min_periods=shift)
            features = features.join(roll.mean().add_suffix(f"_mean_{hours}h"))
            features = features.join(roll.std().add_suffix(f"_std_{hours}h"))
            features = features.join((process - process.shift(shift)).add_suffix(f"_change_{hours}h"))

        q_clean = target.mask((target < 0) | (target > 50))
        history = pd.DataFrame({
            "Q21_origin": q_clean,
            "Q21_invalid_or_offscale": ((target < 0) | (target > 50)).astype(float),
        }, index=frame.index)
        for hours in (1, 3, 6, 12, 24):
            shift = hours * 6
            roll = q_clean.rolling(f"{hours}h", min_periods=shift)
            history[f"Q21_past_mean_{hours}h"] = roll.mean()
            history[f"Q21_past_std_{hours}h"] = roll.std()
            history[f"Q21_past_change_{hours}h"] = q_clean - q_clean.shift(shift)
        features = features.join(history)
        latest = features.tail(1)
        unavailable = [name for name in expected if name not in latest or pd.isna(latest[name].iloc[0])]
        if unavailable:
            raise FeatureContractError("Features unavailable after engineering: " + ", ".join(unavailable[:10]))
        return FeatureBuildResult(
            regression=latest.loc[:, regression_features], risk=latest.loc[:, risk_features],
            current_q21=float(target.iloc[-1]), timestamp=frame.index[-1], points=len(frame),
        )
