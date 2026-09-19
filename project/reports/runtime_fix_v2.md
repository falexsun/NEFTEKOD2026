# Runtime Fix v2 — Report

## Fixed

### 1. Model Wrapper Feature Extraction
- `_extract_feature_names_from_model()` now unwraps `wrapper.model` to access inner estimator
- CatBoost: `CatBoostRegressor.feature_names_` (721 features)
- LightGBM: `LGBMRegressor.feature_name_`
- XGBoost: `XGBRegressor.feature_names_in_`

### 2. Removed `sorted(feature_vector.keys())`
- Quality Agent: uses `model_metadata.feature_names` (stored order from model artifact)
- Surrogate Model: uses `self.feature_names` (stored order)
- If metadata missing → `model_available=False` → ABSTAIN

### 3. Strict Schema Validation
- `ModelArtifactMetadata.validate_feature_vector()` checks feature count + names
- Any mismatch → `model_available=False` with reason
- No silent `feature_vector.get(k, 0.0)` for missing features

### 4. Canonical Tag Naming
- Format: `{source}_{raw_name}` — `avt_T1`, `u24_T5`
- `src/shared/tags/normalization.py`: `normalize_tag()`, `denormalize_tag()`
- Prevents AVT/U24 collision (avt_T6 ≠ u24_T6)

### 5. ControlRegistry
- `src/shared/tags/registry.py`: reads `configs/controls.yaml`
- `ControlSpec` with name, semantic_name, unit, stage, role, model_range, max_step
- `is_control()` checks role ∈ {control_candidate, both}
- `validate_control_value()` checks range + max_step
- `get_optimization_bounds()` returns only control_candidates with ranges

### 6. Safety Agent
- `check_quality_prediction()` gate: rejects if model_available=False
- Control range validation via ControlRegistry
- Fail-closed on any exception

### 7. Orchestrator
- Uses `state.feature_vector` (not separate arg)
- Checks `quality_pred.model_available` before proceeding
- Checks `allow_optimization` from DataQuality Agent
- Checks `simulation_available` from Optimizer
- Full `decision_id` (not truncated UUID)

### 8. Surrogate Model
- `SimulationResult` with explicit status ("ok"/"unavailable"/"error")
- Exact `control_to_feature_map` — NO substring matching
- lag/rolling features NOT modified by actions
- Returns status="unavailable" when no model loaded

### 9. API
- Singleton agents (created at startup, not per request)
- `/model/info` endpoint for model artifact metadata
- `/ready` uses `is_ready` (model + schema), not just `is_available`
- `/safety/check` uses typed `SafetyCheckRequest` (no magic defaults)
- `/agents/status` shows all agent states
- Controls loaded from ControlRegistry, not from telemetry ±20%

### 10. Docker
- Trainer in `profiles: [training]` — does NOT start by default
- `docker compose up --build` works without trainer
- Optional services (mlflow, minio) in `profiles: [monitoring]`

### 11. Source Freshness
- StateBuilder properly populates `SourceFreshness` with real age values
- AVT, U24, PAK sulfur, PAK density, LIMS freshness tracked

### 12. Reliability Agent
- Frozen sensor detection uses rolling history (not `val == int(val)`)
- Canonical tags prevent avt_T6/u24_T6 history collision
- Baseline risk documented as assumption

### 13. QualityPrediction Schema
- `confidence: float | None` (None when no calibrated confidence)
- `model_available: bool`
- `unavailability_reason: str | None`
- `uncertainty_method: str | None`
- `uncertainty_value: float | None`

## Remaining Limitations

1. **Runtime Feature Buffer**: Full721-feature pipeline requires history for lag/rolling/slope features. Current `/decision` uses raw telemetry as feature_vector (will ABSTAIN with real model due to schema mismatch). Full feature buffer is Phase 3 work.

2. **Surrogate Model**: No real surrogate loaded — reports unavailable. Optimization Agent correctly ABSTAINs.

3. **Quality Source Resolver**: Policy YAML created but resolver logic not yet integrated into runtime flow.

4. **Production/Energy Proxy**: Returns None (no semantic tag lists configured). Honest but limited.

5. **No Postgres writes**: Schema not created. No persistent storage of decisions.

6. **No Redis Streams consumers**: Events published by replay but no consumer services.

7. **No Prometheus/Grafana**: Monitoring infrastructure deferred.

## Runtime Path

```
DecisionRequest
  → normalize tags (canonical avt_T1, u24_T5)
  → StateBuilder (ProcessState + SourceFreshness)
  → feature_vector (currently raw telemetry; needs RuntimeFeatureBuffer for full 721)
  → Orchestrator
    → DataQuality Agent (checks freshness, frozen, jumps)
    → Quality Agent (model.predict with correct feature order, or ABSTAIN)
    → Reliability Agent (envelope + frozen via history)
    → Optimization Agent (ControlRegistry bounds, NO CHANGE baseline)
    → Safety Agent (model_available, control ranges, fail-closed)
    → Recommendation / ABSTAIN
```

## Model Integration

- CatBoost: loaded successfully, 721 features extracted from inner CatBoostRegressor
- LightGBM: loaded successfully, 721 features via feature_name_
- XGBoost: loaded successfully, 721 features via feature_names_in_
- Feature order: from model artifact, NOT sorted()
- Schema validation: strict — any mismatch → ABSTAIN

## Tests

```
passed: 27
failed: 0
skipped: 1 (Docker smoke)
```

## Docker

`docker compose up --build` starts:
- gateway (FastAPI, port8000)
- dashboard (Streamlit, port8501)
- redis (port6379)
- postgres (port5432)

Does NOT start: trainer, mlflow, minio (profiles only)

## Known ABSTAIN Cases

1. No ML model loaded → model_available=False
2. Feature schema mismatch (721 features expected, fewer provided)
3. Model inference error
4. Data quality insufficient (too few signals)
5. All quality sources stale
6. Surrogate unavailable → cannot evaluate scenarios
7. No safe scenarios (all rejected by Safety Agent)
8. All scenario simulations failed
9. Insufficient history for lag/rolling features (when RuntimeFeatureBuffer implemented)
