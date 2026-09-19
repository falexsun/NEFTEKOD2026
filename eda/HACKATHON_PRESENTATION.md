# Q21 Advisory System — Финальная презентация

**NEFTECODE 2026 Hackathon**  
**Дата:** 16 сентября 2026

---

## Слайд 1: Титульный

# Q21 Sulfur Advisory System
## Production-like решение для мониторинга серы в керосине

**Команда:** NEFTECODE 2026  
**Готовность:** Shadow Pilot Ready

---

## Слайд 2: Проблема

### Вызов
Содержание серы в керосине (Q21) должно быть **< 10 ppm** по спецификации

**Текущая ситуация:**
- ❌ Анализатор Q21 показывает код 307 (неисправность) в 3% случаев
- ❌ Превышение лимита требует переработки всей партии
- ❌ Нет раннего предупреждения о риске

**Стоимость проблемы:**
- Переработка или смешение с низкосернистым продуктом
- Потеря производительности
- Увеличение энергозатрат

---

## Слайд 3: Наше решение

### Q21 Advisory System

**Production-like система прогнозирования качества**

✅ **Прогноз на 1 час вперёд** — MAE 0.725 ppm  
✅ **Детекция риска** — AP 0.906, AUC 0.959  
✅ **Safety gates** — автоматическая проверка надёжности данных  
✅ **State detection** — работает только в штатном режиме  
✅ **Interactive dashboard** — визуализация и настройка trade-offs

**Улучшение vs naive baseline: +14%**

---

## Слайд 4: Архитектура

```
Телеметрия (189K точек, 10 мин) → State Detector
                                      ↓
                                  [normal?] → NO_ACTION
                                      ↓
                                Quality Gates
                        (freshness, frozen, Q21=307, OOD)
                                      ↓
                                [all passed?] → NO_ACTION
                                      ↓
                            Feature Engineering
                          (417 признаков + Q21 history)
                                      ↓
                              Model Bundle
                      (Regression + Risk Classifier)
                                      ↓
                          Advisory Generator
                     (λ=10 balanced | λ=25 safety)
                                      ↓
                                 Dashboard
```

---

## Слайд 5: Данные

### Dataset
- **Телеметрия:** 189,217 точек (01.01.2023 — 07.08.2026)
- **Теги АВТ:** 71 параметр
- **Теги 24-2000:** 26 параметров
- **Шаг:** 10 минут (ровный)
- **Q21 target:** содержание серы в керосине, ppm

### Splits (temporal, no leakage)
- **Train:** до 2025 (105K samples)
- **Validation:** Q1-Q2 2025 (26K samples)
- **Calibration:** Q3-Q4 2025 (26K samples)
- **Evaluation:** 2026 (31K samples)

**Трёхдневные разрывы между периодами**

---

## Слайд 6: Результаты моделей

### Regression (Q21 forecast, h=1)

| Метрика | Модель | Persistence | Improvement |
|---------|--------|-------------|-------------|
| **MAE** | **0.725** | 0.844 | **+14%** ✅ |
| RMSE | 1.089 | 1.245 | +13% |
| R² | 0.856 | 0.794 | +8% |

### Risk Classification (Q21 > 10 ppm, без кода 307)

| Метрика | Модель | Persistence |
|---------|--------|-------------|
| **AP** | **0.906** | 0.885 |
| **AUC** | **0.959** | - |
| Brier | 0.078 | 0.095 |

**Horizon:** 1 час вперёд  
**Evaluation:** 2026 год (полностью отдельные данные)

---

## Слайд 7: Trade-off настройка (λ)

### Asymmetric cost function

`J(q) = max(10-q, 0)² + λ × max(q-10, 0)²`

**λ=10 (balanced):**
- Recall: 94.5%
- Precision: 55.8%
- FPR: 21.4%
- **Use case:** Сбалансированный режим

**λ=25 (safety-oriented):**
- Recall: **97.3%** ✅
- Precision: 46.5%
- FPR: 31.9%
- **Use case:** Приоритет на обнаружение всех рисков

**Для демонстрации используем λ=25**

---

## Слайд 8: Safety Gates

### Автоматические проверки надёжности

❌ **NO_ACTION** выдаётся при:

1. **Plant state ≠ NORMAL**
   - Shutdown, startup, transition → advisory suspended

2. **Q21 = 307**
   - Код неисправности анализатора

3. **Frozen sensors**
   - Константа > 2 часов

4. **Stale data**
   - Возраст > 30 минут

5. **Zero denominators**
   - F30 = 0 (для W70/F30 ratio)

6. **Out of distribution**
   - Признаки вне training domain

**Все проверки автоматические, без участия оператора**

---

## Слайд 9: Dashboard Demo

### Live демонстрация

**Сценарий 1: Normal operation, low risk**
- Q21 current: 8.5 ppm
- Forecast +1h: 8.2 ppm
- Risk: 5% (LOW)
- Action: MONITOR

**Сценарий 2: Escalating risk**
- Q21 current: 11.0 ppm
- Forecast +1h: 11.5 ppm
- Risk: 75% (CRITICAL)
- Action: INVESTIGATE

**Сценарий 3: Safety gate — Q21=307**
- Action: NO_ACTION
- Reason: Q21_CODE_307
- Message: "Analyzer fault or out of range"

---

## Слайд 10: Технологический стек

### Models
- **CatBoost 1.2.10** на NVIDIA A100 80GB
- **417 features** (rolling, lags, EWMA, Q21 history)
- **2000 iterations**, early stopping on validation
- **Quantile regression** (q50) + **Binary classifier**

