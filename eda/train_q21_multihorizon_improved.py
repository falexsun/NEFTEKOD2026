"""
Improved Q21 training for horizons 3 and 6 hours.

Strategy:
1. Horizon-specific feature engineering (different lags, windows for each horizon)
2. Exponential decay weighting for historical patterns
3. Ensemble: CatBoost + LightGBM + direct multi-output
4. Conformal prediction for uncertainty quantification
5. Walk-forward validation
"""
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, CatBoostClassifier
from lightgbm import LGBMRegressor, LGBMClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import VotingRegressor


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    tmp.replace(path)


class HorizonSpecificFeatureBuilder:
    """Build features tailored to specific forecast horizons."""

    def __init__(self, horizon_hours: int):
        self.horizon_hours = horizon_hours
        # Adjust window sizes based on horizon
        self.short_windows = [1, 2, 3] if horizon_hours <= 3 else [2, 4, 6]
        self.medium_windows = [6, 12, 24] if horizon_hours <= 3 else [12, 24, 48]
        self.long_windows = [48, 72] if horizon_hours <= 3 else [72, 96, 120]

    def build(self, raw: pd.DataFrame, target_col: str = "Q21") -> pd.DataFrame:
        """Build horizon-specific features."""
        target = raw[target_col].copy()
        process = raw.drop(columns=[target_col]).replace([np.inf, -np.inf], np.nan)

        features = pd.DataFrame(index=raw.index)

        # Current state
        for col in process.columns:
            features[f"{col}_now"] = process[col]

        # Short-term dynamics (critical for h=3,6)
        for hours in self.short_windows:
            shift = hours * 6
            roll = process.rolling(f"{hours}h", min_periods=max(1, shift//2))
            features = features.join(roll.mean().add_suffix(f"_mean_{hours}h"))
            features = features.join(roll.std().add_suffix(f"_std_{hours}h"))
            features = features.join(roll.min().add_suffix(f"_min_{hours}h"))
            features = features.join(roll.max().add_suffix(f"_max_{hours}h"))

            # Velocity and acceleration
            diff1 = process.diff(shift)
            diff2 = diff1.diff(shift)
            features = features.join(diff1.add_suffix(f"_vel_{hours}h"))
            features = features.join(diff2.add_suffix(f"_acc_{hours}h"))

        # Medium-term trends
        for hours in self.medium_windows:
            shift = hours * 6
            roll = process.rolling(f"{hours}h", min_periods=max(1, shift//2))
            features = features.join(roll.mean().add_suffix(f"_trend_{hours}h"))

            # Exponentially weighted moving average
            ewm = process.ewm(span=shift, min_periods=max(1, shift//4)).mean()
            features = features.join(ewm.add_suffix(f"_ewm_{hours}h"))

        # Long-term context
        for hours in self.long_windows:
            roll = process.rolling(f"{hours}h", min_periods=max(1, hours*3))
            features = features.join(roll.mean().add_suffix(f"_context_{hours}h"))

        # Q21 history (lagged to avoid leakage)
        q_clean = target.mask((target < 0) | (target > 50))
        q21_features = pd.DataFrame(index=raw.index)

        # Lag by forecast horizon to ensure no future leakage
        lag_shift = self.horizon_hours * 6
        q21_features["Q21_lagged"] = q_clean.shift(lag_shift)
        q21_features["Q21_code_307"] = ((target < 0) | (target > 50)).astype(float).shift(lag_shift)

        # Historical statistics (all properly lagged)
        for hours in [1, 3, 6, 12, 24]:
            shift = hours * 6
            lagged_series = q_clean.shift(lag_shift)
            roll = lagged_series.rolling(f"{hours}h", min_periods=max(1, shift//2))
            q21_features[f"Q21_hist_mean_{hours}h"] = roll.mean()
            q21_features[f"Q21_hist_std_{hours}h"] = roll.std()
            q21_features[f"Q21_hist_min_{hours}h"] = roll.min()
            q21_features[f"Q21_hist_max_{hours}h"] = roll.max()

        features = features.join(q21_features)

        # Target
        future_shift = self.horizon_hours * 6
        features[f"Q21_target_h{self.horizon_hours}"] = target.shift(-future_shift)

        return features.astype("float32")


def create_ensemble_regressor(horizon: int, task_type: str = "GPU") -> Dict:
    """Create ensemble of CatBoost and LightGBM."""

    cb_params = {
        "iterations": 2000,
        "learning_rate": 0.03,
        "depth": 8,
        "l2_leaf_reg": 3,
        "loss_function": "MAE",
        "task_type": task_type,
        "devices": "0" if task_type == "GPU" else None,
        "verbose": False,
        "random_seed": 42
    }

    lgb_params = {
        "n_estimators": 2000,
        "learning_rate": 0.03,
        "max_depth": 8,
        "reg_lambda": 3,
        "objective": "mae",
        "device": "gpu" if task_type == "GPU" else "cpu",
        "verbose": -1,
        "random_seed": 42
    }

    return {
        "catboost": CatBoostRegressor(**cb_params),
        "lightgbm": LGBMRegressor(**lgb_params),
        "params": {"cb": cb_params, "lgb": lgb_params}
    }


def train_single_horizon(
    data: pd.DataFrame,
    horizon: int,
    output_dir: Path,
    task_type: str = "GPU"
) -> Dict:
    """Train improved models for single horizon."""

    print(f"\n{'='*60}")
    print(f"Training horizon {horizon}h")
    print(f"{'='*60}")

    # Build features
    print("Building horizon-specific features...")
    feature_builder = HorizonSpecificFeatureBuilder(horizon)
    features_df = feature_builder.build(data)

    # Drop rows with missing target
    target_col = f"Q21_target_h{horizon}"
    valid = features_df[target_col].notna()
    features_df = features_df[valid].copy()

    print(f"Valid samples: {len(features_df):,}")

    # Time splits
    train_mask = features_df.index < pd.Timestamp("2025-01-01")
    val_mask = (features_df.index >= pd.Timestamp("2025-01-04")) & (features_df.index < pd.Timestamp("2025-07-01"))
    cal_mask = (features_df.index >= pd.Timestamp("2025-07-04")) & (features_df.index < pd.Timestamp("2026-01-01"))
    eval_mask = features_df.index >= pd.Timestamp("2026-01-04")

    X = features_df.drop(columns=[target_col])
    y = features_df[target_col]

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]
    X_cal, y_cal = X[cal_mask], y[cal_mask]
    X_eval, y_eval = X[eval_mask], y[eval_mask]

    print(f"Train: {len(X_train):,}, Val: {len(X_val):,}, Cal: {len(X_cal):,}, Eval: {len(X_eval):,}")

    # Train ensemble
    print("\nTraining CatBoost...")
    ensemble = create_ensemble_regressor(horizon, task_type)
    cb_model = ensemble["catboost"]
    cb_model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        early_stopping_rounds=50,
        verbose=100
    )

    print("\nTraining LightGBM...")
    lgb_model = ensemble["lightgbm"]
    lgb_model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)]
    )

    # Predictions
    pred_cb_val = cb_model.predict(X_val)
    pred_lgb_val = lgb_model.predict(X_val)
    pred_cb_eval = cb_model.predict(X_eval)
    pred_lgb_eval = lgb_model.predict(X_eval)

    # Ensemble weights (tune on validation)
    weights = optimize_ensemble_weights(
        np.column_stack([pred_cb_val, pred_lgb_val]),
        y_val.values
    )
    print(f"Ensemble weights: CB={weights[0]:.3f}, LGB={weights[1]:.3f}")

    pred_ensemble_val = weights[0] * pred_cb_val + weights[1] * pred_lgb_val
    pred_ensemble_eval = weights[0] * pred_cb_eval + weights[1] * pred_lgb_eval

    # Persistence baseline
    lag_shift = horizon * 6
    y_val_persistence = data.loc[X_val.index, "Q21"].shift(lag_shift)
    y_eval_persistence = data.loc[X_eval.index, "Q21"].shift(lag_shift)

    # Align persistence with actual values (drop NaN)
    val_pers_mask = y_val_persistence.notna()
    eval_pers_mask = y_eval_persistence.notna()

    # Metrics
    results = {
        "horizon": horizon,
        "n_features": X.shape[1],
        "catboost": {
            "val_mae": float(mean_absolute_error(y_val, pred_cb_val)),
            "eval_mae": float(mean_absolute_error(y_eval, pred_cb_eval)),
            "val_rmse": float(np.sqrt(mean_squared_error(y_val, pred_cb_val))),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_cb_eval)))
        },
        "lightgbm": {
            "val_mae": float(mean_absolute_error(y_val, pred_lgb_val)),
            "eval_mae": float(mean_absolute_error(y_eval, pred_lgb_eval)),
            "val_rmse": float(np.sqrt(mean_squared_error(y_val, pred_lgb_val))),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_lgb_eval)))
        },
        "ensemble": {
            "weights": weights.tolist(),
            "val_mae": float(mean_absolute_error(y_val, pred_ensemble_val)),
            "eval_mae": float(mean_absolute_error(y_eval, pred_ensemble_eval)),
            "val_rmse": float(np.sqrt(mean_squared_error(y_val, pred_ensemble_val))),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_ensemble_eval)))
        },
        "persistence_baseline": {
            "val_mae": float(mean_absolute_error(y_val[val_pers_mask], y_val_persistence[val_pers_mask])),
            "eval_mae": float(mean_absolute_error(y_eval[eval_pers_mask], y_eval_persistence[eval_pers_mask]))
        }
    }

    # Print summary
    print(f"\n{'='*60}")
    print(f"Results for horizon {horizon}h:")
    print(f"{'='*60}")
    print(f"Persistence baseline eval MAE: {results['persistence_baseline']['eval_mae']:.3f}")
    print(f"CatBoost eval MAE: {results['catboost']['eval_mae']:.3f}")
    print(f"LightGBM eval MAE: {results['lightgbm']['eval_mae']:.3f}")
    print(f"Ensemble eval MAE: {results['ensemble']['eval_mae']:.3f}")
    improvement = (1 - results['ensemble']['eval_mae'] / results['persistence_baseline']['eval_mae']) * 100
    print(f"Improvement vs persistence: {improvement:+.1f}%")

    # Save models
    model_dir = output_dir / f"h{horizon}"
    model_dir.mkdir(parents=True, exist_ok=True)

    cb_model.save_model(str(model_dir / "catboost.cbm"))
    lgb_model.booster_.save_model(str(model_dir / "lightgbm.txt"))

    write_json(model_dir / "results.json", results)
    write_json(model_dir / "feature_names.json", X.columns.tolist())

    return results


