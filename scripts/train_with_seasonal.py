#!/usr/bin/env python3
"""
Обучение модели с сезонными признаками на A100
"""

import sys
from pathlib import Path
import logging
import json
import time
import pickle

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from catboost import CatBoostRegressor, Pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_seasonal_features(df):
    """Добавить сезонные признаки"""

    # Предполагаем что есть колонка date
    if 'date' not in df.columns:
        logger.warning("No date column, skipping seasonal features")
        return df

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])

    # Извлекаем временные компоненты
    df['month'] = df['date'].dt.month
    df['day_of_year'] = df['date'].dt.dayofyear

    # Циклические признаки (лучше для непрерывности)
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['day_sin'] = np.sin(2 * np.pi * df['day_of_year'] / 365)
    df['day_cos'] = np.cos(2 * np.pi * df['day_of_year'] / 365)

    # Сезоны (one-hot)
    df['is_winter'] = df['month'].isin([12, 1, 2]).astype(int)
    df['is_spring'] = df['month'].isin([3, 4, 5]).astype(int)
    df['is_summer'] = df['month'].isin([6, 7, 8]).astype(int)
    df['is_autumn'] = df['month'].isin([9, 10, 11]).astype(int)

    # Убираем временные колонки
    df = df.drop(columns=['month', 'day_of_year'])

    logger.info("Added seasonal features: month_sin/cos, day_sin/cos, season one-hot")

    return df


def load_and_prepare_data(data_dir: Path, with_seasonal: bool = True):
    """Загрузка и подготовка данных"""
    logger.info("Loading data...")

    # Load
    avt = pd.read_csv(data_dir / 'avt_tags.csv')
    hydro = pd.read_csv(data_dir / '242000_tags.csv')

    logger.info(f"AVT: {avt.shape}, 24-2000: {hydro.shape}")

    # Merge
    avt['date'] = pd.to_datetime(avt['date'])
    hydro['date'] = pd.to_datetime(hydro['date'])

    avt_clean = avt.set_index('date').sort_index()
    hydro_clean = hydro.set_index('date').sort_index()

    avt_clean.columns = ['AVT_' + col for col in avt_clean.columns]
    hydro_clean.columns = ['H24_' + col for col in hydro_clean.columns]

    combined = pd.merge_asof(
        avt_clean.reset_index(),
        hydro_clean.reset_index(),
        on='date',
        tolerance=pd.Timedelta('5min'),
        direction='nearest'
    )

    logger.info(f"Combined: {combined.shape}")

    # Add seasonal features if requested
    if with_seasonal:
        combined = add_seasonal_features(combined)

    # Target
    target_col = 'H24_F25'
    target = combined[target_col].dropna()

    # Top correlated features
    features_base = combined.drop(columns=[target_col, 'date'])
    correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
    top_features = correlations.head(20).index.tolist()

    logger.info(f"Top features: {top_features[:5]}...")

    # Feature engineering
    df = combined[top_features + [target_col, 'date']].copy()

    # Сохраняем date для сезонных признаков
    dates = df['date'].copy()
    df = df.drop(columns=['date'])

    # Lags
    for col in top_features[:10]:
        df[f'{col}_lag_6'] = df[col].shift(6)
        df[f'{col}_lag_12'] = df[col].shift(12)

    # Rolling
    for col in top_features[:5]:
        df[f'{col}_roll_6'] = df[col].rolling(6, min_periods=1).mean()

    # Add seasonal features if we have them
    if with_seasonal:
        seasonal_cols = ['month_sin', 'month_cos', 'day_sin', 'day_cos',
                        'is_winter', 'is_spring', 'is_summer', 'is_autumn']

        for col in seasonal_cols:
            if col in combined.columns:
                # Используем оригинальные индексы
                df[col] = combined[col].values[:len(df)]

    # Clean
    df = df.dropna(subset=[target_col])
    feature_cols = [col for col in df.columns if col != target_col]
    df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median())
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    X = df[feature_cols]
    y = df[target_col]

    logger.info(f"Final: X={X.shape}, y={y.shape}")
    logger.info(f"Features: {X.shape[1]} (including seasonal: {with_seasonal})")

    return X, y, top_features


def train_best_config(X_train, y_train, X_val, y_val):
    """Обучить лучшую конфигурацию с A100"""
    logger.info("Training with best config from A100 search...")

    start = time.time()

    # Best config: CatBoost i1000_d8_lr0.03_l23
    model = CatBoostRegressor(
        iterations=1000,
        learning_rate=0.03,
        depth=8,
        l2_leaf_reg=3,
        task_type='GPU',
        devices='0',
        loss_function='RMSE',
        eval_metric='MAE',
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )

    # Scaling
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    # Train
    train_pool = Pool(X_train_scaled, y_train)
    val_pool = Pool(X_val_scaled, y_val)

    model.fit(train_pool, eval_set=val_pool, verbose=False)

    # Evaluate
    y_pred = model.predict(X_val_scaled)
    mae = mean_absolute_error(y_val, y_pred)
    rmse = np.sqrt(mean_squared_error(y_val, y_pred))
    r2 = r2_score(y_val, y_pred)

    elapsed = time.time() - start

    logger.info(f"✓ MAE={mae:.2f}, R²={r2:.4f}, {elapsed:.1f}s")

    return model, scaler, {'mae': float(mae), 'rmse': float(rmse), 'r2': float(r2), 'time': elapsed}


