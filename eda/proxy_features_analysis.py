#!/usr/bin/env python3
"""
Анализ стабильных соотношений и прокси-признаков
Проверяем W70/F30 ≈ 0.78125 и ищем другие подобные паттерны
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats
import json

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'eda'))

from eda_utils import load_telemetry

# Load data
data_dir = ROOT / 'data'
avt = load_telemetry(data_dir / 'avt_tags.csv')
hydro = load_telemetry(data_dir / '242000_tags.csv')

print("="*80)
print("АНАЛИЗ СТАБИЛЬНЫХ СООТНОШЕНИЙ И ПРОКСИ-ПРИЗНАКОВ")
print("="*80)

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

print(f"Данные: {combined.shape[0]} записей, {combined.shape[1]} параметров")

# ===== АНАЛИЗ 1: W70/F30 соотношение =====
print("\n" + "="*80)
print("АНАЛИЗ 1: Проверка соотношения W70/F30")
print("="*80)

if 'AVT_W70' in combined.columns and 'AVT_F30' in combined.columns:
    # Calculate ratio
    w70 = combined['AVT_W70'].dropna()
    f30 = combined['AVT_F30'].dropna()

    # Only where both non-zero
    valid = (w70 != 0) & (f30 != 0)
    ratio = (w70[valid] / f30[valid]).dropna()

    print(f"\nW70/F30 соотношение:")
    print(f"  Записей: {len(ratio)}")
    print(f"  Среднее: {ratio.mean():.5f}")
    print(f"  Медиана: {ratio.median():.5f}")
    print(f"  Std: {ratio.std():.5f}")
    print(f"  CV (коэффициент вариации): {ratio.std()/ratio.mean()*100:.2f}%")
    print(f"  Min: {ratio.min():.5f}")
    print(f"  Max: {ratio.max():.5f}")
    print(f"  p01: {ratio.quantile(0.01):.5f}")
    print(f"  p99: {ratio.quantile(0.99):.5f}")
    print(f"  p10-p90 диапазон: [{ratio.quantile(0.10):.5f}, {ratio.quantile(0.90):.5f}]")

    # Check stability
    cv = ratio.std() / ratio.mean() * 100

    if cv < 5:
        print(f"\n✅ ОЧЕНЬ СТАБИЛЬНОЕ соотношение (CV={cv:.2f}% < 5%)")
        print("   Рекомендация: ОБЯЗАТЕЛЬНО использовать как признак!")
    elif cv < 10:
        print(f"\n✅ СТАБИЛЬНОЕ соотношение (CV={cv:.2f}% < 10%)")
        print("   Рекомендация: Использовать как признак")
    elif cv < 20:
        print(f"\n⚠️ УМЕРЕННО СТАБИЛЬНОЕ (CV={cv:.2f}% < 20%)")
        print("   Рекомендация: Можно попробовать")
    else:
        print(f"\n❌ НЕСТАБИЛЬНОЕ (CV={cv:.2f}% >= 20%)")
        print("   Рекомендация: Не использовать")

    # Correlation with target
    target_col = 'H24_F25'
    if target_col in combined.columns:
        # Align indices
        combined_temp = combined.copy()
        combined_temp['W70_F30_ratio'] = w70 / f30

        corr = combined_temp[['W70_F30_ratio', target_col]].dropna().corr().iloc[0, 1]
        print(f"\n  Корреляция с target (H24_F25): ρ={corr:.4f}")

        if abs(corr) > 0.3:
            print(f"  ✅ СИЛЬНАЯ корреляция - признак ПОЛЕЗЕН!")
        elif abs(corr) > 0.1:
            print(f"  ⚠️ Умеренная корреляция - может быть полезен")
        else:
            print(f"  ❌ Слабая корреляция - малополезен")

# ===== АНАЛИЗ 2: Поиск других стабильных соотношений =====
print("\n" + "="*80)
print("АНАЛИЗ 2: Поиск других стабильных соотношений (прокси-признаков)")
print("="*80)

# Candidates for ratios (параметры одного типа)
flow_params = [col for col in combined.columns if col.startswith('F') or col.startswith('AVT_F') or col.startswith('H24_F')]
temp_params = [col for col in combined.columns if col.startswith('T') or col.startswith('AVT_T') or col.startswith('H24_T')]
pressure_params = [col for col in combined.columns if col.startswith('P') or col.startswith('AVT_P') or col.startswith('H24_P')]

print(f"\nНайдено параметров:")
print(f"  Расходы (F): {len(flow_params)}")
print(f"  Температуры (T): {len(temp_params)}")
print(f"  Давления (P): {len(pressure_params)}")

def find_stable_ratios(params, combined, max_pairs=50):
    """Find stable ratios between parameters"""
    results = []

    # Try all pairs
    from itertools import combinations
    pairs = list(combinations(params, 2))[:max_pairs]  # Limit for speed

    for p1, p2 in pairs:
        if p1 not in combined.columns or p2 not in combined.columns:
            continue

        v1 = combined[p1].dropna()
        v2 = combined[p2].dropna()

        # Only where both non-zero
        valid = (v1 != 0) & (v2 != 0)

        if valid.sum() < 100:  # Need enough data
            continue

        ratio = (v1[valid] / v2[valid]).replace([np.inf, -np.inf], np.nan).dropna()

        if len(ratio) < 100:
            continue

        # Calculate stability
        cv = ratio.std() / abs(ratio.mean()) * 100 if ratio.mean() != 0 else 999

        # Only stable ones
        if cv < 15:  # CV < 15% - стабильное
            # Check correlation with target
            target_col = 'H24_F25'
            if target_col in combined.columns:
                temp_df = pd.DataFrame({
                    'ratio': v1 / v2,
                    'target': combined[target_col]
                }).dropna()

                if len(temp_df) > 100:
                    corr = temp_df.corr().iloc[0, 1]
                else:
                    corr = 0
            else:
                corr = 0

            results.append({
                'param1': p1,
                'param2': p2,
                'name': f'{p1}/{p2}',
                'mean': float(ratio.mean()),
                'std': float(ratio.std()),
                'cv': float(cv),
                'p01': float(ratio.quantile(0.01)),
                'p99': float(ratio.quantile(0.99)),
                'n_samples': len(ratio),
                'corr_with_target': float(corr)
            })

    return results

# Find stable flow ratios
print("\n[1/3] Поиск стабильных соотношений расходов (F/F)...")
flow_ratios = find_stable_ratios(flow_params, combined, max_pairs=50)
print(f"  Найдено стабильных: {len(flow_ratios)}")

# Find stable temperature ratios
print("[2/3] Поиск стабильных соотношений температур (T/T)...")
temp_ratios = find_stable_ratios(temp_params, combined, max_pairs=50)
print(f"  Найдено стабильных: {len(temp_ratios)}")

# Find stable pressure ratios
print("[3/3] Поиск стабильных соотношений давлений (P/P)...")
pressure_ratios = find_stable_ratios(pressure_params, combined, max_pairs=50)
print(f"  Найдено стабильных: {len(pressure_ratios)}")

# Combine all
all_ratios = flow_ratios + temp_ratios + pressure_ratios

# Sort by CV (most stable first)
all_ratios_sorted = sorted(all_ratios, key=lambda x: x['cv'])

print("\n" + "="*80)
print("ТОП-20 САМЫХ СТАБИЛЬНЫХ СООТНОШЕНИЙ:")
print("="*80)
print(f"{'#':<3} {'Соотношение':<35} {'CV%':<8} {'Корр.':<8} {'Диапазон p01-p99':<25}")
print("-"*80)

for i, r in enumerate(all_ratios_sorted[:20], 1):
    name_short = r['name'][:34]
    range_str = f"{r['p01']:.3f}–{r['p99']:.3f}"

    # Mark by quality
    if r['cv'] < 5 and abs(r['corr_with_target']) > 0.3:
        mark = "🏆"
    elif r['cv'] < 10:
        mark = "✅"
    else:
        mark = "⚠️"

    print(f"{i:<3} {mark} {name_short:<33} {r['cv']:<7.2f} {r['corr_with_target']:<7.3f} {range_str:<25}")

# ===== АНАЛИЗ 3: Физические соотношения =====
print("\n" + "="*80)
print("АНАЛИЗ 3: Физически осмысленные соотношения")
print("="*80)

physical_ratios = []

# Material balance ratios
print("\n1. МАТЕРИАЛЬНЫЙ БАЛАНС:")

# AVT: вход vs выход
if 'AVT_F3' in combined.columns and 'AVT_F41' in combined.columns:
    # F3 = сырье, F41 = боковой погон
    v1 = combined['AVT_F3'].dropna()
    v2 = combined['AVT_F41'].dropna()
    valid = (v1 != 0) & (v2 != 0)
    ratio = (v2[valid] / v1[valid]).dropna()

    if len(ratio) > 100:
        cv = ratio.std() / ratio.mean() * 100
        print(f"  AVT_F41/F3 (боковой погон / сырье):")
        print(f"    Среднее: {ratio.mean():.3f} (CV={cv:.2f}%)")
        print(f"    Интерпретация: доля бокового погона от сырья")

        physical_ratios.append({
            'name': 'AVT_F41/F3',
            'description': 'Yield бокового погона',
            'mean': float(ratio.mean()),
            'cv': float(cv)
        })

# Energy efficiency
print("\n2. ЭНЕРГЕТИЧЕСКАЯ ЭФФЕКТИВНОСТЬ:")

# Temperature difference across unit
if 'AVT_T1' in combined.columns and 'AVT_T55' in combined.columns:
    delta_t = (combined['AVT_T55'] - combined['AVT_T1']).dropna()

    print(f"  ΔT через АВТ (T55-T1):")
    print(f"    Среднее: {delta_t.mean():.1f}°C (CV={delta_t.std()/delta_t.mean()*100:.2f}%)")

# Circulation ratios
print("\n3. ЦИРКУЛЯЦИОННЫЕ КОЭФФИЦИЕНТЫ:")

if 'AVT_F9' in combined.columns and 'AVT_F3' in combined.columns:
    v1 = combined['AVT_F9'].dropna()
    v2 = combined['AVT_F3'].dropna()
    valid = (v1 != 0) & (v2 != 0)
    ratio = (v1[valid] / v2[valid]).dropna()

    if len(ratio) > 100:
        cv = ratio.std() / ratio.mean() * 100
        print(f"  AVT_F9/F3 (циркуляция / сырье):")
        print(f"    Среднее: {ratio.mean():.3f} (CV={cv:.2f}%)")
        print(f"    Интерпретация: кратность циркуляции")

# ===== ИТОГОВАЯ ТАБЛИЦА =====
print("\n" + "="*80)
print("РЕКОМЕНДАЦИИ ПО НОВЫМ ПРИЗНАКАМ:")
print("="*80)

# Top candidates
top_candidates = [r for r in all_ratios_sorted[:10] if r['cv'] < 10]

print(f"\n✅ РЕКОМЕНДУЕТСЯ ДОБАВИТЬ ({len(top_candidates)} признаков):")
for r in top_candidates:
    print(f"\n  • {r['name']}")
    print(f"      CV: {r['cv']:.2f}% (очень стабильное)")
    print(f"      Корреляция с target: ρ={r['corr_with_target']:.3f}")
    print(f"      Диапазон: [{r['p01']:.3f}, {r['p99']:.3f}]")

# Save results
output = {
    'w70_f30_analysis': {
        'mean': float(ratio.mean()) if 'ratio' in locals() else None,
        'cv': float(cv) if 'cv' in locals() else None,
        'recommendation': 'use' if cv < 10 else 'optional'
    },
    'stable_ratios': all_ratios_sorted[:20],
    'top_candidates': top_candidates
}

output_path = HERE.parent / 'eda' / 'artifacts' / 'proxy_features_analysis.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\n✓ Результаты сохранены: {output_path}")

print("\n" + "="*80)
print("ИТОГО:")
print("="*80)
print(f"  Проанализировано соотношений: {len(all_ratios)}")
print(f"  Стабильных (CV < 15%): {len([r for r in all_ratios if r['cv'] < 15])}")
print(f"  Очень стабильных (CV < 5%): {len([r for r in all_ratios if r['cv'] < 5])}")
print(f"  С сильной корреляцией (|ρ| > 0.3): {len([r for r in all_ratios if abs(r['corr_with_target']) > 0.3])}")
print(f"\n✅ Рекомендуется добавить в модель: {len(top_candidates)} новых признаков")
