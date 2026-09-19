"""
Multi-horizon residual learning experiment.

Обучить residual models для h=0.5, h=2, h=6 часов.
Цель: построить полную кривую точности по горизонтам.
"""
import pandas as pd
import numpy as np
from catboost import CatBoostRegressor, Pool
from pathlib import Path
from datetime import datetime
import json

def load_data(root):
    df = pd.read_csv(root / 'data' / '242000_tags.csv')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    mask = (df['Q21'] > 0) & (df['Q21'] < 50)
    df = df[mask].copy()
    return df

def build_features(df, horizon_steps):
    """Универсальные residual features для любого горизонта"""
    features = []

    # Target
    df[f'Q21_h{horizon_steps}'] = df['Q21'].shift(-horizon_steps)
    df[f'Q21_delta_h{horizon_steps}'] = df[f'Q21_h{horizon_steps}'] - df['Q21']
    df['Q21_persistence'] = df['Q21']

    # Базовые controls
    for col in df.columns:
        if col in ['date'] or 'Q21_h' in col or 'Q21_delta' in col or col == 'Q21_persistence':
            continue
        if df[col].dtype in ['float64', 'int64']:
            features.append(col)

    # Q21 lags - адаптировать к горизонту
    max_lag = min(horizon_steps * 2, 36)  # До 2x горизонт или 6 часов
    lag_steps = [1, 2, 3, 6, 12, 18, max_lag] if max_lag > 18 else [1, 2, 3, 6, 12, 18]
    for lag in lag_steps:
        df[f'Q21_lag{lag}'] = df['Q21'].shift(lag)
        features.append(f'Q21_lag{lag}')

    # Trend features
    for window in [6, 18, 36]:
        df[f'Q21_mean_{window}'] = df['Q21'].rolling(window, min_periods=1).mean()
        df[f'Q21_std_{window}'] = df['Q21'].rolling(window, min_periods=1).std()
        df[f'Q21_min_{window}'] = df['Q21'].rolling(window, min_periods=1).min()
        df[f'Q21_max_{window}'] = df['Q21'].rolling(window, min_periods=1).max()
        features.extend([
            f'Q21_mean_{window}', f'Q21_std_{window}',
            f'Q21_min_{window}', f'Q21_max_{window}'
        ])

    # Velocity
    df['Q21_diff1'] = df['Q21'].diff(1)
    df['Q21_diff6'] = df['Q21'].diff(6)
    features.extend(['Q21_diff1', 'Q21_diff6'])

    # Volatility
    df['Q21_abs_diff_mean_18'] = df['Q21'].diff(1).abs().rolling(18, min_periods=1).mean()
    features.append('Q21_abs_diff_mean_18')

    # Controls lags
    controls = ['F1', 'P8', 'T11', 'F19', 'F25']
    for col in controls:
        if col in df.columns:
            for lag in [0, 1, 3, 6]:
                df[f'{col}_lag{lag}'] = df[col].shift(lag)
                features.append(f'{col}_lag{lag}')

    return df, features

def split_data(df):
    train = df[df['date'] <= '2023-12-28'].copy()
    val = df[(df['date'] >= '2024-01-01') & (df['date'] <= '2024-06-27')].copy()
    cal = df[(df['date'] >= '2024-07-01') & (df['date'] <= '2025-12-28')].copy()
    eval_data = df[df['date'] >= '2026-01-01'].copy()
    return train, val, cal, eval_data

def train_residual(X_train, y_train, X_val, y_val, quantile=0.5):
    model = CatBoostRegressor(
        loss_function=f'Quantile:alpha={quantile}',
        iterations=2000,
        learning_rate=0.02,
        depth=5,
        l2_leaf_reg=10,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=150,
        task_type="GPU",
        devices="0"
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), use_best_model=True)
    return model

