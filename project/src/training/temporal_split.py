"""Temporal train/val/test split — NO shuffle, NO future leakage."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def chronological_split(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split time-series data chronologically (no shuffle).

    Returns (train, val, test) DataFrames.
    """
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6

    n = len(df)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train = df.iloc[:train_end].copy()
    val = df.iloc[train_end:val_end].copy()
    test = df.iloc[val_end:].copy()

    logger.info(
        f"Chronological split: train={len(train)} ({train.index.min()} – {train.index.max()}), "
        f"val={len(val)} ({val.index.min()} – {val.index.max()}), "
        f"test={len(test)} ({test.index.min()} – {test.index.max()})"
    )
    return train, val, test


def walk_forward_splits(
    df: pd.DataFrame,
    n_splits: int = 5,
    min_train_days: int = 90,
    test_days: int = 30,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Generate walk-forward validation splits.

    Each split: train from start to t, test from t to t+test_days.
    Returns list of (train, test) tuples.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    start = df.index.min()
    end = df.index.max()

    # Calculate test boundaries
    total_days = (end - start).days
    available_test_days = total_days - min_train_days

    if available_test_days < test_days:
        logger.warning(
            f"Not enough data for walk-forward: {total_days} days total, "
            f"need {min_train_days}+{test_days}={min_train_days + test_days}"
        )
        # Fall back to single split
        split_point = start + pd.Timedelta(days=int(total_days * 0.7))
        train = df[df.index < split_point]
        test = df[df.index >= split_point]
        return [(train, test)]

    # Evenly space test windows
    step = available_test_days / n_splits
    splits = []

    for i in range(n_splits):
        test_start = start + pd.Timedelta(days=min_train_days + int(i * step))
        test_end = test_start + pd.Timedelta(days=test_days)
        if test_end > end:
            test_end = end

        train = df[df.index < test_start]
        test = df[(df.index >= test_start) & (df.index < test_end)]

        if len(train) > 0 and len(test) > 0:
            splits.append((train, test))
            logger.info(
                f"Walk-forward split {i+1}: train={len(train)} rows "
                f"({train.index.min().date()} – {train.index.max().date()}), "
                f"test={len(test)} rows ({test.index.min().date()} – {test.index.max().date()})"
            )

    return splits


def check_leakage(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    target_col: str,
) -> dict[str, any]:
    """Verify no temporal leakage between train and test sets.

    Returns dict with leakage check results.
    """
    results = {
        "has_leakage": False,
        "issues": [],
    }

    # Check temporal ordering
    if not train_df.index.is_monotonic_increasing:
        results["has_leakage"] = True
        results["issues"].append("Training set is not monotonically increasing")

    if not test_df.index.is_monotonic_increasing:
        results["has_leakage"] = True
        results["issues"].append("Test set is not monotonically increasing")

    # Check no temporal overlap
    if len(train_df) > 0 and len(test_df) > 0:
        train_max = train_df.index.max()
        test_min = test_df.index.min()
        if train_max >= test_min:
            results["has_leakage"] = True
            results["issues"].append(
                f"Temporal overlap: train_max={train_max} >= test_min={test_min}"
            )

    # Check target column doesn't contain future info
    if target_col in train_df.columns:
        # Verify target values are reasonable (no NaN from future shift in training)
        train_target_nan = train_df[target_col].isna().sum()
        results["train_target_nan_count"] = int(train_target_nan)

    return results
