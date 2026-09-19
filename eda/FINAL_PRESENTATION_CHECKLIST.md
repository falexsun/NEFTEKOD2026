# Чеклист финальной презентации NEFTECODE 2026

**Дата:** 2026-09-16  
**Команда:** Q21 Advisory System  
**Статус:** ✅ Готов к демонстрации

---

## Перед началом презентации (за 30 минут)

### Технические проверки

- [ ] Запустить dashboard локально
  ```bash
  cd /Users/falexsun/code/Нефтекод/eda
  streamlit run q21_dashboard_enhanced.py
  ```
  Ожидаемый URL: `http://localhost:8501`

- [ ] Проверить загрузку всех моделей (должно быть 5 горизонтов)
- [ ] Проверить отображение всех вкладок: Current Status, Multi-Horizon, Risk, Features
- [ ] Проверить переключение λ=10/25
- [ ] Открыть презентационные графики в отдельных вкладках браузера
- [ ] Резервная копия: открыть статичные PNG из `eda/presentation_plots/`

### Материалы для показа

- [ ] **График 1**: Multi-horizon performance - показать все 5 горизонтов
- [ ] **График 2**: Risk classification trade-offs - λ sensitivity
- [ ] **График 3**: Uncertainty quantification - 80% intervals
- [ ] **График 4**: System overview - ключевые метрики

### Документация наготове

- [ ] `RESEARCH_SESSION_FINAL_SUMMARY.md` - полный отчёт
- [ ] `MULTIHORIZON_RESULTS.md` - детали regression моделей
- [ ] `QUANTILE_REGRESSION_RESULTS.md` - uncertainty analysis
- [ ] `MASTER_AGENT_HANDOFF.md` - контекст всего проекта

---

## Структура презентации (7-10 минут)

### Слайд 1: Проблема и решение (30 сек)

**Что говорить:**
> "Содержание серы в дизеле должно быть ниже 10 ppm. Превышение = некондиция,
> повторная обработка, потери. Но слишком низкая сера = лишняя энергия.
> 
> Мы разработали advisory систему, которая прогнозирует Q21 от 30 минут до 6 часов
> вперёд и предупреждает о рисках превышения."

**Показать:**
- Dashboard: Current Status tab
- Текущий Q21, прогноз на 1 час, margin to spec

### Слайд 2: Multi-Horizon Прогнозирование (90 сек)

**Что говорить:**
> "Система даёт прогноз на 5 горизонтов:
> - 30 минут: для немедленной реакции (MAE 0.57 ppm)
> - 1 час: для оперативных решений (MAE 0.73 ppm, улучшение +14%)
> - 3 часа: для раннего предупреждения (MAE 1.31 ppm, улучшение +10%)
> - 6 часов: для планирования смены
> 
> Все горизонты улучшают простой persistence baseline."

**Показать:**
- **График 1**: Multi-horizon performance
- Dashboard: Multi-Horizon Forecast tab
- Timeline с прогнозами и confidence intervals

**Ключевые цифры:**
- ✅ h=1: 0.725 ppm MAE (+14%)
- ✅ h=3: 1.312 ppm MAE (+9.9%) - наилучшее улучшение
- ✅ Все 5 горизонтов beat baseline

### Слайд 3: Risk Assessment (90 сек)

**Что говорить:**
> "Система оценивает вероятность превышения 10 ppm и показывает риск.
> 
> Мы позволяем настроить чувствительность через параметр λ:
> - λ=10: компромисс (recall 95%, precision 56%)
> - λ=25: safety-oriented (recall 97%, precision 47%)
> 
> Жюри может выбрать баланс между пропущенными превышениями и ложными тревогами."

**Показать:**
- **График 2**: Risk classification trade-offs
- Dashboard: Risk Analysis tab
- Переключить λ с 10 на 25, показать изменение метрик
- Risk gauge meter

**Ключевые цифры:**
- ✅ λ=25: recall 97.3% (пропускаем только 179 из 6,636 cases)
- ⚠️ Trade-off: FPR 32% (7,412 false alarms)
- 🎯 Настраиваемый баланс safety vs operational cost

### Слайд 4: Uncertainty Quantification (60 сек)

**Что говорить:**
> "Каждый прогноз сопровождается uncertainty interval.
> 
> 80% интервалы хорошо калиброваны: actual coverage 77-80%.
> Ширина интервала ~3.6 ppm показывает реальную неопределённость модели.
> 
> Это позволяет принимать решения с учётом риска."

