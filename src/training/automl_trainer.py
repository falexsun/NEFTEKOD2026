#!/usr/bin/env python3
"""
GPU-Accelerated AutoML Trainer для Нефтекод
Массовое обучение моделей с hyperparameter tuning и MLflow tracking
"""

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, RobustScaler, PowerTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import mlflow
import mlflow.sklearn
from catboost import CatBoostRegressor, Pool
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """Конфигурация модели"""
    name: str
    model_type: str  # 'catboost', 'lightgbm', 'xgboost'
    params: Dict[str, Any]
    use_gpu: bool = True
    preprocessing: str = 'standard'  # 'standard', 'robust', 'power', 'log'


@dataclass
class TrainingResult:
    """Результат обучения"""
    model_name: str
    model_type: str
    run_id: str
    metrics: Dict[str, float]
    best_params: Dict[str, Any]
    train_time: float
    model_path: str
    artifact_path: str


class FeatureEngineer:
    """Feature engineering с различными трансформациями"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.scalers = {}

    def create_lag_features(self, df: pd.DataFrame, target_col: str,
                           lags: List[int]) -> pd.DataFrame:
        """Создает лаговые признаки"""
        result = df.copy()
        for lag in lags:
            result[f'{target_col}_lag_{lag}'] = result[target_col].shift(lag)
        return result

    def create_rolling_features(self, df: pd.DataFrame,
                               columns: List[str],
                               windows: List[int]) -> pd.DataFrame:
        """Создает rolling статистики"""
        result = df.copy()
        for col in columns:
            for window in windows:
                result[f'{col}_rolling_mean_{window}'] = \
                    result[col].rolling(window=window, min_periods=1).mean()
                result[f'{col}_rolling_std_{window}'] = \
                    result[col].rolling(window=window, min_periods=1).std()
                result[f'{col}_rolling_min_{window}'] = \
                    result[col].rolling(window=window, min_periods=1).min()
                result[f'{col}_rolling_max_{window}'] = \
                    result[col].rolling(window=window, min_periods=1).max()
        return result

    def create_time_features(self, df: pd.DataFrame,
                            date_col: str = 'date') -> pd.DataFrame:
        """Создает временные признаки"""
        result = df.copy()
        if date_col in result.columns:
            dt = pd.to_datetime(result[date_col])
            result['hour'] = dt.dt.hour
            result['day_of_week'] = dt.dt.dayofweek
            result['day_of_month'] = dt.dt.day
            result['month'] = dt.dt.month
            result['quarter'] = dt.dt.quarter
            result['is_weekend'] = (dt.dt.dayofweek >= 5).astype(int)
        return result

    def apply_log_transform(self, df: pd.DataFrame,
                           columns: List[str]) -> pd.DataFrame:
        """Логарифмическая трансформация"""
        result = df.copy()
        for col in columns:
            if col in result.columns:
                # Добавляем 1 чтобы избежать log(0)
                result[f'{col}_log'] = np.log1p(result[col].clip(lower=0))
        return result

    def fit_scaler(self, data: np.ndarray, method: str = 'standard') -> Any:
        """Обучает scaler"""
        if method == 'standard':
            scaler = StandardScaler()
        elif method == 'robust':
            scaler = RobustScaler()
        elif method == 'power':
            scaler = PowerTransformer(method='yeo-johnson')
        else:
            raise ValueError(f"Unknown scaling method: {method}")

        scaler.fit(data)
        return scaler

    def transform(self, data: np.ndarray, scaler: Any) -> np.ndarray:
        """Применяет scaler"""
        return scaler.transform(data)


class AutoMLTrainer:
    """Автоматизированное обучение множества моделей"""

    def __init__(self,
                 experiment_name: str = "neftekod_quality_prediction",
                 mlflow_uri: str = "http://localhost:5000"):
        self.experiment_name = experiment_name
        self.mlflow_uri = mlflow_uri
        self.feature_engineer = FeatureEngineer({})

        # Настройка MLflow
        mlflow.set_tracking_uri(mlflow_uri)
        mlflow.set_experiment(experiment_name)

        logger.info(f"AutoML Trainer initialized: {experiment_name}")

    def _get_default_model_configs(self) -> List[ModelConfig]:
        """Возвращает конфигурации моделей по умолчанию"""
        configs = []

        # CatBoost конфигурации
        catboost_params_base = {
            'iterations': 1000,
            'learning_rate': 0.05,
            'depth': 6,
            'l2_leaf_reg': 3,
            'loss_function': 'RMSE',
            'eval_metric': 'MAE',
            'random_seed': 42,
            'verbose': 100,
            'early_stopping_rounds': 50,
            'task_type': 'GPU',
            'devices': '0'
        }

        # Grid для CatBoost
        for depth in [4, 6, 8]:
            for lr in [0.01, 0.05, 0.1]:
                for l2 in [1, 3, 5]:
                    params = catboost_params_base.copy()
                    params.update({
                        'depth': depth,
                        'learning_rate': lr,
                        'l2_leaf_reg': l2
                    })
                    configs.append(ModelConfig(
                        name=f'catboost_d{depth}_lr{lr}_l2{l2}',
                        model_type='catboost',
                        params=params,
                        use_gpu=True,
                        preprocessing='standard'
                    ))

        # LightGBM конфигурации
        lgbm_params_base = {
            'n_estimators': 1000,
            'learning_rate': 0.05,
            'num_leaves': 31,
            'max_depth': 6,
            'min_child_samples': 20,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 0.1,
            'reg_lambda': 0.1,
            'random_state': 42,
            'verbosity': 1,
            'device': 'gpu',
            'gpu_platform_id': 0,
            'gpu_device_id': 0
        }

        # Grid для LightGBM
        for leaves in [15, 31, 63]:
            for lr in [0.01, 0.05, 0.1]:
                for depth in [4, 6, 8]:
                    params = lgbm_params_base.copy()
                    params.update({
                        'num_leaves': leaves,
                        'learning_rate': lr,
                        'max_depth': depth
                    })
                    configs.append(ModelConfig(
                        name=f'lightgbm_l{leaves}_lr{lr}_d{depth}',
                        model_type='lightgbm',
                        params=params,
                        use_gpu=True,
                        preprocessing='robust'
                    ))

        # XGBoost конфигурации
        xgb_params_base = {
            'n_estimators': 1000,
            'learning_rate': 0.05,
            'max_depth': 6,
            'min_child_weight': 1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'gamma': 0,
            'reg_alpha': 0.1,
            'reg_lambda': 1,
            'random_state': 42,
            'tree_method': 'gpu_hist',
            'gpu_id': 0,
            'verbosity': 1
        }

        # Grid для XGBoost
        for depth in [4, 6, 8]:
            for lr in [0.01, 0.05, 0.1]:
                for gamma in [0, 0.1, 0.5]:
                    params = xgb_params_base.copy()
                    params.update({
                        'max_depth': depth,
                        'learning_rate': lr,
                        'gamma': gamma
                    })
                    configs.append(ModelConfig(
                        name=f'xgboost_d{depth}_lr{lr}_g{gamma}',
                        model_type='xgboost',
                        params=params,
                        use_gpu=True,
                        preprocessing='power'
                    ))

        logger.info(f"Generated {len(configs)} model configurations")
        return configs

    def _create_model(self, config: ModelConfig) -> Any:
        """Создает модель по конфигурации"""
        if config.model_type == 'catboost':
            return CatBoostRegressor(**config.params)
        elif config.model_type == 'lightgbm':
            return LGBMRegressor(**config.params)
        elif config.model_type == 'xgboost':
            return XGBRegressor(**config.params)
        else:
            raise ValueError(f"Unknown model type: {config.model_type}")

    def _preprocess_data(self, X: pd.DataFrame, y: pd.Series,
                        method: str,
                        scaler: Optional[Any] = None,
                        fit: bool = True) -> Tuple[np.ndarray, Any]:
        """Препроцессинг данных"""
        X_processed = X.copy()

        # Log transform для положительных признаков
        if method in ['log', 'power']:
            positive_cols = X_processed.columns[X_processed.min() >= 0]
            for col in positive_cols:
                X_processed[f'{col}_log'] = np.log1p(X_processed[col])

        # Заполнение пропусков
        X_processed = X_processed.fillna(X_processed.median())

        # Scaling
        if fit:
            scaler = self.feature_engineer.fit_scaler(
                X_processed.values,
                method=method if method != 'log' else 'standard'
            )

        X_scaled = self.feature_engineer.transform(X_processed.values, scaler)

        return X_scaled, scaler

    def _evaluate_model(self, y_true: np.ndarray,
                       y_pred: np.ndarray) -> Dict[str, float]:
        """Вычисляет метрики"""
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        r2 = r2_score(y_true, y_pred)

        # MAPE (с защитой от деления на 0)
        mask = y_true != 0
        mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100 if mask.sum() > 0 else np.inf

        return {
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'mape': mape
        }

    def train_model(self,
                   X_train: pd.DataFrame,
                   y_train: pd.Series,
                   X_val: pd.DataFrame,
                   y_val: pd.Series,
                   config: ModelConfig,
                   tags: Optional[Dict[str, str]] = None) -> TrainingResult:
        """Обучает одну модель с MLflow tracking"""

        with mlflow.start_run(run_name=config.name):
            start_time = time.time()

            # Логируем параметры
            mlflow.log_params(config.params)
            mlflow.log_param('model_type', config.model_type)
            mlflow.log_param('preprocessing', config.preprocessing)
            mlflow.log_param('use_gpu', config.use_gpu)

            if tags:
                mlflow.set_tags(tags)

            try:
                # Preprocessing
                logger.info(f"Training {config.name}...")
                X_train_processed, scaler = self._preprocess_data(
                    X_train, y_train, config.preprocessing, fit=True
                )
                X_val_processed, _ = self._preprocess_data(
                    X_val, y_val, config.preprocessing, scaler=scaler, fit=False
                )

                # Создание модели
                model = self._create_model(config)

                # Обучение
                if config.model_type == 'catboost':
                    train_pool = Pool(X_train_processed, y_train)
                    val_pool = Pool(X_val_processed, y_val)
                    model.fit(train_pool, eval_set=val_pool, verbose=False)
                elif config.model_type == 'lightgbm':
                    model.fit(
                        X_train_processed, y_train,
                        eval_set=[(X_val_processed, y_val)],
                        callbacks=[lgbm.early_stopping(50), lgbm.log_evaluation(100)]
                    )
                else:  # xgboost
                    model.fit(
                        X_train_processed, y_train,
                        eval_set=[(X_val_processed, y_val)],
                        verbose=False
                    )

                # Предикция
                y_train_pred = model.predict(X_train_processed)
                y_val_pred = model.predict(X_val_processed)

                # Метрики
                train_metrics = self._evaluate_model(y_train, y_train_pred)
                val_metrics = self._evaluate_model(y_val, y_val_pred)

                # Логируем метрики
                for metric, value in train_metrics.items():
                    mlflow.log_metric(f'train_{metric}', value)
                for metric, value in val_metrics.items():
                    mlflow.log_metric(f'val_{metric}', value)

                train_time = time.time() - start_time
                mlflow.log_metric('train_time_seconds', train_time)

                # Сохраняем модель и scaler
                artifacts = {
                    'model': model,
                    'scaler': scaler,
                    'config': asdict(config)
                }

                model_path = f"models/{config.name}"
                mlflow.sklearn.log_model(
                    artifacts,
                    model_path,
                    registered_model_name=f"neftekod_{config.model_type}"
                )

                # Feature importance (если доступно)
                if hasattr(model, 'feature_importances_'):
                    importance_df = pd.DataFrame({
                        'feature': X_train.columns,
                        'importance': model.feature_importances_
                    }).sort_values('importance', ascending=False)

                    importance_df.to_csv('feature_importance.csv', index=False)
                    mlflow.log_artifact('feature_importance.csv')

                run_id = mlflow.active_run().info.run_id

                result = TrainingResult(
                    model_name=config.name,
                    model_type=config.model_type,
                    run_id=run_id,
                    metrics=val_metrics,
                    best_params=config.params,
                    train_time=train_time,
                    model_path=model_path,
                    artifact_path=mlflow.get_artifact_uri()
                )

                logger.info(f"✓ {config.name}: val_mae={val_metrics['mae']:.4f}, "
                          f"val_r2={val_metrics['r2']:.4f}, time={train_time:.1f}s")

                return result

            except Exception as e:
                logger.error(f"✗ {config.name} failed: {e}")
                mlflow.log_param('status', 'failed')
                mlflow.log_param('error', str(e))
                raise

    def train_all_models(self,
                        X_train: pd.DataFrame,
                        y_train: pd.Series,
                        X_val: pd.DataFrame,
                        y_val: pd.Series,
                        configs: Optional[List[ModelConfig]] = None,
                        n_jobs: int = 1) -> List[TrainingResult]:
        """Обучает все модели параллельно"""

        if configs is None:
            configs = self._get_default_model_configs()

        logger.info(f"Starting training of {len(configs)} models...")

        results = []
        for config in configs:
            try:
                result = self.train_model(X_train, y_train, X_val, y_val, config)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to train {config.name}: {e}")
                continue

        # Сортируем по val_mae
        results.sort(key=lambda x: x.metrics['mae'])

        logger.info(f"\n{'='*80}")
        logger.info(f"TRAINING COMPLETE: {len(results)}/{len(configs)} models succeeded")
        logger.info(f"{'='*80}")
        logger.info(f"TOP 5 MODELS:")
        for i, result in enumerate(results[:5], 1):
            logger.info(f"{i}. {result.model_name}: "
                       f"MAE={result.metrics['mae']:.4f}, "
                       f"R²={result.metrics['r2']:.4f}, "
                       f"RMSE={result.metrics['rmse']:.4f}")

        return results


def main():
    """Пример использования"""
    # Загрузка данных
    from pathlib import Path
    import sys

    HERE = Path(__file__).parent
    ROOT = HERE.parent.parent
    sys.path.insert(0, str(ROOT))

    # Генерируем синтетические данные для демо
    np.random.seed(42)
    n_samples = 10000
    n_features = 20

    X = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f'feature_{i}' for i in range(n_features)]
    )
    y = pd.Series(
        X['feature_0'] * 2 + X['feature_1'] ** 2 + np.random.randn(n_samples) * 0.1,
        name='target'
    )

    # Split
    split_idx = int(0.8 * n_samples)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    # Обучение
    trainer = AutoMLTrainer()
    results = trainer.train_all_models(X_train, y_train, X_val, y_val)

    print(f"\n✓ Best model: {results[0].model_name}")
    print(f"  MAE: {results[0].metrics['mae']:.4f}")
    print(f"  Run ID: {results[0].run_id}")


if __name__ == '__main__':
    main()
