"""RuntimeFeatureBuffer — maintains history and builds 721-feature vectors for inference.

Stores last N telemetry points. Builds lag/rolling/delta/slope features
using the SAME logic as training pipeline. Reports feature_ready when
sufficient history exists for all expected features.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

KEY_COLS = [
    "avt_T1", "avt_P2", "avt_F3", "avt_P4", "avt_F5", "avt_T6", "avt_F7", "avt_F8", "avt_F9",
    "avt_D10", "avt_T20", "avt_T40", "avt_T48", "avt_P44", "avt_L43",
    "avt_F30", "avt_F32", "avt_W70",
    "u24_T5", "u24_T6", "u24_W7", "u24_P8", "u24_F9", "u24_F15", "u24_T11", "u24_T16",
    "u24_F22", "u24_P24", "u24_P13", "u24_F1",
]

LAG_WINDOWS = [1, 2, 3, 6, 12]
ROLLING_WINDOWS = [6, 12, 36]
SLOPE_COLS = KEY_COLS[:10]


class RuntimeFeatureBuffer:
    """Maintains history buffer and builds full feature vectors.

    Min history = max rolling window = 36 points (6 hours at 10-min).
    When history insufficient, feature_ready=False and inference must ABSTAIN.
    """

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self._history: deque[dict] = deque(maxlen=max_history)
        self._df: pd.DataFrame | None = None

    @property
    def history_size(self) -> int:
        return len(self._history)

    @property
    def feature_ready(self) -> bool:
        return self.history_size >= max(ROLLING_WINDOWS)

    def push(self, timestamp: datetime, avt: dict[str, float], u24: dict[str, float],
             pak_sulfur: float | None = None, pak_density: float | None = None,
             lims: dict[str, float] | None = None):
        row = {"timestamp": timestamp}
        for k, v in avt.items():
            row[k] = v
        for k, v in u24.items():
            row[k] = v
        if pak_sulfur is not None:
            row["sulfur_mg_kg"] = pak_sulfur
        if pak_density is not None:
            row["density_15"] = pak_density
        if lims:
            for k, v in lims.items():
                row[f"lims_{k}"] = v
        self._history.append(row)
        self._df = None

    def build_feature_vector(self, expected_features: list[str]) -> tuple[dict[str, float] | None, str | None]:
        if not self.feature_ready:
            return None, f"Insufficient history: {self.history_size}/{max(ROLLING_WINDOWS)} points"

        df = self._to_dataframe()
        if df is None or len(df) < max(ROLLING_WINDOWS):
            return None, "Failed to build history DataFrame"

        features_df = self._build_features(df)
        if features_df is None or features_df.empty:
            return None, "Feature construction failed"

        last_row = features_df.iloc[-1]
        vector = {}
        missing = []
        for name in expected_features:
            if name in last_row.index and pd.notna(last_row[name]):
                vector[name] = float(last_row[name])
            else:
                missing.append(name)

        if missing:
            return None, f"Missing {len(missing)} features: {missing[:5]}..."

        return vector, None

    def _to_dataframe(self) -> pd.DataFrame | None:
        if self._df is not None:
            return self._df
        if not self._history:
            return None
        df = pd.DataFrame(list(self._history))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        self._df = df
        return df

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame | None:
        try:
            merged = df.copy()
            avail = [c for c in KEY_COLS if c in merged.columns]

            for col in avail:
                for lag in LAG_WINDOWS:
                    merged[f"{col}_lag{lag}"] = merged[col].shift(lag)

            for col in avail:
                for w in ROLLING_WINDOWS:
                    roller = merged[col].rolling(window=w, min_periods=1)
                    merged[f"{col}_rmean{w}"] = roller.mean()
                    merged[f"{col}_rstd{w}"] = roller.std()
                    merged[f"{col}_rmin{w}"] = roller.min()
                    merged[f"{col}_rmax{w}"] = roller.max()

            for col in avail:
                merged[f"{col}_delta"] = merged[col].diff(1)
                merged[f"{col}_delta6"] = merged[col].diff(6)

            for col in SLOPE_COLS:
                if col in merged.columns:
                    merged[f"{col}_slope6"] = _rolling_slope(merged[col], window=6)
                    merged[f"{col}_slope12"] = _rolling_slope(merged[col], window=12)

            for col in avail:
                merged[f"{col}_missing"] = merged[col].isna().astype(int)

            if "avt_T6" in merged.columns and "avt_T1" in merged.columns:
                merged["avt_T6_T1_ratio"] = merged["avt_T6"] / merged["avt_T1"].replace(0, np.nan)
            feed_cols = [c for c in ["avt_F7", "avt_F8", "avt_F9"] if c in merged.columns]
            if len(feed_cols) >= 2:
                merged["avt_total_feed"] = merged[feed_cols].sum(axis=1)
            if "u24_T5" in merged.columns and "u24_P8" in merged.columns:
                merged["u24_T_spread"] = merged["u24_T5"] - merged["u24_P8"]
            if "u24_F1" in merged.columns and "u24_F26" in merged.columns:
                merged["u24_F1_F26_ratio"] = merged["u24_F1"] / merged["u24_F26"].replace(0, np.nan)
            if "avt_F30" in merged.columns and "avt_F32" in merged.columns:
                merged["avt_heavy_light_ratio"] = merged["avt_F30"] / merged["avt_F32"].replace(0, np.nan)

            merged = merged.fillna(0).replace([np.inf, -np.inf], 0)
            return merged

        except Exception as e:
            logger.error(f"Feature construction failed: {e}")
            return None


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    def slope(x):
        if len(x) < 2:
            return 0.0
        try:
            return np.polyfit(np.arange(len(x)), x.values, 1)[0]
        except:
            return 0.0
    return series.rolling(window=window, min_periods=2).apply(slope, raw=False).fillna(0)
