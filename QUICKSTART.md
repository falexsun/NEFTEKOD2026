# Q21 Advisory System — Quick Start Guide

**NEFTECODE 2026 Hackathon Solution**  
**Status:** ✅ Ready for Demo & Shadow Pilot

---

## TL;DR

```bash
# 1. Install dependencies
cd /Users/falexsun/code/Нефтекод/project
pip install -e .

# 2. Run dashboard
streamlit run src/dashboard/q21_advisory_dashboard.py

# 3. Open browser
# http://localhost:8501
```

**Demo ready in 2 minutes!** 🚀

---

## What is this?

**Q21 Advisory System** — production-like система для прогнозирования содержания серы в керосине с горизонтом 1 час.

**Key features:**
- ✅ MAE 0.725 ppm (улучшение +14% vs persistence baseline)
- ✅ Risk detection: AP 0.906, AUC 0.959
- ✅ Safety gates (6 types of checks)
- ✅ State detection (normal/shutdown/startup)
- ✅ Interactive dashboard с настройкой trade-offs

**Not for:**
- ❌ Автоматическое управление установкой
- ❌ Гарантии качества < 10 ppm
- ❌ Замена решений технолога

---

## Repository Structure

```
Нефтекод/
├── data/                          # Телеметрия (189K samples, 10min step)
│   ├── avt_tags.csv              # 71 тег АВТ
│   └── 242000_tags.csv           # 26 тегов 24-2000
│
├── eda/                           # Experiments & analysis
│   ├── experiments/
│   │   └── q21_target_asymmetric_v3_20260915/
│   │       └── models/           # ✅ Trained models here
│   │           ├── reg_h1_all_plus_q21_history_q50.cbm
│   │           └── risk_h1_controls_plus_q21_history_s42.cbm
│   │
│   ├── MASTER_AGENT_HANDOFF.md   # 📖 Full project handoff
│   ├── Q21_ADVISORY_SYSTEM_GUIDE.md  # 📖 User guide
│   ├── DEMO_CHECKLIST.md         # 📋 Demo preparation
│   ├── HACKATHON_PRESENTATION.md # 📊 Presentation slides
│   └── FINAL_PROJECT_SUMMARY.md  # 📄 This project summary
│
└── project/                       # Production code
    ├── src/
    │   ├── inference/            # ✅ Core inference system
    │   │   ├── model_bundle.py
    │   │   ├── state_detector.py
    │   │   ├── quality_gates.py
    │   │   └── advisory_system.py
    │   │
    │   └── dashboard/            # ✅ UI
    │       └── q21_advisory_dashboard.py
    │
    ├── tests/                    # ✅ Unit tests
    │   └── test_inference.py
    │
    └── pyproject.toml            # Dependencies
```

---

## Quick Start

### 1. Install Dependencies

```bash
cd /Users/falexsun/code/Нефтекод/project
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Required:**
- Python ≥3.11
- CatBoost ≥1.2.10
- Streamlit, Plotly, pandas, numpy

### 2. Verify Models

```bash
cd /Users/falexsun/code/Нефтекод/eda/experiments/q21_target_asymmetric_v3_20260915/models

# Check models exist
ls -lh *.cbm

# Verify SHA256 checksums
shasum -a 256 *.cbm
```

**Expected output:**
```
95469b40d8b550fa1dbf16e7faba4ed400c0a9398fe015f8042c00259d478eee  reg_h1_all_plus_q21_history_q50.cbm
a0ef98b61af8ba439260e546da13e787c171f0ec90ebd5c300d6b89d18f3e496  risk_h1_controls_plus_q21_history_s42.cbm
```

### 3. Run Dashboard

```bash
cd /Users/falexsun/code/Нефтекод/project
source .venv/bin/activate
streamlit run src/dashboard/q21_advisory_dashboard.py
```

**Browser will open automatically at `http://localhost:8501`**

### 4. Run Tests (optional)

```bash
pytest tests/test_inference.py -v
```

---

## Dashboard Demo Scenarios

### Scenario 1: Normal Operation, Low Risk

**Setup:**
- Use demo data (checkbox checked)
- Q21 current: 8.5 ppm
- Lambda: 25 (safety-oriented)

**Expected:**
- ✅ State: NORMAL
- ✅ Forecast: ~8.2 ppm
- ✅ Risk: ~5% (LOW)
- ✅ Action: MONITOR

### Scenario 2: Escalating Risk

**Setup:**
- Modify demo data: Q21 = 11.0 ppm
- Lambda: 25

**Expected:**
- ⚠️ State: NORMAL
- ⚠️ Forecast: ~11.5 ppm
- ⚠️ Risk: ~75% (CRITICAL)
- ⚠️ Action: INVESTIGATE

### Scenario 3: Lambda Trade-off

**Demo:**
- Switch λ from 25 to 10
- Show change in trade-off metrics

**Explain:**
- λ=25: Recall 97.3%, Precision 46.5% (catch all risks)
- λ=10: Recall 94.5%, Precision 55.8% (balanced)

### Scenario 4: Safety Gate — Q21=307

**Setup:**
- Modify demo: Q21 = 307

**Expected:**
- ❌ Action: NO_ACTION
- ❌ Reason: Q21_CODE_307
- ❌ Message: "Q21 shows unreliable code 307 (analyzer fault)"

---

## Model Performance

### Regression (Q21 forecast, h=1)

| Split | MAE | RMSE | Samples |
|-------|-----|------|---------|
| Validation | 0.656 | 0.988 | 25,626 |
| Calibration | 0.675 | 1.012 | 26,022 |
| **Evaluation** | **0.725** | **1.089** | **29,835** |
| Persistence (eval) | 0.844 | 1.245 | 29,835 |

