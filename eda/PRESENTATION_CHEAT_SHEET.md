# Q21 Advisory - Presentation Cheat Sheet

**1-страничная шпаргалка для финала NEFTECODE 2026**

---

## 🎯 Elevator Pitch (30 сек)

> "Разработана production-like advisory система для прогнозирования содержания серы Q21
> в дизеле с горизонтами от 30 минут до 6 часов. Основной прогноз (1 час) достигает
> MAE 0.725 ppm с улучшением +14% vs baseline. Включает risk assessment (recall 97%),
> uncertainty quantification (80% intervals calibrated 77%), state detection и quality gates.
> Готова к теневому пилоту с human-in-the-loop."

---

## 📊 Ключевые цифры (запомнить!)

### Multi-Horizon Performance
```
h=30min: 0.574 ppm  (+1.7%)   → Immediate reaction
h=1hour: 0.725 ppm  (+14%)    → ⭐ Operational decisions
h=2hour: 1.148 ppm  (+7.2%)   → Medium planning
h=3hour: 1.312 ppm  (+9.9%)   → ⭐ Best improvement, early warning
h=6hour: 1.571 ppm  (+2.8%)   → Shift planning
```

### Risk Classification (λ=25)
```
Recall:     97.3%  (catches 97% of exceedances)
Precision:  46.5%  (~50% alerts are real)
FPR:        31.9%  (~32% false alarm rate)
AP Score:   0.906  (excellent ranking)
```

### Uncertainty (h=1)
```
80% Coverage:  77.3%  ✅ well-calibrated
80% Width:     3.6 ppm
50% Coverage:  44.3%  ⚠️ miscalibrated (честно признаём)
```

---

## 🎨 Что показывать

### Слайд 1: Проблема (30 сек)
- Dashboard → Current Status tab
- Q21 current, forecast 1h, margin to spec

### Слайд 2: Multi-Horizon (90 сек)
- **График 1**: Multi-horizon performance bars
- Dashboard → Multi-Horizon Forecast tab
- "Все 5 горизонтов beat baseline"

### Слайд 3: Risk (90 сек)
- **График 2**: Lambda sensitivity curves
- Dashboard → Risk Analysis tab
- Переключить λ: 10 → 25
- "Настраиваемый trade-off safety vs false alarms"

### Слайд 4: Uncertainty (60 сек)
- **График 3**: Coverage calibration
- Dashboard → Multi-Horizon с confidence bands
- "80% intervals well-calibrated"

### Слайд 5: Architecture (60 сек)
- **График 4**: System overview
- "State detection + quality gates + reason codes"

### Слайд 6: Validation (45 сек)
- "Temporal splits, evaluation 2026 = blind holdout"

### Слайд 7: Demo (60 сек)
- Scenario 1: Normal (Q21=8.5, risk medium)
- Scenario 2: High risk (Q21=9.5, forecast 10.2)
- Scenario 3: Safety gate (Q21=307 → NO_ACTION)

---

## ✅ Что ГОВОРИТЬ

- "Production-like advisory prototype"
- "Теневой пилот с human-in-the-loop"
- "Все горизонты улучшают baseline"
- "Calibrated uncertainty intervals"
- "Configurable risk sensitivity"
- "Требует валидации технологом"
- "Correlation найдена, causation нужно pilot"

---

## ❌ Что НЕ говорить

- ~~"Гарантирует прогноз"~~
- ~~"Готово к автоматическому управлению"~~
- ~~"SHAP доказывает причинность"~~
- ~~"Quantile regression лучше"~~
- ~~"W70/F30 это D15"~~

---

## 💬 Ответы на вопросы (1 минута каждый)

### "Почему quantile median хуже?"
> "Distribution shift: train 1.3 → eval 2.9 ppm MAE. Quantile более чувствителен.
> Используем regression для predictions, quantile только для uncertainty bounds."

### "Можно внедрять завтра?"
> "Готов к теневому пилоту. Для production нужно: подтверждение controls от технологов,
> pilot testing рекомендаций, integration с real-time, regulatory approval.
> Advisory system, не autopilot."

### "Как обучалось?"
> "NVIDIA A100 80GB, CatBoost, residual learning: Δ = Q21(t+h) - Q21(t).
> Temporal splits, evaluation 2026 blind holdout. ~2-3 часа на все модели."

### "Плотность и цетан?"
> "Q21: основной результат (0.7-1.3 ppm). Цетан: 42 таргета, MAE ~1.3.
> W70/F30 proxy показали, но не называем D15. Q21 лучшие данные (10 мин)."

### "Как часто retraining?"
> "Drift наблюдаем. Рекомендуем: мониторинг еженедельно, retraining каждые 2-3 месяца
> или при drift >20%. OOD detection предупредит о новых режимах."

### "Почему h=3 лучший improvement?"
> "Sweet spot! Autocorr Q21 = 0.723 на h=3. h=0.5: autocorr 0.974, persistence сильный.
> h=3: predictability есть, persistence слабеет. h=6: predictability падает."

---

## 🔧 Технические детали

### Архитектура
- Regression: CatBoost, 770-1500 iter
- Risk: CatBoost Classifier, asymmetric loss
- Quantile: CatBoost, loss='Quantile'
- Features: Q21 history, rolling, diffs, controls, time

### Data
- 189,217 rows, 10-min, 2023-2026
- Splits: train (2023-24), val (H1 2025), cal (H2 2025), eval (2026)
- 3-day gaps между splits

### Inference
- <100ms per prediction
- SHA256 model verification
- State detection (5 states)
- Freshness <1 hour
- OOD detection

---

## 🚨 Backup Plan

### Dashboard не запускается?
→ Показать PNG из `presentation_plots/`

### Нет демо данных?
→ Описать словами + таблицы из markdown

### Забыл цифры?
→ Эта шпаргалка!

---

## 📱 Быстрые команды

### Запуск dashboard
```bash
cd /Users/falexsun/code/Нефтекод/eda
streamlit run q21_dashboard_enhanced.py
```

### Открыть графики
```bash
open eda/presentation_plots/*.png
```

### Проверить модели
```bash
ls -lh project/models/*.cbm
```

---

## 🎓 Статус

✅ Multi-horizon система (5 горизонтов)  
✅ Risk assessment (recall 97%)  
✅ Uncertainty quantification (calibrated)  
✅ Production architecture (gates + codes)  
✅ Interactive dashboard  
✅ Presentation plots  
✅ Полная документация  

**ГОТОВ К ФИНАЛУ! 🚀**

---

**Время:** 7-10 мин + Q&A  
**URL dashboard:** http://localhost:8501  
**Графики:** `eda/presentation_plots/`  
**Docs:** `eda/DOCUMENTATION_INDEX.md`
