# Runtime Fix v4 — Report

## Implemented

### 1. StateBuilder Runtime Fix
- Added `build_state_from_runtime(timestamp, avt_telemetry, unit_242000_telemetry, quality, ...)`
- No column list dependency — accepts pre-normalized canonical dicts directly
- Original `build_state()` (alias `build_state_from_row()`) preserved for batch pipeline

### 2. Shared FeatureTransformer
- `src/feature_service/transformer.py` — single source of truth
- Contains `FEATURE_KEY_COLUMNS`, `LAG_WINDOWS`, `ROLLING_WINDOWS`, `SLOPE_COLUMNS`, `MISSING_FLAG_COLUMNS`
- `transform(df)` applies: lags, rolling, delta, slope, missing flags, domain features, ffill+fillna(0)
- Both training (`features.py`) and runtime (`runtime_buffer.py`) reference same constants

### 3. RuntimeFeatureBuffer Uses Shared Transformer
- `_transformer = FeatureTransformer()` — same formulas as training
- `history_ready` checks both `history_size >= min_points` AND `history_duration_minutes >= min_duration`
- `build_feature_vector(expected_features)` returns exact model schema or error

### 4. QualitySourceResolver Integrated
- `/decision` resolves sulfur source before building state
- Priority: LIMS=1, PAK=2, VAK=3 (from quality_source_policy.yaml)
- Freshness check: LIMS max_age=4320min, PAK max_age=120min
- If all stale → no quality signal → allow_optimization=False

### 5. Single Surrogate Instance
- One `SurrogateModel()` created at startup
- Shared between `_agents["surrogate"]` and `_agents["optimization"].surrogate`
- `/agents/status` verifies `single_surrogate` identity

### 6. RuntimeConfig Applied
- `src/shared/config/runtime.py` loads `configs/runtime.yaml`
- `apply_to_data_quality_agent()` sets thresholds
- `apply_to_safety_agent()` sets limits
- `apply_to_reliability_agent()` sets baseline risk

### 7. Timestamp Validation
- `DecisionRequest` uses `datetime | None` (Pydantic handles validation)
- Invalid ISO format → 422 automatically
- No silent `except: return None`

### 8. Proper Early ABSTAIN
- Early ABSTAIN gets real `uuid.uuid4()` (not "N/A")
- Returns `AbstainRecommendation`-compatible dict
- Consistent response format for all `/decision` responses

### 9. Singleton Orchestrator
- Created once at startup with all agents
- Controls passed once from ControlRegistry
- DQ/Reliability history preserved between requests

### 10. Runtime Reset Endpoint
- `POST /runtime/reset` — clears feature buffer, DQ history, reliability history
- For demo/test only

### 11. Model Info Correctness
- Reports `model_feature_count`, `history_size`, `history_duration_minutes`, `history_ready`

## Feature Parity
- `FeatureTransformer.transform()` uses identical formulas for training and runtime
- `FEATURE_KEY_COLUMNS` shared via `src/feature_service/transformer.py`
- Missing flags: same 20 columns
- Fill policy: ffill() then fillna(0)
- Domain features: same5 formulas

## Runtime Readiness
- `/ready` reports: `prediction_ready`, `quality_model_ready`, `history_ready`, `runtime_schema_ready`, `optimization_ready`, `surrogate_ready`
- `prediction_ready = quality_model_ready AND runtime_schema_ready`

## Safety
- max_step via ControlRegistry with current state values
- Fail-closed on any exception
- Unavailable model → reject

## Tests
```
passed: 29
failed: 0
skipped: 1 (Docker smoke)
```

## Known Limitations
1. **Surrogate not loaded** — no real surrogate model → optimization ABSTAINs
2. **Feature parity test** — batch vs runtime parity not yet verified against real data (requires running both pipelines on same timestamp)
3. **HTTP warmup test** — not yet implemented (needs40 sequential requests)
4. **Quality inference after warmup** — not yet verified (needs full721-feature warmup)
5. **No Postgres/Redis/Prometheus/Grafana**