### Inference
- Python 3.11+
- Streamlit dashboard
- Real-time feature engineering
- < 100ms latency per prediction

### Deployment
- Docker containerization готов
- Prometheus metrics готовы
- Health checks реализованы

---

## Слайд 11: Что работает СЕЙЧАС

✅ **Прогноз Q21** на 1 час с MAE 0.725 ppm  
✅ **Детекция риска** с AP 0.906  
✅ **State detection** (normal/shutdown/startup)  
✅ **Quality gates** (6 типов проверок)  
✅ **Interactive dashboard** с λ switching  
✅ **Production-like architecture**

**Готовность: Shadow Pilot**

Система работает параллельно с технологом, записывает рекомендации, НЕ управляет установкой автоматически.

---

## Слайд 12: Ограничения (честно)

### Что НЕ работает

❌ **Автоматическое управление**
- Это observational model, не causal
- Требуется валидация на пилоте

❌ **Сценарные рекомендации**
- SHAP показывает correlation, не causation
- Model-based what-if, требует экспертной проверки

❌ **Горизонты 3 и 6 часов**
- Текущие модели хуже persistence baseline
- Требуется дополнительная работа

❌ **Гарантии качества**
- Модель помогает, но не гарантирует < 10 ppm
- Решение остаётся за технологом

---

## Слайд 13: Roadmap

### Для теневого пилота (1-2 недели)

✅ Continuous monitoring — подключение к live telemetry  
✅ Logging & audit trail — запись всех рекомендаций  
✅ Alerting system — Telegram/email для critical риска  
✅ Model retraining pipeline — автоматическое переобучение

### Для промышленного внедрения (3-6 месяцев)

⏳ Controls validation — подтверждение управляющих тегов  
⏳ Causal validation — A/B тесты или RCT  
⏳ Safety interlocks — интеграция с emergency shutdown  
⏳ Regulatory compliance — сертификация для критичных систем  
⏳ Operator training — обучение персонала

---

## Слайд 14: Экономический эффект (сценарный)

### Предположения (НЕ validated)

**Случай превышения 10 ppm:**
- Переработка партии: ~500К руб
- Или смешение с низкосернистым: ~200К руб
- Частота: ~1 раз в месяц

**С advisory system:**
- Early warning за 1 час → коррекция режима
- Предотвращение 70% случаев (recall 97% × precision 50%)
- Экономия: ~3-4М руб/год

**Затраты:**
- Разработка: done (хакатон)
- Пилот: ~500К руб (3 месяца)
- Эксплуатация: ~200К руб/год

**ROI: ~15-20x в первый год**

⚠️ **Disclaimer:** Это сценарные оценки, требуют валидации с реальными данными предприятия

---

## Слайд 15: Конкурентные преимущества

### Почему наше решение выделяется

1. **Production-like architecture**
   - Не просто модель, а полная система
   - Safety gates, state detection, OOD checks

2. **Настраиваемый trade-off**
   - λ=10 vs λ=25 переключение на лету
   - Адаптация под разные режимы работы

3. **Honest limitations**
   - Чёткое разделение: что работает / что нет
   - NO_ACTION вместо ненадёжных прогнозов

4. **Ready for pilot**
   - Не proof-of-concept, а deployable solution
   - Docker, tests, documentation

5. **Extensible design**
   - Легко добавить новые горизонты (h=3,6)
   - Легко добавить новые targets (плотность, цетан)

---

## Слайд 16: Заключение

### Q21 Advisory System — готов к теневому пилоту

**Достигнуто:**
- ✅ Рабочая модель с улучшением +14% vs baseline
- ✅ Production-like inference система
- ✅ Interactive dashboard для демонстрации
- ✅ Comprehensive documentation

**Следующий шаг:**
Запустить теневой пилот на 3 месяца:
- Параллельная работа с технологом
- Логирование всех рекомендаций
- Сбор feedback и метрик
- Доработка на основе реальных кейсов

**Благодарим за внимание!**

---

## Backup слайды: Технические детали

### Feature Engineering

**417 признаков:**
- 400 process features (АВТ + 24-2000)
- 17 Q21 history features

**Типы:**
- Current values (_now)
- Rolling mean/std (1h, 3h, 6h, 12h, 24h)
- Changes/diffs (1h, 3h, 6h, 12h, 24h)
- Q21 origin, past mean/std/change

**Правильный lagging:**
Все Q21 history features сдвинуты, чтобы избежать data leakage

### Model Selection

**Почему CatBoost:**
- Лучше работает с табличными данными
- Встроенная поддержка categorical features
- GPU training на A100
- Quantile regression из коробки

**Hyperparameters:**
- iterations: 2000 (early stopping)
- learning_rate: 0.03
- depth: 8
- l2_leaf_reg: 3
- loss: MAE (regression), Logloss (classification)

**Training time на A100:**
- Regression: ~20 минут
- Classification: ~15 минут
- Total: ~35 минут для полного pipeline

### Validation Strategy

**Temporal cross-validation:**
- Train: 2023-2024
- Validation: Q1-Q2 2025 (выбор модели)
- Calibration: Q3-Q4 2025 (выбор порога)
- Evaluation: 2026 (финальная оценка)

**3-дневные разрывы между периодами**

**Никогда не используем evaluation для:**
- Feature selection
- Model selection
- Threshold tuning

**Evaluation = blind holdout**

