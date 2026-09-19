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

    return {
        'train': df[train_mask].copy(),
        'validation': df[val_mask].copy(),
        'calibration': df[cal_mask].copy(),
        'evaluation': df[eval_mask].copy()
    }


def train_quantile_model(
    X_train, y_train,
    X_val, y_val,
    quantile: float,
    iterations: int = 1000
):
    """Train a single quantile regressor."""
    model = CatBoostRegressor(
        iterations=iterations,
        learning_rate=0.03,
        depth=6,
        loss_function=f'Quantile:alpha={quantile}',
        task_type='GPU',
        devices='0',
        random_seed=42,
        verbose=100
    )

    train_pool = Pool(X_train, y_train)
    val_pool = Pool(X_val, y_val)

    model.fit(
        train_pool,
        eval_set=val_pool,
        use_best_model=True,
        early_stopping_rounds=100
    )

    return model


def evaluate_quantile_coverage(y_true, quantile_preds: dict, split_name: str):
    """Check if quantile predictions are calibrated."""
    results = {}

    # Expected coverage for intervals
    intervals = [
        ('80%', 0.10, 0.90, 0.80),
        ('90%', 0.05, 0.95, 0.90),
        ('50%', 0.25, 0.75, 0.50)
    ]

    for name, q_low, q_high, expected in intervals:
        if q_low in quantile_preds and q_high in quantile_preds:
            low = quantile_preds[q_low]
            high = quantile_preds[q_high]

            # Check coverage
            in_interval = (y_true >= low) & (y_true <= high)
            actual_coverage = in_interval.mean()

            # Interval width
            width = (high - low).mean()

            results[name] = {
                'expected': expected,
                'actual': actual_coverage,
                'width': width,
                'calibrated': abs(actual_coverage - expected) < 0.05
            }

    print(f"\n{split_name} Coverage Analysis:")
    for name, res in results.items():
        status = "✅" if res['calibrated'] else "⚠️"
        print(f"  {status} {name} interval: "
              f"expected={res['expected']:.1%}, "
              f"actual={res['actual']:.1%}, "
              f"width={res['width']:.3f}")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=str, required=True)
    parser.add_argument('--horizons', nargs='+', type=float, default=[1.0, 3.0],
                       help='Horizons in hours')
    parser.add_argument('--iterations', type=int, default=1000)
    args = parser.parse_args()

    root = Path(args.root)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Quantiles to train
    quantiles = [0.10, 0.25, 0.50, 0.75, 0.90]

    print("="*60)
    print("Q21 Quantile Regression Training")
    print("="*60)
    print(f"Horizons: {args.horizons}")
    print(f"Quantiles: {quantiles}")
    print(f"Iterations: {args.iterations}")

    # Load data
    df = load_data(root)

    all_results = {}

    for horizon_h in args.horizons:
        print(f"\n{'='*60}")
        print(f"Training horizon h={horizon_h}h")
        print(f"{'='*60}")

        # Prepare features
        df_h, features = create_residual_features(df, horizon_h)

        # Remove rows with NaN
        valid_mask = df_h[features + ['target_delta']].notna().all(axis=1)
        df_clean = df_h[valid_mask].copy()

        print(f"Valid samples: {len(df_clean)}")

        # Split
        splits = split_temporal(df_clean)

        X_train = splits['train'][features]
        y_train = splits['train']['target_delta']
        X_val = splits['validation'][features]
        y_val = splits['validation']['target_delta']
        X_cal = splits['calibration'][features]
        y_cal = splits['calibration']['target_delta']
        X_eval = splits['evaluation'][features]
        y_eval = splits['evaluation']['target_delta']

        print(f"Train: {len(X_train)}, Val: {len(X_val)}, "
              f"Cal: {len(X_cal)}, Eval: {len(X_eval)}")

        # Create experiment directory
        exp_dir = root / "eda" / "experiments" / f"q21_quantiles_h{horizon_h}_{timestamp}"
        exp_dir.mkdir(parents=True, exist_ok=True)

        # Train each quantile
        models = {}
        quantile_preds = {split: {} for split in ['train', 'validation', 'calibration', 'evaluation']}

        for q in quantiles:
            print(f"\n--- Training quantile {q} ---")

            model = train_quantile_model(
                X_train, y_train,
                X_val, y_val,
                quantile=q,
                iterations=args.iterations
            )

            models[q] = model

            # Save model
            model_path = exp_dir / f"quantile_{q:.2f}.cbm"
            model.save_model(str(model_path))
            print(f"Saved: {model_path}")

            # Predictions on all splits
            quantile_preds['train'][q] = model.predict(X_train)
            quantile_preds['validation'][q] = model.predict(X_val)
            quantile_preds['calibration'][q] = model.predict(X_cal)
            quantile_preds['evaluation'][q] = model.predict(X_eval)

        # Evaluate coverage
        print(f"\n{'='*60}")
        print("Quantile Calibration Check")
        print(f"{'='*60}")

        coverage_results = {}
        for split_name, y_true in [
            ('train', y_train),
            ('validation', y_val),
            ('calibration', y_cal),
            ('evaluation', y_eval)
        ]:
            coverage = evaluate_quantile_coverage(
                y_true,
                quantile_preds[split_name],
                split_name.capitalize()
            )
            coverage_results[split_name] = coverage

        # Point estimates (median)
        median_preds = {
            'train': quantile_preds['train'][0.50],
            'validation': quantile_preds['validation'][0.50],
            'calibration': quantile_preds['calibration'][0.50],
            'evaluation': quantile_preds['evaluation'][0.50]
        }

        # MAE of median
        mae_results = {}
        for split_name, y_true in [
            ('train', y_train),
            ('validation', y_val),
            ('calibration', y_cal),
            ('evaluation', y_eval)
        ]:
            mae = mean_absolute_error(y_true, median_preds[split_name])
            mae_results[split_name] = mae
            print(f"{split_name.capitalize()} MAE (median): {mae:.3f} ppm")

        # Save results
        results = {
            'horizon_hours': horizon_h,
            'quantiles': quantiles,
            'features': features,
            'n_features': len(features),
            'splits': {
                'train': len(X_train),
                'validation': len(X_val),
                'calibration': len(X_cal),
                'evaluation': len(X_eval)
            },
            'mae': mae_results,
            'coverage': coverage_results,
            'timestamp': timestamp
        }

        results_path = exp_dir / 'quantile_results.json'
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\nResults saved: {results_path}")

        all_results[f'h{horizon_h}'] = results

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY: Quantile Regression Complete")
    print(f"{'='*60}")

    for h_key, res in all_results.items():
        print(f"\n{h_key}:")
        print(f"  Evaluation MAE (median): {res['mae']['evaluation']:.3f} ppm")

        eval_cov = res['coverage']['evaluation']
        for interval_name, cov_res in eval_cov.items():
            status = "✅" if cov_res['calibrated'] else "⚠️"
            print(f"  {status} {interval_name}: "
                  f"coverage={cov_res['actual']:.1%}, "
                  f"width={cov_res['width']:.3f}")


if __name__ == '__main__':
    main()
