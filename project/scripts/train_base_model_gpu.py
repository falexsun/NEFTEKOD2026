#!/usr/bin/env python3
"""
Remote GPU Training на A100
Массовое обучение базовых моделей для выбора архитектуры
"""

import sys
from pathlib import Path
import logging
import json
import time
from typing import Dict, List, Any
import pickle

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from catboost import CatBoostRegressor, Pool
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseModelSelector:
    """Массовый поиск лучшей базовой архитектуры на GPU"""

    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self.results = []

    def get_extensive_configs(self) -> List[Dict[str, Any]]:
        """Большой grid для поиска базовой модели"""
        configs = []

        # CatBoost - МНОГО конфигураций
        for iterations in [500, 1000, 2000, 3000]:
            for depth in [4, 6, 8, 10]:
                for lr in [0.01, 0.03, 0.05, 0.1, 0.15]:
                    for l2 in [1, 3, 5, 7, 10]:
                        for bootstrap in ['Bayesian', 'Bernoulli', 'MVS']:
                            configs.append({
                                'type': 'catboost',
                                'name': f'cb_i{iterations}_d{depth}_lr{lr}_l2{l2}_{bootstrap}',
                                'params': {
                                    'iterations': iterations,
                                    'learning_rate': lr,
                                    'depth': depth,
                                    'l2_leaf_reg': l2,
                                    'bootstrap_type': bootstrap,
                                    'task_type': 'GPU',
                                    'devices': '0',
                                    'loss_function': 'RMSE',
                                    'eval_metric': 'MAE',
                                    'random_seed': 42,
                                    'verbose': False,
                                    'early_stopping_rounds': 100
                                }
                            })

        # LightGBM
        for n_est in [500, 1000, 2000, 3000]:
            for leaves in [15, 31, 63, 127]:
                for lr in [0.01, 0.03, 0.05, 0.1]:
                    for depth in [-1, 8, 10, 12]:
                        configs.append({
                            'type': 'lightgbm',
                            'name': f'lgbm_n{n_est}_l{leaves}_lr{lr}_d{depth}',
                            'params': {
                                'n_estimators': n_est,
                                'learning_rate': lr,
                                'num_leaves': leaves,
                                'max_depth': depth,
                                'min_child_samples': 20,
                                'subsample': 0.8,
                                'colsample_bytree': 0.8,
                                'reg_alpha': 0.1,
                                'reg_lambda': 0.1,
                                'random_state': 42,
                                'device': 'gpu',
                                'gpu_platform_id': 0,
                                'gpu_device_id': 0,
                                'verbosity': -1
                            }
                        })

        # XGBoost
        for n_est in [500, 1000, 2000, 3000]:
            for depth in [4, 6, 8, 10, 12]:
                for lr in [0.01, 0.03, 0.05, 0.1]:
                    for gamma in [0, 0.1, 0.5, 1.0]:
                        configs.append({
                            'type': 'xgboost',
                            'name': f'xgb_n{n_est}_d{depth}_lr{lr}_g{gamma}',
                            'params': {
                                'n_estimators': n_est,
                                'learning_rate': lr,
                                'max_depth': depth,
                                'gamma': gamma,
                                'min_child_weight': 1,
                                'subsample': 0.8,
                                'colsample_bytree': 0.8,
                                'reg_alpha': 0.1,
                                'reg_lambda': 1,
                                'random_state': 42,
                                'tree_method': 'gpu_hist',
                                'gpu_id': 0,
                                'verbosity': 0
                            }
                        })

        logger.info(f"Generated {len(configs)} configurations for extensive search")
        return configs

    def train_single(self, config: Dict, X_train, y_train, X_val, y_val, scaler):
        """Обучает одну конфигурацию"""
        start = time.time()

        try:
            # Scaling
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)

            # Создание модели
            if config['type'] == 'catboost':
                model = CatBoostRegressor(**config['params'])
                train_pool = Pool(X_train_scaled, y_train)
                val_pool = Pool(X_val_scaled, y_val)
                model.fit(train_pool, eval_set=val_pool, verbose=False)
            elif config['type'] == 'lightgbm':
                model = LGBMRegressor(**config['params'])
                model.fit(X_train_scaled, y_train,
                         eval_set=[(X_val_scaled, y_val)],
                         callbacks=[])
            else:  # xgboost
                model = XGBRegressor(**config['params'])
                model.fit(X_train_scaled, y_train,
                         eval_set=[(X_val_scaled, y_val)],
                         verbose=False)

            # Оценка
            y_pred = model.predict(X_val_scaled)
            mae = mean_absolute_error(y_val, y_pred)
            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            r2 = r2_score(y_val, y_pred)

            elapsed = time.time() - start

            result = {
                'name': config['name'],
                'type': config['type'],
                'params': config['params'],
                'metrics': {
                    'mae': float(mae),
                    'rmse': float(rmse),
                    'r2': float(r2)
                },
                'time': float(elapsed),
                'success': True
            }

            logger.info(f"✓ {config['name']}: MAE={mae:.2f}, R²={r2:.4f}, {elapsed:.1f}s")
            return result, model, scaler

        except Exception as e:
            logger.error(f"✗ {config['name']}: {e}")
            return {
                'name': config['name'],
                'type': config['type'],
                'success': False,
                'error': str(e)
            }, None, None

    def find_best_base_model(self, X_train, y_train, X_val, y_val, max_models: int = 100):
        """Ищет лучшую базовую модель"""
        logger.info(f"Starting extensive search for base model (max {max_models} configs)")

        configs = self.get_extensive_configs()[:max_models]

        results = []
        best_mae = float('inf')
        best_model = None
        best_scaler = None
        best_config = None

        for i, config in enumerate(configs, 1):
            logger.info(f"\n[{i}/{len(configs)}] Training {config['name']}...")

            scaler = RobustScaler()
            result, model, scaler_fitted = self.train_single(
                config, X_train, y_train, X_val, y_val, scaler
            )

            results.append(result)

            if result['success'] and result['metrics']['mae'] < best_mae:
                best_mae = result['metrics']['mae']
                best_model = model
                best_scaler = scaler_fitted
                best_config = config
                logger.info(f"🏆 NEW BEST: {config['name']} with MAE={best_mae:.2f}")

            # Сохраняем промежуточные результаты каждые 10 моделей
            if i % 10 == 0:
                self._save_checkpoint(results, best_config, i)

        # Финальное сохранение
        results_sorted = sorted([r for r in results if r['success']],
                               key=lambda x: x['metrics']['mae'])

        return {
            'best_model': best_model,
            'best_scaler': best_scaler,
            'best_config': best_config,
            'all_results': results_sorted,
            'total_trained': len([r for r in results if r['success']]),
            'total_failed': len([r for r in results if not r['success']])
        }

    def _save_checkpoint(self, results, best_config, iteration):
        """Сохраняет промежуточные результаты"""
        checkpoint = {
            'iteration': iteration,
            'results': results,
            'best_config': best_config,
            'timestamp': time.time()
        }

        with open(f'checkpoint_iter_{iteration}.json', 'w') as f:
            json.dump(checkpoint, f, indent=2)

        logger.info(f"Checkpoint saved: iteration {iteration}")


