#!/usr/bin/env python3
"""
РАСШИРЕННОЕ ОБУЧЕНИЕ НА A100 GPU
- Добавление interaction features (AVT_T42×H24_P8, H24_F15×H24_T11)
- Массовый grid search (100+ конфигураций)
- Ансамблирование (voting, stacking)
- Полиномиальные признаки для топ-параметров
"""

import sys
from pathlib import Path
import logging
import time
import json
import pickle
from typing import Dict, List, Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Device detection
try:
    from catboost import CatBoostRegressor, Pool
    import lightgbm as lgb
    import xgboost as xgb

    # Check GPU
    import subprocess
    result = subprocess.run(['nvidia-smi'], capture_output=True)
    GPU_AVAILABLE = result.returncode == 0
    logger.info(f"🎮 GPU Available: {GPU_AVAILABLE}")
except Exception as e:
    GPU_AVAILABLE = False
    logger.warning(f"GPU check failed: {e}")


def load_and_prepare_data(data_dir: Path):
    """Загрузка и подготовка данных"""
    logger.info("="*80)
    logger.info("📊 ЗАГРУЗКА ДАННЫХ")
    logger.info("="*80)

    avt = pd.read_csv(data_dir / 'avt_tags.csv')
    hydro = pd.read_csv(data_dir / '242000_tags.csv')

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
    ).set_index('date')

    logger.info(f"✓ Загружено: {combined.shape[0]:,} записей, {combined.shape[1]} параметров")

    return combined


def engineer_features(combined: pd.DataFrame, target_col: str = 'H24_F25'):
    """Feature engineering с interaction и polynomial features"""
    logger.info("\n" + "="*80)
    logger.info("⚙️ FEATURE ENGINEERING")
    logger.info("="*80)

    df = combined.copy()
    target = df[target_col].dropna()

    # Базовые признаки - топ по корреляции
    features_base = df.drop(columns=[target_col])
    correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
    top_features = correlations.head(20).index.tolist()

    logger.info(f"✓ Топ-20 базовых признаков выбрано")

    # === INTERACTION FEATURES (из анализа) ===
    logger.info("\n📊 Добавление interaction features:")

    if 'AVT_T42' in df.columns and 'H24_P8' in df.columns:
        df['AVT_T42_x_H24_P8'] = df['AVT_T42'] * df['H24_P8']
        top_features.append('AVT_T42_x_H24_P8')
        logger.info("  ✓ AVT_T42 × H24_P8 (temp-pressure coupling, ρ=0.8400)")

    if 'H24_F15' in df.columns and 'H24_T11' in df.columns:
        df['H24_F15_x_H24_T11'] = df['H24_F15'] * df['H24_T11']
        top_features.append('H24_F15_x_H24_T11')
        logger.info("  ✓ H24_F15 × H24_T11 (flow-temp interaction, ρ=0.9009)")

    # === POLYNOMIAL FEATURES (квадраты топ-5) ===
    logger.info("\n📈 Добавление полиномиальных признаков:")

    for param in correlations.head(5).index:
        if param in df.columns and param != target_col:
            squared_name = f'{param}_squared'
            df[squared_name] = df[param] ** 2
            top_features.append(squared_name)
            logger.info(f"  ✓ {param}²")

    # === LAG FEATURES ===
    logger.info("\n⏱️ Добавление lag features:")

    for param in correlations.head(10).index:
        if param not in df.columns:
            continue

        for lag in [6, 12]:
            lag_name = f'{param}_lag{lag}'
            df[lag_name] = df[param].shift(lag)
            top_features.append(lag_name)

    logger.info(f"  ✓ Лаги 6, 12 для топ-10 параметров")

    # === ROLLING MEANS ===
    logger.info("\n📊 Добавление rolling statistics:")

    for param in correlations.head(5).index:
        if param not in df.columns:
            continue

        roll_name = f'{param}_roll6'
        df[roll_name] = df[param].rolling(window=6, min_periods=1).mean()
        top_features.append(roll_name)

    logger.info(f"  ✓ Rolling mean (6) для топ-5")

    # Final dataset
    feature_cols = [f for f in top_features if f in df.columns]
    final_df = df[feature_cols + [target_col]].dropna()

    logger.info(f"\n✅ ИТОГО: {len(feature_cols)} признаков")
    logger.info(f"   • Базовые: 20")
    logger.info(f"   • Interactions: 2")
    logger.info(f"   • Polynomial: 5")
    logger.info(f"   • Lags: 20")
    logger.info(f"   • Rolling: 5")
    logger.info(f"   • Записей: {len(final_df):,}")

    return final_df, feature_cols, target_col


