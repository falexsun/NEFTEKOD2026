"""ML model wrappers for baseline training and evaluation."""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    precision_score,
    recall_score,
    average_precision_score,
)

logger = logging.getLogger(__name__)


# ── Baseline models ─────────────────────────────────────────────

class NaiveLastValue:
    """Baseline: predict the last known value of the target."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "NaiveLastValue":
        self.last_value = y.iloc[-1] if len(y) > 0 else 0.0
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self.last_value)


class NaiveMean:
    """Baseline: predict the rolling mean of the target."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "NaiveMean":
        self.mean_value = y.mean()
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self.mean_value)


# ── Model wrappers ──────────────────────────────────────────────

class CatBoostModel:
    """Wrapper for CatBoost regressor."""

    def __init__(self, params: dict[str, Any] | None = None):
        from catboost import CatBoostRegressor
        self.params = params or {}
        self.model = CatBoostRegressor(**self.params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "CatBoostModel":
        self.model.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def get_feature_importance(self) -> pd.Series:
        imp = self.model.get_feature_importance()
        names = self.model.feature_names_
        return pd.Series(imp, index=names).sort_values(ascending=False)


class LightGBMModel:
    """Wrapper for LightGBM regressor."""

    def __init__(self, params: dict[str, Any] | None = None):
        import lightgbm as lgb
        self.params = params or {}
        self.model = lgb.LGBMRegressor(**self.params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LightGBMModel":
        self.model.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def get_feature_importance(self) -> pd.Series:
        imp = self.model.feature_importances_
        names = self.model.feature_names_
        return pd.Series(imp, index=names).sort_values(ascending=False)


class XGBoostModel:
    """Wrapper for XGBoost regressor."""

    def __init__(self, params: dict[str, Any] | None = None):
        import xgboost as xgb
        self.params = params or {}
        self.model = xgb.XGBRegressor(**self.params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "XGBoostModel":
        self.model.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def get_feature_importance(self) -> pd.Series:
        imp = self.model.feature_importances_
        names = self.model.feature_names_in_
        return pd.Series(imp, index=names).sort_values(ascending=False)


# ── Metrics ─────────────────────────────────────────────────────

def compute_regression_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    sulfur_limit: float = 10.0,
) -> dict[str, float]:
    """Compute comprehensive regression + classification metrics for sulfur."""
    metrics = {}

    # Regression metrics
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_t = y_true[mask]
    y_p = y_pred[mask]

    if len(y_t) == 0:
        return metrics

    metrics["mae"] = float(mean_absolute_error(y_t, y_p))
    metrics["rmse"] = float(np.sqrt(mean_squared_error(y_t, y_p)))
    metrics["r2"] = float(r2_score(y_t, y_p))

    # Violation classification metrics
    y_true_violation = (y_t > sulfur_limit).astype(int)
    y_pred_violation = (y_p > sulfur_limit).astype(int)

    n_true_violations = y_true_violation.sum()
    n_pred_violations = y_pred_violation.sum()

    metrics["n_true_violations"] = int(n_true_violations)
    metrics["n_pred_violations"] = int(n_pred_violations)

    if n_true_violations > 0:
        metrics["recall_violation"] = float(recall_score(
            y_true_violation, y_pred_violation, zero_division=0
        ))
    else:
        metrics["recall_violation"] = 0.0

    if n_pred_violations > 0:
        metrics["precision_violation"] = float(precision_score(
            y_true_violation, y_pred_violation, zero_division=0
        ))
    else:
        metrics["precision_violation"] = 0.0

    # PR-AUC
    if n_true_violations > 0 and n_true_violations < len(y_t):
        metrics["pr_auc"] = float(average_precision_score(
            y_true_violation, y_p
        ))

    # False Safe Rate: predicted safe but actually violated
    false_safe = ((y_p <= sulfur_limit) & (y_t > sulfur_limit)).sum()
    if n_true_violations > 0:
        metrics["false_safe_rate"] = float(false_safe / n_true_violations)

    # Prediction interval coverage (simple std-based)
    residuals = y_t - y_p
    std_resid = np.std(residuals)
    lower = y_p - 1.96 * std_resid
    upper = y_p + 1.96 * std_resid
    coverage = ((y_t >= lower) & (y_t <= upper)).mean()
    metrics["prediction_interval_coverage_95"] = float(coverage)

    # Distribution stats
    metrics["target_mean"] = float(np.mean(y_t))
    metrics["target_std"] = float(np.std(y_t))
    metrics["target_min"] = float(np.min(y_t))
    metrics["target_max"] = float(np.max(y_t))

    return metrics


def save_model(model: Any, path: str | Path) -> None:
    """Save model to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"Model saved to {path}")


def load_model(path: str | Path) -> Any:
    """Load model from disk."""
    with open(path, "rb") as f:
        return pickle.load(f)
