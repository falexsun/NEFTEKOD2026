# Q21 Multihorizon Models — Готово к запуску

**Статус:** Все файлы подготовлены, готово к обучению на GPU  
**Дата:** 16 сентября 2026

---

## Созданные улучшения для h=3 и h=6

### 1. Новый training pipeline: `train_q21_multihorizon_improved.py`

**Ключевые улучшения vs baseline:**

#### A. Horizon-Specific Features (класс `HorizonSpecificFeatureBuilder`)

**Для каждого горизонта свой набор временных окон:**

```python
# h=3 часа
short_windows = [1, 2, 3]      # Короткие паттерны
medium_windows = [6, 12, 24]   # Средние тренды
long_windows = [48, 72]        # Долгосрочный контекст

# h=6 часов
short_windows = [2, 4, 6]      # Более широкие окна
medium_windows = [12, 24, 48]  # Расширенные тренды
long_windows = [72, 96, 120]   # Глубокая история
```

**Новые типы признаков:**
- Mean, std, min, max в каждом окне (не только mean/std как в baseline)
- Velocity (first derivative): `diff(1h)`, `diff(2h)`, `diff(3h)`
- Acceleration (second derivative): `diff2(1h)`, `diff2(2h)`
- EWMA (exponentially weighted moving average) для улавливания трендов

#### B. Правильный lagging для Q21 history

**Критическое отличие:**

```python
# Baseline: Q21 history не был сдвинут на forecast horizon
# Это могло создавать data leakage

# Improved: Q21 history сдвинут корректно
lag_shift = horizon_hours * 6
q21_features["Q21_lagged"] = q_clean.shift(lag_shift)

# Все rolling statistics применяются к lagged series
for hours in [1, 3, 6, 12, 24]:
    lagged_series = q_clean.shift(lag_shift)
    roll = lagged_series.rolling(f"{hours}h")
    q21_features[f"Q21_hist_mean_{hours}h"] = roll.mean()
```

#### C. Ensemble: CatBoost + LightGBM

**Два алгоритма вместо одного:**

```python
# CatBoost (основной)
cb_model = CatBoostRegressor(
    iterations=2000,
    learning_rate=0.03,
    depth=8,
    loss_function="MAE",
    task_type="GPU"
)

# LightGBM (дополнительный)
lgb_model = LGBMRegressor(
    n_estimators=2000,
    learning_rate=0.03,
    max_depth=8,
    objective="mae",
    device="gpu"
)

# Ensemble с оптимизированными весами
weights = optimize_ensemble_weights(predictions, y_val)
pred_ensemble = weights[0] * pred_cb + weights[1] * pred_lgb
```

**Ожидаемый эффект:** снижение variance, более стабильные прогнозы.

#### D. Comprehensive Metrics

```python
results = {
    "catboost": {
        "val_mae": ...,
        "eval_mae": ...,
        "val_rmse": ...,
        "eval_rmse": ...
    },
    "lightgbm": {...},
    "ensemble": {...},
    "persistence_baseline": {...}
}
```

---

## 2. Теоретическое обоснование улучшений

### Проблема baseline моделей

**h=3:**
- MAE 1,387 ppm vs persistence 1,443 ppm
- Только +4% improvement — слишком слабо
- **Причина:** generic features не улавливают 3-часовые паттерны

**h=6:**
- MAE 1,735 ppm vs persistence 1,588 ppm
- -9% worse — модель хуже наивного baseline!
- **Причина:** недостаточная долгосрочная информация

### Как улучшения решают проблему

| Улучшение | Эффект | Потенциал |
|-----------|--------|-----------|
| Horizon-specific windows | Правильный временной масштаб | +3-5% |
| Velocity/acceleration | Улавливание трендов | +2-3% |
| EWMA | Экспоненциальное затухание старых данных | +2-3% |
| Proper Q21 lagging | Устранение leakage, использование всей истории | +2-4% |
| Ensemble CB+LGB | Снижение variance | +1-2% |
| **ИТОГО** | | **+10-17%** |

**Целевые метрики:**
- h=3: MAE < 1,30 ppm (>10% improvement vs persistence 1,443)
- h=6: MAE < 1,50 ppm (>5% improvement vs persistence 1,588)

---

## 3. Команды для запуска

### Шаг 1: Загрузить скрипт

```bash
scp /Users/falexsun/code/Нефтекод/eda/train_q21_multihorizon_improved.py \
    faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/eda/
```

### Шаг 2: Подключиться и запустить

```bash
ssh faizov@37.75.249.204

cd /home/faizov/projects/NEFTECODE2026
source venv/bin/activate

# Проверить GPU
nvidia-smi

# Запустить обучение
nohup venv/bin/python eda/train_q21_multihorizon_improved.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --horizons 3 6 \
  --run-id q21_improved_h36_20260916 \
  --gpu \
  > eda/experiments/q21_improved_h36_20260916/training.log 2>&1 &

echo "Training PID: $!"

# Мониторить
tail -f eda/experiments/q21_improved_h36_20260916/training.log
```

