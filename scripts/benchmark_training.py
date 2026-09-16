#!/usr/bin/env python3
"""
Benchmark: Время обучения на CPU vs GPU
Сценарии: полное обучение, инкрементальное (дообучение), предикция
"""

import sys
from pathlib import Path
import logging
import time
import pickle

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def benchmark_catboost_cpu():
    """Бенчмарк CatBoost на CPU"""
    from catboost import CatBoostRegressor, Pool

    logger.info("="*80)
    logger.info("BENCHMARK: CatBoost на CPU")
    logger.info("="*80)

    # Загрузка данных
    data_dir = Path('../data')

    logger.info("\nЗагрузка данных...")
    avt = pd.read_csv(data_dir / 'avt_tags.csv')
    hydro = pd.read_csv(data_dir / '242000_tags.csv')

    # Быстрая подготовка (упрощенная)
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

    # Target
    target_col = 'H24_F25'
    target = combined[target_col].dropna()

    # Топ-10 признаков (для скорости)
    features_base = combined.drop(columns=[target_col])
    correlations = features_base.corrwith(target).abs().sort_values(ascending=False)
    top_features = correlations.head(10).index.tolist()

    df = combined[top_features + [target_col]].dropna()

    X = df[top_features]
    y = df[target_col]

    # Split
    split_idx = int(0.8 * len(X))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    logger.info(f"Данные: Train={len(X_train)}, Val={len(X_val)}, Features={len(top_features)}")

    # Scaling
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    results = {}

    # ===== СЦЕНАРИЙ 1: Полное обучение (разные iterations) =====
    logger.info("\n" + "="*80)
    logger.info("СЦЕНАРИЙ 1: Полное обучение с нуля")
    logger.info("="*80)

    for iterations in [100, 500, 1000, 2000]:
        logger.info(f"\n[iterations={iterations}]")

        model = CatBoostRegressor(
            iterations=iterations,
            learning_rate=0.03,
            depth=8,
            l2_leaf_reg=3,
            task_type='CPU',
            thread_count=4,  # Типичный ноутбук
            loss_function='RMSE',
            random_seed=42,
            verbose=False
        )

        start = time.time()
        train_pool = Pool(X_train_scaled, y_train)
        val_pool = Pool(X_val_scaled, y_val)
        model.fit(train_pool, eval_set=val_pool, verbose=False)
        elapsed = time.time() - start

        y_pred = model.predict(X_val_scaled)
        mae = mean_absolute_error(y_val, y_pred)

        logger.info(f"  Время: {elapsed:.1f}s ({elapsed/60:.1f} мин)")
        logger.info(f"  MAE: {mae:.2f}")
        logger.info(f"  Скорость: {iterations/elapsed:.1f} iter/s")

        results[f'full_train_{iterations}'] = {
            'time': elapsed,
            'mae': mae,
            'iterations': iterations
        }

    # ===== СЦЕНАРИЙ 2: Инкрементальное обучение (warm start) =====
    logger.info("\n" + "="*80)
    logger.info("СЦЕНАРИЙ 2: Инкрементальное обучение (дообучение)")
    logger.info("="*80)

    # Обучаем базовую модель
    logger.info("\nШаг 1: Обучаем базовую модель (1000 iter)...")
    base_model = CatBoostRegressor(
        iterations=1000,
        learning_rate=0.03,
        depth=8,
        l2_leaf_reg=3,
        task_type='CPU',
        thread_count=4,
        loss_function='RMSE',
        random_seed=42,
        verbose=False
    )

    start = time.time()
    base_model.fit(Pool(X_train_scaled, y_train), verbose=False)
    base_time = time.time() - start

    logger.info(f"  Базовая модель обучена за {base_time:.1f}s")

    # Дообучаем на новых данных
    logger.info("\nШаг 2: Дообучаем на новых данных (разное кол-во iter)...")

    # Симулируем новые данные (последние 10%)
    new_data_idx = int(0.9 * len(X_train))
    X_new = X_train.iloc[new_data_idx:]
    y_new = y_train.iloc[new_data_idx:]
    X_new_scaled = scaler.transform(X_new)

    logger.info(f"  Новых данных: {len(X_new)} записей")

    for extra_iter in [50, 100, 200]:
        incremental_model = CatBoostRegressor(
            iterations=extra_iter,
            learning_rate=0.03,
            depth=8,
            l2_leaf_reg=3,
            task_type='CPU',
            thread_count=4,
            loss_function='RMSE',
            random_seed=42,
            verbose=False
        )

        start = time.time()
        incremental_model.fit(
            Pool(X_new_scaled, y_new),
            init_model=base_model,  # Warm start!
            verbose=False
        )
        elapsed = time.time() - start

        y_pred = incremental_model.predict(X_val_scaled)
        mae = mean_absolute_error(y_val, y_pred)

        logger.info(f"\n  [+{extra_iter} iter дообучения]")
        logger.info(f"    Время дообучения: {elapsed:.1f}s")
        logger.info(f"    MAE после дообучения: {mae:.2f}")
        logger.info(f"    Общее время: {base_time + elapsed:.1f}s (база + дообучение)")
        logger.info(f"    Экономия: {((1000+extra_iter)/elapsed - 1000/base_time)*100:.0f}% быстрее чем полное")

        results[f'incremental_{extra_iter}'] = {
            'time': elapsed,
            'total_time': base_time + elapsed,
            'mae': mae,
            'extra_iterations': extra_iter
        }

    # ===== СЦЕНАРИЙ 3: Предикция =====
    logger.info("\n" + "="*80)
    logger.info("СЦЕНАРИЙ 3: Предикция на новых данных")
    logger.info("="*80)

    model = base_model

    # Разные размеры батчей
    for batch_size in [1, 10, 100, 1000, 10000]:
        X_batch = X_val_scaled[:batch_size]

        # Прогреваем
        _ = model.predict(X_batch)

        # Замеряем
        start = time.time()
        for _ in range(10):  # 10 итераций для стабильности
            _ = model.predict(X_batch)
        elapsed = (time.time() - start) / 10

        logger.info(f"\n  Batch size: {batch_size:>6d}")
        logger.info(f"    Время: {elapsed*1000:.2f} ms")
        logger.info(f"    Скорость: {batch_size/elapsed:.0f} predictions/s")

        results[f'predict_{batch_size}'] = {
            'time_ms': elapsed * 1000,
            'speed': batch_size / elapsed,
            'batch_size': batch_size
        }

    # Сохраняем результаты
    with open('benchmark_cpu_results.json', 'w') as f:
        import json
        json.dump(results, f, indent=2)

    logger.info("\n✓ Результаты сохранены: benchmark_cpu_results.json")

    return results


