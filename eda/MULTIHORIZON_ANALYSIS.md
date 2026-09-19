# Анализ моделей h=3 и h=6 часов

**Дата:** 16 сентября 2026  
**Вопрос:** Имеет ли смысл использовать модели на горизонтах 3 и 6 часов?

---

## 📊 Сравнение с Persistence Baseline

### Persistence Baseline (evaluation 2026)

| Horizon | MAE (ppm) | AP | AUC |
|---------|-----------|-----|-----|
| **h=1** | **0.844** | 0.885 | 0.932 |
| **h=3** | **1.443** | 0.750 | 0.811 |
| **h=6** | **1.588** | 0.729 | 0.805 |

**Наблюдение:** Persistence baseline деградирует с горизонтом:
- h=1: 0.844 ppm
- h=3: 1.443 ppm (+71% хуже)
- h=6: 1.588 ppm (+88% хуже)

---

## 🔴 REGRESSION: Модели ХУЖЕ baseline

### h=3 (3 часа вперёд)

**Лучшая модель:** `reg_h3_controls_plus_q21_history_q50`
- **MAE: 1.438 ppm**
- **Persistence: 1.443 ppm**
- **Улучшение: +0.3%** ⚠️ (несущественное)

**Другие модели:**
- `all_plus_q21_history_q50`: MAE 1.935 ppm ❌ (-34% vs persistence!)
- `all_plus_q21_history_q80`: MAE 1.486 ppm ❌ (-3%)

### h=6 (6 часов вперёд)

**Лучшая модель:** `reg_h6_q21_history_only_q80`
- **MAE: 1.702 ppm**
- **Persistence: 1.588 ppm**
- **Ухудшение: -7.2%** ❌

**Другие модели:**
- `q21_history_only_q50`: MAE 1.735 ppm ❌ (-9.3%)
- `controls_plus_q21_history_q90`: MAE 1.929 ppm ❌ (-21.5%)

### 🚨 Вывод по regression:
- ✅ **h=3: можно использовать** (примерно равен persistence)
- ❌ **h=6: НЕ имеет смысла** (хуже baseline на 7-9%)

---

## 🟡 CLASSIFICATION: Модели НЕМНОГО лучше baseline

### h=3 (3 часа вперёд)

**Лучшая модель:** `risk_h3_q21_history_only_s42`
- **AP: 0.773**
- **AUC: 0.846**
- **Persistence AP: 0.750**
- **Улучшение: +3.1%** ✅

**Feature set:** `q21_history_only` (17 признаков Q21 истории)

### h=6 (6 часов вперёд)

**Лучшая модель:** `risk_h6_q21_history_only_s2026`
- **AP: 0.754**
- **AUC: 0.835**
- **Persistence AP: 0.729**
- **Улучшение: +3.4%** ✅

**Feature set:** `q21_history_only` (17 признаков Q21 истории)

### 🟡 Вывод по classification:
- ✅ **h=3: имеет смысл** (AP +3%, AUC +3.5%)
- ✅ **h=6: имеет смысл** (AP +3.4%, AUC +3%)
- ⚠️ **Но улучшение небольшое** (vs +2.5% для h=1)

---

## 💡 Интерпретация результатов

### Почему regression деградирует?

1. **Процесс более стохастичен на длинных горизонтах**
   - За 6 часов может произойти много изменений
   - Модель не видит будущие управляющие действия
   - Внешние возмущения накапливаются

2. **Persistence = сильный baseline для медленных процессов**
   - Если Q21 меняется медленно, persistence работает хорошо
   - Модель может улучшить только если видит leading indicators
   - Видимо, на h=6 таких индикаторов недостаточно

3. **Overfitting на h=6**
   - Модели `all_plus_q21_history` значительно хуже baseline
   - Слишком много признаков для сигнала на h=6
   - Модель учит шум вместо закономерностей

### Почему classification работает лучше?

1. **Задача проще: бинарная (Q21 > 10 ppm)**
   - Не нужно точно предсказывать значение
   - Достаточно поймать паттерн "будет плохо"

2. **Q21 history содержит тренд**
   - Если Q21 растёт последние часы → риск выше
   - Это работает даже на h=6

3. **Asymmetric loss λ=25**
   - Модель оптимизирована ловить риски
   - False positives допустимы

---

## 🎯 Рекомендации

### ✅ Для production использования

**1. h=1 (1 час) — ОСНОВНАЯ МОДЕЛЬ** ⭐️
- **Regression:** MAE 0.725 ppm (+14% vs persistence) ✅
- **Classification:** AP 0.907, AUC 0.951 ✅
- **Use case:** Оперативные действия технолога

