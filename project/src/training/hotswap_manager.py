#!/usr/bin/env python3
"""
Hot-Swap Model Manager - Безшовная замена моделей в production
Реализует механизм champion/challenger с atomic swap без downtime
"""

import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import time
import pickle

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    """Метаданные модели"""
    model_id: str
    run_id: str
    model_type: str
    version: int
    loaded_at: datetime
    metrics: Dict[str, float]
    artifact_uri: str
    status: str  # 'champion', 'challenger', 'retired'


class ModelWrapper:
    """Обертка над моделью с preprocessing"""

    def __init__(self, artifacts: Dict[str, Any], metadata: ModelMetadata):
        self.model = artifacts['model']
        self.scaler = artifacts.get('scaler')
        self.config = artifacts.get('config', {})
        self.metadata = metadata
        self._predict_count = 0
        self._total_latency = 0.0
        self._lock = threading.Lock()

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Предикция с препроцессингом"""
        start = time.time()

        try:
            # Preprocessing
            X_processed = X.copy()

            # Log transform если нужно
            if self.config.get('preprocessing') in ['log', 'power']:
                positive_cols = X_processed.columns[X_processed.min() >= 0]
                for col in positive_cols:
                    X_processed[f'{col}_log'] = np.log1p(X_processed[col])

            # Заполнение пропусков
            X_processed = X_processed.fillna(X_processed.median())

            # Scaling
            if self.scaler is not None:
                X_scaled = self.scaler.transform(X_processed.values)
            else:
                X_scaled = X_processed.values

            # Предикция
            predictions = self.model.predict(X_scaled)

            # Статистика
            latency = time.time() - start
            with self._lock:
                self._predict_count += 1
                self._total_latency += latency

            return predictions

        except Exception as e:
            logger.error(f"Prediction error in {self.metadata.model_id}: {e}")
            raise

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику использования"""
        with self._lock:
            avg_latency = self._total_latency / self._predict_count if self._predict_count > 0 else 0
            return {
                'predict_count': self._predict_count,
                'total_latency': self._total_latency,
                'avg_latency_ms': avg_latency * 1000,
                'model_id': self.metadata.model_id,
                'status': self.metadata.status
            }


