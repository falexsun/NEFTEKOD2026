"""Feature parity for universal residual and h=1 quantile models."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .feature_builder import FeatureContractError


def _prepared(telemetry: pd.DataFrame) -> pd.DataFrame:
    frame = telemetry.copy()
    if "timestamp" not in frame or "Q21" not in frame:
        raise FeatureContractError("Required columns: timestamp and Q21")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.sort_values("timestamp")
    if frame["timestamp"].isna().any() or frame["timestamp"].duplicated().any():
        raise FeatureContractError("Invalid or duplicate timestamp")
    if len(frame) < 37:
        raise FeatureContractError("Need at least 37 points for extended forecasts")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(minutes=10)).all():
        raise FeatureContractError("History must have uninterrupted 10-minute cadence")
    frame = frame.reset_index(drop=True)
    return frame


def build_multihorizon_features(telemetry: pd.DataFrame, expected: list[str]) -> pd.DataFrame:
    frame = _prepared(telemetry)
    raw = [name for name in expected if "_lag" not in name and not name.startswith("Q21_")]
    missing = [name for name in set(raw + ["Q21"]) if name not in frame]
    if missing:
        raise FeatureContractError("Missing multi-horizon tags: " + ", ".join(sorted(missing)))
    frame[list(set(raw + ["Q21"]))] = frame[list(set(raw + ["Q21"]))].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(frame[list(set(raw + ["Q21"]))].to_numpy(float)).all():
        raise FeatureContractError("Multi-horizon history contains missing or non-finite values")
    q = frame["Q21"]
    for lag in (1, 2, 3, 6, 12, 18, 24, 36):
        frame[f"Q21_lag{lag}"] = q.shift(lag)
    for window in (6, 18, 36):
        roll = q.rolling(window, min_periods=1)
        frame[f"Q21_mean_{window}"] = roll.mean()
        frame[f"Q21_std_{window}"] = roll.std()
        frame[f"Q21_min_{window}"] = roll.min()
        frame[f"Q21_max_{window}"] = roll.max()
    frame["Q21_diff1"] = q.diff(1)
    frame["Q21_diff6"] = q.diff(6)
    frame["Q21_abs_diff_mean_18"] = q.diff(1).abs().rolling(18, min_periods=1).mean()
    for tag in ("F1", "P8", "T11", "F19", "F25"):
        for lag in (0, 1, 3, 6):
            frame[f"{tag}_lag{lag}"] = frame[tag].shift(lag)
    latest = frame.tail(1)
    unavailable = [name for name in expected if name not in latest or pd.isna(latest[name].iloc[0])]
    if unavailable:
        raise FeatureContractError("Multi-horizon features unavailable: " + ", ".join(unavailable[:10]))
    return latest.loc[:, expected]


def build_quantile_features(telemetry: pd.DataFrame, expected: list[str]) -> pd.DataFrame:
    frame = _prepared(telemetry)
    required = ["Q21", "F31", "T33", "T55"]
    missing = [name for name in required if name not in frame]
    if missing:
        raise FeatureContractError("Missing quantile tags: " + ", ".join(missing))
    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(frame[required].to_numpy(float)).all():
        raise FeatureContractError("Quantile history contains missing or non-finite values")
    for lag in (1, 2, 3, 6, 12, 18):
        frame[f"Q21_lag_{lag}"] = frame["Q21"].shift(lag)
    for window in (6, 12, 24):
        roll = frame["Q21"].rolling(window, min_periods=1)
        frame[f"Q21_roll_mean_{window}"] = roll.mean()
        frame[f"Q21_roll_std_{window}"] = roll.std()
    frame["Q21_diff_1"] = frame["Q21"].diff(1)
    frame["Q21_diff_6"] = frame["Q21"].diff(6)
    for tag in ("F31", "T33", "T55"):
        frame[f"{tag}_roll_6"] = frame[tag].rolling(6, min_periods=1).mean()
    frame["hour"] = frame["timestamp"].dt.hour
    frame["day_of_week"] = frame["timestamp"].dt.dayofweek
    latest = frame.tail(1)
    unavailable = [name for name in expected if name not in latest or pd.isna(latest[name].iloc[0])]
    if unavailable:
        raise FeatureContractError("Quantile features unavailable: " + ", ".join(unavailable[:10]))
    return latest.loc[:, expected]