**Показать:**
- **График 3**: Uncertainty quantification
- Dashboard: Multi-horizon forecast с confidence bands
- Показать, что intervals покрывают spec limit

**Ключевые цифры:**
- ✅ 80% coverage: 77.3% (well-calibrated)
- ✅ Width: 3.6 ppm (realistic uncertainty)
- ❌ Честно признать: 50% intervals miscalibrated (44%)

### Слайд 5: Production Architecture (60 сек)

**Что говорить:**
> "Система включает полный production-ready stack:
> - State detector: определяет режим установки (normal/shutdown/startup)
> - Quality gates: проверяет свежесть данных, frozen sensors, Q21=307
> - Advisory engine: даёт рекомендации с reason codes
> - NO_ACTION logic: не даёт советов при некорректных данных
> 
> Обучено на NVIDIA A100 80GB, CatBoost, temporal splits."

**Показать:**
- **График 4**: System overview
- Code structure (если спросят):
  - `project/src/inference/` - production modules
  - `project/src/dashboard/` - Streamlit UI
  - SHA256 verification для моделей

**Ключевые пункты:**
- ✅ State detection + quality gates
- ✅ Comprehensive reason codes
- ✅ Model verification (SHA256)
- ✅ Thread-safe inference
- ⚠️ Advisory only, not automatic control

### Слайд 6: Обучение и валидация (45 сек)

**Что говорить:**
> "Строгая временная валидация:
> - Train: 2023-2024
> - Validation: первое полугодие 2025
> - Calibration: второе полугодие 2025
> - Evaluation: 2026 (blind holdout)
> 
> Все метрики на evaluation 2026 - модели не видели эти данные."

**Показать:**
- Temporal splits diagram (если есть)
- Таблицу с метриками по splits

**Ключевые пункты:**
- ✅ Только временные splits (no random shuffle)
- ✅ 3-дневные gaps между splits
- ✅ Evaluation 2026 = blind holdout
- ✅ Model selection только на validation

### Слайд 7: Демонстрация Live (60 сек)

**Сценарий 1: Нормальный режим**
> "Q21 = 8.5 ppm, margin = 1.5 ppm, риск средний"

**Показать:**
- Current status: всё зелёное
- Forecast: небольшой рост
- Action: MONITOR

**Сценарий 2: Высокий риск**
> "Q21 = 9.5 ppm, прогноз 10.2 ppm через 1 час"

**Показать:**
- Risk level: High/Critical
- Probability: 75%
- Action: INTERVENE
- Рекомендация с disclaimer

**Сценарий 3: Safety gates**
> "Q21 = 307 (code), система определяет как недостоверные данные"

**Показать:**
- Quality gate triggered
- Action: NO_ACTION
- Reason: "Q21 frozen at calibration code 307"

---

## Честные disclaimers (обязательно упомянуть!)

### Что мы НЕ говорим

❌ "Модель гарантирует прогноз"
❌ "Система готова к автоматическому управлению"
❌ "SHAP доказывает причинность"
❌ "W70/F30 это сертифицированная плотность"
❌ "Quantile regression лучше для predictions"

### Что мы ГОВОРИМ

✅ "Production-like advisory prototype"
✅ "Готов к теневому пилоту с human-in-the-loop"
✅ "Рекомендации требуют валидации технологом"
✅ "Correlation найдена, causation требует pilot testing"
✅ "80% intervals well-calibrated, 50% требуют доработки"

---

## Ответы на вопросы жюри

### Q: "Почему quantile median хуже regression?"

**A:**
> "Отличный вопрос. Quantile regression более чувствителен к distribution shift.
> На evaluation 2026 мы наблюдаем drift: train MAE 1.3 → eval MAE 2.9 ppm.
> 
> Regression модели более robustные. Поэтому мы используем:
> - Regression для point predictions
> - Quantile только для uncertainty bounds (которые хорошо калиброваны)
> 
> Это лучшее из обоих миров."

### Q: "Можно ли это внедрять завтра?"

**A:**
> "Система готова к теневому пилоту - работает параллельно с операторами,
> даёт рекомендации, но не записывает уставки.
> 
> Для полного промышленного внедрения нужно:
> 1. Подтверждение control tags и operating limits от технологов
> 2. Валидация сценарных рекомендаций через pilot
> 3. Integration с real-time data streams
> 4. Regulatory approval
> 
> Мы честно позиционируем: advisory system, не autopilot."

### Q: "Как модель обучалась?"

