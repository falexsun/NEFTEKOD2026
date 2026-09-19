# Q21 Advisory System - NEFTECODE 2026 Hackathon

**Статус:** ✅ ГОТОВ К ФИНАЛУ  
**Команда:** Q21 Multi-Horizon Forecasting & Advisory  
**Дата:** 2026-09-16

---

## 🎯 Что это?

Production-like advisory система для прогнозирования содержания серы Q21 в дизеле с горизонтами от 30 минут до 6 часов. Включает:

- ✅ Multi-horizon forecasting (5 горизонтов)
- ✅ Risk assessment (recall 97%)
- ✅ Uncertainty quantification (calibrated)
- ✅ State detection & quality gates
- ✅ Interactive dashboard
- ✅ Production-ready inference code

---

## 🚀 Быстрый старт для демонстрации

### 1. Запустить dashboard
```bash
cd /Users/falexsun/code/Нефтекод/eda
streamlit run q21_dashboard_enhanced.py
```

Откроется в браузере: `http://localhost:8501`

### 2. Открыть presentation plots
```bash
open eda/presentation_plots/*.png
```

### 3. Следовать чеклисту презентации
📋 **[eda/FINAL_PRESENTATION_CHECKLIST.md](eda/FINAL_PRESENTATION_CHECKLIST.md)**

### 4. Шпаргалка с цифрами
📱 **[eda/PRESENTATION_CHEAT_SHEET.md](eda/PRESENTATION_CHEAT_SHEET.md)**

---

## 📊 Ключевые результаты

### Multi-Horizon Performance (Evaluation 2026)
| Horizon | MAE | Improvement | Use Case |
|---------|-----|-------------|----------|
| 30 min | 0.574 ppm | +1.7% | Immediate reaction |
| **1 hour** | **0.725 ppm** | **+14%** | **Operational decisions** ⭐ |
| 2 hours | 1.148 ppm | +7.2% | Medium planning |
| **3 hours** | **1.312 ppm** | **+9.9%** | **Early warning** ⭐ |
| 6 hours | 1.571 ppm | +2.8% | Shift planning |

### Risk Classification (λ=25)
- **Recall:** 97.3% (catches 97% of exceedances)
- **Precision:** 46.5% (~50% alerts are real)
- **FPR:** 31.9% (~32% false alarm rate)
- **AP Score:** 0.906 (excellent ranking)

### Uncertainty Quantification
- **80% Coverage:** 77.3% ✅ (well-calibrated)
- **80% Width:** 3.6 ppm
- **Point MAE:** 0.810 ppm (h=1)

---

## 📂 Структура проекта

```
Нефтекод/
├── eda/                                    # Исследование и результаты
│   ├── DOCUMENTATION_INDEX.md             # 📖 НАЧАТЬ ОТСЮДА
│   ├── FINAL_PRESENTATION_CHECKLIST.md    # ✅ Чеклист для финала
│   ├── PRESENTATION_CHEAT_SHEET.md        # 📱 Шпаргалка с цифрами
│   ├── RESEARCH_SESSION_FINAL_SUMMARY.md  # 📊 Executive summary
│   ├── HANDOFF_COMPLETION_STATUS.md       # ✓ Статус выполнения задач
│   ├── MULTIHORIZON_RESULTS.md            # Результаты regression
│   ├── QUANTILE_REGRESSION_RESULTS.md     # Uncertainty analysis
│   ├── MASTER_AGENT_HANDOFF.md            # Полный контекст проекта
│   │
│   ├── presentation_plots/                # Графики для презентации
│   │   ├── 1_multihorizon_performance.png
│   │   ├── 2_risk_classification.png
│   │   ├── 3_uncertainty_quantification.png
│   │   └── 4_system_overview.png
│   │
│   ├── experiments/                       # Обученные модели
│   │   ├── q21_multihorizon_20260916_054306/
│   │   ├── q21_quantiles_h10_20260916_061952/
│   │   └── q21_quantiles_h30_20260916_061952/
│   │
│   ├── q21_dashboard_enhanced.py          # 🎨 Enhanced dashboard
│   ├── train_q21_multihorizon.py
│   ├── train_q21_quantiles.py
│   ├── analyze_q21_features.py
│   └── create_presentation_plots.py
│
└── project/                               # Production код
    ├── src/
    │   ├── inference/                     # 🔧 Inference engine
    │   │   ├── model_bundle.py
    │   │   ├── state_detector.py
    │   │   ├── quality_gates.py
    │   │   └── advisory_system.py
    │   │
    │   └── dashboard/                     # 🎨 Basic dashboard
    │       └── q21_advisory_dashboard.py
    │
    ├── docs/
    │   ├── DEMO_CHECKLIST.md
    │   └── Q21_ADVISORY_SYSTEM_GUIDE.md
    │
    └── tests/
        └── test_inference.py              # ✓ Test suite
```

