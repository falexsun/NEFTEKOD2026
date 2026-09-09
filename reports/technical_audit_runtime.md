# Technical Audit — Runtime Phase

**Date**: 2026-09-09
**Scope**: Architecture, runtime correctness, safety, inference wiring

---

## 1. Implemented

- Shared Pydantic schemas (ProcessState, QualityPrediction, ReliabilityAssessment, SafetyDecision, Recommendation, AbstainRecommendation)
- Data loaders (AVT, 24-2000, PAK, LIMS)
- Feature engineering pipeline (721 features)
- Temporal train/val/test split (no shuffle)
- Walk-forward validation
- All 6 agents: DataQuality, Quality, Reliability, Optimization, Safety, Orchestrator
- Basic FastAPI gateway with /health, /quality/predict, /reliability/evaluate, /safety/check, /decision
- Streamlit dashboard (6 pages)
- Docker Compose (gateway, dashboard, postgres, redis, minio, mlflow, trainer)
- Historical replay script
- Unit tests (17) + Integration tests (5)

## 2. Partially Implemented

- SourceFreshness — schema exists but **never populated** by StateBuilder (line84: `freshness = SourceFreshness()` with defaults)
- Redis Streams — replay script publishes to Redis but no consumer services exist
- Postgres — defined in Docker Compose but **no schema, no tables, no writes**
- MLflow — Docker service exists but **no model registry integration**
- MinIO — Docker service exists but **no storage integration**
- Trainer service — references `src.training.trainer_service` which **does not exist**

## 3. Placeholders / Not Implemented

- `src/shared/clients/` — does not exist (no HTTP clients for inter-service communication)
- `src/shared/config/` — does not exist (no centralized configuration)
- `src/shared/errors/` — does not exist (no error handling framework)
- `src/shared/logging/` — does not exist (no structured JSON logging)
- `src/shared/events/` — does not exist (no event schemas)
- Feature Service as separate microservice — only exists as Python module
- Individual agent microservices — all agents run in-process
- Prometheus `/metrics` — not implemented
- Grafana dashboards — not implemented
- `/ready` endpoints — not implemented
- Quality source resolver (LIMS/PAK/VAK priority policy) — not implemented
- Control registry — controls come from telemetry ±20%
- Semantic tag registry — tags are identified by first letter of name

## 4. Missing (Required by Spec)

| Component | Status |
|-----------|--------|
| feature-service microservice | Missing |
| quality-agent microservice | Missing |
| reliability-agent microservice | Missing |
| optimization-agent microservice | Missing |
| safety-agent microservice | Missing |
| orchestrator microservice | Missing |
| Prometheus | Missing |
| Grafana | Missing |
| Postgres schema/migrations | Missing |
| Redis Streams consumers | Missing |
| Structured JSON logging | Missing |
| `/ready` endpoints | Missing |
| `/metrics` endpoints | Missing |
| QualitySourceResolver | Missing |
| ControlRegistry | Missing |
| SemanticTagRegistry | Missing |
| ModelArtifactMetadata | Missing |

## 5. Potential Runtime Errors

### CRITICAL: Sorted feature ordering (quality/agent.py:56, surrogate/model.py:53)
```python
feature_names = sorted(feature_vector.keys())
```
Models were trained with DataFrame column order (71 AVT + 26 U24 + derived features). Using `sorted()` produces alphabetical order which is DIFFERENT. **Predictions will be silently wrong**.

### CRITICAL: Magic fallbacks produce fake predictions
- `quality/agent.py:103-112`: Returns `prediction=7.0` when model unavailable — this is a fabricated prediction, not an ABSTAIN
- `quality/agent.py:88-101`: Returns PAK reading as "prediction" with invented bounds and confidence
- `surrogate/model.py:64-71`: Returns current state as "simulation result" when model unavailable
- `optimization/agent.py:108-109`: `predictions.get("sulfur", 7.0)` and `predictions.get("sulfur_std", 1.5)` use magic defaults

### HIGH: Non-deterministic optimizer (optimization/agent.py:71)
```python
n_perturb = np.random.randint(1, max(2, len(controls)))
```
No seed set — results are not reproducible.

### HIGH: Tag-name-based proxy (optimization/agent.py:116-119)
```python
production = sum(v for k, v in action.items() if "F" in k)
energy = sum(v for k, v in action.items() if "T" in k)
```
Determines production/energy by checking if tag name contains "F" or "T". This is unreliable — e.g., `T6` (temperature) contains "T" but so does `P23` which does NOT.

