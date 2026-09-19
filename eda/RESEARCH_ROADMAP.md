# Research Roadmap - Q21 Advisory System

**Дата:** 2026-09-16  
**Статус:** Multi-horizon regression завершён, risk classification в процессе

---

## ✅ Завершённые исследования

### 1. Multi-horizon Regression (DONE)
**Файлы:** `q21_multihorizon_20260916_054306/`

**Результаты:**
- ✅ h=0.5: MAE 0.574 ppm (+1.7% vs persistence)
- ✅ h=1.0: MAE 0.810 ppm (+4.4% vs persistence)
- ✅ h=2.0: MAE 1.148 ppm (+7.2% vs persistence)
- ✅ h=3.0: MAE 1.312 ppm (+9.9% vs persistence) ⭐
- ✅ h=6.0: MAE 1.571 ppm (+2.8% vs persistence)

**Выводы:**
- Все горизонты побеждают persistence
- h=3 - sweet spot для residual learning
- Специализированная h=1 модель (0.725 ppm) всё ещё лучше универсальной (0.810 ppm)

### 2. h=1 Risk Classification (DONE)
**Файлы:** `q21_target_asymmetric_v3_20260915/`

**Результаты:**
- AP: 0.906 (vs 0.885 persistence)
- ROC AUC: 0.959
- λ=25: Recall 97.3%, Precision 46.5%
- λ=10: Recall 94.5%, Precision 55.8%

**Статус:** Production-ready для демонстрации

---

## 🔄 Текущие задачи

### 3. h=3 Risk Classification (IN PROGRESS)
**Цель:** Улучшить risk detection для 3-часового горизонта

**Гипотеза:** 
- h=3 regression показал +9.9% improvement
- Risk classifier должен использовать те же преимущества

**Ожидаемые метрики:**
- Текущий h=3 risk: AP 0.718 (хуже persistence 0.750)
- Целевой h=3 risk: AP > 0.750 (лучше persistence)

**План:**
1. Asymmetric loss с λ=10, 25, 50
2. Residual features (Δt shift, rolling changes)
3. Class weights для imbalanced data
4. Longer training (1500+ iterations)

**Статус:** Обучается на A100

---

## 📋 Приоритетные следующие шаги

### Priority 1: Quantile Regression для Uncertainty (HIGH)

**Цель:** Калиброванные интервалы неопределённости для всех горизонтов

**Зачем:**
- Dashboard должен показывать 80%, 90%, 95% intervals
- Интервалы растут с горизонтом
- Необходимо для честной презентации

**План:**
```python
# Для каждого горизонта: q10, q25, q50, q75, q90
horizons = [0.5, 1.0, 2.0, 3.0, 6.0]
quantiles = [0.10, 0.25, 0.50, 0.75, 0.90]

for h in horizons:
    for q in quantiles:
        train_quantile_regressor(
            horizon=h,
            quantile=q,
            loss='Quantile:alpha={q}'
        )
```

**Ожидаемый результат:**
- 5 horizons × 5 quantiles = 25 models
- Calibration check на evaluation set
- Coverage plots для каждого горизонта

**Время:** ~3-4 часа на A100

**Приоритет:** 🔴 HIGH - нужно для финальной демонстрации

---

### Priority 2: Feature Importance Analysis (MEDIUM)

**Цель:** Понять, какие features предсказывают изменения Q21

**Вопросы:**
1. Какие признаки важны для h=1?
2. Как importance меняется с горизонтом?
3. Есть ли специфичные для горизонта features?

**План:**
```python
# SHAP analysis для каждого горизонта
for h in [0.5, 1.0, 2.0, 3.0, 6.0]:
    model = load_model(f'reg_h{h}')
    explainer = shap.TreeExplainer(model)
    shap_values = explainer(X_eval)
    
    # Top-20 features
    plot_shap_importance(shap_values, h)
    
    # Feature stability across horizons
    compare_importance_across_horizons()
```

**Ожидаемый результат:**
- Список top-20 features для каждого горизонта
- Heatmap: features × horizons
- Interpretation: почему h=3 лучше h=1?

**Время:** ~1 час (local, на готовых моделях)

**Приоритет:** 🟡 MEDIUM - полезно для понимания, не критично для demo

---

### Priority 3: Ensemble Specialized + Universal (MEDIUM)

**Цель:** Best of both worlds для h=1

**Гипотеза:**
- Specialized h=1: 0.725 ppm (точный, но узкий)
- Universal h=1: 0.810 ppm (универсальный)
- Ensemble: может быть лучше обоих?

**План:**
```python
# Simple averaging
pred_ensemble = 0.5 * pred_specialized + 0.5 * pred_universal

# Stacking
meta_model = CatBoostRegressor(iterations=100)
meta_model.fit(
    X=[pred_specialized, pred_universal],
    y=y_true
)

# Compare
print(f"Specialized: {mae_specialized}")
print(f"Universal: {mae_universal}")
print(f"Ensemble: {mae_ensemble}")
```

**Ожидаемый результат:**
- Если ensemble < 0.725: используем в production
- Если нет: продолжаем с specialized

