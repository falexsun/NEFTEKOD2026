#!/usr/bin/env python3
"""
Incremental Learning System
Дообучение модели при поступлении новых LIMS данных
"""

import sys
from pathlib import Path
import logging
import pickle
import time
from typing import Dict, Any, Optional
from datetime import datetime
import json

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from catboost import CatBoostRegressor, Pool
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IncrementalLearner:
    """
    Инкрементальное обучение на новых LIMS данных

    Workflow:
    1. База обучена на исторических данных
    2. Приходят новые LIMS результаты
    3. Дообучаем модель (warm start)
    4. Валидируем улучшение
    5. Если лучше - сохраняем новую версию
    """

    def __init__(self,
                 base_model_path: str,
                 redis_host: str = 'localhost',
                 redis_port: int = 6379):
        self.base_model_path = Path(base_model_path)
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

        # Загрузка базовой модели
        self.load_base_model()

        # История обучения
        self.training_history = []

    def load_base_model(self):
        """Загружает базовую модель"""
        logger.info(f"Loading base model from {self.base_model_path}")

        with open(self.base_model_path, 'rb') as f:
            data = pickle.load(f)

        self.base_model = data['model']
        self.base_scaler = data['scaler']
        self.base_config = data.get('config', {})
        self.base_metrics = data.get('metrics', {})

        logger.info(f"Base model loaded: {self.base_config.get('name', 'unknown')}")
        logger.info(f"Base MAE: {self.base_metrics.get('mae', 'N/A')}")

        # Текущая модель (начинаем с базовой)
        self.current_model = self.base_model
        self.current_scaler = self.base_scaler
        self.current_metrics = self.base_metrics.copy()

    def check_for_new_lims_data(self) -> Optional[pd.DataFrame]:
        """
        Проверяет Redis на новые LIMS данные

        Формат в Redis:
        - Key: "lims:new_data"
        - Value: JSON с массивом записей
        """
        try:
            data_json = self.redis_client.get('lims:new_data')

            if data_json:
                data = json.loads(data_json)
                df = pd.DataFrame(data)

                logger.info(f"Found {len(df)} new LIMS records")

                # Очищаем ключ после чтения
                self.redis_client.delete('lims:new_data')

                return df
            else:
                return None

        except Exception as e:
            logger.error(f"Error checking Redis: {e}")
            return None

    def prepare_incremental_data(self,
                                 lims_df: pd.DataFrame,
                                 features_df: pd.DataFrame) -> tuple:
        """
        Подготавливает данные для дообучения

        Args:
            lims_df: Новые LIMS результаты (с timestamp и quality metrics)
            features_df: Признаки (процессные данные)

        Returns:
            X, y для дообучения
        """
        # Мерджим по времени
        lims_df['timestamp'] = pd.to_datetime(lims_df['timestamp'])
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])

        # Join с допуском ±5 минут
        merged = pd.merge_asof(
            lims_df.sort_values('timestamp'),
            features_df.sort_values('timestamp'),
            on='timestamp',
            tolerance=pd.Timedelta('5min'),
            direction='backward'
        )

        # Target из LIMS (например, сера)
        if 'sulfur_ppm' in merged.columns:
            y = merged['sulfur_ppm']
        elif 'density' in merged.columns:
            y = merged['density']
        else:
            # Fallback - первая числовая колонка из LIMS
            lims_cols = [col for col in lims_df.columns if col != 'timestamp']
            y = merged[lims_cols[0]]

        # Признаки (только из features_df)
        feature_cols = [col for col in features_df.columns if col != 'timestamp']
        X = merged[feature_cols]

        # Очистка
        valid_idx = X.notna().all(axis=1) & y.notna()
        X = X[valid_idx]
        y = y[valid_idx]

        logger.info(f"Prepared {len(X)} samples for incremental training")

        return X, y

    def incremental_train(self,
                         X_new: pd.DataFrame,
                         y_new: pd.Series,
                         iterations: int = 100) -> Dict[str, Any]:
        """
        Дообучает модель на новых данных

        CatBoost поддерживает warm start через init_model
        """
        logger.info(f"Starting incremental training on {len(X_new)} samples...")
        start = time.time()

        # Scaling с тем же scaler
        X_scaled = self.current_scaler.transform(X_new)

        # Создаем новую модель с теми же параметрами
        params = self.base_config.get('params', {}).copy()
        params['iterations'] = iterations
        params['verbose'] = False

        new_model = CatBoostRegressor(**params)

        # Train с warm start от текущей модели
        train_pool = Pool(X_scaled, y_new)

        new_model.fit(
            train_pool,
            init_model=self.current_model,  # Warm start!
            verbose=False
        )

        # Оценка на новых данных (cross-validation would be better)
        y_pred = new_model.predict(X_scaled)

        mae = mean_absolute_error(y_new, y_pred)
        rmse = np.sqrt(mean_squared_error(y_new, y_pred))
        r2 = r2_score(y_new, y_pred)

        elapsed = time.time() - start

        result = {
            'mae': float(mae),
            'rmse': float(rmse),
            'r2': float(r2),
            'n_samples': len(X_new),
            'iterations': iterations,
            'time': elapsed,
            'timestamp': datetime.now().isoformat()
        }

        logger.info(f"✓ Incremental training complete: MAE={mae:.2f}, R²={r2:.4f}, {elapsed:.1f}s")

        return result, new_model

    def validate_improvement(self,
                            new_metrics: Dict[str, float],
                            threshold: float = 0.02) -> bool:
        """
        Проверяет улучшилась ли модель

        Args:
            new_metrics: Метрики новой модели
            threshold: Минимальное улучшение MAE (относительное)

        Returns:
            True если модель улучшилась достаточно
        """
        old_mae = self.current_metrics.get('mae', float('inf'))
        new_mae = new_metrics['mae']

        improvement = (old_mae - new_mae) / old_mae

        logger.info(f"Old MAE: {old_mae:.2f}, New MAE: {new_mae:.2f}")
        logger.info(f"Improvement: {improvement*100:.2f}%")

        if improvement >= threshold:
            logger.info(f"✓ Improvement sufficient ({improvement*100:.1f}% >= {threshold*100:.1f}%)")
            return True
        else:
            logger.warning(f"✗ Improvement insufficient ({improvement*100:.1f}% < {threshold*100:.1f}%)")
            return False

    def update_model(self, new_model, new_metrics: Dict):
        """Обновляет текущую модель"""
        self.current_model = new_model
        self.current_metrics = new_metrics

        # Сохраняем в историю
        self.training_history.append({
            'timestamp': datetime.now().isoformat(),
            'metrics': new_metrics,
            'improvement': (self.base_metrics.get('mae', 0) - new_metrics['mae']) / self.base_metrics.get('mae', 1)
        })

        logger.info("✓ Model updated")

    def save_checkpoint(self, path: Optional[Path] = None):
        """Сохраняет чекпоинт текущей модели"""
        if path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = Path(f'model_checkpoint_{timestamp}.pkl')

        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.current_model,
                'scaler': self.current_scaler,
                'config': self.base_config,
                'metrics': self.current_metrics,
                'training_history': self.training_history,
                'base_metrics': self.base_metrics
            }, f)

        logger.info(f"✓ Checkpoint saved: {path}")

        return path

    def run_continuous_learning(self,
                               features_df: pd.DataFrame,
                               check_interval: int = 60,
                               max_iterations: Optional[int] = None):
        """
        Непрерывный цикл обучения

        Args:
            features_df: DataFrame с процессными данными (с timestamp)
            check_interval: Интервал проверки Redis (секунды)
            max_iterations: Максимальное количество итераций (None = бесконечно)
        """
        logger.info("Starting continuous learning loop...")
        logger.info(f"Check interval: {check_interval}s")

        iteration = 0

        while True:
            iteration += 1

            if max_iterations and iteration > max_iterations:
                logger.info("Max iterations reached")
                break

            # Проверка новых данных
            new_lims = self.check_for_new_lims_data()

            if new_lims is not None and len(new_lims) > 0:
                logger.info(f"\n[Iteration {iteration}] Processing {len(new_lims)} new LIMS records")

                try:
                    # Подготовка
                    X_new, y_new = self.prepare_incremental_data(new_lims, features_df)

                    if len(X_new) < 10:
                        logger.warning("Too few samples for training, skipping")
                        continue

                    # Дообучение
                    new_metrics, new_model = self.incremental_train(X_new, y_new)

                    # Валидация
                    if self.validate_improvement(new_metrics):
                        self.update_model(new_model, new_metrics)

                        # Сохранение каждые 5 обновлений
                        if len(self.training_history) % 5 == 0:
                            self.save_checkpoint()
                    else:
                        logger.info("Model not updated (insufficient improvement)")

                except Exception as e:
                    logger.error(f"Error during incremental training: {e}")

            # Ждем следующей итерации
            time.sleep(check_interval)


