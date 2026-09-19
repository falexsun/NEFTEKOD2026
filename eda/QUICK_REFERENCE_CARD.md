# Q21 Advisory System - Quick Reference Card

**Проект:** NEFTECODE 2026 | **Статус:** ✅ ГОТОВ | **Дата:** 2026-09-16

---

## 🎯 ELEVATOR PITCH (30 сек)

> Production-like advisory система для прогнозирования серы Q21 в дизеле (30 мин - 6 часов).
> h=1: MAE 0.725 ppm (+14% vs baseline). Risk: recall 97%. Uncertainty: 80% calibrated.
> Control tags validated. Готов к теневому пилоту с human-in-the-loop.

---

## 📊 KEY METRICS

| Метрика | Значение | Статус |
|---------|----------|--------|
| **h=1 MAE** | **0.725 ppm** | ⭐ PRIMARY |
| **h=3 MAE** | **1.312 ppm** | ⭐ +9.9% |
| **Risk Recall** | **97.3%** | ✅ λ=25 |
| **80% Coverage** | **77.3%** | ✅ Calibrated |
| **Models** | **15 trained** | ✅ A100 |

---

## 🔥 КРИТИЧЕСКИЕ ОБНОВЛЕНИЯ (16.09)

✅ **Q21=307** - "это выброс" (подтверждено)  
✅ **Плотность** - 820-845 kg/m³ (specs известны)  
✅ **F31** - Расход H₂ (validated CRITICAL)  
✅ **T33** - Температура К-2 (validated HIGH)  
✅ **T55** - Температура П-3 (validated HIGH)  
✅ **VAK формулы** - 9 моделей получены  
✅ **71 тег** - полное описание  

---

## 🚀 БЫСТРЫЙ СТАРТ

### Dashboard
```bash
cd eda && streamlit run q21_dashboard_enhanced.py
```

### Графики
```bash
open presentation_plots/*.png
```

### Копировать новые файлы
```bash
cp /tmp/formuly_vak.csv docs/
cp /tmp/tegi_avt.csv docs/
```

---

## 📁 ГЛАВНЫЕ ДОКУМЕНТЫ

| Файл | Назначение |
|------|------------|
| `README_FINAL_UPDATED.md` | 🚀 Начать отсюда |
| `FINAL_PRESENTATION_CHECKLIST.md` | ✅ Для финала |
| `PRESENTATION_CHEAT_SHEET.md` | 📱 Шпаргалка |
| `CRITICAL_UPDATE_NEW_INFO.md` | 🔥 Новое важное |
| `PRODUCTION_HANDOFF_FOR_NEXT_AGENT.md` | 🔧 Внедрение |

---

## 🎨 ЧТО ПОКАЗЫВАТЬ

1. Multi-horizon timeline (5 horizons)
2. Risk λ=10 vs λ=25
3. 80% intervals calibrated
4. Production architecture
5. **Validated control tags** ⭐

---

## ⚠️ ЧЕСТНЫЕ DISCLAIMERS

❌ 50% intervals miscalibrated (44%)  
❌ Quantile median хуже regression (2.9 vs 0.8)  
❌ Advisory only, не automatic control  
❌ Correlation ≠ Causation  
❌ Need operating ranges  

---

## 🔬 IMPROVEMENT POTENTIAL

**HIGH:** Add VAK physics features (+2-5% MAE)  
**MEDIUM:** Calibrate density (820-845 target)  
**LOW:** Multi-task Q21 + density  

---

## 📞 HELP

**Stuck?** Read `DOCUMENTATION_INDEX.md`  
**Questions?** Check `PRODUCTION_HANDOFF_FOR_NEXT_AGENT.md`  
**Forgot metrics?** See `PRESENTATION_CHEAT_SHEET.md`  

---

## ✅ STATUS

**Research:** 100% ✅  
**Models:** 100% ✅  
**Code:** 100% ✅  
**Dashboard:** 100% ✅  
**Docs:** 100% ✅  
**Validation:** 90% ✅  

**READY FOR FINAL! 🏆**