class HotSwapModelManager:
    """
    Менеджер моделей с hot-swap функционалом

    Основные возможности:
    - Загрузка моделей из MLflow
    - Атомарная замена champion/challenger
    - Shadow mode для A/B тестирования
    - Метрики в реальном времени
    - Автоматический rollback при деградации
    """

    def __init__(self,
                 mlflow_uri: str = "http://localhost:5000",
                 model_registry_name: str = "neftekod_quality",
                 cache_dir: Optional[Path] = None):
        self.mlflow_uri = mlflow_uri
        self.model_registry_name = model_registry_name
        self.cache_dir = cache_dir or Path("./model_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        mlflow.set_tracking_uri(mlflow_uri)

        self._champion: Optional[ModelWrapper] = None
        self._challenger: Optional[ModelWrapper] = None
        self._lock = threading.RLock()
        self._swap_history = []

        logger.info(f"HotSwap Manager initialized: {model_registry_name}")

    def load_model_from_mlflow(self,
                               run_id: str,
                               status: str = 'challenger') -> ModelWrapper:
        """Загружает модель из MLflow"""
        try:
            logger.info(f"Loading model from run {run_id}...")

            # Получаем run info
            client = mlflow.tracking.MlflowClient()
            run = client.get_run(run_id)

            # Загружаем артефакты
            artifact_uri = run.info.artifact_uri
            model_uri = f"runs:/{run_id}/model"

            # Загружаем модель
            artifacts = mlflow.sklearn.load_model(model_uri)

            # Метаданные
            metrics = {k: v for k, v in run.data.metrics.items() if k.startswith('val_')}
            metadata = ModelMetadata(
                model_id=f"{run.data.params.get('model_type', 'unknown')}_{run_id[:8]}",
                run_id=run_id,
                model_type=run.data.params.get('model_type', 'unknown'),
                version=int(time.time()),
                loaded_at=datetime.now(),
                metrics=metrics,
                artifact_uri=artifact_uri,
                status=status
            )

            wrapper = ModelWrapper(artifacts, metadata)

            logger.info(f"✓ Model loaded: {metadata.model_id} (MAE={metrics.get('val_mae', 'N/A')})")

            return wrapper

        except Exception as e:
            logger.error(f"Failed to load model from {run_id}: {e}")
            raise

    def load_champion(self, run_id: str) -> None:
        """Загружает champion модель"""
        with self._lock:
            model = self.load_model_from_mlflow(run_id, status='champion')
            old_champion = self._champion
            self._champion = model

            self._swap_history.append({
                'timestamp': datetime.now(),
                'action': 'load_champion',
                'old': old_champion.metadata.model_id if old_champion else None,
                'new': model.metadata.model_id
            })

            logger.info(f"✓ Champion loaded: {model.metadata.model_id}")

    def load_challenger(self, run_id: str) -> None:
        """Загружает challenger модель"""
        with self._lock:
            model = self.load_model_from_mlflow(run_id, status='challenger')
            old_challenger = self._challenger
            self._challenger = model

            self._swap_history.append({
                'timestamp': datetime.now(),
                'action': 'load_challenger',
                'old': old_challenger.metadata.model_id if old_challenger else None,
                'new': model.metadata.model_id
            })

            logger.info(f"✓ Challenger loaded: {model.metadata.model_id}")

    def promote_challenger_to_champion(self) -> None:
        """Промоутит challenger в champion (atomic swap)"""
        with self._lock:
            if self._challenger is None:
                raise ValueError("No challenger loaded")

            old_champion = self._champion
            self._challenger.metadata.status = 'champion'
            self._champion = self._challenger
            self._challenger = None

            if old_champion:
                old_champion.metadata.status = 'retired'

            self._swap_history.append({
                'timestamp': datetime.now(),
                'action': 'promote_to_champion',
                'old': old_champion.metadata.model_id if old_champion else None,
                'new': self._champion.metadata.model_id
            })

            logger.info(f"✓ PROMOTED: {self._champion.metadata.model_id} is now champion")

    def rollback_to_previous_champion(self) -> None:
        """Откатывается к предыдущему champion"""
        # Для полноценного rollback нужно хранить историю моделей
        # Это упрощенная версия
        logger.warning("Rollback: need to manually load previous champion")
        raise NotImplementedError("Implement full history tracking")

    def predict(self,
                X: pd.DataFrame,
                use_challenger: bool = False) -> np.ndarray:
        """
        Предикция с текущей моделью

        Args:
            X: Признаки
            use_challenger: Если True, использует challenger (для A/B testing)
        """
        with self._lock:
            if use_challenger and self._challenger is not None:
                return self._challenger.predict(X)
            elif self._champion is not None:
                return self._champion.predict(X)
            else:
                raise RuntimeError("No model loaded (neither champion nor challenger)")

    def predict_both(self, X: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Предикция обеими моделями (shadow mode)"""
        results = {}

        with self._lock:
            if self._champion is not None:
                results['champion'] = self._champion.predict(X)

            if self._challenger is not None:
                results['challenger'] = self._challenger.predict(X)

        return results

    def compare_models(self,
                      X_test: pd.DataFrame,
                      y_test: pd.Series) -> Dict[str, Dict[str, float]]:
        """Сравнивает champion и challenger на тестовых данных"""
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        results = {}

        with self._lock:
            if self._champion is not None:
                y_pred_champion = self._champion.predict(X_test)
                results['champion'] = {
                    'mae': mean_absolute_error(y_test, y_pred_champion),
                    'rmse': np.sqrt(mean_squared_error(y_test, y_pred_champion)),
                    'r2': r2_score(y_test, y_pred_champion)
                }

            if self._challenger is not None:
                y_pred_challenger = self._challenger.predict(X_test)
                results['challenger'] = {
                    'mae': mean_absolute_error(y_test, y_pred_challenger),
                    'rmse': np.sqrt(mean_squared_error(y_test, y_pred_challenger)),
                    'r2': r2_score(y_test, y_pred_challenger)
                }

        return results

    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус системы"""
        with self._lock:
            status = {
                'champion': None,
                'challenger': None,
                'swap_history_count': len(self._swap_history),
                'last_swap': self._swap_history[-1] if self._swap_history else None
            }

            if self._champion:
                status['champion'] = {
                    'metadata': {
                        'model_id': self._champion.metadata.model_id,
                        'model_type': self._champion.metadata.model_type,
                        'loaded_at': self._champion.metadata.loaded_at.isoformat(),
                        'metrics': self._champion.metadata.metrics
                    },
                    'stats': self._champion.get_stats()
                }

            if self._challenger:
                status['challenger'] = {
                    'metadata': {
                        'model_id': self._challenger.metadata.model_id,
                        'model_type': self._challenger.metadata.model_type,
                        'loaded_at': self._challenger.metadata.loaded_at.isoformat(),
                        'metrics': self._challenger.metadata.metrics
                    },
                    'stats': self._challenger.get_stats()
                }

            return status

    def save_state(self, path: Path) -> None:
        """Сохраняет состояние менеджера"""
        state = {
            'champion_run_id': self._champion.metadata.run_id if self._champion else None,
            'challenger_run_id': self._challenger.metadata.run_id if self._challenger else None,
            'swap_history': self._swap_history
        }

        with open(path, 'wb') as f:
            pickle.dump(state, f)

        logger.info(f"State saved to {path}")

    def load_state(self, path: Path) -> None:
        """Загружает состояние менеджера"""
        with open(path, 'rb') as f:
            state = pickle.load(f)

        if state['champion_run_id']:
            self.load_champion(state['champion_run_id'])

        if state['challenger_run_id']:
            self.load_challenger(state['challenger_run_id'])

        self._swap_history = state['swap_history']

        logger.info(f"State loaded from {path}")


class AutoPromoter:
    """
    Автоматический промоутер challenger -> champion
    на основе метрик в production
    """

    def __init__(self,
                 manager: HotSwapModelManager,
                 promotion_criteria: Dict[str, Any]):
        self.manager = manager
        self.criteria = promotion_criteria
        self._observations = []

    def observe(self,
                X: pd.DataFrame,
                y_true: pd.Series) -> Dict[str, Any]:
        """Собирает наблюдения для обеих моделей"""
        from sklearn.metrics import mean_absolute_error

        predictions = self.manager.predict_both(X)
        results = {}

        for model_type, y_pred in predictions.items():
            mae = mean_absolute_error(y_true, y_pred)
            results[model_type] = {'mae': mae, 'count': len(y_true)}

        self._observations.append({
            'timestamp': datetime.now(),
            'results': results
        })

        return results

    def should_promote(self) -> bool:
        """Определяет, нужно ли промоутить challenger"""
        if len(self._observations) < self.criteria.get('min_observations', 100):
            return False

        # Вычисляем средние метрики
        recent = self._observations[-self.criteria.get('window_size', 100):]

        champion_maes = [obs['results']['champion']['mae']
                        for obs in recent if 'champion' in obs['results']]
        challenger_maes = [obs['results']['challenger']['mae']
                          for obs in recent if 'challenger' in obs['results']]

        if not champion_maes or not challenger_maes:
            return False

        avg_champion_mae = np.mean(champion_maes)
        avg_challenger_mae = np.mean(challenger_maes)

        # Challenger должен быть лучше на improvement_threshold %
        improvement = (avg_champion_mae - avg_challenger_mae) / avg_champion_mae
        threshold = self.criteria.get('improvement_threshold', 0.05)

        logger.info(f"Promotion check: champion MAE={avg_champion_mae:.4f}, "
                   f"challenger MAE={avg_challenger_mae:.4f}, "
                   f"improvement={improvement*100:.1f}%")

        return improvement >= threshold

    def auto_promote_if_ready(self) -> bool:
        """Автоматически промоутит если критерии выполнены"""
        if self.should_promote():
            logger.info("AUTO-PROMOTION triggered")
            self.manager.promote_challenger_to_champion()
            self._observations = []  # Сброс
            return True
        return False


def demo():
    """Демонстрация hot-swap"""
    logger.info("Hot-Swap Demo")

    manager = HotSwapModelManager()

    # Симуляция: загружаем модели
    # manager.load_champion(run_id='abc123...')
    # manager.load_challenger(run_id='def456...')

    # Получаем статус
    status = manager.get_status()
    print(f"\nStatus: {status}")

    # Предикция
    # X = pd.DataFrame(...)
    # y_pred = manager.predict(X)

    # Сравнение
    # comparison = manager.compare_models(X_test, y_test)
    # print(f"Comparison: {comparison}")

    # Промоушн
    # if comparison['challenger']['mae'] < comparison['champion']['mae']:
    #     manager.promote_challenger_to_champion()

    logger.info("✓ Demo complete")


if __name__ == '__main__':
    demo()
