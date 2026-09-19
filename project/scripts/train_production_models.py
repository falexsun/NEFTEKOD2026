#!/usr/bin/env python3
"""
Production Training Pipeline для Нефтекод
Полный цикл: загрузка данных -> feature engineering -> AutoML -> MLflow -> hot-swap
"""

import sys
from pathlib import Path
import logging
from typing import Dict, Any, List, Tuple
import argparse

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
import mlflow

# Добавляем пути
HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ROOT / 'eda'))

from training.automl_trainer import AutoMLTrainer, FeatureEngineer, ModelConfig
from training.hotswap_manager import HotSwapModelManager
from eda_utils import load_telemetry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProductionTrainingPipeline:
    """Production training pipeline"""

    def __init__(self,
                 data_dir: Path,
                 experiment_name: str = "neftekod_production",
                 mlflow_uri: str = "http://localhost:5000"):
        self.data_dir = data_dir
        self.experiment_name = experiment_name
        self.mlflow_uri = mlflow_uri
        self.feature_engineer = FeatureEngineer({})

    def load_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Загружает данные АВТ и 24-2000"""
        logger.info("Loading data...")

        avt = load_telemetry(self.data_dir / 'avt_tags.csv')
        hydro = load_telemetry(self.data_dir / '242000_tags.csv')

        logger.info(f"AVT: {avt.shape}, 24-2000: {hydro.shape}")

        return avt, hydro

    def prepare_dataset(self,
                       avt: pd.DataFrame,
                       hydro: pd.DataFrame,
                       target_col: str = 'H24_F25') -> Tuple[pd.DataFrame, pd.Series]:
        """
        Подготавливает датасет с feature engineering

        Target: H24_F25 - расход продукта (proxy для качества без LIMS)
        """
        logger.info("Feature engineering...")

        # Объединяем данные
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

        # Выбираем топ коррелирующие с target
        target = combined[target_col].dropna()
        features_base = combined.drop(columns=[target_col])

        # Корреляционный фильтр
        correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
        top_features = correlations.head(30).index.tolist()

        logger.info(f"Selected {len(top_features)} top correlated features")

        # Feature engineering
        df = combined[top_features + [target_col]].copy()

        # 1. Лаговые признаки (1, 6, 12, 24 периода = 10min, 1h, 2h, 4h)
        for col in top_features[:10]:  # Топ-10 для лагов
            for lag in [1, 6, 12, 24]:
                df[f'{col}_lag_{lag}'] = df[col].shift(lag)

        # 2. Rolling статистики (окна 6, 12, 24 = 1h, 2h, 4h)
        for col in top_features[:10]:
            for window in [6, 12, 24]:
                df[f'{col}_roll_mean_{window}'] = df[col].rolling(window, min_periods=1).mean()
                df[f'{col}_roll_std_{window}'] = df[col].rolling(window, min_periods=1).std()

        # 3. Разности (скорость изменения)
        for col in top_features[:10]:
            df[f'{col}_diff_1'] = df[col].diff()
            df[f'{col}_diff_6'] = df[col].diff(6)

        # 4. Временные признаки
        df = self.feature_engineer.create_time_features(df)

        # 5. Логарифмы для положительных признаков
        positive_cols = [col for col in df.columns if col != target_col and df[col].min() >= 0]
        df = self.feature_engineer.apply_log_transform(df, positive_cols[:20])

        # Удаляем строки с NaN в target
        df = df.dropna(subset=[target_col])

        # Заполняем пропуски в признаках медианой
        feature_cols = [col for col in df.columns if col != target_col]
        df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median())

        # Финальная проверка
        df = df.replace([np.inf, -np.inf], np.nan).dropna()

        X = df[feature_cols]
        y = df[target_col]

        logger.info(f"Final dataset: {X.shape}, target: {y.shape}")
        logger.info(f"Target stats: mean={y.mean():.2f}, std={y.std():.2f}, min={y.min():.2f}, max={y.max():.2f}")

        return X, y

    def create_time_splits(self,
                          X: pd.DataFrame,
                          y: pd.Series,
                          n_splits: int = 5) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Создает time series splits"""
        tscv = TimeSeriesSplit(n_splits=n_splits)
        splits = list(tscv.split(X))

        logger.info(f"Created {n_splits} time series splits")
        for i, (train_idx, val_idx) in enumerate(splits):
            logger.info(f"  Split {i+1}: train={len(train_idx)}, val={len(val_idx)}")

        return splits

    def run_automl(self,
                  X: pd.DataFrame,
                  y: pd.Series,
                  n_models: int = 50) -> List[Any]:
        """Запускает AutoML с grid search"""
        logger.info(f"\n{'='*80}")
        logger.info(f"STARTING AUTOML: {n_models} models")
        logger.info(f"{'='*80}\n")

        # Split данных
        split_idx = int(0.8 * len(X))
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

        logger.info(f"Train: {X_train.shape}, Val: {X_val.shape}")

        # Создаем trainer
        trainer = AutoMLTrainer(
            experiment_name=self.experiment_name,
            mlflow_uri=self.mlflow_uri
        )

        # Получаем конфигурации
        all_configs = trainer._get_default_model_configs()

        # Ограничиваем количество
        if n_models < len(all_configs):
            # Берем по n_models // 3 от каждого типа
            per_type = n_models // 3
            catboost_configs = [c for c in all_configs if c.model_type == 'catboost'][:per_type]
            lgbm_configs = [c for c in all_configs if c.model_type == 'lightgbm'][:per_type]
            xgb_configs = [c for c in all_configs if c.model_type == 'xgboost'][:per_type]
            configs = catboost_configs + lgbm_configs + xgb_configs
        else:
            configs = all_configs

        logger.info(f"Training {len(configs)} models:")
        logger.info(f"  CatBoost: {sum(1 for c in configs if c.model_type == 'catboost')}")
        logger.info(f"  LightGBM: {sum(1 for c in configs if c.model_type == 'lightgbm')}")
        logger.info(f"  XGBoost: {sum(1 for c in configs if c.model_type == 'xgboost')}")

        # Обучаем
        results = trainer.train_all_models(
            X_train, y_train,
            X_val, y_val,
            configs=configs
        )

        return results

    def run_full_pipeline(self,
                         n_models: int = 50,
                         auto_deploy: bool = False) -> Dict[str, Any]:
        """
        Запускает полный pipeline

        Args:
            n_models: Количество моделей для обучения
            auto_deploy: Автоматически деплоить лучшую модель
        """
        # 1. Загрузка данных
        avt, hydro = self.load_data()

        # 2. Feature engineering
        X, y = self.prepare_dataset(avt, hydro)

        # 3. AutoML
        results = self.run_automl(X, y, n_models=n_models)

        # 4. Выбираем лучшую модель
        best_result = results[0]

        logger.info(f"\n{'='*80}")
        logger.info(f"BEST MODEL: {best_result.model_name}")
        logger.info(f"{'='*80}")
        logger.info(f"Metrics:")
        for metric, value in best_result.metrics.items():
            logger.info(f"  {metric}: {value:.4f}")
        logger.info(f"Run ID: {best_result.run_id}")
        logger.info(f"Training time: {best_result.train_time:.1f}s")

        # 5. Auto-deploy
        if auto_deploy:
            logger.info("\nDeploying best model to production...")
            manager = HotSwapModelManager(mlflow_uri=self.mlflow_uri)
            manager.load_champion(best_result.run_id)
            logger.info("✓ Model deployed as champion")

        return {
            'best_model': best_result,
            'all_results': results,
            'dataset_shape': X.shape
        }


