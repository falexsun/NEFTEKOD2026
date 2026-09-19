"""
Финальная попытка улучшить h=3: фокус на робастности к distribution shift.

Стратегии:
1. Residual learning: предсказывать Δ относительно persistence
2. Добавить trend/volatility features для адаптации к eval режиму
3. Более консервативная регуляризация
4. Ensemble с persistence
"""
import pandas as pd
import numpy as np
from catboost import CatBoostRegressor, CatBoostClassifier, Pool
from pathlib import Path
from datetime import datetime
import json

def load_data(root):
    df = pd.read_csv(root / 'data' / '242000_tags.csv')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Удалить Unnamed колонки
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]

    # Фильтрация кодов 307 и экстремальных значений
    mask = (df['Q21'] > 0) & (df['Q21'] < 50)
    df = df[mask].copy()

    return df

def build_features(df, horizon_steps=18):
    """
    Создать признаки для h=3 с акцентом на робастность.

    Новые фичи:
    - Residual target: Δ = Q21_h3 - Q21 (persistence)
    - Trend indicators: rolling mean/std
    - Volatility regime: последние N шагов |diff|
    """
    features = []

    # Target
    df['Q21_h3'] = df['Q21'].shift(-horizon_steps)
    df['Q21_delta_h3'] = df['Q21_h3'] - df['Q21']  # Residual target

    # Persistence
    df['Q21_persistence_h3'] = df['Q21']

    # 1. Базовые фичи
    for col in df.columns:
        if col in ['date', 'Q21_h3', 'Q21_delta_h3', 'Q21_persistence_h3']:
            continue
        if df[col].dtype in ['float64', 'int64']:
            features.append(col)

    # 2. Q21 history (короткая для h=3)
    for lag in [1, 2, 3, 6, 12, 18]:  # До 3 часов
        df[f'Q21_lag{lag}'] = df['Q21'].shift(lag)
        features.append(f'Q21_lag{lag}')

    # 3. Trend features - критически важны для eval shift
    for window in [6, 18, 36]:  # 1h, 3h, 6h
        # Mean trend
        df[f'Q21_mean_{window}'] = df['Q21'].rolling(window, min_periods=1).mean()
        features.append(f'Q21_mean_{window}')

        # Std (volatility)
        df[f'Q21_std_{window}'] = df['Q21'].rolling(window, min_periods=1).std()
        features.append(f'Q21_std_{window}')

        # Min/Max
        df[f'Q21_min_{window}'] = df['Q21'].rolling(window, min_periods=1).min()
        df[f'Q21_max_{window}'] = df['Q21'].rolling(window, min_periods=1).max()
        features.append(f'Q21_min_{window}')
        features.append(f'Q21_max_{window}')

    # 4. Velocity features
    df['Q21_diff1'] = df['Q21'].diff(1)  # 10-мин изменение
    df['Q21_diff6'] = df['Q21'].diff(6)  # 1-час изменение
    features.extend(['Q21_diff1', 'Q21_diff6'])

    # 5. Volatility regime indicator
    df['Q21_abs_diff_mean_18'] = df['Q21'].diff(1).abs().rolling(18, min_periods=1).mean()
    features.append('Q21_abs_diff_mean_18')

    # 6. Controls короткие лаги
    controls = ['F1', 'P8', 'T11', 'F19', 'F25']
    for col in controls:
        if col in df.columns:
            for lag in [0, 1, 3, 6]:
                df[f'{col}_lag{lag}'] = df[col].shift(lag)
                features.append(f'{col}_lag{lag}')

    print(f"Generated {len(features)} features")
    return df, features

def split_data(df):
    # 3-day gaps
    train = df[df['date'] <= '2023-12-28'].copy()
    val = df[(df['date'] >= '2024-01-01') & (df['date'] <= '2024-06-27')].copy()
    cal = df[(df['date'] >= '2024-07-01') & (df['date'] <= '2025-12-28')].copy()
    eval_data = df[df['date'] >= '2026-01-01'].copy()

    return train, val, cal, eval_data

