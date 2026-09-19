"""
Fixed Q21 training for horizons 3 and 6 hours.
Key fix: proper persistence baseline calculation aligned with filtered data.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


def utc() -> str:
    return datetime.utcnow().isoformat()


def write_json(path: Path, obj: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    tmp.replace(path)


def prepare_features(data: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    """Build features for given forecast horizon."""

    # Target: future Q21 value
    target = data["Q21"].copy()
    future_shift = horizon_hours * 6

    # Process features (everything except Q21)
    process = data.drop(columns=["Q21"]).replace([np.inf, -np.inf], np.nan)

    features = pd.DataFrame(index=data.index)

    # Current state
    for col in process.columns:
        features[f"{col}_now"] = process[col]

    # Rolling windows adapted to horizon
    if horizon_hours <= 3:
        short_w = [1, 2, 3]
        medium_w = [6, 12, 24]
        long_w = [48, 72]
    else:
        short_w = [2, 4, 6]
        medium_w = [12, 24, 48]
        long_w = [72, 96]

    # Short-term
    for h in short_w:
        roll = process.rolling(f"{h}h", min_periods=max(1, h*3))
        features = features.join(roll.mean().add_suffix(f"_mean_{h}h"))
        features = features.join(roll.std().add_suffix(f"_std_{h}h"))
        features = features.join(process.diff(h*6).add_suffix(f"_diff_{h}h"))

    # Medium-term
    for h in medium_w:
        roll = process.rolling(f"{h}h", min_periods=max(1, h*3))
        features = features.join(roll.mean().add_suffix(f"_trend_{h}h"))
        ewm = process.ewm(span=h*6, min_periods=max(1, h*3)).mean()
        features = features.join(ewm.add_suffix(f"_ewm_{h}h"))

    # Long-term
    for h in long_w:
        roll = process.rolling(f"{h}h", min_periods=max(1, h*3))
        features = features.join(roll.mean().add_suffix(f"_ctx_{h}h"))

    # Q21 history (lagged by forecast horizon)
    q_clean = target.mask((target < 0) | (target > 50))
    lag_shift = horizon_hours * 6

    features["Q21_lagged"] = q_clean.shift(lag_shift)
    features["Q21_is_307"] = ((target < 0) | (target > 50)).astype(float).shift(lag_shift)

    for h in [1, 3, 6, 12, 24]:
        lagged = q_clean.shift(lag_shift)
        roll = lagged.rolling(f"{h}h", min_periods=max(1, h*3))
        features[f"Q21_hist_mean_{h}h"] = roll.mean()
        features[f"Q21_hist_std_{h}h"] = roll.std()

    # Target (future value)
    features["target"] = target.shift(-future_shift)

    return features.astype("float32")


def train_horizon(data: pd.DataFrame, horizon: int, output_dir: Path) -> Dict:
    """Train models for one horizon."""

    print(f"\n{'='*60}")
    print(f"Horizon {horizon}h")
    print(f"{'='*60}")

    # Build features
    print("Building features...")
    df = prepare_features(data, horizon)

    # Drop rows without target
    valid = df["target"].notna()
    df = df[valid].copy()
    print(f"Valid samples: {len(df):,}")

    # Splits
    train_m = df.index < pd.Timestamp("2025-01-01")
    val_m = (df.index >= "2025-01-04") & (df.index < "2025-07-01")
    eval_m = df.index >= "2026-01-04"

    X = df.drop(columns=["target"])
    y = df["target"]

    X_train, y_train = X[train_m], y[train_m]
    X_val, y_val = X[val_m], y[val_m]
    X_eval, y_eval = X[eval_m], y[eval_m]

    print(f"Train: {len(X_train):,}, Val: {len(X_val):,}, Eval: {len(X_eval):,}")

    # Persistence baseline (on same filtered indices)
    lag_shift = horizon * 6
    q21_full = data["Q21"].copy()

    # Align persistence with filtered data indices
    y_val_pers = q21_full.reindex(y_val.index).shift(lag_shift)
    y_eval_pers = q21_full.reindex(y_eval.index).shift(lag_shift)

    # Drop NaN from persistence
    val_pers_valid = y_val_pers.notna()
    eval_pers_valid = y_eval_pers.notna()

    pers_val_mae = mean_absolute_error(
        y_val[val_pers_valid],
        y_val_pers[val_pers_valid]
    )
    pers_eval_mae = mean_absolute_error(
        y_eval[eval_pers_valid],
        y_eval_pers[eval_pers_valid]
    )

    print(f"Persistence baseline - Val MAE: {pers_val_mae:.3f}, Eval MAE: {pers_eval_mae:.3f}")

    # Train CatBoost
    print("\nTraining CatBoost...")
    cb = CatBoostRegressor(
        iterations=2000,
        learning_rate=0.03,
        depth=8,
        loss_function="MAE",
        task_type="GPU",
        devices="0",
        verbose=100,
        random_seed=42
    )
    cb.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=50)

    pred_cb_val = cb.predict(X_val)
    pred_cb_eval = cb.predict(X_eval)

    # Train LightGBM
    print("\nTraining LightGBM...")
    lgb = LGBMRegressor(
        n_estimators=2000,
        learning_rate=0.03,
        max_depth=8,
        objective="mae",
        device="gpu",
        verbose=-1,
        random_seed=42
    )

    import lightgbm
    lgb.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lightgbm.early_stopping(50, verbose=False),
            lightgbm.log_evaluation(100)
        ]
    )

    pred_lgb_val = lgb.predict(X_val)
    pred_lgb_eval = lgb.predict(X_eval)

    # Ensemble weights
    best_w, best_mae = 0.0, float('inf')
    for w_cb in np.linspace(0, 1, 21):
        w_lgb = 1 - w_cb
        pred = w_cb * pred_cb_val + w_lgb * pred_lgb_val
        mae = mean_absolute_error(y_val, pred)
        if mae < best_mae:
            best_mae = mae
            best_w = w_cb

    w_lgb = 1 - best_w
    print(f"Ensemble weights: CB={best_w:.3f}, LGB={w_lgb:.3f}")

    pred_ens_eval = best_w * pred_cb_eval + w_lgb * pred_lgb_eval

    # Results
    results = {
        "horizon": horizon,
        "n_features": X.shape[1],
        "persistence": {
            "val_mae": float(pers_val_mae),
            "eval_mae": float(pers_eval_mae)
        },
        "catboost": {
            "eval_mae": float(mean_absolute_error(y_eval, pred_cb_eval)),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_cb_eval)))
        },
        "lightgbm": {
            "eval_mae": float(mean_absolute_error(y_eval, pred_lgb_eval)),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_lgb_eval)))
        },
        "ensemble": {
            "weights": [float(best_w), float(w_lgb)],
            "eval_mae": float(mean_absolute_error(y_eval, pred_ens_eval)),
            "eval_rmse": float(np.sqrt(mean_squared_error(y_eval, pred_ens_eval)))
        }
    }

    # Summary
    print(f"\n{'='*60}")
    print(f"Results for horizon {horizon}h:")
    print(f"{'='*60}")
    print(f"Persistence:  MAE {pers_eval_mae:.3f}")
    print(f"CatBoost:     MAE {results['catboost']['eval_mae']:.3f}")
    print(f"LightGBM:     MAE {results['lightgbm']['eval_mae']:.3f}")
    print(f"Ensemble:     MAE {results['ensemble']['eval_mae']:.3f}")

    imp = (1 - results['ensemble']['eval_mae'] / pers_eval_mae) * 100
    print(f"Improvement:  {imp:+.1f}%")

    # Save
    h_dir = output_dir / f"h{horizon}"
    h_dir.mkdir(parents=True, exist_ok=True)

    cb.save_model(str(h_dir / "catboost.cbm"))
    lgb.booster_.save_model(str(h_dir / "lightgbm.txt"))
    write_json(h_dir / "results.json", results)
    write_json(h_dir / "features.json", X.columns.tolist())

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--horizons", type=int, nargs="+", default=[3, 6])
    parser.add_argument("--run-id", default=f"q21_h36_fixed_{datetime.now().strftime('%Y%m%d_%H%M')}")
    args = parser.parse_args()

    # Load data
    print("Loading data...")
    df = pd.read_csv(
        args.root / "data" / "242000_tags.csv",
        parse_dates=["date"]
    ).set_index("date").sort_index()

    df = df.drop(columns=[c for c in df if c.startswith("Unnamed:")]).astype(float)
    print(f"Loaded {len(df):,} samples")

    # Output
    output = args.root / "eda" / "experiments" / args.run_id
    output.mkdir(parents=True, exist_ok=True)

    # Train
    all_results = {}
    for h in args.horizons:
        results = train_horizon(df, h, output)
        all_results[f"h{h}"] = results

    # Manifest
    manifest = {
        "run_id": args.run_id,
        "started_utc": utc(),
        "horizons": args.horizons,
        "results": all_results
    }
    write_json(output / "manifest.json", manifest)

    print(f"\n{'='*60}")
    print(f"Complete! Results: {output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
