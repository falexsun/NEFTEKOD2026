# Data Audit Report

## Summary

### AVT Unit Telemetry
- **Rows**: 189,217
- **Columns**: 71
- **Date range**: 2023-01-01 00:00:00 – 2026-08-07 00:00:00
- **Duration**: 1314 days
- **Missing ratio**: 0.0000
- **Constant columns**: 0
- **Duplicate timestamps**: 0

### 24-2000 Unit Telemetry
- **Rows**: 189,217
- **Columns**: 26
- **Date range**: 2023-01-01 00:00:00 – 2026-08-07 00:00:00
- **Duration**: 1314 days
- **Missing ratio**: 0.0000

### PAK Sulfur (Online Analyzer)
- **Records**: 189,649
- **Date range**: 2023-01-01 00:00:00 – 2026-08-10 00:00:00

### Sulfur Target Analysis

#### PAK Sulfur
- **Count**: 189,649
- **Mean**: 8.43 mg/kg
- **Median**: 8.37 mg/kg
- **Std**: 1.98 mg/kg
- **Min**: 0.00 mg/kg
- **Max**: 20.00 mg/kg
- **Count > 10 mg/kg**: 22,845
- **Fraction > 10 mg/kg**: 0.1205

### LIMS Laboratory Data
- **Total records**: 36,800
- **Sampling points**: 6
- **Quality indicators**: 22
- **Indicators**: cloud_point2, IBP, EBP, cloud_point, PTF, T90, density_15, sulfur_avg, pour_point, T50, cetane_number, T90b, sulfur_md, T95, ODIS_250, density_avg, cloud_point_350, cloud_point_350b, T98, flash_point

### Data Alignment
- **Overlap start**: 2023-01-01 00:00:00
- **Overlap end**: 2026-08-07 00:00:00

## Key Findings

1. Both telemetry datasets (AVT, 24-2000) have consistent 10-minute sampling from 2023-01-01
2. PAK sulfur provides continuous target variable for ML training
3. LIMS data is irregular (~every 2-3 days) but provides lab-validated quality measurements
4. Primary ML target: PAK sulfur (24-2000:Mg.Sulfur) — online, continuous, directly relevant
5. Secondary target: PAK density (24-2000:D15) — available from 2025-03-05
6. Sulfur values should be checked against 10 mg/kg limit (GOST R 52368-2005)

## Assumptions

- All assumptions documented in configs/assumptions.yaml
- D10 column in AVT assumed to be density (integer values ~307, possibly coded)
- PAK sulfur in ppm assumed equivalent to mg/kg
- VAK (virtual analyzer) formulas from tag dictionary provide fallback predictions