**Время:** ~30 минут (local)

**Приоритет:** 🟡 MEDIUM - потенциальное улучшение, не обязательно

---

### Priority 4: Dashboard Multi-horizon Integration (HIGH)

**Цель:** Показать все горизонты в одном dashboard

**Компоненты:**

1. **Timeline view:**
   ```
   Now    0.5h   1h     2h     3h           6h
    |------|------|------|------|-----------|
    8.5    8.6    8.8    9.0    9.2         9.5 ppm
   ```

2. **Uncertainty cone:**
   - Интервалы расширяются с горизонтом
   - 80%, 90%, 95% zones
   - Risk threshold at 10 ppm

3. **Risk matrix:**
   ```
   Horizon | Forecast | P(>10ppm) | Action
   --------|----------|-----------|--------
   0.5h    | 8.6      | 5%        | MONITOR
   1h      | 8.8      | 12%       | MONITOR
   3h      | 9.2      | 35%       | INVESTIGATE
   6h      | 9.5      | 55%       | ALERT
   ```

4. **Horizon selector:**
   - Radio buttons: 0.5h / 1h / 2h / 3h / 6h
   - Show: MAE, improvement%, confidence

**План:**
```python
# Streamlit multi-horizon dashboard
st.title("Q21 Multi-Horizon Advisory")

horizon = st.radio("Select horizon", [0.5, 1, 2, 3, 6])

# Load appropriate model
model = load_model_bundle(horizon)

# Forecast
forecast = model.predict(current_state)
intervals = model.predict_intervals(current_state)
risk_prob = model.predict_risk(current_state)

# Visualize
plot_timeline_with_uncertainty(forecast, intervals)
plot_risk_evolution(all_horizons)
```

**Время:** ~2-3 часа

**Приоритет:** 🔴 HIGH - ключевая часть финальной демонстрации

---

### Priority 5: OOD Detection Enhancement (MEDIUM)

**Цель:** Улучшить детекцию Out-of-Distribution входов

**Текущее состояние:**
- W70/F30 ratio для density proxy
- Q21=307 detection
- Frozen sensor detection

**Что добавить:**

1. **Mahalanobis distance:**
   ```python
   # Training domain covariance
   Sigma = np.cov(X_train.T)
   
   # Distance для новых точек
   def mahalanobis_distance(x):
       delta = x - X_train_mean
       return np.sqrt(delta @ np.linalg.inv(Sigma) @ delta.T)
   
   # Threshold на 99.5 percentile training
   if mahalanobis_distance(x_new) > threshold:
       return "OOD_DETECTED"
   ```

2. **Per-feature range checks:**
   ```python
   # 0.5% - 99.5% quantiles из training
   for feature in features:
       if x[feature] < q_0005[feature] or x[feature] > q_9995[feature]:
           flags.append(f"OOD_{feature}")
   ```

3. **Prediction uncertainty check:**
   ```python
   # Если 90% interval слишком широкий
   interval_width = q90 - q10
   if interval_width > 3 * median_interval_width:
       return "HIGH_UNCERTAINTY"
   ```

**Время:** ~1-2 часа

**Приоритет:** 🟡 MEDIUM - важно для safety, но базовая версия уже есть

---

### Priority 6: Cetane Number Improvement (LOW)

**Текущее состояние:**
- 42 таргета (train=25, val=11, eval=6)
- MAE = 1.254 ppm (residual + last LIMS)
- W70/F30 добавляет минимально (~0.005 ppm)

**Проблемы:**
- Слишком мало данных для сложной модели
- Высокая неопределённость
- SHAP-pruning переобучался на validation

**Возможные улучшения:**

1. **Transfer learning от Q21:**
   ```python
   # Pre-train на Q21 (много данных)
   base_model = train_on_q21_residuals()
   
   # Fine-tune на Cetane (мало данных)
   cetane_model = finetune(
       base_model,
       cetane_data,
       iterations=100
   )
   ```

2. **Ensemble с физической моделью:**
   ```python
   # Если есть корреляция Cetane ~ f(T, P, composition)
   pred_physical = physical_model(process_vars)
   pred_ml = catboost_model.predict(X)
   
   pred_final = 0.3 * pred_physical + 0.7 * pred_ml
   ```

3. **Synthetic data augmentation:**
   ```python
   # Interpolate между реальными точками
   # с консервативным шумом
   for i in range(len(X) - 1):
       X_synthetic = 0.5 * X[i] + 0.5 * X[i+1]
       y_synthetic = 0.5 * y[i] + 0.5 * y[i+1]
   ```

**Реалистичные ожидания:**
- Улучшение вероятно минимально (0.01-0.02 ppm)
- 42 точки - фундаментальное ограничение
- Честнее показать широкие интервалы

**Рекомендация:** Оставить как есть, фокус на Q21

**Приоритет:** 🟢 LOW - не критично, данных слишком мало

---

### Priority 7: State Detection Refinement (LOW)

**Текущее состояние:**
- Normal / Shutdown / Startup / Transition / Unknown
- Based on: flow patterns, temperature stability, rate of change

**Возможные улучшения:**

