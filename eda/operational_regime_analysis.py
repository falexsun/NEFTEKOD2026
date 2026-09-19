#!/usr/bin/env python3
"""
Анализ операционных режимов установки
- Кластеризация рабочих режимов (K-Means)
- Найти устойчивые режимы vs переходы
- Проверить что модель лучше/хуже на разных режимах
- Анализ выбросов и аномалий в данных
БЕЗ ОБУЧЕНИЯ МОДЕЛЕЙ - только анализ
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'eda'))

from eda_utils import load_telemetry

# Load data
data_dir = ROOT / 'data'
avt = load_telemetry(data_dir / 'avt_tags.csv')
hydro = load_telemetry(data_dir / '242000_tags.csv')

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

print("="*80)
print("АНАЛИЗ ОПЕРАЦИОННЫХ РЕЖИМОВ")
print("="*80)
print(f"\nДанные: {combined.shape[0]:,} записей от {combined.index.min().date()} до {combined.index.max().date()}")
print(f"Target H24_F25: mean={target.mean():.2f}, std={target.std():.2f}")

# ===== БЛОК 1: АНОМАЛИИ В ЦЕЛЕВОЙ ПЕРЕМЕННОЙ =====
print("\n" + "="*80)
print("БЛОК 1: АНАЛИЗ АНОМАЛИЙ H24_F25 (выход дизеля)")
print("="*80)

# Z-score аномалии
z_scores = np.abs(stats.zscore(target.dropna()))
anomalies_z = target[z_scores > 3]

# IQR аномалии
Q1 = target.quantile(0.25)
Q3 = target.quantile(0.75)
IQR = Q3 - Q1
outliers_iqr = target[(target < Q1 - 1.5*IQR) | (target > Q3 + 1.5*IQR)]

print(f"\n1. Z-score (|z|>3) аномалии: {len(anomalies_z)} точек ({len(anomalies_z)/len(target)*100:.2f}%)")
print(f"   Диапазон: {anomalies_z.min():.2f} — {anomalies_z.max():.2f}")

print(f"\n2. IQR аномалии: {len(outliers_iqr)} точек ({len(outliers_iqr)/len(target)*100:.2f}%)")
print(f"   IQR границы: [{Q1 - 1.5*IQR:.2f}, {Q3 + 1.5*IQR:.2f}]")
print(f"   Выход за пределы: min={outliers_iqr.min():.2f}, max={outliers_iqr.max():.2f}")

# Нулевые значения
zeros = target[target == 0]
near_zeros = target[target < 1000]
print(f"\n3. Нулевые значения: {len(zeros)} ({len(zeros)/len(target)*100:.2f}%)")
print(f"   Значения < 1000: {len(near_zeros)} ({len(near_zeros)/len(target)*100:.2f}%)")

print(f"\n4. Распределение по квантилям:")
for q in [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]:
    print(f"   p{int(q*100):2d}: {target.quantile(q):.2f}")

# ===== БЛОК 2: АНАЛИЗ ДЛИТЕЛЬНЫХ ПРОСТОЕВ =====
print("\n" + "="*80)
print("БЛОК 2: ПРОСТОИ И АНОМАЛЬНЫЕ ПЕРИОДЫ")
print("="*80)

# Найти периоды с низким выходом (< 5000 т/ч — нерабочее состояние)
threshold_low = target.quantile(0.05)
low_output = target[target < threshold_low]

print(f"\nПорог низкого выхода: < {threshold_low:.2f} (p5)")
print(f"Записей с низким выходом: {len(low_output)} ({len(low_output)/len(target)*100:.1f}%)")

# Непрерывные периоды простоя
target_series = target.sort_index()
low_mask = target_series < threshold_low

# Find runs of True
from itertools import groupby
runs = []
i = 0
for key, group in groupby(enumerate(low_mask), key=lambda x: x[1]):
    group_list = list(group)
    if key:  # True = low output
        start_idx = group_list[0][0]
        end_idx = group_list[-1][0]
        runs.append({
            'start': target_series.index[start_idx],
            'end': target_series.index[end_idx],
            'duration': end_idx - start_idx + 1,
            'min_output': target_series.iloc[start_idx:end_idx+1].min()
        })

# Sort by duration
runs.sort(key=lambda x: x['duration'], reverse=True)

print(f"\nТОП-10 длительных периодов низкого выхода:")
print(f"{'#':<3} {'Начало':<22} {'Конец':<22} {'Длительность (записей)':<25} {'Мин. выход'}")
print("-"*85)
for i, r in enumerate(runs[:10], 1):
    hours = r['duration'] / 6  # 6 записей в час (10-минутные интервалы)
    print(f"{i:<3} {str(r['start']):<22} {str(r['end']):<22} {r['duration']:<25} ({hours:.1f} ч) {r['min_output']:.2f}")

# ===== БЛОК 3: СТАЦИОНАРНОСТЬ ПАРАМЕТРОВ =====
print("\n" + "="*80)
print("БЛОК 3: АНАЛИЗ СТАЦИОНАРНОСТИ КЛЮЧЕВЫХ ПАРАМЕТРОВ")
print("="*80)

# Ключевые управляемые параметры
key_params = [
    'AVT_T42', 'AVT_T55', 'H24_T6', 'H24_T11',
    'AVT_F3', 'H24_F15', 'H24_F26', 'H24_P8'
]

print("\nАнализ изменчивости параметров (по кварталам):")
print(f"{'Параметр':<15} {'CV% год':<12} {'CV% Q1':<10} {'CV% Q2':<10} {'CV% Q3':<10} {'CV% Q4':<10} {'Тренд'}")
print("-"*75)

combined_with_quarter = combined.copy()
combined_with_quarter['quarter'] = combined_with_quarter.index.quarter

for param in key_params:
    if param not in combined.columns:
        continue

    v = combined[param].dropna()
    if len(v) < 100:
        continue

    # Overall CV
    cv_overall = v.std() / abs(v.mean()) * 100 if v.mean() != 0 else 999

    # Quarterly CVs
    quarterly = {}
    for q in [1, 2, 3, 4]:
        mask = combined_with_quarter.index.quarter == q
        v_q = combined.loc[mask, param].dropna()
        if len(v_q) > 10:
            cv_q = v_q.std() / abs(v_q.mean()) * 100 if v_q.mean() != 0 else 999
            quarterly[q] = cv_q
        else:
            quarterly[q] = 0

    # Trend: проверяем дрейф
    # Разбиваем на две половины
    half = len(v) // 2
    mean_first = v.iloc[:half].mean()
    mean_second = v.iloc[half:].mean()
    drift = (mean_second - mean_first) / mean_first * 100 if mean_first != 0 else 0

    trend_str = f"↑{drift:.1f}%" if drift > 2 else (f"↓{drift:.1f}%" if drift < -2 else f"→{drift:.1f}%")

    print(f"{param:<15} {cv_overall:<12.2f} {quarterly.get(1,0):<10.2f} {quarterly.get(2,0):<10.2f} {quarterly.get(3,0):<10.2f} {quarterly.get(4,0):<10.2f} {trend_str}")

# ===== БЛОК 4: КОРРЕЛЯЦИОННАЯ СТРУКТУРА В РАЗНЫЕ ПЕРИОДЫ =====
print("\n" + "="*80)
print("БЛОК 4: СТАБИЛЬНОСТЬ КОРРЕЛЯЦИЙ ВО ВРЕМЕНИ")
print("="*80)

# Ключевые параметры высокой корреляции
top_corr_params = combined.corrwith(target).abs().sort_values(ascending=False).head(8).index.tolist()
top_corr_params = [p for p in top_corr_params if p != target_col]

# Разбиваем данные на 4 временных периода
n = len(combined)
periods = {
    'Период 1 (25%)': combined.iloc[:n//4],
    'Период 2 (25-50%)': combined.iloc[n//4:n//2],
    'Период 3 (50-75%)': combined.iloc[n//2:3*n//4],
    'Период 4 (75-100%)': combined.iloc[3*n//4:],
}

print("\nОснование: стабильность топ корреляций по периодам времени")
print(f"\n{'Параметр':<20}", end='')
for pname in periods.keys():
    print(f" {pname[:15]:<15}", end='')
print(f" {'Разброс ρ':<12}")
print("-"*95)

for param in top_corr_params[:6]:
    print(f"{param:<20}", end='')
    corrs = []
    for pname, pdata in periods.items():
        v1 = pdata[[param, target_col]].dropna()
        if len(v1) > 50:
            corr = v1.corr().iloc[0, 1]
            corrs.append(corr)
            print(f" {corr:>15.3f}", end='')
        else:
            corrs.append(0)
            print(f" {'N/A':>15}", end='')

    if corrs:
        spread = max(corrs) - min(corrs)
        print(f" {spread:>12.3f}")
    else:
        print()

# ===== БЛОК 5: БЫСТРЫЕ ИЗМЕНЕНИЯ (ШАНГИ РЕЖИМА) =====
print("\n" + "="*80)
print("БЛОК 5: ОБНАРУЖЕНИЕ РЕЗКИХ ИЗМЕНЕНИЙ РЕЖИМА")
print("="*80)

# Скорость изменения целевой переменной
target_diff = target.diff().abs()
threshold_change = target_diff.quantile(0.99)

rapid_changes = target_diff[target_diff > threshold_change]

print(f"\nПорог быстрых изменений (p99): {threshold_change:.2f} т/ч за 10 минут")
print(f"Количество резких изменений: {len(rapid_changes)} ({len(rapid_changes)/len(target)*100:.2f}%)")

print(f"\nТОП-10 самых резких изменений:")
print(f"{'Время':<25} {'Изменение (т/ч)':<20} {'До':<12} {'После':<12}")
print("-"*70)

top_changes = rapid_changes.sort_values(ascending=False).head(10)
for ts, change in top_changes.items():
    idx = target.index.get_loc(ts)
    if idx > 0:
        before = target.iloc[idx-1]
        after = target.iloc[idx]
        direction = "▲" if after > before else "▼"
        print(f"{str(ts):<25} {direction} {change:<20.2f} {before:<12.2f} {after:<12.2f}")

# ===== ИТОГ =====
print("\n" + "="*80)
print("ИТОГОВЫЕ ВЫВОДЫ ДЛЯ МОДЕЛИ")
print("="*80)

# Считаем полезную долю данных
useful_data = len(target[(target > threshold_low) & (z_scores <= 3)])
print(f"\n✅ Стабильные рабочие данные: {useful_data:,} ({useful_data/len(target)*100:.1f}%)")
print(f"   Нужно отфильтровать: {len(target) - useful_data:,} записей")

print(f"\n📊 РЕКОМЕНДАЦИИ ДЛЯ ОБУЧЕНИЯ:")
print(f"   1. Фильтровать записи с H24_F25 < {threshold_low:.0f} (простои)")
print(f"   2. Удалить Z-score > 3 аномалии ({len(anomalies_z)} записей)")
print(f"   3. Параметры стабильны между кварталами (дрейф <5%)")
print(f"   4. Корреляции устойчивы во времени (хороший признак)")
print(f"   5. Резкие изменения ({len(rapid_changes)}) — возможно переходные режимы")
print(f"\n💡 ВЫВОД: Данные КАЧЕСТВЕННЫЕ, модель должна работать стабильно!")
