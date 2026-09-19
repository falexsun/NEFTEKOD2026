#!/usr/bin/env python3
"""
Robust GPU Training with auto-resume and error recovery
"""

import sys
from pathlib import Path
import logging
import json
import time
from typing import Dict, List, Any
import pickle
import signal
import os

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('training.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class RobustTrainer:
    """Trainer with checkpoint/resume and error recovery"""

    def __init__(self, data_dir: Path, checkpoint_dir: Path):
        self.data_dir = Path(data_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)

        self.state_file = self.checkpoint_dir / 'training_state.json'
        self.results = []
        self.completed_configs = set()

        # Load state if exists
        self.load_state()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Handle interrupt gracefully"""
        logger.warning(f"Received signal {signum}, saving state...")
        self.save_state()
        logger.info("State saved, exiting")
        sys.exit(0)

    def load_state(self):
        """Load previous training state"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)

                self.results = state.get('results', [])
                self.completed_configs = set(state.get('completed_configs', []))

                logger.info(f"✓ Resumed: {len(self.completed_configs)} configs already completed")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")

    def save_state(self):
        """Save current training state"""
        state = {
            'results': self.results,
            'completed_configs': list(self.completed_configs),
            'timestamp': time.time()
        }

        # Atomic write
        tmp_file = self.state_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2)
        tmp_file.replace(self.state_file)

    def get_configs(self) -> List[Dict]:
        """Generate configurations (simplified for speed)"""
        configs = []

        # CatBoost - fewer configs for faster testing
        for iterations in [500, 1000, 2000]:
            for depth in [6, 8, 10]:
                for lr in [0.03, 0.05, 0.1]:
                    for l2 in [3, 5]:
                        configs.append({
                            'name': f'cb_i{iterations}_d{depth}_lr{lr}_l2{l2}',
                            'type': 'catboost',
                            'params': {
                                'iterations': iterations,
                                'learning_rate': lr,
                                'depth': depth,
                                'l2_leaf_reg': l2,
                                'task_type': 'GPU',
                                'devices': '0',
                                'loss_function': 'RMSE',
                                'eval_metric': 'MAE',
                                'random_seed': 42,
                                'verbose': False,
                                'early_stopping_rounds': 50
                            }
                        })

        # LightGBM
        for n_est in [500, 1000, 2000]:
            for leaves in [31, 63]:
                for lr in [0.03, 0.05, 0.1]:
                    configs.append({
                        'name': f'lgbm_n{n_est}_l{leaves}_lr{lr}',
                        'type': 'lightgbm',
                        'params': {
                            'n_estimators': n_est,
                            'learning_rate': lr,
                            'num_leaves': leaves,
                            'max_depth': -1,
                            'device': 'gpu',
                            'gpu_platform_id': 0,
                            'gpu_device_id': 0,
                            'random_state': 42,
                            'verbosity': -1
                        }
                    })

        # XGBoost
        for n_est in [500, 1000, 2000]:
            for depth in [6, 8, 10]:
                for lr in [0.03, 0.05, 0.1]:
                    configs.append({
                        'name': f'xgb_n{n_est}_d{depth}_lr{lr}',
                        'type': 'xgboost',
                        'params': {
                            'n_estimators': n_est,
                            'learning_rate': lr,
                            'max_depth': depth,
                            'tree_method': 'gpu_hist',
                            'gpu_id': 0,
                            'random_state': 42,
                            'verbosity': 0
                        }
                    })

        logger.info(f"Generated {len(configs)} configurations")
        return configs

    def train_single(self, config: Dict, X_train, y_train, X_val, y_val):
        """Train one model with error handling"""

        # Skip if already done
        if config['name'] in self.completed_configs:
            logger.info(f"⊘ Skipping {config['name']} (already completed)")
            return None

        start = time.time()

        try:
            # Import here to handle missing packages gracefully
            from catboost import CatBoostRegressor, Pool
            from lightgbm import LGBMRegressor
            from xgboost import XGBRegressor

            # Scaling
            scaler = RobustScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)

            # Create model
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

            # Evaluate
            y_pred = model.predict(X_val_scaled)
            mae = mean_absolute_error(y_val, y_pred)
            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            r2 = r2_score(y_val, y_pred)

            elapsed = time.time() - start

            result = {
                'name': config['name'],
                'type': config['type'],
                'metrics': {
                    'mae': float(mae),
                    'rmse': float(rmse),
                    'r2': float(r2)
                },
                'time': float(elapsed),
                'success': True
            }

            logger.info(f"✓ {config['name']}: MAE={mae:.2f}, R²={r2:.4f}, {elapsed:.1f}s")

            self.completed_configs.add(config['name'])
            self.results.append(result)

            return result, model, scaler

        except Exception as e:
            logger.error(f"✗ {config['name']}: {e}")

            result = {
                'name': config['name'],
                'type': config['type'],
                'success': False,
                'error': str(e)
            }

            self.results.append(result)
            return None

    def run(self, max_models: int = 100):
        """Run training with auto-save"""

        logger.info("="*80)
        logger.info("ROBUST GPU TRAINING")
        logger.info("="*80)

        # Load data
        logger.info("Loading data...")
        try:
            # Try parquet first (faster)
            if (self.data_dir / 'avt_tags.parquet').exists():
                avt = pd.read_parquet(self.data_dir / 'avt_tags.parquet')
            else:
                avt = pd.read_csv(self.data_dir / 'avt_tags.csv')

            if (self.data_dir / '242000_tags.parquet').exists():
                hydro = pd.read_parquet(self.data_dir / '242000_tags.parquet')
            else:
                hydro = pd.read_csv(self.data_dir / '242000_tags.csv')

            logger.info(f"AVT: {avt.shape}, 24-2000: {hydro.shape}")

        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            logger.info("Using synthetic data for testing...")

            # Fallback to synthetic
            np.random.seed(42)
            n_train, n_val = 100000, 20000
            n_features = 50

            X_train = pd.DataFrame(np.random.randn(n_train, n_features))
            y_train = pd.Series(X_train.iloc[:, 0] * 2 + np.random.randn(n_train) * 0.1)
            X_val = pd.DataFrame(np.random.randn(n_val, n_features))
            y_val = pd.Series(X_val.iloc[:, 0] * 2 + np.random.randn(n_val) * 0.1)

            configs = self.get_configs()[:max_models]

            # Training loop
            best_mae = float('inf')
            best_model = None

            for i, config in enumerate(configs, 1):
                logger.info(f"\n[{i}/{len(configs)}] Training {config['name']}...")

                result = self.train_single(config, X_train, y_train, X_val, y_val)

                if result and result[0]['success']:
                    if result[0]['metrics']['mae'] < best_mae:
                        best_mae = result[0]['metrics']['mae']
                        best_model = (result[1], result[2], config)
                        logger.info(f"🏆 NEW BEST: MAE={best_mae:.2f}")

                # Auto-save every 5 models
                if i % 5 == 0:
                    self.save_state()
                    logger.info(f"💾 Checkpoint saved ({i}/{len(configs)})")

            # Final save
            self.save_state()

            # Save best model
            if best_model:
                with open('best_base_model.pkl', 'wb') as f:
                    pickle.dump({
                        'model': best_model[0],
                        'scaler': best_model[1],
                        'config': best_model[2]
                    }, f)

                logger.info(f"\n✓ Best model saved: {best_model[2]['name']}")

            # Save results
            results_sorted = sorted([r for r in self.results if r['success']],
                                   key=lambda x: x['metrics']['mae'])

            with open('training_results.json', 'w') as f:
                json.dump({
                    'top_10': results_sorted[:10],
                    'all_results': results_sorted,
                    'total_trained': len([r for r in self.results if r['success']]),
                    'total_failed': len([r for r in self.results if not r['success']])
                }, f, indent=2)

            logger.info("\n" + "="*80)
            logger.info("TRAINING COMPLETE")
            logger.info("="*80)
            logger.info(f"Total trained: {len([r for r in self.results if r['success']])}")
            logger.info(f"Total failed: {len([r for r in self.results if not r['success']])}")
            if results_sorted:
                logger.info(f"Best MAE: {results_sorted[0]['metrics']['mae']:.2f}")
                logger.info(f"Best model: {results_sorted[0]['name']}")

            return results_sorted


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=str, default='./data')
    parser.add_argument('--checkpoint-dir', type=str, default='./checkpoints')
    parser.add_argument('--max-models', type=int, default=100)
    args = parser.parse_args()

    trainer = RobustTrainer(
        data_dir=Path(args.data_dir),
        checkpoint_dir=Path(args.checkpoint_dir)
    )

    trainer.run(max_models=args.max_models)