def main():
    logger.info("="*80)
    logger.info("MASSIVE BASE MODEL SEARCH ON GPU A100")
    logger.info("="*80)

    # Параметры
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-models', type=int, default=100,
                       help='Maximum models to train')
    parser.add_argument('--data-path', type=str,
                       default='/home/faizov/projects/NEFTECODE2026/data')
    args = parser.parse_args()

    # Загрузка данных (предполагаем что уже подготовлены)
    logger.info(f"Loading data from {args.data_path}")

    # Здесь нужно адаптировать под вашу структуру данных на сервере
    # X_train = pd.read_parquet(f'{args.data_path}/X_train.parquet')
    # y_train = pd.read_parquet(f'{args.data_path}/y_train.parquet')
    # X_val = pd.read_parquet(f'{args.data_path}/X_val.parquet')
    # y_val = pd.read_parquet(f'{args.data_path}/y_val.parquet')

    # Для демо - генерируем данные
    np.random.seed(42)
    n_train, n_val = 100000, 20000
    n_features = 50

    X_train = pd.DataFrame(np.random.randn(n_train, n_features))
    y_train = pd.Series(X_train.iloc[:, 0] * 2 + np.random.randn(n_train) * 0.1)

    X_val = pd.DataFrame(np.random.randn(n_val, n_features))
    y_val = pd.Series(X_val.iloc[:, 0] * 2 + np.random.randn(n_val) * 0.1)

    logger.info(f"Train: {X_train.shape}, Val: {X_val.shape}")

    # Поиск
    selector = BaseModelSelector(use_gpu=True)
    result = selector.find_best_base_model(
        X_train, y_train, X_val, y_val,
        max_models=args.max_models
    )

    # Результаты
    logger.info("\n" + "="*80)
    logger.info("SEARCH COMPLETE")
    logger.info("="*80)
    logger.info(f"Total trained: {result['total_trained']}")
    logger.info(f"Total failed: {result['total_failed']}")
    logger.info(f"\nBest model: {result['best_config']['name']}")
    logger.info(f"MAE: {result['all_results'][0]['metrics']['mae']:.2f}")
    logger.info(f"R²: {result['all_results'][0]['metrics']['r2']:.4f}")

    # Сохранение
    with open('base_model_search_results.json', 'w') as f:
        json.dump({
            'best_config': result['best_config'],
            'top_10': result['all_results'][:10],
            'all_results': result['all_results']
        }, f, indent=2)

    with open('best_base_model.pkl', 'wb') as f:
        pickle.dump({
            'model': result['best_model'],
            'scaler': result['best_scaler'],
            'config': result['best_config']
        }, f)

    logger.info("\n✓ Results saved:")
    logger.info("  - base_model_search_results.json")
    logger.info("  - best_base_model.pkl")


if __name__ == '__main__':
    main()
