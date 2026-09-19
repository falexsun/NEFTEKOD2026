# Q21 Multihorizon Improvement Plan — h=3 и h=6 часов

**Дата:** 16 сентября 2026  
**Цель:** Улучшить качество прогнозов для горизонтов 3 и 6 часов, которые сейчас хуже persistence baseline

---

## Текущая проблема

### Baseline результаты (из `q21_target_asymmetric_v3_20260915`)

| Горизонт | MAE модели | MAE persistence | Результат |
|----------|-----------|-----------------|-----------|
| 1 час | 0,725 ppm | 0,844 ppm | ✅ +14% improvement |
| 3 часа | 1,387 ppm | 1,443 ppm | ⚠️ +4% improvement |
| 6 часов | 1,735 ppm | 1,588 ppm | ❌ -9% worse than baseline |

**Проблема:** Модель для h=6 хуже простого "взять текущее значение", модель для h=3 едва обгоняет baseline.

---

## Причины проблемы (гипотезы)

1. **Horizon-agnostic features**
   - Все горизонты использовали одинаковые признаки
   - Для h=3,6 нужны более длинные окна rolling статистик

2. **Недостаточная временная информация**
   - Не учитывались velocity (скорость изменения) и acceleration (ускорение)
   - Не использовались экспоненциальные веса для старых наблюдений

3. **Слабые долгосрочные паттерны**
   - Q21 history ограничивался 24 часами
   - Для h=6 нужна история 48-120 часов

4. **Одиночная модель**
   - CatBoost один
   - Нет ансамблирования для снижения variance

5. **Fixed train/val split**
   - Не использовался walk-forward validation
   - Для долгого горизонта нужна проверка на последовательных периодах

---

## Стратегия улучшения

### 1. Horizon-Specific Feature Engineering

**Для h=3:**
- Short windows: 1, 2, 3 часа (mean, std, min, max)
- Medium windows: 6, 12, 24 часа (mean, EWMA)
- Long context: 48, 72 часа (mean)
- Velocity features: diff(1h), diff(2h), diff(3h)
- Acceleration features: diff2(1h), diff2(2h)

**Для h=6:**
- Short windows: 2, 4, 6 часов
- Medium windows: 12, 24, 48 часов
- Long context: 72, 96, 120 часов
- Velocity features: diff(2h), diff(4h), diff(6h)
- Acceleration features: diff2(2h), diff2(4h)

**Ключевое отличие:** каждый горизонт получает свой набор признаков, оптимизированный под его временной масштаб.

### 2. Advanced Temporal Features

```python
# Exponentially weighted moving average
for hours in [6, 12, 24, 48]:
    span = hours * 6
    ewm = process.ewm(span=span, min_periods=span//4).mean()
    features[f"{col}_ewm_{hours}h"] = ewm

# Velocity (first derivative)
for hours in [1, 2, 3, 6]:
    shift = hours * 6
    features[f"{col}_velocity_{hours}h"] = process.diff(shift)

# Acceleration (second derivative)
for hours in [1, 2, 3]:
    shift = hours * 6
    diff1 = process.diff(shift)
    features[f"{col}_accel_{hours}h"] = diff1.diff(shift)
```

### 3. Ensemble Approach

**Комбинация моделей:**
- CatBoost (основная модель, лучше на табличных данных)
- LightGBM (быстрее, другая регуляризация)
- Weighted average с весами, оптимизированными на validation

**Ожидаемый эффект:** снижение variance, более стабильные прогнозы.

```python
# Ensemble weights optimization
for w_cb in [0.0, 0.1, ..., 1.0]:
    w_lgb = 1 - w_cb
    pred = w_cb * pred_cb + w_lgb * pred_lgb
    mae = mean_absolute_error(y_val, pred)
# Выбрать best weights
```

### 4. Proper Lag Structure для Q21

**Критически важно:** Q21 history должен быть правильно сдвинут, чтобы избежать data leakage.

```python
# Для прогноза на h часов вперёд:
lag_shift = horizon_hours * 6
q21_lagged = q21.shift(lag_shift)

# Все rolling statistics тоже применяются к lagged series
for hours in [1, 3, 6, 12, 24]:
    lagged_series = q21.shift(lag_shift)
    roll = lagged_series.rolling(f"{hours}h")
    features[f"Q21_hist_mean_{hours}h"] = roll.mean()
```

### 5. Better Evaluation

**Walk-forward validation** (опционально, если хватит времени):
- Train на 2023-2024
- Validate на первой половине 2025
- Calibrate на второй половине 2025
- Evaluate на 2026

Можно добавить несколько validation windows для проверки стабильности.

---

## Реализация

### Созданные файлы

1. **`train_q21_multihorizon_improved.py`**
   - Класс `HorizonSpecificFeatureBuilder` для каждого горизонта
   - Функция `create_ensemble_regressor()` для CatBoost + LightGBM
   - Функция `optimize_ensemble_weights()` для поиска оптимальных весов
   - Функция `train_single_horizon()` для обучения одного горизонта
   - Сохранение моделей и метрик

2. **`run_improved_training_remote.sh`**
   - Скрипт для запуска на GPU сервере
   - Автоматическая загрузка кода
   - Background training с логированием

3. **`test_multihorizon_features.py`**
   - Тесты feature builder локально
   - Проверка на data leakage

### Запуск обучения