def main():
    logger.info("="*80)
    logger.info("COMPARISON: With vs Without Seasonal Features")
    logger.info("="*80)

    data_dir = Path('./data')

    # ===== MODEL 1: WITHOUT seasonal features =====
    logger.info("\n[1/2] Training WITHOUT seasonal features (baseline)...")

    X1, y1, top1 = load_and_prepare_data(data_dir, with_seasonal=False)

    split_idx = int(0.8 * len(X1))
    X1_train, X1_val = X1.iloc[:split_idx], X1.iloc[split_idx:]
    y1_train, y1_val = y1.iloc[:split_idx], y1.iloc[split_idx:]

    model1, scaler1, metrics1 = train_best_config(X1_train, y1_train, X1_val, y1_val)

    # ===== MODEL 2: WITH seasonal features =====
    logger.info("\n[2/2] Training WITH seasonal features...")

    X2, y2, top2 = load_and_prepare_data(data_dir, with_seasonal=True)

    split_idx = int(0.8 * len(X2))
    X2_train, X2_val = X2.iloc[:split_idx], X2.iloc[split_idx:]
    y2_train, y2_val = y2.iloc[:split_idx], y2.iloc[split_idx:]

    model2, scaler2, metrics2 = train_best_config(X2_train, y2_train, X2_val, y2_val)

    # ===== COMPARISON =====
    logger.info("\n" + "="*80)
    logger.info("RESULTS COMPARISON")
    logger.info("="*80)

    print("\n")
    print("="*80)
    print("MODEL COMPARISON: Baseline vs With Seasonal Features")
    print("="*80)
    print()
    print(f"{'Metric':<20} {'Baseline':<15} {'With Seasonal':<15} {'Improvement':<15}")
    print("-"*80)
    print(f"{'Features':<20} {X1.shape[1]:<15} {X2.shape[1]:<15} {f'+{X2.shape[1] - X1.shape[1]}':<15}")
    print(f"{'MAE':<20} {metrics1['mae']:<15.2f} {metrics2['mae']:<15.2f} {(metrics1['mae'] - metrics2['mae']):<15.2f}")
    print(f"{'RMSE':<20} {metrics1['rmse']:<15.2f} {metrics2['rmse']:<15.2f} {(metrics1['rmse'] - metrics2['rmse']):<15.2f}")
    print(f"{'R²':<20} {metrics1['r2']:<15.4f} {metrics2['r2']:<15.4f} {(metrics2['r2'] - metrics1['r2']):<15.4f}")
    print(f"{'Time (s)':<20} {metrics1['time']:<15.1f} {metrics2['time']:<15.1f} {(metrics2['time'] - metrics1['time']):<15.1f}")
    print("="*80)

    # Calculate improvement
    mae_improvement = (metrics1['mae'] - metrics2['mae']) / metrics1['mae'] * 100
    r2_improvement = (metrics2['r2'] - metrics1['r2']) / metrics1['r2'] * 100

    print()
    print(f"MAE improvement: {mae_improvement:+.2f}%")
    print(f"R² improvement: {r2_improvement:+.2f}%")
    print()

    if mae_improvement > 0.5:
        print("✅ SEASONAL FEATURES ПОМОГЛИ!")
        print(f"   Улучшение MAE на {mae_improvement:.2f}% - это ЗНАЧИМО")
    else:
        print("⚠️ SEASONAL FEATURES дали минимальное улучшение")
        print(f"   Улучшение MAE на {mae_improvement:.2f}% - незначительно")

    # Save best model
    if metrics2['mae'] < metrics1['mae']:
        logger.info("\n✓ Saving model WITH seasonal features as best...")

        with open('best_model_with_seasonal.pkl', 'wb') as f:
            pickle.dump({
                'model': model2,
                'scaler': scaler2,
                'metrics': metrics2,
                'features': list(X2.columns),
                'top_features': top2,
                'has_seasonal': True
            }, f)

        logger.info("✓ Saved: best_model_with_seasonal.pkl")
    else:
        logger.info("\n✓ Baseline model is still better")

    # Save comparison results
    comparison = {
        'baseline': {
            'features': X1.shape[1],
            'metrics': metrics1
        },
        'with_seasonal': {
            'features': X2.shape[1],
            'metrics': metrics2
        },
        'improvement': {
            'mae_pct': float(mae_improvement),
            'r2_pct': float(r2_improvement),
            'mae_abs': float(metrics1['mae'] - metrics2['mae'])
        }
    }

    with open('seasonal_comparison_results.json', 'w') as f:
        json.dump(comparison, f, indent=2)

    logger.info("✓ Saved: seasonal_comparison_results.json")


if __name__ == '__main__':
    main()