**2. h=3 (3 часа) — МОЖНО ИСПОЛЬЗОВАТЬ** 🟡
- **Regression:** MAE 1.438 ppm (≈ persistence, +0.3%)
- **Classification:** AP 0.773 (+3% vs persistence) ✅
- **Use case:** Средний горизонт планирования
- ⚠️ **Disclaimer:** Regression точность низкая (±1.4 ppm при лимите 10 ppm)

**3. h=6 (6 часов) — ТОЛЬКО CLASSIFICATION** 🟡
- **Regression:** ❌ НЕ использовать (хуже baseline на 7%)
- **Classification:** AP 0.754 (+3.4% vs persistence) ✅
- **Use case:** Долгосрочный мониторинг тренда
- ⚠️ **Disclaimer:** Только для раннего предупреждения, не для точного прогноза

### ❌ НЕ использовать

- **h=6 regression** — хуже persistence baseline
- **h=12** — не обучалась, скорее всего будет ещё хуже

---

## 📋 Практическая стратегия

### Архитектура multi-horizon advisory system

```
Текущее время T
│
├─ h=1 (T+1h) — ОСНОВНОЙ прогноз
│  ├─ Regression: Q21 forecast (MAE 0.725 ppm) ✅
│  └─ Classification: Risk probability (AP 0.907) ✅
│
├─ h=3 (T+3h) — Средний горизонт
│  ├─ Regression: Q21 forecast (MAE 1.438 ppm) 🟡
│  └─ Classification: Risk probability (AP 0.773) ✅
│
└─ h=6 (T+6h) — Долгий горизонт
   ├─ Regression: ❌ НЕ показывать
   └─ Classification: Risk trend only (AP 0.754) 🟡
```

### Dashboard visualization

**Слайд 1: Immediate (h=1)**
- Q21 current: 8.5 ppm
- Q21 forecast +1h: 8.2 ppm ✅
- Risk probability: 5% (LOW) ✅
- **Confidence: HIGH**

**Слайд 2: Medium-term (h=3)**
- Q21 forecast +3h: 8.0 ppm 🟡
- Risk probability: 8% (LOW) ✅
- **Confidence: MEDIUM**
- Disclaimer: "±1.4 ppm uncertainty"

**Слайд 3: Long-term (h=6)**
- Q21 forecast: ❌ Not available
- Risk trend: ↗ INCREASING 🟡
- Risk probability: 12% (MEDIUM) ✅
- **Confidence: LOW**
- Disclaimer: "Trend indicator only, not a precise forecast"

---

## 🎯 Итоговый ответ на ваш вопрос

### h=3 (3 часа):
✅ **Имеет смысл для classification** (AP +3%)
🟡 **Можно для regression**, но точность низкая (MAE 1.4 ppm)

**Рекомендация:**
- Показывать как "средний горизонт планирования"
- Добавить disclaimer про uncertainty ±1.4 ppm
- Использовать для тренда, не для точных действий

### h=6 (6 часов):
✅ **Имеет смысл ТОЛЬКО для classification** (AP +3.4%)
❌ **НЕ имеет смысла для regression** (хуже baseline -7%)

**Рекомендация:**
- Показывать ТОЛЬКО risk trend (↗↘)
- НЕ показывать точное значение Q21
- Использовать как "early warning на длинном горизонте"
- Добавить disclaimer: "trend indicator, not forecast"

### h=12 (12 часов):
❌ **Не обучалась**, скорее всего будет ещё хуже h=6

**Рекомендация:**
- Не тратить время на обучение
- Фокус на улучшении h=1 и h=3

---

## 🚀 Что делать дальше

### Для хакатона (сейчас):
✅ Показывать **только h=1** — это честно и работает отлично!
- Regression: +14% improvement ⭐️
- Classification: AP 0.907 ⭐️
- Уверенность: HIGH

### Для пилота (1-2 месяца):
✅ Добавить **h=3 classification** как "medium-term trend"
- AP 0.773 (+3%)
- Confidence: MEDIUM
- Use case: планирование на несколько часов

### Для production (3-6 месяцев):
🔬 **Исследовать h=6 improvement:**
- Попробовать добавить predictive features (planned changes, feed composition forecast)
- Ensemble h=1 + h=3 для h=6
- Но приоритет на h=1 и h=3

---

## 📌 Финальный вывод

**h=1 = ОСНОВНАЯ модель** ⭐️ (используем сейчас)  
**h=3 = МОЖНО добавить** 🟡 (для среднего горизонта)  
**h=6 = ТОЛЬКО risk trend** 🟡 (не точный прогноз)  
**h=12 = НЕ имеет смысла** ❌ (не обучать)

**Для demo показывайте h=1 — это ваш killer feature!** 🚀