def print_summary(results):
    """Печать итоговой таблицы"""

    logger.info("\n" + "="*80)
    logger.info("ИТОГОВАЯ ТАБЛИЦА: Время обучения на CPU (4 cores)")
    logger.info("="*80)

    logger.info("\n1. ПОЛНОЕ ОБУЧЕНИЕ С НУЛЯ:")
    logger.info("-"*80)
    logger.info(f"{'Iterations':<15} {'Время':<15} {'Скорость':<20} {'MAE':<10}")
    logger.info("-"*80)

    for key in ['full_train_100', 'full_train_500', 'full_train_1000', 'full_train_2000']:
        if key in results:
            r = results[key]
            time_str = f"{r['time']:.1f}s" if r['time'] < 60 else f"{r['time']/60:.1f}m"
            speed = r['iterations'] / r['time']
            logger.info(f"{r['iterations']:<15} {time_str:<15} {speed:.1f} iter/s{' '*8} {r['mae']:.2f}")

    logger.info("\n2. ИНКРЕМЕНТАЛЬНОЕ ОБУЧЕНИЕ (дообучение):")
    logger.info("-"*80)
    logger.info(f"{'Дообучение':<15} {'Время':<15} {'Экономия':<20} {'MAE':<10}")
    logger.info("-"*80)

    base_time = results.get('full_train_1000', {}).get('time', 0)

    for key in ['incremental_50', 'incremental_100', 'incremental_200']:
        if key in results:
            r = results[key]
            time_str = f"{r['time']:.1f}s"

            # Сравниваем с полным обучением
            full_iter = 1000 + r['extra_iterations']
            estimated_full_time = base_time * (full_iter / 1000)
            savings = (1 - r['total_time'] / estimated_full_time) * 100

            logger.info(f"+{r['extra_iterations']} iter{' '*7} {time_str:<15} ~{savings:.0f}% быстрее{' '*6} {r['mae']:.2f}")

    logger.info("\n3. ПРЕДИКЦИЯ:")
    logger.info("-"*80)
    logger.info(f"{'Batch size':<15} {'Время (ms)':<15} {'Скорость':<20}")
    logger.info("-"*80)

    for key in ['predict_1', 'predict_10', 'predict_100', 'predict_1000', 'predict_10000']:
        if key in results:
            r = results[key]
            logger.info(f"{r['batch_size']:<15} {r['time_ms']:<15.2f} {r['speed']:.0f} pred/s")

    logger.info("\n" + "="*80)
    logger.info("ПРАКТИЧЕСКИЕ ОЦЕНКИ:")
    logger.info("="*80)

    logger.info("\nДЛЯ PRODUCTION на обычном сервере (4-8 CPU cores):")
    logger.info("  • Полное переобучение (1000 iter): ~15-20 минут")
    logger.info("  • Инкрементальное (100 iter): ~1-2 минуты")
    logger.info("  • Real-time предикция (1 sample): <1 ms")
    logger.info("  • Batch предикция (1000): ~10-20 ms")

    logger.info("\nДЛЯ ЛЭПТОПА (4 cores):")
    logger.info("  • Полное переобучение (1000 iter): ~20-25 минут")
    logger.info("  • Инкрементальное (100 iter): ~2-3 минуты")
    logger.info("  • Предикция: немного медленнее (1.5-2×)")

    logger.info("\nСРАВНЕНИЕ С A100 GPU:")
    if 'full_train_1000' in results:
        cpu_time = results['full_train_1000']['time']
        gpu_time = 4.1  # Из предыдущих экспериментов
        speedup = cpu_time / gpu_time

        logger.info(f"  • CPU (4 cores): {cpu_time:.1f}s = {cpu_time/60:.1f} минут")
        logger.info(f"  • GPU (A100): {gpu_time:.1f}s")
        logger.info(f"  • Ускорение: {speedup:.0f}× быстрее на GPU")

    logger.info("\n" + "="*80)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    results = benchmark_catboost_cpu()
    print_summary(results)