def massive_grid_search(X_train, y_train, X_val, y_val, device='GPU'):
    """Массовый grid search - 100+ конфигураций"""
    logger.info("\n" + "="*80)
    logger.info("🔍 MASSIVE GRID SEARCH (100+ configs)")
    logger.info("="*80)

    results = []

    # CatBoost configurations
    catboost_configs = []

    for iterations in [500, 1000, 2000]:
        for depth in [6, 8, 10]:
            for lr in [0.01, 0.03, 0.05, 0.1]:
                for l2 in [1, 3, 5, 10]:
                    catboost_configs.append({
                        'iterations': iterations,
                        'depth': depth,
                        'learning_rate': lr,
                        'l2_leaf_reg': l2
                    })

    logger.info(f"📦 CatBoost: {len(catboost_configs)} конфигураций")

    # Train all CatBoost models
    for i, config in enumerate(catboost_configs, 1):
        try:
            model = CatBoostRegressor(
                task_type=device,
                devices='0' if device == 'GPU' else None,
                loss_function='RMSE',
                random_seed=42,
                verbose=False,
                **config
            )

            start = time.time()
            train_pool = Pool(X_train, y_train)
            val_pool = Pool(X_val, y_val)
            model.fit(train_pool, eval_set=val_pool, verbose=False)
            elapsed = time.time() - start

            y_pred = model.predict(X_val)
            mae = mean_absolute_error(y_val, y_pred)
            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            r2 = r2_score(y_val, y_pred)

            result = {
                'model_type': 'CatBoost',
                'config': config,
                'mae': float(mae),
                'rmse': float(rmse),
                'r2': float(r2),
                'time': float(elapsed),
                'model_object': model
            }

            results.append(result)

            if i % 10 == 0:
                logger.info(f"  [{i}/{len(catboost_configs)}] Best MAE so far: {min(r['mae'] for r in results):.2f}")

        except Exception as e:
            logger.warning(f"  ❌ Config {i} failed: {e}")
            continue

    # LightGBM configurations
    lgb_configs = []

    for n_estimators in [500, 1000, 2000]:
        for max_depth in [6, 8, 10]:
            for lr in [0.01, 0.03, 0.05]:
                for num_leaves in [31, 63, 127]:
                    lgb_configs.append({
                        'n_estimators': n_estimators,
                        'max_depth': max_depth,
                        'learning_rate': lr,
                        'num_leaves': num_leaves
                    })

    logger.info(f"\n📦 LightGBM: {len(lgb_configs)} конфигураций")

    for i, config in enumerate(lgb_configs, 1):
        try:
            model = lgb.LGBMRegressor(
                device='gpu' if device == 'GPU' and GPU_AVAILABLE else 'cpu',
                random_state=42,
                verbose=-1,
                **config
            )

            start = time.time()
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(50, verbose=False)])
            elapsed = time.time() - start

            y_pred = model.predict(X_val)
            mae = mean_absolute_error(y_val, y_pred)
            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            r2 = r2_score(y_val, y_pred)

            result = {
                'model_type': 'LightGBM',
                'config': config,
                'mae': float(mae),
                'rmse': float(rmse),
                'r2': float(r2),
                'time': float(elapsed),
                'model_object': model
            }

            results.append(result)

            if i % 10 == 0:
                logger.info(f"  [{i}/{len(lgb_configs)}] Best MAE so far: {min(r['mae'] for r in results):.2f}")

        except Exception as e:
            logger.warning(f"  ❌ LGB config {i} failed: {e}")
            continue

    # Sort by MAE
    results_sorted = sorted(results, key=lambda x: x['mae'])

    logger.info(f"\n✅ GRID SEARCH ЗАВЕРШЕН")
    logger.info(f"   • Всего обучено: {len(results)} моделей")
    logger.info(f"   • Лучшая MAE: {results_sorted[0]['mae']:.2f}")
    logger.info(f"   • Лучшая модель: {results_sorted[0]['model_type']}")

    return results_sorted


