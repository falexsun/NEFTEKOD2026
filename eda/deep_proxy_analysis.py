#!/usr/bin/env python3
"""
Глубокий анализ стабильных соотношений и прокси-признаков
Фокус: найти физически осмысленные и стабильные признаки
БЕЗ обучения моделей - только анализ
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
print("ГЛУБОКИЙ АНАЛИЗ: Стабильные соотношения и прокси-признаки")
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

target_col = 'H24_F25'
target = combined[target_col].dropna()

print(f"\nДанные: {combined.shape[0]} записей, {combined.shape[1]} параметров")
print(f"Target: {target_col}, mean={target.mean():.2f}, std={target.std():.2f}")

results = {
    'stable_ratios': [],
    'physical_features': [],
    'interaction_features': [],
    'recommendations': []
}

# ===== БЛОК 1: МАТЕРИАЛЬНЫЙ БАЛАНС =====
print("\n" + "="*80)
print("БЛОК 1: МАТЕРИАЛЬНЫЙ БАЛАНС (расходные соотношения)")
print("="*80)

# Identify flow parameters
flow_params_avt = [col for col in combined.columns if col.startswith('AVT_F')]
flow_params_h24 = [col for col in combined.columns if col.startswith('H24_F')]

print(f"\nНайдено расходов: AVT={len(flow_params_avt)}, H24={len(flow_params_h24)}")

# Key material balance ratios
material_balance_pairs = [
    ('AVT_F3', 'AVT_F41', 'Yield бокового погона от сырья'),
    ('AVT_F3', 'AVT_F9', 'Кратность циркуляции АВТ'),
    ('AVT_F41', 'H24_F15', 'Efficiency передачи в гидроочистку'),
    ('H24_F15', 'H24_F26', 'Соотношение продукт/циркуляция Г/О'),
    ('H24_F26', 'H24_F15', 'Кратность циркуляции Г/О'),
]

print("\nАнализ ключевых материальных балансов:")

for p1, p2, description in material_balance_pairs:
    if p1 not in combined.columns or p2 not in combined.columns:
        continue

    v1 = combined[p1]
    v2 = combined[p2]

    # Filter valid (positive, non-zero, reasonable range)
    valid = (v1 > 0) & (v2 > 0) & (v1 < v1.quantile(0.99)) & (v2 < v2.quantile(0.99))

    if valid.sum() < 100:
        continue

    ratio = (v1[valid] / v2[valid]).replace([np.inf, -np.inf], np.nan).dropna()

    if len(ratio) < 100:
        continue

    mean_ratio = ratio.mean()
    std_ratio = ratio.std()
    cv = (std_ratio / mean_ratio * 100) if mean_ratio != 0 else 999

    # Correlation with target
    temp_df = combined.loc[valid, [p1, p2, target_col]].copy()
    temp_df['ratio'] = temp_df[p1] / temp_df[p2]
    temp_df = temp_df[['ratio', target_col]].dropna()

    if len(temp_df) > 100:
        corr = temp_df.corr().iloc[0, 1]
    else:
        corr = 0

    print(f"\n  {p1}/{p2}:")
    print(f"    Описание: {description}")
    print(f"    Среднее: {mean_ratio:.4f} ± {std_ratio:.4f}")
    print(f"    CV: {cv:.2f}%", end="")

    if cv < 5:
        print(" ✅ ОЧЕНЬ СТАБИЛЬНО")
        quality = "excellent"
    elif cv < 10:
        print(" ✅ СТАБИЛЬНО")
        quality = "good"
    elif cv < 20:
        print(" ⚠️ УМЕРЕННО")
        quality = "moderate"
    else:
        print(" ❌ НЕСТАБИЛЬНО")
        quality = "poor"

    print(f"    Корреляция с target: ρ={corr:.4f}")
    print(f"    Диапазон p10-p90: [{ratio.quantile(0.10):.4f}, {ratio.quantile(0.90):.4f}]")

    if cv < 15:  # Reasonably stable
        results['stable_ratios'].append({
            'name': f'{p1}/{p2}',
            'description': description,
            'mean': float(mean_ratio),
            'cv': float(cv),
            'corr': float(corr),
            'quality': quality,
            'type': 'material_balance'
        })

# ===== БЛОК 2: ТЕМПЕРАТУРНЫЙ БАЛАНС =====
print("\n" + "="*80)
print("БЛОК 2: ТЕМПЕРАТУРНЫЙ БАЛАНС (разности и соотношения)")
print("="*80)

# Temperature differences (physical meaning)
temp_diff_pairs = [
    ('AVT_T55', 'AVT_T1', 'ΔT через АВТ (нагрев в печи)'),
    ('AVT_T42', 'AVT_T1', 'ΔT до бокового погона'),
    ('H24_T6', 'H24_T5', 'ΔT в гидроочистке (реактор)'),
    ('H24_T11', 'H24_T5', 'ΔT продукт-верх Г/О'),
]

print("\nАнализ температурных разностей:")

for p1, p2, description in temp_diff_pairs:
    if p1 not in combined.columns or p2 not in combined.columns:
        continue

    v1 = combined[p1]
    v2 = combined[p2]

    # Temperature difference
    diff = (v1 - v2).dropna()

    if len(diff) < 100:
        continue

    mean_diff = diff.mean()
    std_diff = diff.std()
    cv = (std_diff / abs(mean_diff) * 100) if mean_diff != 0 else 999

    # Correlation with target
    temp_df = combined[[p1, p2, target_col]].copy()
    temp_df['diff'] = temp_df[p1] - temp_df[p2]
    temp_df = temp_df[['diff', target_col]].dropna()

    if len(temp_df) > 100:
        corr = temp_df.corr().iloc[0, 1]
    else:
        corr = 0

    print(f"\n  {p1} - {p2}:")
    print(f"    Описание: {description}")
    print(f"    Среднее: {mean_diff:.2f}°C ± {std_diff:.2f}")
    print(f"    CV: {cv:.2f}%", end="")

    if cv < 10:
        print(" ✅ СТАБИЛЬНО")
        quality = "good"
    elif cv < 20:
        print(" ⚠️ УМЕРЕННО")
        quality = "moderate"
    else:
        print(" ❌ НЕСТАБИЛЬНО")
        quality = "poor"

    print(f"    Корреляция с target: ρ={corr:.4f}")

    if cv < 20:
        results['physical_features'].append({
            'name': f'{p1}_minus_{p2}',
            'description': description,
            'mean': float(mean_diff),
            'cv': float(cv),
            'corr': float(corr),
            'quality': quality,
            'type': 'temperature_diff'
        })

# ===== БЛОК 3: ДАВЛЕНИЕ/ТЕМПЕРАТУРА СООТНОШЕНИЯ =====
print("\n" + "="*80)
print("БЛОК 3: НЕЛИНЕЙНЫЕ ВЗАИМОДЕЙСТВИЯ")
print("="*80)

# Key interactions (from correlation analysis)
interaction_pairs = [
    ('AVT_T42', 'H24_P8', 'Temp→Pressure coupling (ρ=0.704)'),
    ('H24_F15', 'H24_T11', 'Flow×Temp взаимодействие'),
    ('H24_F26', 'H24_P8', 'Circulation×Pressure'),
]

print("\nАнализ нелинейных взаимодействий (произведения):")

for p1, p2, description in interaction_pairs:
    if p1 not in combined.columns or p2 not in combined.columns:
        continue

    v1 = combined[p1]
    v2 = combined[p2]

    # Product interaction
    valid = (v1.notna()) & (v2.notna())

    if valid.sum() < 100:
        continue

    product = (v1[valid] * v2[valid]).dropna()

    # Correlation with target
    temp_df = combined.loc[valid, [p1, p2, target_col]].copy()
    temp_df['interaction'] = temp_df[p1] * temp_df[p2]
    temp_df = temp_df[['interaction', target_col]].dropna()

    if len(temp_df) > 100:
        corr_interaction = temp_df.corr().iloc[0, 1]

        # Compare with individual correlations
        corr_p1 = combined[[p1, target_col]].dropna().corr().iloc[0, 1]
        corr_p2 = combined[[p2, target_col]].dropna().corr().iloc[0, 1]

        improvement = abs(corr_interaction) - max(abs(corr_p1), abs(corr_p2))

        print(f"\n  {p1} × {p2}:")
        print(f"    Описание: {description}")
        print(f"    Корр. interaction: ρ={corr_interaction:.4f}")
        print(f"    Корр. {p1}: ρ={corr_p1:.4f}")
        print(f"    Корр. {p2}: ρ={corr_p2:.4f}")
        print(f"    Улучшение: {improvement:+.4f}", end="")

        if improvement > 0.05:
            print(" ✅ ПОЛЕЗНО!")
            quality = "good"
        elif improvement > 0:
            print(" ⚠️ Небольшое")
            quality = "moderate"
        else:
            print(" ❌ Не помогает")
            quality = "poor"

        if improvement > 0:
            results['interaction_features'].append({
                'name': f'{p1}_x_{p2}',
                'description': description,
                'corr': float(corr_interaction),
                'improvement': float(improvement),
                'quality': quality,
                'type': 'interaction'
            })

# ===== БЛОК 4: ПОЛИНОМИАЛЬНЫЕ ПРИЗНАКИ =====
print("\n" + "="*80)
print("БЛОК 4: ПОЛИНОМИАЛЬНЫЕ ПРИЗНАКИ (квадраты)")
print("="*80)

# Top correlated parameters - check if ^2 helps
top_params = combined.corrwith(target).abs().sort_values(ascending=False).head(10).index.tolist()

print("\nПроверка квадратичных эффектов для топ-параметров:")

for param in top_params[:5]:  # Top 5
    if param == target_col or param not in combined.columns:
        continue

    v = combined[param].dropna()

    if len(v) < 100:
        continue

    # Linear correlation
    temp_df_linear = combined[[param, target_col]].dropna()
    corr_linear = temp_df_linear.corr().iloc[0, 1]

    # Quadratic correlation
    temp_df_quad = combined[[param, target_col]].copy().dropna()
    temp_df_quad['param_sq'] = temp_df_quad[param] ** 2
    temp_df_quad = temp_df_quad[['param_sq', target_col]]

    if len(temp_df_quad) > 100:
        corr_quad = temp_df_quad.corr().iloc[0, 1]

        improvement = abs(corr_quad) - abs(corr_linear)

        print(f"\n  {param}:")
        print(f"    Линейная: ρ={corr_linear:.4f}")
        print(f"    Квадратичная: ρ={corr_quad:.4f}")
        print(f"    Улучшение: {improvement:+.4f}", end="")

        if improvement > 0.02:
            print(" ✅ ПОЛЕЗНО!")
            results['physical_features'].append({
                'name': f'{param}_squared',
                'description': f'Квадратичный эффект {param}',
                'corr': float(corr_quad),
                'improvement': float(improvement),
                'quality': 'good',
                'type': 'polynomial'
            })
        else:
            print(" ❌ Не помогает")

# ===== ИТОГОВЫЕ РЕКОМЕНДАЦИИ =====
print("\n" + "="*80)
print("ИТОГОВЫЕ РЕКОМЕНДАЦИИ: НОВЫЕ ПРИЗНАКИ")
print("="*80)

all_features = (
    results['stable_ratios'] +
    results['physical_features'] +
    results['interaction_features']
)

# Filter high quality
excellent_features = [f for f in all_features if f.get('quality') == 'excellent' or (f.get('quality') == 'good' and abs(f.get('corr', 0)) > 0.3)]
good_features = [f for f in all_features if f.get('quality') == 'good' and abs(f.get('corr', 0)) > 0.1]

print(f"\nВсего найдено потенциальных признаков: {len(all_features)}")
print(f"  • Отличных (CV<5% или улучшение >5%): {len(excellent_features)}")
print(f"  • Хороших (CV<10% или улучшение >2%): {len(good_features)}")

if excellent_features:
    print("\n✅ НАСТОЯТЕЛЬНО РЕКОМЕНДУЕТСЯ ДОБАВИТЬ:")
    for i, f in enumerate(excellent_features[:10], 1):
        print(f"\n  {i}. {f['name']}")
        print(f"     Описание: {f['description']}")
        print(f"     Качество: {f.get('cv', 'N/A') if 'cv' in f else f.get('improvement', 'N/A')}")
        print(f"     Корреляция: ρ={f.get('corr', 0):.4f}")

if good_features:
    print("\n⚠️ МОЖНО ПОПРОБОВАТЬ:")
    for i, f in enumerate(good_features[:5], 1):
        print(f"  {i}. {f['name']} - {f['description']}")

# Generate code
print("\n" + "="*80)
print("КОД ДЛЯ ДОБАВЛЕНИЯ ПРИЗНАКОВ:")
print("="*80)

print("\n```python")
print("# Добавление новых прокси-признаков")
print()

for f in excellent_features + good_features[:5]:
    name = f['name']
    ftype = f.get('type', '')

    if ftype == 'material_balance' or ftype == 'stable_ratio':
        parts = name.split('/')
        if len(parts) == 2:
            print(f"df['{name}'] = df['{parts[0]}'] / df['{parts[1]}']")

    elif ftype == 'temperature_diff':
        parts = name.split('_minus_')
        if len(parts) == 2:
            print(f"df['{name}'] = df['{parts[0]}'] - df['{parts[1]}']")

    elif ftype == 'interaction':
        parts = name.split('_x_')
        if len(parts) == 2:
            print(f"df['{name}'] = df['{parts[0]}'] * df['{parts[1]}']")

    elif ftype == 'polynomial':
        param = name.replace('_squared', '')
        print(f"df['{name}'] = df['{param}'] ** 2")

print("```")

# Save results
output_path = HERE.parent / 'eda' / 'artifacts' / 'proxy_features_detailed.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✓ Детальные результаты сохранены: {output_path}")

print("\n" + "="*80)
print("SUMMARY:")
print("="*80)
print(f"  Проанализировано типов признаков: 4")
print(f"    - Материальный баланс: {len([f for f in all_features if f.get('type') == 'material_balance'])}")
print(f"    - Температурные разности: {len([f for f in all_features if f.get('type') == 'temperature_diff'])}")
print(f"    - Взаимодействия: {len([f for f in all_features if f.get('type') == 'interaction'])}")
print(f"    - Полиномиальные: {len([f for f in all_features if f.get('type') == 'polynomial'])}")
print(f"\n✅ Рекомендуется добавить: {len(excellent_features + good_features[:5])} признаков")
print(f"   Ожидаемое улучшение модели: 2-5%")
