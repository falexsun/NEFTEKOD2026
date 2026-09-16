#!/usr/bin/env python3
"""
Быстрое обучение моделей для хакатона БЕЗ MLflow
Сохранение в pickle для немедленного использования
"""

import sys
from pathlib import Path
import logging
import pickle
import time
import json
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from catboost import CatBoostRegressor, Pool
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
import lightgbm as lgbm

# Пути
HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(ROOT / 'eda'))

from eda_utils import load_telemetry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def prepare_data():
    """Загрузка и подготовка данных"""
    logger.info("Loading data...")

    data_dir = ROOT / 'data'
    avt = load_telemetry(data_dir / 'avt_tags.csv')
    hydro = load_telemetry(data_dir / '242000_tags.csv')

    # Объединение
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
    ).set_index('date')

    logger.info(f"Combined: {combined.shape}")

    # Target
    target_col = 'H24_F25'
    target = combined[target_col].dropna()

    # Топ 20 коррелирующих признаков
    features_base = combined.drop(columns=[target_col])
    correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
    top_features = correlations.head(20).index.tolist()

    logger.info(f"Top features: {top_features[:5]}...")

    # Feature engineering
    df = combined[top_features + [target_col]].copy()

    # Лаги
    for col in top_features[:10]:
        df[f'{col}_lag_6'] = df[col].shift(6)  # 1 час
        df[f'{col}_lag_12'] = df[col].shift(12)  # 2 часа

    # Rolling
    for col in top_features[:5]:
        df[f'{col}_roll_6'] = df[col].rolling(6, min_periods=1).mean()
        df[f'{col}_roll_12'] = df[col].rolling(12, min_periods=1).mean()

    # Очистка
    df = df.dropna(subset=[target_col])
    feature_cols = [col for col in df.columns if col != target_col]
    df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median())
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    X = df[feature_cols]
    y = df[target_col]

    logger.info(f"Final: X={X.shape}, y={y.shape}")
    logger.info(f"Target: mean={y.mean():.2f}, std={y.std():.2f}")

    return X, y, top_features


def train_model(name, model, X_train, y_train, X_val, y_val, scaler):
    """Обучает одну модель"""
    logger.info(f"Training {name}...")
    start = time.time()

    # Scaling
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    # Обучение
    if isinstance(model, CatBoostRegressor):
        train_pool = Pool(X_train_scaled, y_train)
        val_pool = Pool(X_val_scaled, y_val)
        model.fit(train_pool, eval_set=val_pool, verbose=False)
    elif isinstance(model, LGBMRegressor):
        model.fit(
            X_train_scaled, y_train,
            eval_set=[(X_val_scaled, y_val)],
            callbacks=[lgbm.early_stopping(50, verbose=False)]
        )
    else:
        model.fit(
            X_train_scaled, y_train,
            eval_set=[(X_val_scaled, y_val)],
            verbose=False
        )

    # Оценка
    y_pred = model.predict(X_val_scaled)
    mae = mean_absolute_error(y_val, y_pred)
    rmse = np.sqrt(mean_squared_error(y_val, y_pred))
    r2 = r2_score(y_val, y_pred)

    elapsed = time.time() - start

    logger.info(f"✓ {name}: MAE={mae:.2f}, RMSE={rmse:.2f}, R²={r2:.4f}, time={elapsed:.1f}s")

    return {
        'name': name,
        'model': model,
        'scaler': scaler,
        'metrics': {'mae': mae, 'rmse': rmse, 'r2': r2},
        'time': elapsed
    }


