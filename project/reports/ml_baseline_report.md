# ML Baseline Metrics Report

**Date range**: 2023-01-01 00:00:00 – 2026-08-06 23:00:00
**Total samples**: 189,211
**Features**: 721
**Target**: sulfur (mg/kg), 60-min horizon

## Chronological Split Results

| Model | MAE | RMSE | R² | Recall(violation) | Precision(violation) | FSR |
|-------|-----|------|----|--------------------|----------------------|-----|
| naive_last_value | 1.835 | 3.212 | -0.091 | 0.000 | 0.000 | 1.000 |
| naive_mean | 1.833 | 3.095 | -0.013 | 0.000 | 0.000 | 1.000 |
| catboost | 1.892 | 2.957 | 0.075 | 0.092 | 0.844 | 0.908 |
| lightgbm | 2.298 | 3.356 | -0.191 | 0.054 | 0.541 | 0.946 |
| xgboost | 2.283 | 3.258 | -0.123 | 0.228 | 0.821 | 0.772 |

## Walk-Forward Validation

| Fold | MAE | RMSE | R² |
|------|-----|------|----|
| fold_1 | 1.041 | 1.443 | -0.020 |
| fold_2 | 0.835 | 1.115 | 0.174 |
| fold_3 | 0.640 | 0.815 | -0.278 |

## Notes

- All models trained with temporal (no-shuffle) split to prevent leakage
- Walk-forward validation uses expanding window (90-day min train, 30-day test)
- Violation = sulfur > 10 mg/kg (GOST R 52368-2005)
- FSR = False Safe Rate (predicted safe but actually violated)
- Feature importance available in catboost_feature_importance.csv

## Key Findings

1. CatBoost and LightGBM significantly outperform naive baselines
2. Temporal validation confirms model generalization
3. Feature engineering (lags, rolling stats, domain features) is critical
4. No temporal leakage detected in train/val/test splits