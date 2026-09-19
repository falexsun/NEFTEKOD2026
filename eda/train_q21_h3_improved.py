"""
Improved Q21 h=3 training with horizon-specific optimizations.

Key improvements for h=3:
1. Horizon-specific feature engineering (longer lookback windows)
2. Process dynamics features (rates of change, acceleration)
3. Interaction features between controls and Q21 history
4. Enhanced temporal features (time of day, shift patterns)
5. Ensemble of quantile regressors
"""
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, CatBoostClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score, average_precision_score


def write_json(path: Path, obj: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    tmp.replace(path)


def prepare_h3_features(data: pd.DataFrame) -> pd.DataFrame:
    """Build h=3 specific features with focus on medium-term dynamics."""

    target = data["Q21"].copy()
    horizon_hours = 3
    future_shift = horizon_hours * 6  # 18 samples

    process = data.drop(columns=["Q21"]).replace([np.inf, -np.inf], np.nan)

    features = pd.DataFrame(index=data.index)

    print("Building h=3 optimized features...")

    # === 1. Current state ===
    for col in process.columns:
        features[f"{col}_now"] = process[col]

    # === 2. Medium-term momentum (1-6h lookback for 3h forecast) ===
    for h in [1, 2, 3, 6]:
        roll = process.rolling(f"{h}h", min_periods=max(1, h*3))

        # Central tendency
        features = features.join(roll.mean().add_suffix(f"_mean_{h}h"))
        features = features.join(roll.median().add_suffix(f"_med_{h}h"))

        # Variability
        features = features.join(roll.std().add_suffix(f"_std_{h}h"))
        features = features.join((roll.max() - roll.min()).add_suffix(f"_range_{h}h"))

        # Trends
        features = features.join(process.diff(h*6).add_suffix(f"_diff_{h}h"))

        # EWM with appropriate span
        ewm = process.ewm(span=h*6, min_periods=max(1, h*3)).mean()
        features = features.join(ewm.add_suffix(f"_ewm_{h}h"))

    # === 3. Rate of change features (acceleration) ===
    for h in [1, 3]:
        delta_1h = process.diff(6)  # 1h change
        delta_h = process.diff(h*6)  # h-hour change

        # Acceleration: change in rate
        features = features.join(
            (delta_h - delta_1h).add_suffix(f"_accel_{h}h")
        )

        # Rolling rate of change
        roc = (process / process.shift(h*6) - 1).replace([np.inf, -np.inf], np.nan)
        features = features.join(roc.add_suffix(f"_roc_{h}h"))

    # === 4. Long-term context (12-24h for baseline) ===
    for h in [12, 24]:
        roll = process.rolling(f"{h}h", min_periods=max(1, h*3))
        features = features.join(roll.mean().add_suffix(f"_ctx_{h}h"))

        # Distance from long-term mean
        ltm = roll.mean()
        features = features.join(
            (process - ltm).add_suffix(f"_dev_{h}h")
        )

    # === 5. Q21 history (at origin time, no additional lag) ===
    # For h=3 forecast, we use Q21 state at origin (t=0) to predict t+3h
    q_clean = target.mask((target < 0) | (target > 50))

    features["Q21_origin"] = q_clean
    features["Q21_invalid_or_offscale"] = ((target < 0) | (target > 50)).astype(float)

    # Q21 recent history from origin
    for h in [1, 3, 6, 12, 24]:
        shift = h * 6
        roll = q_clean.rolling(f"{h}h", min_periods=shift)

        features[f"Q21_past_mean_{h}h"] = roll.mean()
        features[f"Q21_past_std_{h}h"] = roll.std()
        features[f"Q21_past_change_{h}h"] = q_clean - q_clean.shift(shift)

    # === 6. Interaction features (Q21 × controls) ===
    # Key control variables that might interact with Q21
    control_cols = [col for col in process.columns if any(
        x in col.lower() for x in ['temp', 'flow', 'press', 'level']
    )][:10]  # Top 10 controls

    q_origin = q_clean
    for col in control_cols:
        # Interaction: Q21 × control change
        ctrl_change = process[col].diff(6)
        features[f"Q21x{col}_interaction"] = q_origin * ctrl_change

    # === 7. Temporal features ===
    # Hour of day (cyclical)
    hour = (data.index.to_series().diff().dt.total_seconds() / 3600).cumsum().fillna(0) % 24
    features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    features["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # Shift indicator (assuming 8h shifts)
    features["shift"] = (hour // 8).astype(float)

    # === 8. Target and persistence ===
    features["target"] = target.shift(-future_shift)
    features["persistence"] = target  # Current value

    print(f"Generated {len(features.columns)-2} features (excluding target, persistence)")

    return features.astype("float32")


def train_regression_ensemble(
    X_train, y_train, X_val, y_val,
    quantiles: List[float] = [0.5, 0.8]
) -> Dict[float, CatBoostRegressor]:
    """Train ensemble of quantile regressors for h=3."""

    models = {}

    for alpha in quantiles:
        print(f"\nTraining quantile α={alpha}...")

        model = CatBoostRegressor(
            loss_function=f"Quantile:alpha={alpha}",
            iterations=2000,
            learning_rate=0.03,
            depth=6,
            l2_leaf_reg=5,
            random_seed=42,
            verbose=100,
            early_stopping_rounds=50,
            task_type="GPU",
            devices="0"
        )

        model.fit(
            X_train, y_train,
            eval_set=(X_val, y_val),
            use_best_model=True
        )

        models[alpha] = model

        # Evaluate
        pred_val = model.predict(X_val)
        mae_val = mean_absolute_error(y_val, pred_val)
        print(f"  Validation MAE: {mae_val:.3f} ppm")

    return models


def train_classification(
    X_train, y_train_binary, X_val, y_val_binary,
    seed: int = 42
) -> CatBoostClassifier:
    """Train binary classifier for Q21 > 10 ppm risk."""

    print("\nTraining risk classifier...")

    # Class weights for imbalance
    n_neg = (y_train_binary == 0).sum()
    n_pos = (y_train_binary == 1).sum()
    scale_pos_weight = n_neg / n_pos

    model = CatBoostClassifier(
        loss_function="Logloss",
        iterations=2000,
        learning_rate=0.03,
        depth=5,
        l2_leaf_reg=3,
        scale_pos_weight=scale_pos_weight,
        random_seed=seed,
        verbose=100,
        early_stopping_rounds=50,
        task_type="GPU",
        devices="0"
    )

    model.fit(
        X_train, y_train_binary,
        eval_set=(X_val, y_val_binary),
        use_best_model=True
    )

    # Evaluate
    pred_proba = model.predict_proba(X_val)[:, 1]
    ap = average_precision_score(y_val_binary, pred_proba)
    auc = roc_auc_score(y_val_binary, pred_proba)

    print(f"  Validation AP: {ap:.3f}")
    print(f"  Validation AUC: {auc:.3f}")

    return model


def evaluate_split(models, X, y, pers, split_name: str) -> Dict:
    """Evaluate regression and persistence on a split."""

    results = {}

    # Persistence baseline
    valid_pers = pers.notna() & y.notna()
    pers_mae = mean_absolute_error(y[valid_pers], pers[valid_pers])

    results["persistence_mae"] = float(pers_mae)
    results["n"] = int(valid_pers.sum())

    # Model predictions
    for alpha, model in models.items():
        pred = model.predict(X)
        mae = mean_absolute_error(y, pred)
        improvement = (pers_mae - mae) / pers_mae * 100

        results[f"model_mae_q{int(alpha*100)}"] = float(mae)
        results[f"improvement_q{int(alpha*100)}"] = float(improvement)

    print(f"\n{split_name}:")
    print(f"  Persistence MAE: {pers_mae:.3f} ppm")
    for alpha in models.keys():
        mae = results[f"model_mae_q{int(alpha*100)}"]
        imp = results[f"improvement_q{int(alpha*100)}"]
        print(f"  Model (q={alpha}) MAE: {mae:.3f} ppm ({imp:+.1f}%)")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Project root directory")
    parser.add_argument("--data", default="data/242000_tags.csv", help="CSV file (relative to root)")
    args = parser.parse_args()

    # Setup
    root = args.root.resolve()
    data_path = root / args.data

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    output_dir = root / "eda" / "experiments"
    output_dir.mkdir(parents=True, exist_ok=True)

    exp_name = f"q21_h3_improved_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    exp_dir = output_dir / exp_name
    exp_dir.mkdir()

    print(f"Experiment: {exp_name}")
    print(f"Output: {exp_dir}")

    # Load data
    print(f"\nLoading data from {data_path}...")
    data = pd.read_csv(data_path, parse_dates=["date"])
    data = data.set_index("date").sort_index()
    data = data.drop(columns=[c for c in data.columns if c.startswith("Unnamed:")])
    data = data.astype(float)

    print(f"Loaded {len(data):,} samples")
    print(f"Date range: {data.index.min()} to {data.index.max()}")
    print(f"Columns: {len(data.columns)}")

    # Build h=3 features
    df = prepare_h3_features(data)

    # Remove rows without target or with invalid Q21 (code 307, negatives)
    valid_target = df["target"].notna() & df["target"].between(0, 50)
    valid_pers = df["persistence"].notna() & df["persistence"].between(0, 50)
    valid = valid_target & valid_pers

    df = df[valid].copy()
    print(f"\nValid samples (0 < Q21 < 50): {len(df):,}")

    # Split by year
    year = pd.DatetimeIndex(df.index).year

    train_mask = year <= 2023
    val_mask = year == 2024
    cal_mask = year == 2025
    eval_mask = year == 2026

    X_cols = [c for c in df.columns if c not in ["target", "persistence"]]

    X_train = df.loc[train_mask, X_cols]
    y_train = df.loc[train_mask, "target"]
    pers_train = df.loc[train_mask, "persistence"]

    X_val = df.loc[val_mask, X_cols]
    y_val = df.loc[val_mask, "target"]
    pers_val = df.loc[val_mask, "persistence"]

    X_cal = df.loc[cal_mask, X_cols]
    y_cal = df.loc[cal_mask, "target"]
    pers_cal = df.loc[cal_mask, "persistence"]

    X_eval = df.loc[eval_mask, X_cols]
    y_eval = df.loc[eval_mask, "target"]
    pers_eval = df.loc[eval_mask, "persistence"]

    print(f"\nSplits:")
    print(f"  Train: {len(X_train):,} (≤2023)")
    print(f"  Val:   {len(X_val):,} (2024)")
    print(f"  Cal:   {len(X_cal):,} (2025)")
    print(f"  Eval:  {len(X_eval):,} (2026)")

    # === REGRESSION ===
    print("\n" + "="*60)
    print("REGRESSION h=3")
    print("="*60)

    reg_models = train_regression_ensemble(
        X_train, y_train, X_val, y_val,
        quantiles=[0.5, 0.8]
    )

    # Evaluate on all splits
    metrics = {}
    for split_name, X, y, pers in [
        ("train", X_train, y_train, pers_train),
        ("validation", X_val, y_val, pers_val),
        ("calibration", X_cal, y_cal, pers_cal),
        ("evaluation", X_eval, y_eval, pers_eval)
    ]:
        metrics[split_name] = evaluate_split(reg_models, X, y, pers, split_name)

    # Save regression models
    for alpha, model in reg_models.items():
        model_path = exp_dir / f"reg_h3_improved_q{int(alpha*100)}.cbm"
        model.save_model(str(model_path))
        print(f"\nSaved: {model_path.name}")

    # === CLASSIFICATION ===
    print("\n" + "="*60)
    print("CLASSIFICATION h=3")
    print("="*60)

    # Binary target: Q21 > 10 ppm
    y_train_binary = (y_train > 10).astype(int)
    y_val_binary = (y_val > 10).astype(int)
    y_cal_binary = (y_cal > 10).astype(int)
    y_eval_binary = (y_eval > 10).astype(int)

    print(f"Prevalence:")
    print(f"  Train: {y_train_binary.mean():.1%}")
    print(f"  Val:   {y_val_binary.mean():.1%}")
    print(f"  Eval:  {y_eval_binary.mean():.1%}")

    clf_model = train_classification(X_train, y_train_binary, X_val, y_val_binary)

    # Evaluate classification on all splits
    clf_metrics = {}
    for split_name, X, y_bin in [
        ("train", X_train, y_train_binary),
        ("validation", X_val, y_val_binary),
        ("calibration", X_cal, y_cal_binary),
        ("evaluation", X_eval, y_eval_binary)
    ]:
        pred_proba = clf_model.predict_proba(X)[:, 1]
        ap = average_precision_score(y_bin, pred_proba)
        auc = roc_auc_score(y_bin, pred_proba)

        clf_metrics[split_name] = {
            "ap": float(ap),
            "auc": float(auc),
            "prevalence": float(y_bin.mean()),
            "n": int(len(y_bin))
        }

        print(f"\n{split_name}:")
        print(f"  AP:  {ap:.3f}")
        print(f"  AUC: {auc:.3f}")

    # Save classifier
    clf_path = exp_dir / "risk_h3_improved.cbm"
    clf_model.save_model(str(clf_path))
    print(f"\nSaved: {clf_path.name}")

    # === SUMMARY ===
    summary = {
        "experiment": exp_name,
        "horizon_hours": 3,
        "timestamp": datetime.now().isoformat(),
        "data": {
            "source": args.data,
            "total_samples": int(len(df)),
            "n_features": len(X_cols)
        },
        "regression_metrics": metrics,
        "classification_metrics": clf_metrics
    }

    write_json(exp_dir / "summary.json", summary)

    print("\n" + "="*60)
    print("FINAL RESULTS (Evaluation 2026)")
    print("="*60)

    eval_reg = metrics["evaluation"]
    eval_clf = clf_metrics["evaluation"]

    print(f"\nREGRESSION:")
    print(f"  Persistence: {eval_reg['persistence_mae']:.3f} ppm")
    for alpha in [0.5, 0.8]:
        key = f"model_mae_q{int(alpha*100)}"
        imp_key = f"improvement_q{int(alpha*100)}"
        print(f"  Model (q={alpha}): {eval_reg[key]:.3f} ppm ({eval_reg[imp_key]:+.1f}%)")

    print(f"\nCLASSIFICATION:")
    print(f"  AP:  {eval_clf['ap']:.3f}")
    print(f"  AUC: {eval_clf['auc']:.3f}")

    print(f"\n✅ Experiment complete: {exp_dir}")


if __name__ == "__main__":
    main()