1. **ML-based state classifier:**
   ```python
   # Supervised learning на размеченных эпизодах
   states = ['normal', 'shutdown', 'startup', 'transition']
   
   clf = CatBoostClassifier(iterations=500)
   clf.fit(
       X=telemetry_features,
       y=labeled_states
   )
   ```

2. **HMM для temporal consistency:**
   ```python
   # Не переключаться слишком часто
   from hmmlearn import hmm
   
   model = hmm.GaussianHMM(
       n_components=5,  # 5 states
       covariance_type='diag'
   )
   
   state_sequence = model.predict(telemetry)
   ```

**Проблемы:**
- Нет размеченных ground truth states
- Организаторы допускают NO_ACTION на startup/shutdown

**Рекомендация:** Текущая heuristic достаточна

**Приоритет:** 🟢 LOW - работает, не ломать

---

## 🎯 Финальная демонстрация - что нужно

### Must Have (до 20.09.2026)

1. ✅ h=1 regression + risk (DONE)
2. ✅ h=3 regression (DONE)
3. 🔄 h=3 risk classification (IN PROGRESS)
4. ⬜ Quantile regression для intervals (Priority 1)
5. ⬜ Multi-horizon dashboard (Priority 4)
6. ⬜ Demo checklist update

### Nice to Have

7. ⬜ Feature importance analysis (Priority 2)
8. ⬜ OOD detection enhancement (Priority 5)
9. ⬜ Ensemble experiments (Priority 3)

### Not Needed

10. ❌ Cetane improvement (слишком мало данных)
11. ❌ State detection ML (heuristic достаточна)
12. ❌ Новые feature engineering (текущие работают)

---

## 📊 Метрики для отчёта жюри

### Regression Performance

| Horizon | Model MAE | Baseline MAE | Improvement |
|---------|-----------|--------------|-------------|
| 0.5h | 0.574 ppm | 0.584 ppm | +1.7% |
| **1h** | **0.725 ppm** | **0.846 ppm** | **+14.3%** ⭐ |
| 2h | 1.148 ppm | 1.237 ppm | +7.2% |
| **3h** | **1.312 ppm** | **1.455 ppm** | **+9.9%** ⭐ |
| 6h | 1.571 ppm | 1.616 ppm | +2.8% |

### Risk Classification (Q21 > 10 ppm)

| Horizon | Model AP | Baseline AP | ROC AUC |
|---------|----------|-------------|---------|
| **1h** | **0.906** | 0.885 | **0.959** ⭐ |
| 3h | TBD | 0.750 | TBD |

### Safety Thresholds (λ=25, h=1)

- **Recall:** 97.3% (179/6633 missed)
- **Precision:** 46.5%
- **FPR:** 31.9%
- **Trade-off:** High safety, acceptable false alarms

---

## 🚀 Execution Plan

### Сегодня (16.09.2026)

- [x] Multi-horizon regression - DONE
- [ ] h=3 risk classification - IN PROGRESS
- [ ] Quantile regression для h=1, h=3 - START
- [ ] Feature importance analysis - START

### Завтра (17.09.2026)

- [ ] Quantile regression для всех горизонтов
- [ ] Multi-horizon dashboard integration
- [ ] OOD detection enhancement
- [ ] Update demo checklist

### 18-19.09.2026

- [ ] Full system testing
- [ ] Dashboard polish
- [ ] Presentation materials
- [ ] Rehearsal

### 20.09.2026 - DEMO DAY

- [ ] Final demo
- [ ] Q&A preparation
- [ ] Report submission

---

## 📝 Open Questions

1. **Quantile calibration:**
   - Как проверить coverage на evaluation?
   - Нужна ли recalibration?

2. **Multi-horizon ensemble:**
   - Использовать ли weighted average по accuracy?
   - Как показывать conflicting signals?

3. **Feature selection:**
   - Универсальные features лучше специализированных?
   - Когда отсечь низкоранговые?

4. **Production deployment:**
   - Как обновлять модели с новыми LIMS?
   - Trigger для retraining?

---

## 💡 Ключевые инсайты

### Что работает отлично

1. ✅ **Residual learning** - универсально побеждает persistence
2. ✅ **Asymmetric loss для risk** - high recall с приемлемыми FP
3. ✅ **Multi-horizon architecture** - одна архитектура для всех h
4. ✅ **Q21 как таргет** - больше данных, чем ЛИМС

### Что не работает

1. ❌ **Direct Q21 prediction для h>1** - persistence сильнее
2. ❌ **SHAP-based pruning на 11 точках** - переобучение
3. ❌ **Cetane без residual** - 42 точки слишком мало
4. ❌ **W70/F30 для цетана** - минимальная польза

### Что удивило

1. 🤔 **h=3 improvement > h=1** - 9.9% vs 4.4%
2. 🤔 **Universal h=1 хуже specialized** - на 11.7%
3. 🤔 **MAE растёт линейно** - ~0.17 ppm/час
4. 🤔 **h=6 всё ещё улучшает** - +2.8%, хоть и мало

---

**Статус:** Roadmap готов, приоритеты расставлены, фокус на quantile regression и dashboard! 🎯