---

## 📚 Документация - с чего начать?

### Для презентации (СРОЧНО)
1. 📋 **[FINAL_PRESENTATION_CHECKLIST.md](eda/FINAL_PRESENTATION_CHECKLIST.md)** - что показывать, что говорить
2. 📱 **[PRESENTATION_CHEAT_SHEET.md](eda/PRESENTATION_CHEAT_SHEET.md)** - цифры для запоминания
3. 🎨 **Launch dashboard** - `streamlit run eda/q21_dashboard_enhanced.py`

### Для понимания результатов
1. 📊 **[RESEARCH_SESSION_FINAL_SUMMARY.md](eda/RESEARCH_SESSION_FINAL_SUMMARY.md)** - executive summary
2. 📈 **[MULTIHORIZON_RESULTS.md](eda/MULTIHORIZON_RESULTS.md)** - regression детали
3. 📉 **[QUANTILE_REGRESSION_RESULTS.md](eda/QUANTILE_REGRESSION_RESULTS.md)** - uncertainty детали

### Для полного контекста
1. 📖 **[DOCUMENTATION_INDEX.md](eda/DOCUMENTATION_INDEX.md)** - навигация по всем docs
2. 🔄 **[MASTER_AGENT_HANDOFF.md](eda/MASTER_AGENT_HANDOFF.md)** - весь проект с начала
3. ✓ **[HANDOFF_COMPLETION_STATUS.md](eda/HANDOFF_COMPLETION_STATUS.md)** - что выполнено

---

## 🎨 Dashboard возможности

### Current Status Tab
- Текущий Q21 и прогноз на 1 час
- Risk level (Low/Medium/High/Critical)
- Margin to spec limit (10 ppm)
- State detection status
- Quality gates indicators
- Action recommendation

### Multi-Horizon Forecast Tab
- Timeline 30 min - 6 hours
- Point predictions
- 80% confidence intervals
- Risk probability curve
- Forecast details table

### Risk Analysis Tab
- Lambda switching (λ=10 vs λ=25)
- Recall vs Precision trade-off
- False alarm rate
- Confusion matrix preview
- Safety disclaimers

### Features Tab (placeholder)
- Feature importance (когда analysis готов)
- SHAP values visualization
- Top contributors

---

## 🔧 Production Components

### Inference System
**Локация:** `project/src/inference/`

**Modules:**
- `model_bundle.py` - Model loading с SHA256 verification
- `state_detector.py` - 5 states: normal/shutdown/startup/transition/unknown
- `quality_gates.py` - Freshness, frozen sensors, Q21=307, OOD
- `advisory_system.py` - Coordination и recommendation generation

**Features:**
- Thread-safe operations
- Comprehensive reason codes
- NO_ACTION logic
- Model verification
- Train median imputation
- Feature order preservation

### Tests
```bash
cd project
pytest tests/test_inference.py -v
```

---

## 📊 Presentation Materials

### Plots готовы в `eda/presentation_plots/`
1. **Multi-horizon performance** - MAE bars по горизонтам
2. **Risk classification** - Lambda sensitivity analysis
3. **Uncertainty quantification** - Coverage calibration
4. **System overview** - Key metrics summary

### Генерация plots
```bash
cd /Users/falexsun/code/Нефтекод
python eda/create_presentation_plots.py
```

---

## 🎯 Elevator Pitch (30 сек)

> "Разработана production-like advisory система для прогнозирования серы Q21 в дизеле
> с горизонтами от 30 минут до 6 часов. Основной прогноз (1 час): MAE 0.725 ppm,
> улучшение +14% vs baseline. Включает risk assessment (recall 97%), calibrated
> uncertainty intervals (80% coverage 77%), state detection и quality gates.
> Готова к теневому пилоту с human-in-the-loop."

---

## ✅ Что ПОКАЗЫВАТЬ жюри

1. **Multi-horizon система** - 5 горизонтов, все улучшают baseline
2. **Uncertainty quantification** - 80% intervals calibrated
3. **Risk trade-offs** - λ=10 vs λ=25, recall vs precision
4. **Production architecture** - state detection, quality gates, reason codes
5. **Interactive dashboard** - live demo scenarios

---

## ⚠️ Что ЧЕСТНО признавать

1. **Quantile median хуже regression** - используем regression для predictions, quantile для bounds
2. **50% intervals miscalibrated** - показываем только 80%
3. **Distribution shift observed** - требуется monitoring и retraining
4. **Advisory only** - не automatic control, требует human validation
5. **Correlation ≠ Causation** - scenario recommendations нужно pilot

