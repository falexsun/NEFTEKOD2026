"""
Train quantile regressors for Q21 uncertainty estimation.

For each horizon, train models for quantiles: 0.10, 0.25, 0.50, 0.75, 0.90
This gives calibrated uncertainty intervals for the dashboard.

Usage:
    python eda/train_q21_quantiles.py --root /path/to/project --horizons 1 3
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import mean_absolute_error


def load_data(root: Path):
    """Load and prepare Q21 data."""
    print("Loading telemetry...")
    avt = pd.read_csv(root / "data" / "avt_tags.csv")
    u242000 = pd.read_csv(root / "data" / "242000_tags.csv")

    # Clean unnamed columns
    avt = avt.loc[:, ~avt.columns.str.contains('^Unnamed')]
    u242000 = u242000.loc[:, ~u242000.columns.str.contains('^Unnamed')]

    # Rename date to timestamp if needed
    if 'date' in avt.columns:
        avt = avt.rename(columns={'date': 'timestamp'})
    if 'date' in u242000.columns:
        u242000 = u242000.rename(columns={'date': 'timestamp'})

    # Merge
    df = pd.merge(avt, u242000, on='timestamp', how='inner')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)

    print(f"Loaded {len(df)} rows")
    return df


def create_residual_features(df: pd.DataFrame, horizon_hours: float):
    """Create residual learning features for given horizon."""
    h_steps = int(horizon_hours * 6)  # 10-min steps

    # Target: Δ = Q21(t+h) - Q21(t)
    df['target_delta'] = df['Q21'].shift(-h_steps) - df['Q21']

    # Features
    features = []

    # Current Q21
    features.append('Q21')

    # Recent history
    for lag in [1, 2, 3, 6, 12, 18]:
        df[f'Q21_lag_{lag}'] = df['Q21'].shift(lag)
        features.append(f'Q21_lag_{lag}')

    # Rolling statistics (look back only)
    for window in [6, 12, 24]:
        df[f'Q21_roll_mean_{window}'] = df['Q21'].rolling(window, min_periods=1).mean()
        df[f'Q21_roll_std_{window}'] = df['Q21'].rolling(window, min_periods=1).std()
        features.extend([f'Q21_roll_mean_{window}', f'Q21_roll_std_{window}'])

    # Rate of change
    df['Q21_diff_1'] = df['Q21'].diff(1)
    df['Q21_diff_6'] = df['Q21'].diff(6)
    features.extend(['Q21_diff_1', 'Q21_diff_6'])

    # Controls (if available)
    control_tags = ['F31', 'T33', 'T55']
    for tag in control_tags:
        if tag in df.columns:
            features.append(tag)
            # Rolling averages
            df[f'{tag}_roll_6'] = df[tag].rolling(6, min_periods=1).mean()
            features.append(f'{tag}_roll_6')

    # Time features
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    features.extend(['hour', 'day_of_week'])

    return df, features


def split_temporal(df: pd.DataFrame):
    """Temporal train/val/cal/eval split."""
    # Same splits as before
    train_end = pd.Timestamp('2024-12-31')
    val_end = pd.Timestamp('2025-06-30')
    cal_end = pd.Timestamp('2025-12-31')

    # 3-day gaps
    train_gap = pd.Timedelta(days=3)
    val_gap = pd.Timedelta(days=3)
    cal_gap = pd.Timedelta(days=3)

    train_mask = df['timestamp'] <= train_end
    val_mask = (df['timestamp'] > train_end + train_gap) & (df['timestamp'] <= val_end)
    cal_mask = (df['timestamp'] > val_end + val_gap) & (df['timestamp'] <= cal_end)
    eval_mask = df['timestamp'] > cal_end + cal_gap

    return train_mask, val_mask, cal_mask, eval_mask


def train_quantile_model(X_train, y_train, X_val, y_val, quantile: float, iterations: int):
    """Train single quantile regressor."""
    model = CatBoostRegressor(
        iterations=iterations,
        learning_rate=0.03,
        depth=6,
        loss_function='Quantile:alpha=' + str(quantile),
        eval_metric='MAE',
        task_type='GPU',
        devices='0',
        verbose=False,
        random_seed=42
    )

    train_pool = Pool(X_train, y_train)
    val_pool = Pool(X_val, y_val)

    model.fit(train_pool, eval_set=val_pool, early_stopping_rounds=100, verbose=50)

    return model


def evaluate_quantiles(models_dict, X, y, split_name: str):
    """Evaluate quantile predictions."""
    results = {}

    # Get predictions for all quantiles
    preds = {}
    for q, model in models_dict.items():
        preds[q] = model.predict(X)

    # Check coverage for each quantile pair
    for q_low, q_high in [(0.1, 0.9), (0.25, 0.75)]:
        coverage = np.mean((y >= preds[q_low]) & (y <= preds[q_high]))
        expected = q_high - q_low
        results[f'coverage_{int(q_low*100)}_{int(q_high*100)}'] = coverage
        results[f'expected_{int(q_low*100)}_{int(q_high*100)}'] = expected

    # Median MAE
    median_mae = mean_absolute_error(y, preds[0.5])
    results['median_mae'] = median_mae

    # Interval width (80% and 50%)
    results['width_80pct'] = np.mean(preds[0.9] - preds[0.1])
    results['width_50pct'] = np.mean(preds[0.75] - preds[0.25])

    print(f"\n{split_name}:")
    print(f"  Median MAE: {median_mae:.3f} ppm")
    print(f"  80% coverage: {results['coverage_10_90']:.1%} (expected {results['expected_10_90']:.0%})")
    print(f"  50% coverage: {results['coverage_25_75']:.1%} (expected {results['expected_25_75']:.0%})")
    print(f"  80% interval width: {results['width_80pct']:.3f} ppm")
    print(f"  50% interval width: {results['width_50pct']:.3f} ppm")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--horizons', type=float, nargs='+', default=[1.0, 3.0])
    parser.add_argument('--iterations', type=int, default=1200)
    args = parser.parse_args()

    print("=" * 60)
    print("Q21 Quantile Regression Training")
    print("=" * 60)
    print(f"Horizons: {args.horizons}")
    print(f"Quantiles: [0.1, 0.25, 0.5, 0.75, 0.9]")
    print(f"Iterations: {args.iterations}")

    # Load data
    df = load_data(args.root)

    quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]

    for horizon in args.horizons:
        print(f"\n{'=' * 60}")
        print(f"Training horizon h={horizon}h")
        print(f"{'=' * 60}")

        # Prepare features
        df_h = df.copy()
        df_h, features = create_residual_features(df_h, horizon)

        # Remove NaNs
        df_h = df_h.dropna(subset=['target_delta'] + features)

        # Split
        train_mask, val_mask, cal_mask, eval_mask = split_temporal(df_h)

        X_train = df_h.loc[train_mask, features]
        y_train = df_h.loc[train_mask, 'target_delta']
        X_val = df_h.loc[val_mask, features]
        y_val = df_h.loc[val_mask, 'target_delta']
        X_cal = df_h.loc[cal_mask, features]
        y_cal = df_h.loc[cal_mask, 'target_delta']
        X_eval = df_h.loc[eval_mask, features]
        y_eval = df_h.loc[eval_mask, 'target_delta']

        print(f"Train: {len(X_train)}, Val: {len(X_val)}, Cal: {len(X_cal)}, Eval: {len(X_eval)}")

        # Train models for each quantile
        models = {}
        for q in quantiles:
            print(f"\nTraining quantile {q}...")
            models[q] = train_quantile_model(X_train, y_train, X_val, y_val, q, args.iterations)

        # Evaluate
        print("\n" + "=" * 60)
        print(f"Evaluation Results - h={horizon}h")
        print("=" * 60)

        train_results = evaluate_quantiles(models, X_train, y_train, "Train")
        val_results = evaluate_quantiles(models, X_val, y_val, "Validation")
        cal_results = evaluate_quantiles(models, X_cal, y_cal, "Calibration")
        eval_results = evaluate_quantiles(models, X_eval, y_eval, "Evaluation 2026")

        # Save models
        run_id = f"q21_quantiles_h{int(horizon*10):02d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        exp_dir = args.root / "eda" / "experiments" / run_id
        exp_dir.mkdir(parents=True, exist_ok=True)

        models_dir = exp_dir / "models"
        models_dir.mkdir(exist_ok=True)

        for q, model in models.items():
            model_path = models_dir / f"quantile_{int(q*100):02d}.cbm"
            model.save_model(str(model_path))
            print(f"Saved {model_path.name}")

        # Save feature list
        with open(exp_dir / "features.json", 'w') as f:
            json.dump(features, f, indent=2)

        # Save results
        results_summary = {
            'horizon_hours': horizon,
            'quantiles': quantiles,
            'n_features': len(features),
            'train': train_results,
            'validation': val_results,
            'calibration': cal_results,
            'evaluation': eval_results
        }

        with open(exp_dir / "results.json", 'w') as f:
            json.dump(results_summary, f, indent=2)

        print(f"\nResults saved to: {exp_dir}")

    print("\n" + "=" * 60)
    print("✅ Quantile regression training complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