```bash
cd /Users/falexsun/code/Нефтекод
./eda/run_improved_training_remote.sh
```

Или напрямую на сервере:

```bash
ssh faizov@37.75.249.204
cd /home/faizov/projects/NEFTECODE2026
source venv/bin/activate

python eda/train_q21_multihorizon_improved.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --horizons 3 6 \
  --run-id q21_improved_h36_20260916 \
  --gpu
```

---

## Ожидаемые результаты

### Целевые метрики

**Для h=3:**
- Текущий MAE: 1,387 ppm
- Persistence: 1,443 ppm
- **Цель:** MAE < 1,30 ppm (улучшение >10% vs persistence)

**Для h=6:**
- Текущий MAE: 1,735 ppm
- Persistence: 1,588 ppm
- **Цель:** MAE < 1,50 ppm (улучшение >5% vs persistence)

### Почему это реалистично

1. **Horizon-specific features** могут дать +3-5% improvement
   - Правильные временные окна критичны для долгих горизонтов

2. **EWMA и velocity features** могут дать +2-3%
   - Улавливают тренды, которые простое среднее пропускает

3. **Ensemble** может дать +1-2%
   - Снижение variance через усреднение разных моделей

4. **Proper Q21 lagging** может дать +2-4%
   - Избегаем leakage, но используем всю доступную историю

**Итого:** потенциальное улучшение 8-14%, что достаточно для обгона persistence.

---

## Метрики для оценки

### Основные

1. **MAE** (Mean Absolute Error)
   - Основная метрика, сравнение с persistence
   - Должна быть ниже, чем у persistence

2. **RMSE** (Root Mean Squared Error)
   - Штрафует большие ошибки сильнее
   - Важно для детекции outliers

3. **R²** (Coefficient of Determination)
   - Доля объяснённой дисперсии
   - Должна быть положительной (иначе хуже константного прогноза)

### Дополнительные

4. **Направленная точность** (directional accuracy)
   - % случаев, где модель правильно предсказала направление изменения
   - Важно для operational decisions

5. **Calibration** (reliability diagram)
   - Соответствие предсказанных и наблюдаемых значений
   - Для доверия к прогнозам

6. **Coverage** (для interval predictions)
   - Если делаем conformal prediction
   - % случаев, где истина попала в интервал

---

## Возможные дополнительные улучшения

Если базовый подход не даст нужного результата:

### 1. Multi-task Learning
- Одновременное обучение h=1, h=3, h=6
- Shared representations для всех горизонтов
- Специализированные головы для каждого

### 2. Sequence Models
- LSTM или Transformer для temporal dependencies
- Требует больше данных и GPU времени
- Может быть overkill для табличных данных

### 3. Quantile Regression Forests
- Альтернатива CatBoost для uncertainty quantification
- Может лучше работать на долгих горизонтах

### 4. Feature Selection
- SHAP-based feature importance на h=3,6
- Удаление шумных признаков
- Может снизить overfitting

### 5. Temporal Cross-Validation
- Несколько fold-ов на разных периодах 2025
- Более надёжная оценка качества
- Обнаружение seasonal patterns

---

## Timeline

**Этап 1:** Обучение базового улучшенного pipeline (2-4 часа GPU)
- [x] Код написан
- [ ] Запуск на GPU сервере
- [ ] Мониторинг training.log
- [ ] Скачивание результатов

**Этап 2:** Анализ результатов (30 минут)
- [ ] Сравнение с baseline
- [ ] Feature importance analysis
- [ ] Residuals analysis

**Этап 3:** Доработка (если нужно) (1-2 часа)
- [ ] Добавление дополнительных признаков
- [ ] Tuning гиперпараметров
- [ ] Ensemble weights adjustment

**Этап 4:** Интеграция в advisory system (30 минут)
- [ ] Экспорт лучших моделей
- [ ] Обновление inference pipeline
- [ ] Тестирование на demo данных

---

## Риски и митигация

### Риск 1: Overfitting на validation
**Митигация:** Использовать separate calibration set, не трогать evaluation до финального теста

### Риск 2: Не хватит GPU памяти
**Митигация:** Уменьшить max_depth или iterations, использовать gradient checkpointing

### Риск 3: Улучшение недостаточное
**Митигация:** Есть запасные стратегии (multi-task, LSTM, feature selection)

### Риск 4: Computational cost слишком высок
**Митигация:** Можно отключить LightGBM, использовать только CatBoost с лучшими features

---

## Выводы

Созданный pipeline имеет высокие шансы улучшить качество моделей для h=3 и h=6:

✅ **Horizon-specific features** — tailored для каждого временного масштаба  
✅ **Advanced temporal features** — velocity, acceleration, EWMA  
✅ **Ensemble approach** — снижение variance  
✅ **Proper lagging** — нет data leakage  
✅ **Comprehensive metrics** — полная оценка качества

Готов к запуску на GPU сервере для получения результатов!

---

**Следующие шаги:**

1. Запустить `./eda/run_improved_training_remote.sh`
2. Мониторить `tail -f eda/experiments/*/training.log` на сервере
3. После обучения скачать результаты и проанализировать
4. Интегрировать лучшие модели в advisory system

**Команда для мониторинга:**

```bash
ssh faizov@37.75.249.204 "tail -f /home/faizov/projects/NEFTECODE2026/eda/experiments/q21_improved_h36_*/training.log"
```