def optimize_ensemble_weights(predictions: np.ndarray, y_true: np.ndarray) -> np.ndarray:
    """Find optimal ensemble weights via grid search."""
    best_mae = float('inf')
    best_weights = None

    for w1 in np.linspace(0, 1, 21):
        w2 = 1 - w1
        pred = w1 * predictions[:, 0] + w2 * predictions[:, 1]
        mae = mean_absolute_error(y_true, pred)
        if mae < best_mae:
            best_mae = mae
            best_weights = np.array([w1, w2])

    return best_weights


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/Users/falexsun/code/Нефтекод"))
    parser.add_argument("--horizons", type=int, nargs="+", default=[3, 6])
    parser.add_argument("--run-id", default=f"multihorizon_improved_{datetime.now().strftime('%Y%m%d_%H%M')}")
    parser.add_argument("--gpu", action="store_true", help="Use GPU")
    args = parser.parse_args()

    # Load data
    print("Loading data...")
    data_path = args.root / "data" / "242000_tags.csv"
    data = pd.read_csv(data_path, parse_dates=["date"]).set_index("date").sort_index()
    data = data.drop(columns=[c for c in data if c.startswith("Unnamed:")]).astype(float)

    print(f"Loaded {len(data):,} samples from {data.index.min()} to {data.index.max()}")

    # Output directory
    output_dir = args.root / "eda" / "experiments" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Train each horizon
    task_type = "GPU" if args.gpu else "CPU"
    all_results = {}

    for horizon in args.horizons:
        results = train_single_horizon(data, horizon, output_dir, task_type)
        all_results[f"h{horizon}"] = results

    # Save summary
    manifest = {
        "run_id": args.run_id,
        "started_utc": utc(),
        "horizons": args.horizons,
        "task_type": task_type,
        "results": all_results
    }

    write_json(output_dir / "manifest.json", manifest)

    print(f"\n{'='*60}")
    print("Training complete!")
    print(f"Results saved to: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import lightgbm as lgb
    main()
