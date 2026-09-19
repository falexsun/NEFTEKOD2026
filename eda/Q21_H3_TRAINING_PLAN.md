# Q21 h=3 Training Plan - Fixed Version

**Date:** 2026-09-16  
**Status:** Training in progress on A100 GPU  
**PID:** 574810

## Critical Bug Fixed

**Problem:** Original script used `lag_shift = 18` for Q21 history features, shifting them 3 hours into the past. This created a mismatch:
- Target: Q21 at t+3h
- Features: Q21 at t-3h  
- Result: Model tried to predict t+3h from t-3h, creating 6-hour gap → MAE 26.755 ppm (catastrophic)

**Solution:** Q21 history now uses origin time (t=0), matching the successful h=1 approach:
- Features from origin: Q21_origin, Q21_past_mean_*, Q21_past_std_*, Q21_past_change_*
- Target: Q21 shifted -18 samples (t+3h)
- Proper temporal alignment

## Architecture Changes

### Feature Engineering
1. **Process features** (1h/3h/6h/12h/24h windows):
   - Current values (_now)
   - Rolling means/stds
   - Changes from past

2. **Q21 history at origin** (no lag):
   - Q21_origin (current value)
   - Q21_invalid_or_offscale flag
   - Rolling statistics: mean/std/change over 1/3/6/12/24h

3. **Control dynamics**:
   - Temperature/pressure/flow controls
   - Interactions: Q21 × control_change

4. **Temporal encoding**:
   - Hour cyclical (sin/cos)
   - Day of week

### Model Configuration
- **Regression:** CatBoostRegressor, iterations=2000, depth=6, lr=0.03, GPU
- **Classification:** CatBoostClassifier, λ ∈ {5, 10, 25, 50}, GPU
- **Threshold selection:** Asymmetric cost on calibration set

## Expected Results

Based on handoff h=3 benchmarks (from old run with different features):
- **Regression:** MAE should be ~1.4 ppm (vs persistence 1.443)
- **Classification:** AP ~0.72, AUC ~0.82 (worse than persistence AP 0.75)

If new features improve h=3, we might see:
- Regression: MAE < 1.4 ppm
- Classification: AP > 0.75

## Timeline
- **Started:** 2026-09-16 ~current time
- **Duration:** ~15-20 minutes for regression + 4 classification models
- **Output:** `/home/faizov/projects/NEFTECODE2026/eda/experiments/q21_h3_improved_20260916/`

## Next Steps After Completion

1. **Download results:**
   ```bash
   scp -r faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/eda/experiments/q21_h3_improved_20260916 \
       /Users/falexsun/code/Нефтекод/eda/experiments/
   ```

2. **Compare with h=1:**
   - If h=3 regression MAE < 1.5 ppm → use it
   - If h=3 classification AP > 0.75 → use it
   - Otherwise stick with h=1 for demo

3. **Update advisory system:**
   - Add h=3 models to inference bundle
   - Show both 1h and 3h forecasts in dashboard
   - Label h=3 as "medium-term outlook"

4. **Dashboard demo flow:**
   - Current Q21
   - 1-hour forecast (high confidence)
   - 3-hour forecast (medium confidence)
   - Risk assessment at both horizons
   - NO_ACTION gates still apply

## Monitoring Commands

```bash
# Check status
./eda/monitor_q21_h3.sh

# Check GPU
ssh faizov@37.75.249.204 nvidia-smi

# Follow log
ssh faizov@37.75.249.204 "tail -f /home/faizov/projects/NEFTECODE2026/eda/train_q21_h3_final_*.log"

# Kill if needed
ssh faizov@37.75.249.204 "kill 574810"
```

## Key Differences from h=1

| Aspect | h=1 | h=3 (this run) |
|--------|-----|----------------|
| Horizon | 1 hour (6 samples) | 3 hours (18 samples) |
| Q21 history | At origin | At origin (FIXED) |
| Feature windows | 1/3/6/12/24h | Same |
| Expected MAE | 0.725 ppm | ~1.4 ppm |
| Expected AP | 0.906 | ~0.72 |
| Use case | Immediate action | Medium-term planning |

## Risk Assessment

**Low risk:**
- Feature engineering matches proven h=1 pattern
- GPU training stable
- Temporal splits preserved

**Potential issues:**
- h=3 inherently harder due to longer horizon
- Smaller training set after temporal alignment
- May still underperform persistence baseline

**Mitigation:**
- Ensemble with h=1 if h=3 underperforms
- Use h=3 only for qualitative trend, not hard thresholds
- Mark h=3 as "experimental" in demo if metrics poor