**A:**
> "NVIDIA A100 80GB GPU, CatBoost 1.2.10, residual learning подход.
> 
> Residual = предсказываем изменение Δ = Q21(t+h) - Q21(t), не абсолютное значение.
> Это работает лучше из-за высокой автокорреляции Q21.
> 
> Temporal splits: строгая временная валидация, evaluation 2026 - blind holdout."

### Q: "А что с плотностью и цетановым числом?"

**A:**
> "Мы работали со всеми обязательными показателями:
> - Сера Q21: основной результат (0.7-1.3 ppm MAE)
> - Цетановое число: 42 таргета, MAE ~1.3 (с residual learning)
> - Плотность proxy W70/F30: показали его использование, но не называем D15
> 
> Q21 имеет наилучшие данные (каждые 10 минут), поэтому основная демонстрация на нём."

### Q: "Как часто нужно переобучать?"

**A:**
> "Мы наблюдаем distribution drift. Рекомендуем:
> - Мониторинг performance каждую неделю
> - Retraining каждые 2-3 месяца или при drift > 20%
> - Online learning для адаптации к новым режимам
> 
> Система включает OOD detection, который предупредит о новых режимах."

### Q: "Почему h=3 лучше по improvement?"

**A:**
> "Отличное наблюдение! h=3 shows +9.9% improvement, это sweet spot.
> 
> Причина: автокорреляция Q21 = 0.723 на h=3.
> - На h=0.5: autocorr = 0.974, persistence почти оптимален
> - На h=3: autocorr = 0.723, достаточно предсказуемости но persistence слабеет
> - На h=6: autocorr = 0.659, predictability падает
> 
> h=3 - оптимальный баланс predictability vs persistence strength."

---

## Технические детали (если спросят)

### Архитектура моделей

- **Regression**: CatBoost, 770-1500 iterations, learning_rate default
- **Risk**: CatBoost Classifier, asymmetric loss с configurable λ
- **Quantile**: CatBoost с loss_function='Quantile'
- **Features**: Q21 history, rolling stats, diffs, controls (F31/T33/T55), time

### Data pipeline

- Input: 189,217 rows, 10-min frequency, 2023-2026
- Feature engineering: lags, rolling, diffs, time encoding
- Imputation: train medians
- Splits: temporal with 3-day gaps
- Inference: <100ms per prediction

### Quality assurance

- SHA256 model verification
- State detection (5 states)
- Freshness checks (<1 hour)
- Frozen sensor detection
- Q21=307 code handling
- OOD detection with training domain ranges

---

## После презентации

### Если есть время для вопросов

- [ ] Показать code structure в IDE
- [ ] Показать experiment directories на сервере
- [ ] Показать model verification (SHA256)
- [ ] Показать feature importance (если analysis завершён)

### Материалы для жюри

Если попросят отчёт:
- `RESEARCH_SESSION_FINAL_SUMMARY.md` - executive summary
- `MASTER_AGENT_HANDOFF.md` - полный контекст проекта
- Presentation plots в `eda/presentation_plots/`
- GitHub repo (если публичный)

---

## Ключевые сообщения (запомнить!)

### Топ-3 достижения

1. **Multi-horizon система** - 5 горизонтов, все улучшают baseline
2. **Production-ready architecture** - state detection, quality gates, reason codes
3. **Configurable risk trade-offs** - λ позволяет выбрать баланс

### Топ-3 честных ограничения

1. **Advisory, not autopilot** - требуется human validation
2. **Correlation, not proven causation** - scenario recommendations нужно pilot
3. **Distribution drift observed** - требуется monitoring и retraining

### One-liner для elevator pitch

> "Production-like advisory система прогнозирует серу в дизеле на 5 горизонтов
> от 30 минут до 6 часов с калиброванной неопределённостью и настраиваемым
> risk assessment. Готова к теневому пилоту с human-in-the-loop."

---

## Backup plan (если что-то сломается)

### Если dashboard не запускается

- [ ] Показать статичные PNG из `presentation_plots/`
- [ ] Показать таблицы из markdown отчётов
- [ ] Описать словами, показывая числа

### Если нет интернета

- [ ] Всё локально, интернет не нужен
- [ ] Модели на диске
- [ ] Dashboard работает на localhost

### Если вопросы по GPU/времени обучения

- [ ] NVIDIA A100 80GB: ~2-3 часа на все эксперименты
- [ ] Multi-horizon: 5 моделей параллельно
- [ ] Quantile: 5 quantiles × 2 horizons
- [ ] Total: ~20 моделей обучено

---

**Время финала:** TBD  
**Формат:** 7-10 минут презентация + вопросы  
**Статус подготовки:** ✅ ГОТОВ

**Удачи! 🚀**
