#!/usr/bin/env python3
"""
Сезонный анализ: влияние времени года на температуры и выходы
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

# Paths
HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'eda'))

from eda_utils import load_telemetry

# Load data
data_dir = ROOT / 'data'
avt = load_telemetry(data_dir / 'avt_tags.csv')
hydro = load_telemetry(data_dir / '242000_tags.csv')

print("="*80)
print("СЕЗОННЫЙ АНАЛИЗ: Влияние времени года")
print("="*80)

# Prepare data
avt['date'] = pd.to_datetime(avt['date'])
hydro['date'] = pd.to_datetime(hydro['date'])

avt['month'] = avt['date'].dt.month
avt['season'] = avt['month'].map({
    12: 'Зима', 1: 'Зима', 2: 'Зима',
    3: 'Весна', 4: 'Весна', 5: 'Весна',
    6: 'Лето', 7: 'Лето', 8: 'Лето',
    9: 'Осень', 10: 'Осень', 11: 'Осень'
})

hydro['month'] = hydro['date'].dt.month
hydro['season'] = hydro['month'].map({
    12: 'Зима', 1: 'Зима', 2: 'Зима',
    3: 'Весна', 4: 'Весна', 5: 'Весна',
    6: 'Лето', 7: 'Лето', 8: 'Лето',
    9: 'Осень', 10: 'Осень', 11: 'Осень'
})

print(f"\nДанные: {len(avt)} записей")
print(f"Период: {avt['date'].min()} - {avt['date'].max()}")
print(f"Длительность: {(avt['date'].max() - avt['date'].min()).days} дней")

# ===== АНАЛИЗ 1: Сезонные средние температуры =====
print("\n" + "="*80)
print("АНАЛИЗ 1: Средние температуры по сезонам")
print("="*80)

# Выбираем температурные параметры
temp_params_avt = [col for col in avt.columns if col.startswith('T') and col not in ['date', 'month', 'season']]
temp_params_h24 = [col for col in hydro.columns if col.startswith('T') and col not in ['date', 'month', 'season']]

print(f"\nАВТ: {len(temp_params_avt)} температурных параметров")
print(f"Гидроочистка: {len(temp_params_h24)} температурных параметров")

# Ключевые температуры для анализа
key_temps_avt = ['T42', 'T48', 'T55']  # Боковой погон, стриппинг, мазут
key_temps_h24 = ['T5', 'T6', 'T11']    # Верх, газойль, продукт

results_seasonal_temp = []

for param in key_temps_avt:
    if param in avt.columns:
        seasonal_stats = avt.groupby('season')[param].agg(['mean', 'std', 'min', 'max', 'count'])

        print(f"\n{param} (АВТ):")
        print(seasonal_stats.round(2))

        # ANOVA test
        groups = [avt[avt['season'] == s][param].dropna() for s in ['Зима', 'Весна', 'Лето', 'Осень']]
        f_stat, p_value = stats.f_oneway(*groups)

        significant = "✅ ДА" if p_value < 0.05 else "❌ НЕТ"
        print(f"ANOVA: F={f_stat:.2f}, p-value={p_value:.4f} → Сезонный эффект: {significant}")

        # Разница зима-лето
        winter_mean = seasonal_stats.loc['Зима', 'mean']
        summer_mean = seasonal_stats.loc['Лето', 'mean']
        diff = summer_mean - winter_mean
        diff_pct = (diff / winter_mean * 100) if winter_mean != 0 else 0

        print(f"Разница Лето-Зима: {diff:.2f}°C ({diff_pct:+.1f}%)")

        results_seasonal_temp.append({
            'param': f'AVT_{param}',
            'winter_mean': winter_mean,
            'summer_mean': summer_mean,
            'diff': diff,
            'diff_pct': diff_pct,
            'p_value': p_value,
            'significant': p_value < 0.05
        })

for param in key_temps_h24:
    if param in hydro.columns:
        seasonal_stats = hydro.groupby('season')[param].agg(['mean', 'std', 'min', 'max', 'count'])

        print(f"\n{param} (Гидроочистка):")
        print(seasonal_stats.round(2))

        groups = [hydro[hydro['season'] == s][param].dropna() for s in ['Зима', 'Весна', 'Лето', 'Осень']]
        f_stat, p_value = stats.f_oneway(*groups)

        significant = "✅ ДА" if p_value < 0.05 else "❌ НЕТ"
        print(f"ANOVA: F={f_stat:.2f}, p-value={p_value:.4f} → Сезонный эффект: {significant}")

        winter_mean = seasonal_stats.loc['Зима', 'mean']
        summer_mean = seasonal_stats.loc['Лето', 'mean']
        diff = summer_mean - winter_mean
        diff_pct = (diff / winter_mean * 100) if winter_mean != 0 else 0

        print(f"Разница Лето-Зима: {diff:.2f}°C ({diff_pct:+.1f}%)")

        results_seasonal_temp.append({
            'param': f'H24_{param}',
            'winter_mean': winter_mean,
            'summer_mean': summer_mean,
            'diff': diff,
            'diff_pct': diff_pct,
            'p_value': p_value,
            'significant': p_value < 0.05
        })

# ===== АНАЛИЗ 2: Влияние сезона на выход продукта =====
print("\n" + "="*80)
print("АНАЛИЗ 2: Влияние сезона на выход продукта (H24_F25)")
print("="*80)

if 'F25' in hydro.columns:
    target_seasonal = hydro.groupby('season')['F25'].agg(['mean', 'std', 'min', 'max', 'count'])

    print("\nВыход продукта по сезонам:")
    print(target_seasonal.round(2))

    # ANOVA
    groups_target = [hydro[hydro['season'] == s]['F25'].dropna() for s in ['Зима', 'Весна', 'Лето', 'Осень']]
    f_stat, p_value = stats.f_oneway(*groups_target)

    significant = "✅ ДА" if p_value < 0.05 else "❌ НЕТ"
    print(f"\nANOVA: F={f_stat:.2f}, p-value={p_value:.4f}")
    print(f"Сезонный эффект на выход: {significant}")

    winter_mean = target_seasonal.loc['Зима', 'mean']
    summer_mean = target_seasonal.loc['Лето', 'mean']
    diff = summer_mean - winter_mean
    diff_pct = (diff / winter_mean * 100) if winter_mean != 0 else 0

    print(f"\nРазница Лето-Зима: {diff:.2f} т/ч ({diff_pct:+.1f}%)")

    if abs(diff_pct) > 1.0:
        print("⚠️ ЗНАЧИМОЕ ВЛИЯНИЕ: Сезон влияет на выход более чем на 1%")
    else:
        print("✅ Влияние незначительное: < 1%")

# ===== АНАЛИЗ 3: Корреляция температуры окружающей среды =====
print("\n" + "="*80)
print("АНАЛИЗ 3: Оценка влияния внешней температуры")
print("="*80)

# Нет прямых данных о температуре окружающей среды, но можем оценить по сезону
print("\nПредположение: Средние температуры по сезонам в России (условно):")
print("  Зима: -10°C")
print("  Весна: +10°C")
print("  Лето: +20°C")
print("  Осень: +5°C")

# Проверим есть ли параметры, которые могут быть связаны с охлаждением
cooling_params = []
for param in avt.columns:
    if param in ['T1', 'T2', 'T3']:  # Верх колонны - могут зависеть от охлаждения
        cooling_params.append(('AVT', param))

for param in hydro.columns:
    if param in ['T5']:  # Верх колонны Г/О - зависит от охлаждения
        cooling_params.append(('H24', param))

if cooling_params:
    print(f"\nПараметры потенциально зависящие от внешнего охлаждения: {len(cooling_params)}")

    for unit, param in cooling_params:
        df = avt if unit == 'AVT' else hydro
        if param in df.columns:
            seasonal = df.groupby('season')[param].mean()
            print(f"\n{unit}_{param}:")
            for season in ['Зима', 'Весна', 'Лето', 'Осень']:
                if season in seasonal.index:
                    print(f"  {season}: {seasonal[season]:.2f}°C")

# ===== ИТОГОВАЯ ТАБЛИЦА =====
print("\n" + "="*80)
print("ИТОГОВАЯ ТАБЛИЦА: Сезонные эффекты")
print("="*80)

df_results = pd.DataFrame(results_seasonal_temp)
df_results = df_results.sort_values('diff', key=abs, ascending=False)

print("\nТоп-10 параметров с наибольшим сезонным эффектом:")
print(df_results.head(10).to_string(index=False))

# Статистика
significant_count = df_results['significant'].sum()
total_count = len(df_results)

print(f"\nВсего проанализировано: {total_count} температурных параметров")
print(f"Со значимым сезонным эффектом (p<0.05): {significant_count} ({significant_count/total_count*100:.1f}%)")

# Save
output_path = HERE.parent / 'eda' / 'artifacts' / 'seasonal_analysis.csv'
df_results.to_csv(output_path, index=False)
print(f"\n✓ Результаты сохранены: {output_path}")

print("\n" + "="*80)
print("ВЫВОДЫ:")
print("="*80)

# Автоматические выводы
avg_diff = df_results['diff'].abs().mean()
max_diff = df_results['diff'].abs().max()
max_diff_param = df_results.loc[df_results['diff'].abs().idxmax(), 'param']

print(f"\n1. ТЕМПЕРАТУРЫ:")
print(f"   - Средняя сезонная разница: {avg_diff:.2f}°C")
print(f"   - Максимальная разница: {max_diff:.2f}°C ({max_diff_param})")
print(f"   - {significant_count}/{total_count} параметров имеют значимый сезонный эффект")

if significant_count / total_count > 0.5:
    print("\n   ⚠️ ВЫВОД: Сезон ЗНАЧИМО влияет на температуры процесса")
    print("   РЕКОМЕНДАЦИЯ: Учитывать сезон в модели (добавить season features)")
else:
    print("\n   ✓ ВЫВОД: Сезонный эффект незначителен")
    print("   РЕКОМЕНДАЦИЯ: Сезон можно не учитывать в базовой модели")

print("\n" + "="*80)