def evaluate(model, X, y_true, y_pers, split_name):
    y_delta_pred = model.predict(X)
    y_pred = y_pers + y_delta_pred

    mae_pers = np.abs(y_true - y_pers).mean()
    mae_model = np.abs(y_true - y_pred).mean()
    improvement = (mae_pers - mae_model) / mae_pers * 100

    return {
        'split': split_name,
        'mae_persistence': float(mae_pers),
        'mae_model': float(mae_model),
        'improvement_pct': float(improvement),
        'n': len(y_true)
    }

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=str, required=True)
    args = parser.parse_args()

    root = Path(args.root)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_id = f"q21_multihorizon_{timestamp}"
    output_dir = root / 'eda' / 'experiments' / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Multi-horizon experiment: {run_id}\n")

    # Load data once
    print("Loading data...")
    df = load_data(root)
    print(f"Loaded {len(df):,} samples\n")

    # Horizons: 0.5h, 1h, 2h, 3h, 6h
    horizons_config = [
        (3, 0.5),   # 3 steps = 30 min
        (6, 1.0),   # 6 steps = 1 hour
        (12, 2.0),  # 12 steps = 2 hours
        (18, 3.0),  # 18 steps = 3 hours
        (36, 6.0),  # 36 steps = 6 hours
    ]

    all_results = []

    for steps, hours in horizons_config:
        print("="*60)
        print(f"HORIZON: {hours}h ({steps} steps)")
        print("="*60)

        # Build features
        df_h = df.copy()
        df_h, feature_cols = build_features(df_h, steps)
        df_h = df_h.dropna(subset=[f'Q21_h{steps}'] + feature_cols)

        print(f"Valid samples: {len(df_h):,}")

        # Split
        train, val, cal, eval_data = split_data(df_h)

        # Prepare data
        X_train = train[feature_cols]
        y_train_delta = train[f'Q21_delta_h{steps}']
        y_train_true = train[f'Q21_h{steps}']
        y_train_pers = train['Q21_persistence']

        X_val = val[feature_cols]
        y_val_delta = val[f'Q21_delta_h{steps}']
        y_val_true = val[f'Q21_h{steps}']
        y_val_pers = val['Q21_persistence']

        X_cal = cal[feature_cols]
        y_cal_true = cal[f'Q21_h{steps}']
        y_cal_pers = cal['Q21_persistence']

        X_eval = eval_data[feature_cols]
        y_eval_true = eval_data[f'Q21_h{steps}']
        y_eval_pers = eval_data['Q21_persistence']

        # Train
        print(f"\nTraining residual model for h={hours}h...")
        model = train_residual(X_train, y_train_delta, X_val, y_val_delta)

        # Evaluate
        results_train = evaluate(model, X_train, y_train_true, y_train_pers, 'train')
        results_val = evaluate(model, X_val, y_val_true, y_val_pers, 'validation')
        results_cal = evaluate(model, X_cal, y_cal_true, y_cal_pers, 'calibration')
        results_eval = evaluate(model, X_eval, y_eval_true, y_eval_pers, 'evaluation')

        print(f"\nResults h={hours}h:")
        for r in [results_train, results_val, results_cal, results_eval]:
            print(f"  {r['split']:12s}: MAE={r['mae_model']:.3f} ppm "
                  f"(pers={r['mae_persistence']:.3f}, improvement={r['improvement_pct']:+.1f}%)")

        # Save model
        model_path = output_dir / f"reg_h{hours:.1f}_residual.cbm"
        model.save_model(str(model_path))

        # Collect results
        horizon_result = {
            'horizon_hours': hours,
            'horizon_steps': steps,
            'train': results_train,
            'validation': results_val,
            'calibration': results_cal,
            'evaluation': results_eval,
            'model_path': str(model_path),
            'n_features': len(feature_cols),
        }
        all_results.append(horizon_result)

        print()

    # Summary
    print("\n" + "="*60)
    print("SUMMARY: Multi-Horizon Performance")
    print("="*60)
    print(f"\n{'Horizon':>10s} {'Eval MAE':>12s} {'Pers MAE':>12s} {'Improv %':>12s}")
    print("-" * 50)
    for r in all_results:
        h = r['horizon_hours']
        e = r['evaluation']
        print(f"{h:>9.1f}h {e['mae_model']:>11.3f} {e['mae_persistence']:>11.3f} {e['improvement_pct']:>11.1f}%")

    # Save
    with open(output_dir / 'multihorizon_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n✅ Multi-horizon experiment complete: {output_dir}")

if __name__ == '__main__':
    main()
