#!/usr/bin/env python3
"""
Real data training on A100 - Neftekod dataset
"""

import sys
from pathlib import Path
import logging
import json
import time
import pickle
import signal

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('training_real.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_and_prepare_data(data_dir: Path):
    """Load and prepare real Neftekod data"""
    logger.info("Loading real data...")

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
    ).set_index('date')

    logger.info(f"Combined: {combined.shape}")

    # Target
    target_col = 'H24_F25'
    target = combined[target_col].dropna()

    # Top correlated features
    features_base = combined.drop(columns=[target_col])
    correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
    top_features = correlations.head(20).index.tolist()

    logger.info(f"Top features: {top_features[:5]}...")

    # Feature engineering
    df = combined[top_features + [target_col]].copy()

    # Lags
    for col in top_features[:10]:
        df[f'{col}_lag_6'] = df[col].shift(6)
        df[f'{col}_lag_12'] = df[col].shift(12)

    # Rolling
    for col in top_features[:5]:
        df[f'{col}_roll_6'] = df[col].rolling(6, min_periods=1).mean()

    # Clean
    df = df.dropna(subset=[target_col])
    feature_cols = [col for col in df.columns if col != target_col]
    df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median())
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    X = df[feature_cols]
    y = df[target_col]

    logger.info(f"Final: X={X.shape}, y={y.shape}")
    logger.info(f"Target: mean={y.mean():.2f}, std={y.std():.2f}")

    # Split
    split_idx = int(0.8 * len(X))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    return X_train, y_train, X_val, y_val, top_features


def get_configs():
    """Generate model configurations"""
    configs = []

    # CatBoost
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
                        'device': 'cpu',  # LightGBM GPU has issues
                        'random_state': 42,
                        'verbosity': -1
                    }
                })

    logger.info(f"Generated {len(configs)} configurations")
    return configs


def train_single(config, X_train, y_train, X_val, y_val):
    """Train one model"""
    start = time.time()

    try:
        from catboost import CatBoostRegressor, Pool
        from lightgbm import LGBMRegressor

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
        else:  # lightgbm
            model = LGBMRegressor(**config['params'])
            model.fit(X_train_scaled, y_train,
                     eval_set=[(X_val_scaled, y_val)])

        # Evaluate
        y_pred = model.predict(X_val_scaled)
        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        r2 = r2_score(y_val, y_pred)

        elapsed = time.time() - start

        result = {
            'name': config['name'],
            'type': config['type'],
            'metrics': {'mae': float(mae), 'rmse': float(rmse), 'r2': float(r2)},
            'time': float(elapsed),
            'success': True
        }

        logger.info(f"✓ {config['name']}: MAE={mae:.2f}, R²={r2:.4f}, {elapsed:.1f}s")

        return result, model, scaler

    except Exception as e:
        logger.error(f"✗ {config['name']}: {e}")
        return {'name': config['name'], 'type': config['type'], 'success': False, 'error': str(e)}, None, None


def main():
    logger.info("="*80)
    logger.info("TRAINING ON REAL NEFTEKOD DATA (A100)")
    logger.info("="*80)

    # Load data
    data_dir = Path('./data')
    X_train, y_train, X_val, y_val, top_features = load_and_prepare_data(data_dir)

    # Get configs
    configs = get_configs()

    # Train
    results = []
    best_mae = float('inf')
    best_model = None

    for i, config in enumerate(configs, 1):
        logger.info(f"\n[{i}/{len(configs)}] Training {config['name']}...")

        result, model, scaler = train_single(config, X_train, y_train, X_val, y_val)

        results.append(result)

        if result['success'] and result['metrics']['mae'] < best_mae:
            best_mae = result['metrics']['mae']
            best_model = (model, scaler, config, top_features)
            logger.info(f"🏆 NEW BEST: MAE={best_mae:.2f}")

        # Auto-save every 10
        if i % 10 == 0:
            logger.info(f"💾 Checkpoint at {i}/{len(configs)}")

    # Save best
    if best_model:
        with open('best_real_model.pkl', 'wb') as f:
            pickle.dump({
                'model': best_model[0],
                'scaler': best_model[1],
                'config': best_model[2],
                'top_features': best_model[3],
                'metrics': {
                    'mae': float(best_mae),
                    'type': 'real_neftekod_data'
                }
            }, f)

        logger.info(f"\n✓ Best model saved: {best_model[2]['name']}")

    # Save results
    results_sorted = sorted([r for r in results if r['success']], key=lambda x: x['metrics']['mae'])

    with open('training_real_results.json', 'w') as f:
        json.dump({
            'top_10': results_sorted[:10],
            'all_results': results_sorted,
            'total_trained': len([r for r in results if r['success']]),
            'total_failed': len([r for r in results if not r['success']])
        }, f, indent=2)

    logger.info("\n" + "="*80)
    logger.info("TRAINING COMPLETE")
    logger.info("="*80)
    logger.info(f"Total trained: {len([r for r in results if r['success']])}")
    if results_sorted:
        logger.info(f"Best MAE: {results_sorted[0]['metrics']['mae']:.2f}")
        logger.info(f"Best R²: {results_sorted[0]['metrics']['r2']:.4f}")
        logger.info(f"Best model: {results_sorted[0]['name']}")


if __name__ == '__main__':
    main()