### MEDIUM: API creates new agents per request (api/app.py:62, 150-160)
Each `/quality/predict` call creates a new `QualityAgent` → re-loads model from disk. Each `/decision` creates a full orchestrator with all agents.

## 6. Potential Safety Problems

### CRITICAL: Safety Agent does not check for unavailable predictions
Safety Agent receives `quality_pred: QualityPrediction` but never checks if `quality_pred.model_type == "fallback"` or `confidence == 0.1`. A fallback prediction passes all safety checks.

### CRITICAL: Orchestrator does not verify quality prediction succeeded
`orchestrator/agent.py:74`: Calls `quality_agent.predict()` but doesn't check if the result is a fallback or real prediction. Proceeds to optimization regardless.

### HIGH: Safety Agent catches no exceptions
If any check raises an unexpected exception, the scenario is allowed (no explicit fail-closed).

### HIGH: Frozen sensor detection is broken
`reliability/agent.py:58`: `val == 0.0 or (isinstance(val, float) and val == int(val))` — this flags ANY integer-lik值 value as frozen. Temperature 234.0°? Flagged. Flow 100.0? Flagged. This is wrong.

### MEDIUM: Safety Agent rate-of-change check is placeholder
`safety/agent.py:83`: `if abs(value) > 1e5` — only checks for extremely large values, not actual rate-of-change limits.

## 7. Problems: Microservices Architecture

- **Monolithic module structure**: All agents run in the same process. No actual microservice separation.
- **Docker Compose**: Only `gateway` and `dashboard` are application services. The6 required agent services do not exist.
- **No inter-service communication**: No HTTP clients, no service discovery, no timeouts.
- **Trainer references non-existent module**: `src.training.trainer_service` does not exist.

## 8. Problems: Docker

- Single `Dockerfile` shared by all services — no service-specific build
- Trainer service will fail to start (missing module)
- No health checks on most services
- No `/ready` distinction from `/health`
- Missing: feature-service, quality-agent, reliability-agent, optimization-agent, safety-agent, orchestrator, prometheus, grafana

## 9. Problems: Redis

- Replay script writes to `telemetry.received` stream but no consumer reads it
- No consumer groups, no ACK, no idempotency
- No event schema validation
- Redis is in Docker Compose but only used as a pass-through

## 10. Problems: API

- No `/ready` endpoint
- No `/metrics` endpoint
- No Pydantic error models for4xx/5xx
- No request validation beyond Pydantic basics
- No correlation_id or decision_id in API responses (only in orchestrator)
- `/safety/check` accepts untyped `dict[str, Any]` instead of Pydantic model
- Creates new agents per request (performance + state loss)

## 11. Problems: Inference Wiring

- **No ModelArtifactMetadata**: No record of which features the model expects, in what order
- **No feature schema validation**: Feature vector is passed as dict, sorted alphabetically, sent to model — silently wrong if model expects different order
- **No schema mismatch detection**: If model receives wrong number of features, it may error or produce garbage silently

## 12. Problems: Observability

- No structured JSON logging (uses basic `logging.info`)
- No `decision_id` / `correlation_id` propagation in logs
- No Prometheus metrics
- No Grafana dashboards
- No request duration tracking
- No error rate tracking

---

## Summary of Critical Issues (Must Fix)

| # | Issue | File | Severity |
|---|-------|------|----------|
| 1 | Sorted feature ordering → wrong predictions | quality/agent.py:56 | CRITICAL |
| 2 | Magic fallback → fake predictions | quality/agent.py:88-112 | CRITICAL |
| 3 | Magic fallback → fake simulation | surrogate/model.py:49-72 | CRITICAL |
| 4 | Safety accepts fallback predictions | safety/agent.py | CRITICAL |
| 5 | No prediction validation in orchestrator | orchestrator/agent.py:74 | CRITICAL |
| 6 | Tag-name-based proxy | optimization/agent.py:116-119 | HIGH |
| 7 | Non-deterministic optimizer | optimization/agent.py:71 | HIGH |
| 8 | Broken frozen sensor detection | reliability/agent.py:58 | HIGH |
| 9 | SourceFreshness never populated | state_builder.py:84 | HIGH |
| 10 | All agents run in-process (no microservices) | docker-compose.yml | HIGH |