def main():
    logger.info("="*80)
    logger.info("FAST TRAINING FOR HACKATHON")
    logger.info("="*80)

    # Данные
    X, y, top_features = prepare_data()

    # Split
    split_idx = int(0.8 * len(X))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    logger.info(f"\nTrain: {X_train.shape}, Val: {X_val.shape}")

    # Модели
    models = [
        ('catboost_fast', CatBoostRegressor(
            iterations=500, learning_rate=0.1, depth=6,
            task_type='CPU', verbose=False, random_seed=42
        )),
        ('catboost_deep', CatBoostRegressor(
            iterations=1000, learning_rate=0.05, depth=8,
            task_type='CPU', verbose=False, random_seed=42
        )),
        ('lightgbm_fast', LGBMRegressor(
            n_estimators=500, learning_rate=0.1, num_leaves=31,
            random_state=42, verbosity=-1
        )),
        ('lightgbm_deep', LGBMRegressor(
            n_estimators=1000, learning_rate=0.05, num_leaves=63,
            random_state=42, verbosity=-1
        )),
        ('xgboost_fast', XGBRegressor(
            n_estimators=500, learning_rate=0.1, max_depth=6,
            random_state=42, verbosity=0
        )),
        ('xgboost_deep', XGBRegressor(
            n_estimators=1000, learning_rate=0.05, max_depth=8,
            random_state=42, verbosity=0
        )),
    ]

    # Обучение
    results = []
    for name, model in models:
        scaler = RobustScaler()
        result = train_model(name, model, X_train, y_train, X_val, y_val, scaler)
        results.append(result)

    # Сортировка
    results.sort(key=lambda x: x['metrics']['mae'])

    # Лучшая модель
    best = results[0]

    logger.info("\n" + "="*80)
    logger.info("TOP 3 MODELS:")
    for i, r in enumerate(results[:3], 1):
        logger.info(f"{i}. {r['name']}: MAE={r['metrics']['mae']:.2f}, "
                   f"R²={r['metrics']['r2']:.4f}")

    logger.info("\n" + "="*80)
    logger.info(f"BEST MODEL: {best['name']}")
    logger.info(f"MAE: {best['metrics']['mae']:.2f}")
    logger.info(f"RMSE: {best['metrics']['rmse']:.2f}")
    logger.info(f"R²: {best['metrics']['r2']:.4f}")

    # Сохранение
    models_dir = PROJECT_ROOT / 'models'
    models_dir.mkdir(exist_ok=True)

    # Сохраняем лучшую
    best_path = models_dir / 'best_model.pkl'
    with open(best_path, 'wb') as f:
        pickle.dump({
            'model': best['model'],
            'scaler': best['scaler'],
            'metrics': best['metrics'],
            'name': best['name'],
            'features': list(X.columns),
            'top_features': top_features
        }, f)

    logger.info(f"\n✓ Best model saved: {best_path}")

    # Сохраняем все
    all_path = models_dir / 'all_models.pkl'
    with open(all_path, 'wb') as f:
        pickle.dump(results, f)

    logger.info(f"✓ All models saved: {all_path}")

    # Метаданные
    meta = {
        'best_model': best['name'],
        'best_mae': float(best['metrics']['mae']),
        'best_r2': float(best['metrics']['r2']),
        'n_features': len(X.columns),
        'n_train': len(X_train),
        'n_val': len(X_val),
        'top_features': top_features,
        'all_results': [
            {
                'name': r['name'],
                'mae': float(r['metrics']['mae']),
                'rmse': float(r['metrics']['rmse']),
                'r2': float(r['metrics']['r2']),
                'time': float(r['time'])
            }
            for r in results
        ]
    }

    meta_path = models_dir / 'training_results.json'
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    logger.info(f"✓ Metadata saved: {meta_path}")

    logger.info("\n" + "="*80)
    logger.info("✓ TRAINING COMPLETE!")
    logger.info("="*80)
    logger.info(f"\nTo use best model:")
    logger.info(f"  import pickle")
    logger.info(f"  with open('{best_path}', 'rb') as f:")
    logger.info(f"      model_data = pickle.load(f)")
    logger.info(f"  predictions = model_data['model'].predict(model_data['scaler'].transform(X))")


if __name__ == '__main__':
    main()
