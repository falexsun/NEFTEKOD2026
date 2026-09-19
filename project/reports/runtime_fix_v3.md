# Runtime Fix v3 — Report

## Implemented

### 1. API Tag Normalization
`/decision` now normalizes raw tags via `normalize_telemetry_dict()`:
- `{"T6": 234}` (AVT) → `{"avt_T6": 234}`
- `{"T6": 8.5}` (U24) → `{"u24_T6": 8.5}`
- No more AVT/U24 collision.

### 2. StateBuilder Integration
`/decision` uses `StateBuilder.build_state()` to construct `ProcessState`.
No more manual `ProcessState(avt_telemetry=...)`.

### 3. Sulfur/Freshness Integration
Request fields `pak_sulfur_value`, `pak_sulfur_timestamp` populate `state.quality["sulfur"]` via StateBuilder.
`SourceFreshness` properly populated: `avt_minutes`, `u24_minutes`, `pak_sulfur_minutes`, etc.

### 4. QualitySourceResolver
`src/feature_service/quality_source_resolver.py` — reads `configs/quality_source_policy.yaml`.
Resolves by priority (LIMS=1, PAK=2, VAK=3) + freshness check.
Returns `None` when all sources stale → caller ABSTAINs.
**Status**: implemented, not yet integrated into Orchestrator flow (Orchestrator still uses state.quality directly).

### 5. RuntimeFeatureBuffer
`src/feature_service/runtime_buffer.py` — stores last N telemetry points.
Builds full721-feature vector (lag, rolling, delta, slope, missing flags, domain features) using same logic as training.
`feature_ready` = True when ≥36 points (6 hours at10-min).
`build_feature_vector(expected_features)` returns exact model schema or error.
Replay warmup: each point pushes to buffer sequentially.

### 6. Model Schema Matching
`build_feature_vector()` checks `len(vector) == len(expected_features)`.
Missing features → returns `(None, reason)`, not zero-filled.

### 7. Surrogate Strict Schema
No more `modified_features.get(k, 0.0)`.
Missing features → `SimulationResult(status="unavailable")`.

### 8. Safety max_step with ProcessState
`check_scenario()` now accepts `state: ProcessState`.
For each action param, gets current value from state and passes to `ControlRegistry.validate_control_value(param, value, current=current)`.
`avt_T1=130, max_step=5, candidate=150` → REJECT.

### 9. Safety Endpoint Action Validation
`/safety/check` builds `ScenarioEvaluation` from request and calls `agent.check_scenario()`.
`SafetyCheckRequest` includes `current_state` dict for max_step checking.

### 10. Recommendation confidence=None
`Recommendation.confidence: float | None = None` — validates with None.

### 11. Optimizer No Magic Defaults
`predictions.get("sulfur", 0.0)` removed.
If `sulfur` or `sulfur_std` missing from simulation → `simulation_status="error"`.

### 12. Config Changes
- `configs/quality_source_policy.yaml` — explicit priority fields
- `configs/runtime.yaml` — thresholds externalized from agents
- `configs/assumptions.yaml` — updated with A011-A014

### 13. HTTP Behavioral Tests
`TestClient` tests: `/health`, `/ready`, `/model/info`, `/decision`.

## Runtime Flow (actual)

```
DecisionRequest
  → normalize_telemetry_dict(avt, "avt")
  → normalize_telemetry_dict(u24, "u24")
  → RuntimeFeatureBuffer.push(timestamp, avt, u24, pak_sulfur, pak_density, lims)
  → RuntimeFeatureBuffer.build_feature_vector(model.feature_names)
    → if insufficient history → ABSTAIN
    → if features built → 721-feature dict
  → StateBuilder.build_state(row, timestamp, sulfur_value, sulfur_ts, ...)
  → state.feature_vector = feature_vector
  → Orchestrator.run_decision_cycle(state)
    → DataQualityAgent.evaluate(state)
    → QualityAgent.predict(state, state.feature_vector)
    → ReliabilityAgent.evaluate(state)
    → OptimizationAgent.generate_candidates(state, controls)
    → OptimizationAgent.evaluate_scenarios(state, candidates, state.feature_vector, reliability)
    → SafetyAgent.filter_scenarios(evaluations, quality_pred, dq.score, state=state)
    → Recommendation / AbstainRecommendation
```

## Feature Buffer

- Stores last100 points (configurable)
- Minimum36 points required (6 hours of10-min data)
- Builds lag(1,2,3,6,12), rolling(6,12,36), delta, slope, missing, domain features
- Same formulas as training pipeline (reuses KEY_COLS, LAG_WINDOWS, ROLLING_WINDOWS)
- `feature_ready` property: `history_size >=36`
- Warmup: replay feeds points sequentially until ready

## Model Compatibility

- CatBoost expects721 features
- RuntimeFeatureBuffer builds721 features when history sufficient
- Schema match verified by `build_feature_vector(expected_features)`

## Safety — Real Checks

- model_available
- quality prediction not None
- sulfur UCB ≤10
- P(violation) ≤0.2
- reliability risk ≤0.8
- data quality ≥0.3
- control within model range (ControlRegistry)
- **control max_step** (new: passes current value from ProcessState)
- fail-closed on any exception

## Tests

```
passed: 24
failed: 0
skipped: 1 (Docker smoke)
```

## Known Limitations

1. **QualitySourceResolver not yet integrated into Orchestrator** — created but Orchestrator uses state.quality directly. Integration is straightforward but not done.
2. **Surrogate not loaded** — no real surrogate model, optimization always ABSTAINs.
3. **Full721-feature inference** — requires36 points warmup. Cold start → ABSTAIN.
4. **No Postgres/Redis/Prometheus/Grafana** — deferred.
5. **No microservices** — in-process only (intentional for this phase).