### Шаг 3: После завершения — скачать результаты

```bash
# Проверить что обучение завершилось
ssh faizov@37.75.249.204 "ls -la /home/faizov/projects/NEFTECODE2026/eda/experiments/q21_improved_h36_20260916/"

# Скачать результаты
scp -r faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/eda/experiments/q21_improved_h36_20260916 \
    /Users/falexsun/code/Нефтекод/eda/experiments/
```

---

## 4. Ожидаемые результаты

### Структура output директории

```
q21_improved_h36_20260916/
├── manifest.json          # Общая информация о run
├── training.log           # Логи обучения
├── h3/                    # Результаты для h=3
│   ├── catboost.cbm       # CatBoost модель
│   ├── lightgbm.txt       # LightGBM модель
│   ├── results.json       # Метрики
│   └── feature_names.json # Список признаков
└── h6/                    # Результаты для h=6
    ├── catboost.cbm
    ├── lightgbm.txt
    ├── results.json
    └── feature_names.json
```

### Формат results.json

```json
{
  "horizon": 3,
  "n_features": 850,
  "catboost": {
    "val_mae": 1.25,
    "eval_mae": 1.28,
    "val_rmse": 1.65,
    "eval_rmse": 1.70
  },
  "lightgbm": {
    "val_mae": 1.27,
    "eval_mae": 1.30,
    "val_rmse": 1.68,
    "eval_rmse": 1.73
  },
  "ensemble": {
    "weights": [0.6, 0.4],
    "val_mae": 1.23,
    "eval_mae": 1.26,
    "val_rmse": 1.63,
    "eval_rmse": 1.68
  },
  "persistence_baseline": {
    "val_mae": 1.45,
    "eval_mae": 1.443
  }
}
```

---

## 5. Интерпретация результатов

### Успех если:

✅ **h=3:**
- Ensemble eval_mae < 1.30 ppm
- Improvement vs persistence > 10%
- RMSE также улучшился

✅ **h=6:**
- Ensemble eval_mae < 1.50 ppm
- Improvement vs persistence > 5%
- Модель обгоняет persistence (это критично!)

### Если результаты недостаточны:

**План Б — дополнительные улучшения:**

1. **Feature selection**
   - SHAP importance на h=3,6
   - Удалить bottom 20% features
   - Переобучить

2. **Hyperparameter tuning**
   - Grid search: depth [6,8,10], learning_rate [0.01,0.03,0.05]
   - Iterations [1500,2000,2500]

3. **Multi-task learning**
   - Одновременно h=1,3,6
   - Shared trunk + task heads

4. **Temporal cross-validation**
   - Walk-forward на 2025
   - 3-4 folds вместо одного validation

---

## 6. Интеграция в advisory system

После подтверждения качества:

```python
# Обновить model_bundle.py
class Q21ModelBundleMultiHorizon:
    def __init__(self, models_dir: Path):
        self.models = {}
        for h in [1, 3, 6]:
            self.models[h] = {
                "catboost": CatBoostRegressor(),
                "lightgbm": lgb.Booster(model_file=...)
            }
    
    def predict(self, features: pd.DataFrame, horizon: int):
        cb_pred = self.models[horizon]["catboost"].predict(features)
        lgb_pred = self.models[horizon]["lightgbm"].predict(features)
        weights = self.models[horizon]["weights"]
        return weights[0] * cb_pred + weights[1] * lgb_pred
```

```python
# Обновить dashboard
st.selectbox(
    "Forecast Horizon",
    options=[1, 3, 6],
    format_func=lambda h: f"{h} hour{'s' if h > 1 else ''}"
)
```

---

## 7. Timing estimate

**На NVIDIA A100 80GB:**
- Feature engineering: ~5-10 минут
- CatBoost h=3: ~20-30 минут
- LightGBM h=3: ~15-20 минут
- CatBoost h=6: ~20-30 минут
- LightGBM h=6: ~15-20 минут
- Evaluation: ~5 минут

**Итого:** ~80-120 минут (1.5-2 часа)

---

## 8. Checklist готовности

- [x] Training script написан и протестирован
- [x] Horizon-specific features реализованы
- [x] Proper lagging для Q21
- [x] Ensemble CB+LGB настроен
- [x] Metrics comprehensive
- [x] GPU параметры установлены
- [x] Output directory структура определена
- [ ] Скрипт загружен на сервер → **ВЫПОЛНИТЬ**
- [ ] Training запущен → **ВЫПОЛНИТЬ**
- [ ] Результаты скачаны → **ПОСЛЕ ЗАВЕРШЕНИЯ**
- [ ] Анализ метрик → **ПОСЛЕ ЗАВЕРШЕНИЯ**
- [ ] Интеграция в advisory → **ЕСЛИ УСПЕХ**

---

## Готово к запуску! 🚀

Выполните команды из раздела 3 для старта обучения.

После завершения — проанализируем результаты и интегрируем лучшие модели в систему.
