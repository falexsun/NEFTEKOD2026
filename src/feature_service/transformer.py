"""FeatureTransformer — single source of truth for feature engineering.

Used by BOTH training and runtime to eliminate training-serving skew.
All feature formulas defined here ONCE.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Single source of truth for key columns ──────────────────────
FEATURE_KEY_COLUMNS = [
    "avt_T1", "avt_P2", "avt_F3", "avt_P4", "avt_F5", "avt_T6", "avt_F7", "avt_F8", "avt_F9",
    "avt_D10", "avt_T20", "avt_T40", "avt_T48", "avt_P44", "avt_L43",
    "avt_F30", "avt_F32", "avt_W70",
    "u24_T5", "u24_T6", "u24_W7", "u24_P8", "u24_F9", "u24_F15", "u24_T11", "u24_T16",
    "u24_F22", "u24_P24", "u24_P13", "u24_F1",
]

LAG_WINDOWS = [1, 2, 3, 6, 12]
ROLLING_WINDOWS = [6, 12, 36]
SLOPE_COLUMNS = FEATURE_KEY_COLUMNS[:10]
MISSING_FLAG_COLUMNS = FEATURE_KEY_COLUMNS[:20]  # Same as training: key_cols[:20]

# Domain feature definitions
DOMAIN_FEATURES = {
    "avt_T6_T1_ratio": lambda df: df["avt_T6"] / df["avt_T1"].replace(0, np.nan)
        if "avt_T6" in df.columns and "avt_T1" in df.columns else None,
    "avt_total_feed": lambda df: df[["avt_F7", "avt_F8", "avt_F9"]].sum(axis=1)
        if all(c in df.columns for c in ["avt_F7", "avt_F8", "avt_F9"]) else None,
    "u24_T_spread": lambda df: df["u24_T5"] - df["u24_P8"]
        if "u24_T5" in df.columns and "u24_P8" in df.columns else None,
    "u24_F1_F26_ratio": lambda df: df["u24_F1"] / df["u24_F26"].replace(0, np.nan)
        if "u24_F1" in df.columns and "u24_F26" in df.columns else None,
    "avt_heavy_light_ratio": lambda df: df["avt_F30"] / df["avt_F32"].replace(0, np.nan)
        if "avt_F30" in df.columns and "avt_F32" in df.columns else None,
}


class FeatureTransformer:
    """Transforms a DataFrame with raw telemetry into full feature matrix.

    Used identically by training pipeline and runtime buffer.
    """

    def __init__(self):
        self.feature_key_columns = FEATURE_KEY_COLUMNS
        self.lag_windows = LAG_WINDOWS
        self.rolling_windows = ROLLING_WINDOWS
        self.slope_columns = SLOPE_COLUMNS
        self.missing_flag_columns = MISSING_FLAG_COLUMNS

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all feature transformations to a DataFrame.

        Input: DataFrame with raw telemetry columns (avt_T1, u24_T5, etc.)
        Output: DataFrame with all derived features added.

        Fill policy: ffill() then fillna(0) — SAME as training.
        """
        merged = df.copy()
        available = [c for c in self.feature_key_columns if c in merged.columns]

        # Lag features
        for col in available:
            for lag in self.lag_windows:
                merged[f"{col}_lag{lag}"] = merged[col].shift(lag)

        # Rolling features
        for col in available:
            for w in self.rolling_windows:
                roller = merged[col].rolling(window=w, min_periods=1)
                merged[f"{col}_rmean{w}"] = roller.mean()
                merged[f"{col}_rstd{w}"] = roller.std()
                merged[f"{col}_rmin{w}"] = roller.min()
                merged[f"{col}_rmax{w}"] = roller.max()

        # Delta features
        for col in available:
            merged[f"{col}_delta"] = merged[col].diff(1)
            merged[f"{col}_delta6"] = merged[col].diff(6)

        # Slope features
        for col in self.slope_columns:
            if col in merged.columns:
                merged[f"{col}_slope6"] = self._rolling_slope(merged[col], 6)
                merged[f"{col}_slope12"] = self._rolling_slope(merged[col], 12)

        # Missing flags — SAME columns as training (first 20 key cols)
        for col in self.missing_flag_columns:
            if col in merged.columns:
                merged[f"{col}_missing"] = merged[col].isna().astype(int)

        # Domain features
        for name, fn in DOMAIN_FEATURES.items():
            result = fn(merged)
            if result is not None:
                merged[name] = result

        # Fill policy: ffill then fillna(0) — SAME as training pipeline
        merged = merged.ffill().fillna(0)
        merged = merged.replace([np.inf, -np.inf], 0)

        return merged

    @staticmethod
    def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
        def slope(x):
            if len(x) < 2:
                return 0.0
            try:
                return np.polyfit(np.arange(len(x)), x.values, 1)[0]
            except:
                return 0.0
        return series.rolling(window=window, min_periods=2).apply(slope, raw=False).fillna(0)
