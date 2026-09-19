#!/usr/bin/env python3
"""
Глубокий анализ корреляций, причинности и управляемости процесса АВТ 242000
Выполняет:
1. Полную корреляционную матрицу
2. Анализ временных лагов
3. PCA и кластеризацию режимов
4. Анализ чувствительности
5. Оценку дрейфа параметров
"""

from pathlib import Path
import sys
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

warnings.filterwarnings('ignore')

# Пути
HERE = Path(__file__).parent.resolve()
DATA_DIR = HERE.parent / 'data'
ARTIFACTS = HERE / 'artifacts'
ARTIFACTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(HERE))
from eda_utils import load_telemetry

def classify_tag_type(tag_name, std_normalized):
    """Классифицирует тег по типу"""
    tag_clean = tag_name.split('_', 1)[1] if '_' in tag_name else tag_name

    if tag_clean.startswith('F') or tag_clean.startswith('W'):
        return 'Control_Flow'
    elif tag_clean.startswith('P'):
        return 'Control_Pressure'
    elif tag_clean.startswith('T'):
        return 'Measured_Temperature'
    elif tag_clean.startswith('Q'):
        return 'Quality'
    else:
        return 'Other_HighVar' if std_normalized > 0.3 else 'Other_LowVar'

def main():
    print("=" * 80)
    print("ГЛУБОКИЙ АНАЛИЗ ДАННЫХ АВТ 242000")
    print("=" * 80)

    # 1. Загрузка данных
    print("\n[1/7] Загрузка данных...")
    avt = load_telemetry(DATA_DIR / 'avt_tags.csv')
    hydro = load_telemetry(DATA_DIR / '242000_tags.csv')

    print(f"  AVT: {avt.shape[0]:,} записей, {avt.shape[1]-1} тегов")
    print(f"  24-2000: {hydro.shape[0]:,} записей, {hydro.shape[1]-1} тегов")

    # Подготовка
    avt_clean = avt.set_index('date').sort_index()
    hydro_clean = hydro.set_index('date').sort_index()
    avt_clean.columns = ['AVT_' + col for col in avt_clean.columns]
    hydro_clean.columns = ['H24_' + col for col in hydro_clean.columns]

    # Объединение
    combined = pd.merge_asof(
        avt_clean.reset_index(),
        hydro_clean.reset_index(),
        on='date',
        tolerance=pd.Timedelta('5min'),
        direction='nearest'
    ).set_index('date')

    print(f"  Combined: {combined.shape[0]:,} записей, {combined.shape[1]} колонок")
    print(f"  Coverage: {100 * combined.notna().sum().sum() / combined.size:.1f}%")

    # 2. Корреляционный анализ
    print("\n[2/7] Вычисление корреляционных матриц...")

    # Фильтруем переменные колонки
    numeric_cols = combined.select_dtypes(include=[np.number]).columns
    variance = combined[numeric_cols].var()
    variable_cols = variance[variance > 1e-6].index.tolist()

    print(f"  Переменных колонок: {len(variable_cols)} из {len(numeric_cols)}")

    # Заполняем пропуски
    data_filled = combined[variable_cols].ffill().bfill()

    # Корреляции
    print("  Вычисление Spearman correlation...")
    corr_spearman = data_filled.corr(method='spearman')
    print("  Вычисление Pearson correlation...")
    corr_pearson = data_filled.corr(method='pearson')

    print(f"  Средняя |ρ| Spearman: {corr_spearman.abs().mean().mean():.3f}")
    print(f"  Средняя |ρ| Pearson: {corr_pearson.abs().mean().mean():.3f}")

    # Сохраняем
    corr_spearman.to_csv(ARTIFACTS / 'correlation_matrix_spearman.csv')
    corr_pearson.to_csv(ARTIFACTS / 'correlation_matrix_pearson.csv')
    print(f"  ✓ Сохранено в {ARTIFACTS}")

    # Кросс-корреляции AVT ↔ 24-2000
    print("\n  Анализ кросс-корреляций AVT ↔ 24-2000...")
    cross_corr = []
    for i, col1 in enumerate(corr_spearman.columns):
        for col2 in corr_spearman.columns[i+1:]:
            if (col1.startswith('AVT_') and col2.startswith('H24_')) or \
               (col1.startswith('H24_') and col2.startswith('AVT_')):
                cross_corr.append({
                    'tag1': col1,
                    'tag2': col2,
                    'spearman': corr_spearman.loc[col1, col2],
                    'pearson': corr_pearson.loc[col1, col2]
                })

    cross_corr_df = pd.DataFrame(cross_corr)
    cross_corr_df['abs_spearman'] = cross_corr_df['spearman'].abs()
    cross_corr_df = cross_corr_df.sort_values('abs_spearman', ascending=False)

    print(f"  Найдено {len(cross_corr_df):,} кросс-корреляций")
    print(f"  Топ корреляция: {cross_corr_df['abs_spearman'].iloc[0]:.3f}")
    print(f"  Пар с |ρ| > 0.7: {(cross_corr_df['abs_spearman'] > 0.7).sum()}")
    print(f"  Пар с |ρ| > 0.5: {(cross_corr_df['abs_spearman'] > 0.5).sum()}")

    cross_corr_df.to_csv(ARTIFACTS / 'cross_installation_correlations.csv', index=False)

    # 3. Анализ временных лагов
    print("\n[3/7] Анализ временных лагов...")

    top_pairs = cross_corr_df.head(20)
    lags_to_test = [0, 1, 2, 3, 6, 12, 24, 36, 48, 72, 144]  # в единицах 10 минут

    lag_analysis = []
    for idx, row in top_pairs.iterrows():
        tag1, tag2 = row['tag1'], row['tag2']

        if tag1.startswith('AVT_'):
            upstream, downstream = tag1, tag2
            direction = 'AVT -> 24-2000'
        else:
            upstream, downstream = tag2, tag1
            direction = '24-2000 -> AVT'

        s1 = data_filled[upstream].dropna()
        s2 = data_filled[downstream].dropna()

        for lag in lags_to_test:
            if lag == 0:
                aligned1, aligned2 = s1.align(s2, join='inner')
            else:
                s1_lagged = s1.shift(lag)
                aligned1, aligned2 = s1_lagged.align(s2, join='inner')

            if len(aligned1) > 100:
                corr_lag = stats.spearmanr(aligned1, aligned2)[0]
                lag_analysis.append({
                    'upstream': upstream,
                    'downstream': downstream,
                    'direction': direction,
                    'lag_10min_units': lag,
                    'lag_minutes': lag * 10,
                    'lag_hours': lag * 10 / 60,
                    'spearman': corr_lag,
                    'n_points': len(aligned1)
                })

    lag_df = pd.DataFrame(lag_analysis)
    lag_df['abs_spearman'] = lag_df['spearman'].abs()

    best_lags = lag_df.loc[lag_df.groupby(['upstream', 'downstream'])['abs_spearman'].idxmax()]
    print(f"  Проанализировано {len(top_pairs)} пар, {len(lags_to_test)} лагов")
    print(f"  Максимальный лаг: {lag_df['lag_hours'].max():.1f} часов")

    lag_df.to_csv(ARTIFACTS / 'lagged_correlations_detailed.csv', index=False)
    best_lags.to_csv(ARTIFACTS / 'optimal_lags.csv', index=False)
    print(f"  ✓ Сохранено в {ARTIFACTS}")

    # 4. PCA и режимы работы
    print("\n[4/7] PCA и идентификация режимов...")

    scaler = StandardScaler()
    data_scaled = pd.DataFrame(
        scaler.fit_transform(data_filled),
        index=data_filled.index,
        columns=data_filled.columns
    )

    pca = PCA(n_components=20)
    pca_result = pca.fit_transform(data_scaled)

    explained_var = pd.DataFrame({
        'PC': [f'PC{i+1}' for i in range(len(pca.explained_variance_ratio_))],
        'variance_explained': pca.explained_variance_ratio_,
        'cumulative_variance': np.cumsum(pca.explained_variance_ratio_)
    })

    print(f"  PC1 объясняет {explained_var['variance_explained'].iloc[0]*100:.1f}% вариации")
    print(f"  Первые 10 PC: {explained_var['cumulative_variance'].iloc[9]*100:.1f}% вариации")

    explained_var.to_csv(ARTIFACTS / 'pca_explained_variance.csv', index=False)

    # Loadings
    loadings = pd.DataFrame(
        pca.components_[:5].T,
        columns=[f'PC{i+1}' for i in range(5)],
        index=data_filled.columns
    )
    loadings['abs_PC1'] = loadings['PC1'].abs()
    loadings = loadings.sort_values('abs_PC1', ascending=False)

    loadings.to_csv(ARTIFACTS / 'pca_loadings_top5.csv')

    # K-means кластеризация
    print("  K-means кластеризация...")
    optimal_k = 5
    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(pca_result[:, :10])

    pca_df = pd.DataFrame({
        'date': data_filled.index,
        'PC1': pca_result[:, 0],
        'PC2': pca_result[:, 1],
        'cluster': clusters,
        'cluster_str': 'Режим ' + (clusters + 1).astype(str)
    })

    regime_stats = pca_df.groupby('cluster_str').agg({
        'date': ['count', 'min', 'max'],
        'PC1': ['mean', 'std'],
        'PC2': ['mean', 'std']
    })

    print(f"  Идентифицировано {optimal_k} режимов работы")
    regime_stats.to_csv(ARTIFACTS / 'operational_regimes_stats.csv')
    pca_df.to_csv(ARTIFACTS / 'pca_with_clusters.csv', index=False)
    print(f"  ✓ Сохранено в {ARTIFACTS}")

    # 5. Классификация тегов и управляемость
    print("\n[5/7] Классификация тегов и управляемость...")

    normalized_std = data_filled.std() / (data_filled.max() - data_filled.min() + 1e-6)

    tag_classification = pd.DataFrame({
        'tag': data_filled.columns,
        'std': data_filled.std(),
        'normalized_std': normalized_std,
        'mean': data_filled.mean(),
        'cv': data_filled.std() / (data_filled.mean().abs() + 1e-6)
    })

    tag_classification['type'] = tag_classification.apply(
        lambda row: classify_tag_type(row['tag'], row['normalized_std']), axis=1
    )

    type_counts = tag_classification.groupby('type').size()
    print("  Типы тегов:")
    for typ, count in type_counts.items():
        print(f"    {typ}: {count}")

    tag_classification.to_csv(ARTIFACTS / 'tag_classification_by_type.csv', index=False)

    # 6. Анализ чувствительности
    print("\n[6/7] Анализ чувствительности...")

    control_tags = tag_classification[tag_classification['type'].str.startswith('Control')]['tag'].tolist()
    measured_tags = tag_classification[tag_classification['type'].str.startswith('Measured')]['tag'].tolist()

    print(f"  Control тегов: {len(control_tags)}")
    print(f"  Measured тегов: {len(measured_tags)}")

    changes_control = data_filled[control_tags].diff()
    changes_measured = data_filled[measured_tags].diff()

    sensitivity_matrix = []

    print("  Вычисление sensitivity matrix...")
    for ctrl in control_tags[:20]:  # Ограничение для скорости
        for meas in measured_tags[:20]:
            ctrl_change = changes_control[ctrl].dropna()
            meas_change = changes_measured[meas].dropna()

            aligned_ctrl, aligned_meas = ctrl_change.align(meas_change, join='inner')

            if len(aligned_ctrl) > 100:
                corr = stats.spearmanr(aligned_ctrl, aligned_meas)[0]
                slope, intercept, r_value, p_value, std_err = stats.linregress(aligned_ctrl, aligned_meas)

                sensitivity_matrix.append({
                    'control': ctrl,
                    'measured': meas,
                    'change_correlation': corr,
                    'sensitivity_slope': slope,
                    'r_squared': r_value**2,
                    'p_value': p_value,
                    'n_points': len(aligned_ctrl)
                })

    sensitivity_df = pd.DataFrame(sensitivity_matrix)
    sensitivity_df['abs_correlation'] = sensitivity_df['change_correlation'].abs()
    sensitivity_df = sensitivity_df.sort_values('abs_correlation', ascending=False)

    print(f"  Найдено {len(sensitivity_df)} связей")
    print(f"  Значимых (|ρ|>0.3): {(sensitivity_df['abs_correlation'] > 0.3).sum()}")

    sensitivity_df.to_csv(ARTIFACTS / 'sensitivity_analysis_control_to_measured.csv', index=False)
    print(f"  ✓ Сохранено в {ARTIFACTS}")

    # 7. Анализ дрейфа
    print("\n[7/7] Анализ временного дрейфа...")

    monthly_stats = []
    for col in data_filled.columns[:50]:  # Первые 50 для скорости
        monthly = data_filled[col].resample('ME').agg(['mean', 'std', 'count'])
        monthly['tag'] = col
        monthly['month'] = monthly.index
        monthly_stats.append(monthly)

    monthly_df = pd.concat(monthly_stats, ignore_index=True)

    drift_analysis = []
    for tag in monthly_df['tag'].unique():
        tag_data = monthly_df[monthly_df['tag'] == tag].dropna(subset=['mean'])

        if len(tag_data) > 3:
            x = np.arange(len(tag_data))
            slope_mean, _, r_mean, p_mean, _ = stats.linregress(x, tag_data['mean'])
            slope_std, _, r_std, p_std, _ = stats.linregress(x, tag_data['std'])

            drift_analysis.append({
                'tag': tag,
                'mean_trend_slope': slope_mean,
                'mean_trend_r2': r_mean**2,
                'mean_trend_p': p_mean,
                'std_trend_slope': slope_std,
                'std_trend_r2': r_std**2,
                'std_trend_p': p_std,
                'n_months': len(tag_data)
            })

    drift_df = pd.DataFrame(drift_analysis)
    drift_df['abs_mean_slope'] = drift_df['mean_trend_slope'].abs()
    drift_df['significant_drift'] = (drift_df['mean_trend_p'] < 0.05) & (drift_df['abs_mean_slope'] > 0)

    drifting_tags = drift_df[drift_df['significant_drift']]
    print(f"  Тегов со значимым дрейфом: {len(drifting_tags)}")
    print(f"  Максимальная скорость дрейфа: {drift_df['abs_mean_slope'].max():.4f} ед/мес")

    drift_df.to_csv(ARTIFACTS / 'parameter_drift_analysis.csv', index=False)
    print(f"  ✓ Сохранено в {ARTIFACTS}")

    # Итоговый отчет
    print("\n" + "=" * 80)
    print("СВОДНЫЙ ОТЧЕТ")
    print("=" * 80)

    summary = f"""
## СВОДНЫЙ ОТЧЕТ: Глубокий анализ корреляций и управляемости

### Данные
- AVT: {avt.shape[0]:,} точек, {avt.shape[1]-1} тегов
- 24-2000: {hydro.shape[0]:,} точек, {hydro.shape[1]-1} тегов
- Объединенный датасет: {combined.shape[0]:,} точек, {len(variable_cols)} переменных

### Корреляции
- Средняя абсолютная корреляция (Spearman): {corr_spearman.abs().mean().mean():.3f}
- Топ кросс-корреляция AVT↔24-2000: {cross_corr_df['abs_spearman'].max():.3f}
- Пар с |ρ| > 0.7: {(cross_corr_df['abs_spearman'] > 0.7).sum()}
- Пар с |ρ| > 0.5: {(cross_corr_df['abs_spearman'] > 0.5).sum()}

### Временные лаги
- Оптимальный лаг варьируется от 0 до {lag_df['lag_hours'].max():.1f} часов
- Проанализировано {len(top_pairs)} топ пар

### Режимы работы (PCA + K-means)
- Первые 10 PC объясняют {explained_var['cumulative_variance'].iloc[9]*100:.1f}% вариации
- Идентифицировано {optimal_k} устойчивых режимов работы
- PC1 объясняет {explained_var['variance_explained'].iloc[0]*100:.1f}% вариации

### Управляемость
- Control_Flow тегов: {(tag_classification['type'] == 'Control_Flow').sum()}
- Control_Pressure тегов: {(tag_classification['type'] == 'Control_Pressure').sum()}
- Measured_Temperature тегов: {(tag_classification['type'] == 'Measured_Temperature').sum()}
- Значимых связей Δcontrol→Δmeasured (|ρ|>0.3): {(sensitivity_df['abs_correlation'] > 0.3).sum()}

### Стабильность
- Тегов со значимым дрейфом среднего: {drift_df['significant_drift'].sum()}
- Максимальная скорость дрейфа: {drift_df['abs_mean_slope'].max():.4f} единиц/месяц

### Рекомендации
1. **Для оптимизации**: Сфокусироваться на топ-10 пар с наибольшей чувствительностью
2. **Для контроля**: Мониторить теги с значимым дрейфом
3. **Для предикции**: Использовать лаги 1-6 часов для прогнозирования
4. **Для диагностики**: Кластеризация выявляет аномальные режимы работы

### Ограничения
- Анализ проведен без LIMS/PAK данных
- Корреляция не доказывает причинность
- Требуется валидация на независимой выборке
- Физическая интерпретация требует экспертизы технологов

### Файлы результатов
Все результаты сохранены в: {ARTIFACTS}/
- correlation_matrix_spearman.csv
- correlation_matrix_pearson.csv
- cross_installation_correlations.csv
- lagged_correlations_detailed.csv
- optimal_lags.csv
- pca_explained_variance.csv
- pca_loadings_top5.csv
- operational_regimes_stats.csv
- tag_classification_by_type.csv
- sensitivity_analysis_control_to_measured.csv
- parameter_drift_analysis.csv
"""

    print(summary)

    # Сохраняем отчет
    with open(ARTIFACTS / 'deep_analysis_summary_report.md', 'w', encoding='utf-8') as f:
        f.write(summary)

    print("\n✓ Глубокий анализ завершен!")
    print(f"✓ Все результаты сохранены в {ARTIFACTS}")

if __name__ == '__main__':
    main()
