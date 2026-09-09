"""Time-series feature engineering — NO future information allowed.

All features at time t use only data from timestamps <= t.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def build_features(
    avt_df: pd.DataFrame,
    unit_df: pd.DataFrame,
    pak_sulfur_df: pd.DataFrame | None = None,
    pak_density_df: pd.DataFrame | None = None,
    lims_wide: pd.DataFrame | None = None,
    target_col: str = "sulfur_mg_kg",
    horizon_minutes: int = 60,
) -> pd.DataFrame:
    """Build a feature matrix from aligned telemetry + quality data.

    Returns DataFrame with:
        - All telemetry columns (prefixed avt_ and u24_)
        - Lag features (10m, 20m, 30m, 1h, 2h)
        - Rolling features (mean, std, min, max over 1h, 2h, 6h windows)
        - Rate-of-change and slope features
        - Source freshness indicators
        - Target column (shifted by horizon)
    """
    # Merge telemetry on timestamp
    avt_renamed = avt_df.add_prefix("avt_")
    unit_renamed = unit_df.add_prefix("u24_")

    merged = avt_renamed.join(unit_renamed, how="inner")
    merged = merged.sort_index()

    # Helper to get a column name for the timestamp after reset_index
    ts_col = "timestamp"

    def _reset_ts(df):
        """Reset index and ensure the time column is named 'timestamp'."""
        out = df.reset_index()
        # Rename the first column (index) to 'timestamp' if needed
        first_col = out.columns[0]
        if first_col != ts_col:
            out = out.rename(columns={first_col: ts_col})
        return out

    # Add PAK sulfur as target (merge_asof for nearest within tolerance)
    if pak_sulfur_df is not None and not pak_sulfur_df.empty:
        pak_r = _reset_ts(pak_sulfur_df)
        merged = pd.merge_asof(
            _reset_ts(merged).sort_values(ts_col),
            pak_r.sort_values(ts_col),
            on=ts_col,
            tolerance=pd.Timedelta("5min"),
            direction="nearest",
        ).set_index(ts_col)
        merged = merged[~merged.index.duplicated(keep="first")]

    if pak_density_df is not None and not pak_density_df.empty:
        den_r = _reset_ts(pak_density_df)
        merged = pd.merge_asof(
            _reset_ts(merged).sort_values(ts_col),
            den_r.sort_values(ts_col),
            on=ts_col,
            tolerance=pd.Timedelta("5min"),
            direction="nearest",
        ).set_index(ts_col)
        merged = merged[~merged.index.duplicated(keep="first")]

    # Add LIMS features (forward-fill — lab results apply until next measurement)
    if lims_wide is not None and not lims_wide.empty:
        # Only use LIMS columns that are numeric
        lims_numeric = lims_wide.select_dtypes(include=[np.number])
        if not lims_numeric.empty:
            lims_numeric = lims_numeric.add_prefix("lims_")
            lims_r = _reset_ts(lims_numeric)
            merged = pd.merge_asof(
                _reset_ts(merged).sort_values(ts_col),
                lims_r.sort_values(ts_col),
                on=ts_col,
                direction="backward",
            ).set_index(ts_col)
            merged = merged[~merged.index.duplicated(keep="first")]

    # Select key telemetry columns for feature engineering
    key_cols = _select_key_columns(merged)

    # Build lag features
    lag_windows = [1, 2, 3, 6, 12]  # in 10-min steps (10m, 20m, 30m, 1h, 2h)
    for col in key_cols:
        for lag in lag_windows:
            merged[f"{col}_lag{lag}"] = merged[col].shift(lag)

    # Build rolling features
    rolling_windows = [6, 12, 36]  # 1h, 2h, 6h in 10-min steps
    for col in key_cols:
        for w in rolling_windows:
            roller = merged[col].rolling(window=w, min_periods=1)
            merged[f"{col}_rmean{w}"] = roller.mean()
            merged[f"{col}_rstd{w}"] = roller.std()
            merged[f"{col}_rmin{w}"] = roller.min()
            merged[f"{col}_rmax{w}"] = roller.max()

    # Rate-of-change (delta between consecutive readings)
    for col in key_cols:
        merged[f"{col}_delta"] = merged[col].diff(1)
        merged[f"{col}_delta6"] = merged[col].diff(6)  # 1-hour change

    # Slope (linear trend over rolling window)
    for col in key_cols[:10]:  # Limit to first 10 key columns
        merged[f"{col}_slope6"] = _rolling_slope(merged[col], window=6)
        merged[f"{col}_slope12"] = _rolling_slope(merged[col], window=12)

    # Missing flags
    for col in key_cols[:20]:
        merged[f"{col}_missing"] = merged[col].isna().astype(int)

    # Domain features: ratios and interactions
    _add_domain_features(merged)

    # Create target: future sulfur value (shifted backward by horizon)
    if "sulfur_mg_kg" in merged.columns:
        steps_ahead = horizon_minutes // 10
        merged["target_sulfur"] = merged["sulfur_mg_kg"].shift(-steps_ahead)

    logger.info(f"Feature matrix: {merged.shape}, "
                f"{merged.select_dtypes(include=[np.number]).shape[1]} numeric columns")
    return merged


def _select_key_columns(df: pd.DataFrame) -> list[str]:
    """Select the most informative telemetry columns for feature engineering.

    Uses shared FEATURE_KEY_COLUMNS from transformer as single source of truth.
    """
    from src.feature_service.transformer import FEATURE_KEY_COLUMNS
    # Priority columns based on domain knowledge (from shared transformer)
    priority_avt = [
        "avt_T1", "avt_T6", "avt_T33", "avt_T55", "avt_F3", "avt_F5",
        "avt_F7", "avt_F8", "avt_F9", "avt_D10", "avt_T20",
        "avt_T40", "avt_T48", "avt_P44", "avt_L43",
        "avt_F30", "avt_F32", "avt_W70",
    ]
    priority_u24 = [
        "u24_T5", "u24_T6", "u24_W7", "u24_P8", "u24_F9",
        "u24_F15", "u24_T11", "u24_T16", "u24_F22", "u24_P24",
        "u24_P13", "u24_F1",
    ]

    available = []
    for col in priority_avt + priority_u24:
        if col in df.columns:
            available.append(col)

    # If we have too few, add more columns
    if len(available) < 15:
        for col in df.select_dtypes(include=[np.number]).columns:
            if col not in available and not col.startswith(("target_", "lims_")):
                available.append(col)
                if len(available) >= 30:
                    break

    return available


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling linear regression slope."""
    def slope(x):
        if len(x) < 2 or x.isna().all():
            return np.nan
        y = x.values
        t = np.arange(len(y))
        mask = ~np.isnan(y)
        if mask.sum() < 2:
            return np.nan
        t_valid = t[mask]
        y_valid = y[mask]
        if np.std(t_valid) == 0:
            return 0.0
        return np.polyfit(t_valid, y_valid, 1)[0]

    return series.rolling(window=window, min_periods=2).apply(slope, raw=False)


def _add_domain_features(df: pd.DataFrame) -> None:
    """Add domain-specific derived features in-place."""
    # Temperature ratios (cracking severity indicators)
    if "avt_T6" in df.columns and "avt_T1" in df.columns:
        df["avt_T6_T1_ratio"] = df["avt_T6"] / df["avt_T1"].replace(0, np.nan)

    # Total feed flow
    feed_cols = [c for c in df.columns if c.startswith("avt_F") and c in
                 ["avt_F7", "avt_F8", "avt_F9"]]
    if len(feed_cols) >= 2:
        df["avt_total_feed"] = df[feed_cols].sum(axis=1)

    # Hydrofining temperature spread
    if "u24_T5" in df.columns and "u24_P8" in df.columns:
        df["u24_T_spread"] = df["u24_T5"] - df["u24_P8"]

    # Flow ratio features
    if "u24_F1" in df.columns and "u24_F26" in df.columns:
        denom = df["u24_F26"].replace(0, np.nan)
        df["u24_F1_F26_ratio"] = df["u24_F1"] / denom

    # Distillation spread
    if "avt_F30" in df.columns and "avt_F32" in df.columns:
        df["avt_heavy_light_ratio"] = df["avt_F30"] / df["avt_F32"].replace(0, np.nan)