---

## 🔄 Удалённый сервер (для retraining)

### SSH access
```bash
ssh faizov@37.75.249.204
cd /home/faizov/projects/NEFTECODE2026
```

### GPU info
```bash
nvidia-smi  # NVIDIA A100 80GB PCIe
```

### Python env
```bash
venv/bin/python  # Python с CatBoost 1.2.10
```

### Experiments
```bash
# Multi-horizon regression
venv/bin/python eda/train_q21_multihorizon.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --run-id q21_multihorizon_$(date +%Y%m%d_%H%M%S)

# Quantile regression
venv/bin/python eda/train_q21_quantiles.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --horizon 1.0 \
  --run-id q21_quantiles_h10_$(date +%Y%m%d_%H%M%S)

# Feature importance
venv/bin/python eda/analyze_q21_features.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --exp-dir q21_multihorizon_20260916_054306
```

---

## 🏆 Достижения

### Технические
- ✅ 5-horizon forecasting система
- ✅ All horizons beat persistence baseline
- ✅ Calibrated uncertainty intervals
- ✅ Configurable risk sensitivity
- ✅ Production-ready inference
- ✅ Interactive dashboard

### Методологические
- ✅ Residual learning approach
- ✅ Temporal validation splits
- ✅ Honest assessment of limitations
- ✅ Ensemble approach (regression + quantile + classification)
- ✅ Complete documentation

### Научные инсайты
- 🎯 h=3 sweet spot (+9.9% improvement)
- 📉 Linear MAE degradation with horizon
- ⚠️ Quantile median sensitive to drift
- ✅ 80% intervals robust
- 🔄 Specialized vs universal trade-off documented

---

## 📞 Быстрые команды

### Проверить модели
```bash
ls -lh project/models/*.cbm
```

### Запустить dashboard
```bash
cd eda && streamlit run q21_dashboard_enhanced.py
```

### Открыть plots
```bash
open eda/presentation_plots/*.png
```

### Запустить тесты
```bash
cd project && pytest tests/ -v
```

---

## 🎓 Статус готовности

### Для хакатона: ✅ 100%
- Inference system ✅
- Dashboard ✅
- Presentation plots ✅
- Documentation ✅
- Checklists ✅

### Для теневого пилота: ✅ 90%
- Production code ✅
- Quality gates ✅
- Model verification ✅
- Testing ✅
- Need: real-time integration ⬜

### Для промышленного управления: ⚠️ 50%
- Foundation ready ✅
- Need: controls validation ⬜
- Need: pilot testing ⬜
- Need: regulatory approval ⬜

---

## 🚨 Emergency contacts

### Если dashboard не запускается
→ Показать PNG из `eda/presentation_plots/`

### Если забыли цифры
→ Открыть `eda/PRESENTATION_CHEAT_SHEET.md`

### Если вопросы от жюри
→ Секция Q&A в `eda/FINAL_PRESENTATION_CHECKLIST.md`

---

## 📅 Timeline обучения

**Текущая сессия (2026-09-16):**
- Multi-horizon regression: ~1.5h (5 моделей)
- Risk classification h=3: ~15 min
- Quantile h=1: ~45 min (5 quantiles)
- Quantile h=3: ~45 min (5 quantiles)
- **Total GPU time:** ~3-4 часа на A100 80GB

**Предыдущие сессии:**
- Q21 target asymmetric: ~2h
- Cetane + density: ~4h
- Various explorations: ~6h
- **Total project GPU time:** ~15-20 часов

---

## 🎬 Финальный чеклист

### За 30 минут до презентации
- [ ] Запустить dashboard
- [ ] Проверить загрузку моделей
- [ ] Открыть presentation plots
- [ ] Прочитать cheat sheet
- [ ] Rehearsal elevator pitch

### Во время презентации
- [ ] Показать 4 основных графика
- [ ] Demo 3 scenarios на dashboard
- [ ] Упомянуть honest disclaimers
- [ ] Ответить на вопросы жюри

### После презентации
- [ ] Предоставить ссылки на docs (если попросят)
- [ ] Показать code structure (если интересно)
- [ ] Обсудить next steps

---

**ГОТОВ К ФИНАЛУ! 🚀🛢️🏆**

**Удачи на презентации!**

---

**Quick links:**
- 📋 [Presentation Checklist](eda/FINAL_PRESENTATION_CHECKLIST.md)
- 📱 [Cheat Sheet](eda/PRESENTATION_CHEAT_SHEET.md)
- 📖 [Documentation Index](eda/DOCUMENTATION_INDEX.md)
- 📊 [Research Summary](eda/RESEARCH_SESSION_FINAL_SUMMARY.md)