def main():
    parser = argparse.ArgumentParser(description='Production ML Training Pipeline')
    parser.add_argument('--data-dir', type=Path,
                       default=Path(__file__).parent.parent.parent / 'data',
                       help='Path to data directory')
    parser.add_argument('--n-models', type=int, default=50,
                       help='Number of models to train')
    parser.add_argument('--experiment', type=str, default='neftekod_hackathon',
                       help='MLflow experiment name')
    parser.add_argument('--mlflow-uri', type=str, default='http://localhost:5000',
                       help='MLflow tracking URI')
    parser.add_argument('--auto-deploy', action='store_true',
                       help='Automatically deploy best model')

    args = parser.parse_args()

    logger.info("="*80)
    logger.info("NEFTEKOD PRODUCTION TRAINING PIPELINE")
    logger.info("="*80)
    logger.info(f"Data dir: {args.data_dir}")
    logger.info(f"N models: {args.n_models}")
    logger.info(f"Experiment: {args.experiment}")
    logger.info(f"Auto-deploy: {args.auto_deploy}")
    logger.info("="*80 + "\n")

    # Запуск
    pipeline = ProductionTrainingPipeline(
        data_dir=args.data_dir,
        experiment_name=args.experiment,
        mlflow_uri=args.mlflow_uri
    )

    result = pipeline.run_full_pipeline(
        n_models=args.n_models,
        auto_deploy=args.auto_deploy
    )

    logger.info("\n" + "="*80)
    logger.info("✓ PIPELINE COMPLETE")
    logger.info("="*80)
    logger.info(f"Best model: {result['best_model'].model_name}")
    logger.info(f"MAE: {result['best_model'].metrics['mae']:.4f}")
    logger.info(f"RMSE: {result['best_model'].metrics['rmse']:.4f}")
    logger.info(f"R²: {result['best_model'].metrics['r2']:.4f}")
    logger.info(f"\nTo deploy manually:")
    logger.info(f"  python -m src.training.hotswap_manager --load-champion {result['best_model'].run_id}")


if __name__ == '__main__':
    main()
