"""
Анализ проблемы h=3: почему regression не работает на eval.

Гипотезы:
1. Distribution shift между train/val/cal и eval 2026
2. Признаки h=3 слишком зашумлены (30-минутная история)
3. Модель переобучилась на артефакты train/cal
4. Нужны другие признаки для долгосрочного прогноза
"""
import pandas as pd
import numpy as np
from pathlib import Path

def load_data(root):
    df = pd.read_csv(root / 'data' / '242000_tags.csv')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Фильтрация кодов
    mask = (df['Q21'] > 0) & (df['Q21'] < 50)
    df = df[mask].copy()

    return df

def create_h3_target(df):
    """Создать таргет через 3 часа (18 шагов по 10 мин)"""
    df['Q21_h3'] = df['Q21'].shift(-18)
    df['Q21_delta_h3'] = df['Q21_h3'] - df['Q21']
    return df

def split_data(df):
    splits = {
        'train': df[df['date'].dt.year <= 2023].copy(),
        'val': df[df['date'].dt.year == 2024].copy(),
        'cal': df[df['date'].dt.year == 2025].copy(),
        'eval': df[df['date'].dt.year == 2026].copy(),
    }
    return splits

def analyze_distribution_shift(splits):
    """Проверить distribution shift Q21 и дельт"""
    print("\n" + "="*60)
    print("DISTRIBUTION SHIFT ANALYSIS")
    print("="*60)

    for name, data in splits.items():
        valid = data.dropna(subset=['Q21_h3'])
        if len(valid) == 0:
            continue

        q21_stats = valid['Q21'].describe()
        delta_stats = valid['Q21_delta_h3'].describe()

        print(f"\n{name.upper()}:")
        print(f"  N: {len(valid):,}")
        print(f"  Q21 mean: {q21_stats['mean']:.3f}, std: {q21_stats['std']:.3f}")
        print(f"  Q21 range: [{q21_stats['min']:.1f}, {q21_stats['max']:.1f}]")
        print(f"  Delta mean: {delta_stats['mean']:.3f}, std: {delta_stats['std']:.3f}")
        print(f"  Delta range: [{delta_stats['min']:.1f}, {delta_stats['max']:.1f}]")
        print(f"  Prevalence >10: {(valid['Q21_h3'] > 10).mean()*100:.1f}%")

def analyze_volatility(splits):
    """Проверить волатильность по периодам"""
    print("\n" + "="*60)
    print("VOLATILITY ANALYSIS")
    print("="*60)

    for name, data in splits.items():
        valid = data.dropna(subset=['Q21_h3'])
        if len(valid) == 0:
            continue

        # Подсчитать % больших изменений
        abs_delta = valid['Q21_delta_h3'].abs()
        large_changes = (abs_delta > 2).mean() * 100
        huge_changes = (abs_delta > 5).mean() * 100

        print(f"\n{name.upper()}:")
        print(f"  |Δ| > 2 ppm: {large_changes:.1f}%")
        print(f"  |Δ| > 5 ppm: {huge_changes:.1f}%")
        print(f"  Max |Δ|: {abs_delta.max():.1f} ppm")

def analyze_autocorrelation(df):
    """Проверить автокорреляцию Q21"""
    print("\n" + "="*60)
    print("AUTOCORRELATION ANALYSIS")
    print("="*60)

    # Лаги в шагах (1 шаг = 10 мин)
    lags = [1, 6, 18, 36, 72]  # 10мин, 1ч, 3ч, 6ч, 12ч

    for lag in lags:
        q21_shifted = df['Q21'].shift(lag)
        corr = df['Q21'].corr(q21_shifted)
        hours = lag * 10 / 60
        print(f"  Lag {lag} steps ({hours:.1f}h): {corr:.3f}")

def main():
    root = Path('/Users/falexsun/code/Нефтекод')

    print("Loading data...")
    df = load_data(root)
    print(f"Loaded {len(df):,} samples after filtering")

    print("Creating h=3 target...")
    df = create_h3_target(df)

    print("Splitting data...")
    splits = split_data(df)

    analyze_distribution_shift(splits)
    analyze_volatility(splits)
    analyze_autocorrelation(df)

    # Финальные выводы
    print("\n" + "="*60)
    print("CONCLUSIONS")
    print("="*60)

    eval_data = splits['eval'].dropna(subset=['Q21_h3'])
    train_data = splits['train'].dropna(subset=['Q21_h3'])

    eval_std = eval_data['Q21_delta_h3'].abs().std()
    train_std = train_data['Q21_delta_h3'].abs().std()

    print(f"\nEval volatility: {eval_std:.3f} ppm")
    print(f"Train volatility: {train_std:.3f} ppm")
    print(f"Ratio: {eval_std/train_std:.2f}x")

    # Persistence baseline на eval
    eval_data['persistence_error'] = (eval_data['Q21_h3'] - eval_data['Q21']).abs()
    persistence_mae = eval_data['persistence_error'].mean()
    print(f"\nPersistence MAE on eval: {persistence_mae:.3f} ppm")

    # Теоретический предел
    print(f"\nТеоретический предел для MAE при h=3:")
    print(f"  Если |Δ| ~ {eval_std:.1f}, то MAE ≥ {eval_std*0.8:.2f} ppm")
    print(f"  Persistence = {persistence_mae:.3f} ppm")
    print(f"  Для улучшения нужно MAE < {persistence_mae:.3f} ppm")

if __name__ == '__main__':
    main()