def create_ensemble(top_models: List[Dict], X_val, y_val):
    """Создание ансамбля из лучших моделей"""
    logger.info("\n" + "="*80)
    logger.info("🎭 ENSEMBLE MODELS")
    logger.info("="*80)

    # Simple voting ensemble
    logger.info("\n1️⃣ Simple Voting Ensemble (топ-5 моделей)")

    predictions = []
    for model_result in top_models[:5]:
        model = model_result['model_object']
        y_pred = model.predict(X_val)
        predictions.append(y_pred)

    # Average
    y_pred_avg = np.mean(predictions, axis=0)
    mae_avg = mean_absolute_error(y_val, y_pred_avg)
    rmse_avg = np.sqrt(mean_squared_error(y_val, y_pred_avg))
    r2_avg = r2_score(y_val, y_pred_avg)

    logger.info(f"   MAE: {mae_avg:.2f}")
    logger.info(f"   RMSE: {rmse_avg:.2f}")
    logger.info(f"   R²: {r2_avg:.4f}")

    # Weighted voting
    logger.info("\n2️⃣ Weighted Voting (веса по 1/MAE)")

    weights = [1 / model_result['mae'] for model_result in top_models[:5]]
    weights = np.array(weights) / sum(weights)

    y_pred_weighted = np.average(predictions, axis=0, weights=weights)
    mae_weighted = mean_absolute_error(y_val, y_pred_weighted)
    rmse_weighted = np.sqrt(mean_squared_error(y_val, y_pred_weighted))
    r2_weighted = r2_score(y_val, y_pred_weighted)

    logger.info(f"   MAE: {mae_weighted:.2f}")
    logger.info(f"   RMSE: {rmse_weighted:.2f}")
    logger.info(f"   R²: {r2_weighted:.4f}")

    ensemble_results = {
        'simple_voting': {
            'mae': float(mae_avg),
            'rmse': float(rmse_avg),
            'r2': float(r2_avg),
            'n_models': 5
        },
        'weighted_voting': {
            'mae': float(mae_weighted),
            'rmse': float(rmse_weighted),
            'r2': float(r2_weighted),
            'weights': weights.tolist()
        }
    }

    return ensemble_results, y_pred_weighted