**Improvement: +14.1% vs persistence**

### Risk Classification (Q21 > 10 ppm, h=1)

| Lambda | Recall | Precision | FPR | AP | AUC |
|--------|--------|-----------|-----|-----|-----|
| λ=10 | 94.5% | 55.8% | 21.4% | 0.906 | 0.959 |
| λ=25 | **97.3%** | 46.5% | 31.9% | 0.906 | 0.959 |

**For demo: use λ=25 (safety-oriented)**

---

## API Usage

### Python API

```python
from pathlib import Path
from src.inference.advisory_system import Q21AdvisorySystem
import pandas as pd

# Initialize
models_dir = Path("eda/experiments/q21_target_asymmetric_v3_20260915/models")
system = Q21AdvisorySystem(models_dir, lambda_penalty=25)

# Prepare telemetry (last 12 points, 10-min step)
telemetry = pd.DataFrame({
    'timestamp': pd.date_range(end=pd.Timestamp.now(), periods=12, freq='10min'),
    'Q21': [8.2, 8.5, 8.7, 9.1, 9.3, 9.5, 9.8, 10.2, 10.5, 10.8, 11.1, 11.3],
    'F30': [100.5] * 12,
    'F31': [45.2] * 12,
    'W70': [78.5] * 12,
    'T33': [285.3] * 12,
    'T55': [365.7] * 12,
    # ... other tags
})

# Generate advisory
advisory = system.generate_advisory(
    telemetry=telemetry,
    current_q21=11.3
)

# Results
print(f"State: {advisory.plant_state.value}")
print(f"Q21 forecast: {advisory.q21_forecast_1h:.1f} ppm")
print(f"Risk: {advisory.exceedance_probability:.1%}")
print(f"Action: {advisory.action}")
print(f"Message: {advisory.message}")
```

### Output Format

```python
@dataclass
class AdvisoryRecommendation:
    timestamp: pd.Timestamp
    plant_state: PlantState  # NORMAL, SHUTDOWN, STARTUP, etc.
    q21_current: float
    q21_forecast_1h: float
    exceedance_probability: float
    exceedance_risk: str  # LOW, MEDIUM, HIGH, CRITICAL
    action: str  # MONITOR, NO_ACTION, INVESTIGATE
    reason_code: str
    message: str
    confidence: str  # HIGH, MEDIUM, LOW, NO_CONFIDENCE
    details: Dict
    validation_failures: List[ValidationResult]
```

---

## Documentation

**Read these for details:**

1. **`MASTER_AGENT_HANDOFF.md`** — Complete project handoff
   - Task and expectations
   - Data sources
   - Model results
   - Architecture
   - Readiness assessment

2. **`Q21_ADVISORY_SYSTEM_GUIDE.md`** — User guide
   - Installation
   - API usage
   - Interpreting results
   - Deployment

3. **`DEMO_CHECKLIST.md`** — Demo preparation
   - Pre-demo setup
   - Demo script (5-7 minutes)
   - Q&A answers prepared
   - Emergency troubleshooting

4. **`HACKATHON_PRESENTATION.md`** — Presentation slides
   - 16 main slides
   - 3 backup slides with technical details
   - Ready to convert to PowerPoint

5. **`FINAL_PROJECT_SUMMARY.md`** — Complete summary
   - What was done
   - Results
   - Metrics
   - Next steps

---

## Important Disclaimers

⚠️ **This system is NOT for:**

1. **Automated control** of the plant
   - It's an advisory tool, not a control system
   - Recommendations require expert review

2. **Guaranteeing quality** < 10 ppm
   - It predicts risk, doesn't prevent violation
   - Final decision is with the technologist

3. **Causal recommendations**
   - Model shows correlation, not proven causation
   - SHAP importance ≠ control effectiveness

4. **Production use** without pilot
   - Ready for shadow pilot
   - Requires validation for production deployment

**Correct positioning:**
- ✅ "Production-like advisory prototype"
- ✅ "Ready for shadow pilot"
- ✅ "Helps technologist, doesn't replace"

**Wrong positioning:**
- ❌ "Automated control system"
- ❌ "Guaranteed quality < 10 ppm"
- ❌ "Production-ready for automatic operation"

---

## Troubleshooting

### Dashboard doesn't start

```bash
# Check dependencies
pip list | grep streamlit

# Reinstall if needed
pip install streamlit plotly pandas numpy catboost

# Check models exist
ls -la eda/experiments/q21_target_asymmetric_v3_20260916/models/
```

### Models not loading

```bash
# Verify checksums
cd eda/experiments/q21_target_asymmetric_v3_20260916/models
shasum -a 256 *.cbm

# If wrong, re-download from server
scp faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/eda/experiments/q21_target_asymmetric_v3_20260916/models/*.cbm .
```

### Graphs not displaying

- Refresh browser (F5)
- Check browser console for errors
- Try Chrome (recommended)
- Check Streamlit version ≥1.63.0

---

## Contact & Support

**For hackathon:**
- Demo: Use `DEMO_CHECKLIST.md`
- Q&A: Prepared answers in checklist
- Issues: Check `FINAL_PROJECT_SUMMARY.md`

**For future development:**
- Architecture: `MASTER_AGENT_HANDOFF.md`
- API: `Q21_ADVISORY_SYSTEM_GUIDE.md`
- Training: Scripts in `eda/train_*.py`

---

## License

NEFTECODE 2026 Hackathon Project

---

**Ready to demo! Good luck! 🚀**