def train_residual_regression(X_train, y_train, X_val, y_val, quantile=0.5):
    """
    Обучить модель предсказывать residual (Δ), не абсолютное значение.
    """
    model = CatBoostRegressor(
        loss_function=f'Quantile:alpha={quantile}',
        iterations=1500,
        learning_rate=0.02,  # Медленнее для робастности
        depth=5,             # Меньше глубина
        l2_leaf_reg=10,      # Сильная регуляризация
        random_seed=42,
        verbose=100,
        early_stopping_rounds=100,
        task_type="GPU",
        devices="0"
    )

    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        use_best_model=True
    )

    return model

def evaluate_residual_model(model, X, y_true, y_persistence, split_name):
    """
    Оценить residual модель.
    """
    # Предсказать Δ
    y_delta_pred = model.predict(X)

    # Финальный прогноз = persistence + Δ
    y_pred = y_persistence + y_delta_pred

    # Метрики
    mae_persistence = np.abs(y_true - y_persistence).mean()
    mae_model = np.abs(y_true - y_pred).mean()
    improvement = (mae_persistence - mae_model) / mae_persistence * 100

    print(f"\n{split_name}:")
    print(f"  Persistence MAE: {mae_persistence:.3f} ppm")
    print(f"  Model MAE: {mae_model:.3f} ppm ({improvement:+.1f}%)")

    return mae_model

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=str, required=True)
    args = parser.parse_args()

    root = Path(args.root)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_id = f"q21_h3_residual_{timestamp}"
    output_dir = root / 'eda' / 'experiments' / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Experiment: {run_id}")
    print(f"Output: {output_dir}")

    # Load
    print("\nLoading data...")
    df = load_data(root)
    print(f"Loaded {len(df):,} samples")

    # Features
    print("\nBuilding residual features...")
    df, feature_cols = build_features(df, horizon_steps=18)

    # Dropna
    df = df.dropna(subset=['Q21_h3'] + feature_cols)
    print(f"Valid samples: {len(df):,}")

    # Split
    print("\nSplitting...")
    train, val, cal, eval_data = split_data(df)
    print(f"  Train: {len(train):,}")
    print(f"  Val: {len(val):,}")
    print(f"  Cal: {len(cal):,}")
    print(f"  Eval: {len(eval_data):,}")

    # Prepare
    X_train = train[feature_cols]
    y_train_delta = train['Q21_delta_h3']  # Residual target!
    y_train_true = train['Q21_h3']
    y_train_pers = train['Q21_persistence_h3']

    X_val = val[feature_cols]
    y_val_delta = val['Q21_delta_h3']
    y_val_true = val['Q21_h3']
    y_val_pers = val['Q21_persistence_h3']

    X_cal = cal[feature_cols]
    y_cal_true = cal['Q21_h3']
    y_cal_pers = cal['Q21_persistence_h3']

    X_eval = eval_data[feature_cols]
    y_eval_true = eval_data['Q21_h3']
    y_eval_pers = eval_data['Q21_persistence_h3']

    print("\n" + "="*60)
    print("RESIDUAL REGRESSION h=3")
    print("="*60)

    print("\nTraining residual model...")
    model = train_residual_regression(X_train, y_train_delta, X_val, y_val_delta, quantile=0.5)

    # Eval
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    evaluate_residual_model(model, X_train, y_train_true, y_train_pers, "train")
    evaluate_residual_model(model, X_val, y_val_true, y_val_pers, "validation")
    evaluate_residual_model(model, X_cal, y_cal_true, y_cal_pers, "calibration")
    mae_eval = evaluate_residual_model(model, X_eval, y_eval_true, y_eval_pers, "evaluation")

    # Save
    model_path = output_dir / "reg_h3_residual.cbm"
    model.save_model(str(model_path))
    print(f"\nSaved: {model_path}")

    # Metadata
    metadata = {
        'run_id': run_id,
        'approach': 'residual_learning',
        'target': 'Q21_delta_h3',
        'horizon': 3,
        'eval_mae': float(mae_eval),
        'features': feature_cols,
        'n_features': len(feature_cols),
    }

    with open(output_dir / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Experiment complete: {output_dir}")

if __name__ == '__main__':
    main()