def main():
    logger.info("="*80)
    logger.info("🚀 РАСШИРЕННОЕ ОБУЧЕНИЕ НА A100 GPU")
    logger.info("="*80)

    # Paths
    data_dir = Path('../data')
    models_dir = Path('../project/models')
    models_dir.mkdir(exist_ok=True)

    # Load data
    combined = load_and_prepare_data(data_dir)

    # Feature engineering
    df, feature_cols, target_col = engineer_features(combined)

    X = df[feature_cols]
    y = df[target_col]

    # Time-based split
    split_idx = int(0.8 * len(X))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    # Scaling
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    logger.info(f"\n📊 Dataset Split:")
    logger.info(f"   Train: {len(X_train):,} записей")
    logger.info(f"   Val: {len(X_val):,} записей")
    logger.info(f"   Features: {len(feature_cols)}")

    # Device
    device = 'GPU' if GPU_AVAILABLE else 'CPU'
    logger.info(f"\n🎮 Device: {device}")

    # === MASSIVE GRID SEARCH ===
    start_total = time.time()
    results = massive_grid_search(X_train_scaled, y_train, X_val_scaled, y_val, device=device)

    # === ENSEMBLE ===
    ensemble_results, y_pred_ensemble = create_ensemble(results, X_val_scaled, y_val)

    total_time = time.time() - start_total

    # === ИТОГОВЫЙ ОТЧЕТ ===
    logger.info("\n" + "="*80)
    logger.info("📊 ИТОГОВЫЙ ОТЧЕТ")
    logger.info("="*80)

    logger.info(f"\n🏆 ТОП-10 МОДЕЛЕЙ:")
    logger.info("-"*80)
    logger.info(f"{'#':<4} {'Type':<12} {'MAE':<10} {'RMSE':<10} {'R²':<8} {'Time':<8}")
    logger.info("-"*80)

    for i, r in enumerate(results[:10], 1):
        logger.info(f"{i:<4} {r['model_type']:<12} {r['mae']:<10.2f} {r['rmse']:<10.2f} {r['r2']:<8.4f} {r['time']:<8.2f}s")

    logger.info(f"\n🎭 АНСАМБЛИ:")
    logger.info(f"   Simple Voting: MAE={ensemble_results['simple_voting']['mae']:.2f}")
    logger.info(f"   Weighted Voting: MAE={ensemble_results['weighted_voting']['mae']:.2f}")

    logger.info(f"\n⏱️ ОБЩЕЕ ВРЕМЯ: {total_time:.1f}s ({total_time/60:.1f} мин)")
    logger.info(f"   Средняя скорость: {total_time/len(results):.2f}s на модель")

    # Сравнение с baseline
    baseline_mae = 780.10
    best_mae = results[0]['mae']
    improvement = ((baseline_mae - best_mae) / baseline_mae) * 100

    logger.info(f"\n📈 СРАВНЕНИЕ С BASELINE:")
    logger.info(f"   Baseline (без interactions): MAE={baseline_mae:.2f}")
    logger.info(f"   Лучшая новая модель: MAE={best_mae:.2f}")
    logger.info(f"   Улучшение: {improvement:+.2f}%")

    # Save results
    output_data = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'device': device,
        'features': {
            'total': len(feature_cols),
            'interactions': 2,
            'polynomial': 5,
            'lags': 20,
            'rolling': 5
        },
        'top_10_models': [
            {
                'rank': i+1,
                'model_type': r['model_type'],
                'mae': r['mae'],
                'rmse': r['rmse'],
                'r2': r['r2'],
                'time': r['time'],
                'config': r['config']
            }
            for i, r in enumerate(results[:10])
        ],
        'ensemble': ensemble_results,
        'baseline_comparison': {
            'baseline_mae': baseline_mae,
            'new_best_mae': best_mae,
            'improvement_pct': improvement
        },
        'total_time': total_time,
        'total_models_trained': len(results)
    }

    output_path = Path('advanced_training_results.json')
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    logger.info(f"\n✓ Результаты сохранены: {output_path}")

    # Save best model
    best_model = results[0]['model_object']
    best_model_path = models_dir / 'best_advanced_model_a100.pkl'

    with open(best_model_path, 'wb') as f:
        pickle.dump({
            'model': best_model,
            'scaler': scaler,
            'feature_cols': feature_cols,
            'config': results[0]['config'],
            'metrics': {
                'mae': results[0]['mae'],
                'rmse': results[0]['rmse'],
                'r2': results[0]['r2']
            }
        }, f)

    logger.info(f"✓ Лучшая модель сохранена: {best_model_path}")

    # Save ensemble
    ensemble_path = models_dir / 'ensemble_model_a100.pkl'
    with open(ensemble_path, 'wb') as f:
        pickle.dump({
            'top_models': [r['model_object'] for r in results[:5]],
            'weights': ensemble_results['weighted_voting']['weights'],
            'scaler': scaler,
            'feature_cols': feature_cols,
            'metrics': ensemble_results['weighted_voting']
        }, f)

    logger.info(f"✓ Ансамбль сохранен: {ensemble_path}")

    logger.info("\n" + "="*80)
    logger.info("✅ ГОТОВО!")
    logger.info("="*80)


if __name__ == '__main__':
    main()