def main():
    """Пример использования"""
    import argparse

    parser = argparse.ArgumentParser(description='Incremental Learning System')
    parser.add_argument('--base-model', type=str, required=True,
                       help='Path to base model pickle')
    parser.add_argument('--features', type=str, required=True,
                       help='Path to features parquet/csv')
    parser.add_argument('--redis-host', type=str, default='localhost')
    parser.add_argument('--redis-port', type=int, default=6379)
    parser.add_argument('--interval', type=int, default=60,
                       help='Check interval in seconds')
    parser.add_argument('--mode', choices=['continuous', 'once'], default='once')

    args = parser.parse_args()

    # Инициализация
    learner = IncrementalLearner(
        base_model_path=args.base_model,
        redis_host=args.redis_host,
        redis_port=args.redis_port
    )

    # Загрузка признаков
    if args.features.endswith('.parquet'):
        features_df = pd.read_parquet(args.features)
    else:
        features_df = pd.read_csv(args.features)

    logger.info(f"Features loaded: {features_df.shape}")

    # Запуск
    if args.mode == 'continuous':
        learner.run_continuous_learning(
            features_df=features_df,
            check_interval=args.interval
        )
    else:
        # Однократная проверка
        new_lims = learner.check_for_new_lims_data()

        if new_lims is not None:
            X_new, y_new = learner.prepare_incremental_data(new_lims, features_df)
            new_metrics, new_model = learner.incremental_train(X_new, y_new)

            if learner.validate_improvement(new_metrics):
                learner.update_model(new_model, new_metrics)
                learner.save_checkpoint()
        else:
            logger.info("No new LIMS data available")


if __name__ == '__main__':
    main()
