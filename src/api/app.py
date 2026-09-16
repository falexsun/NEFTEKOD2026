"""FastAPI — MVP4 full runtime integration.

Fixes:
- StateBuilder.build_state_from_runtime() (no empty column lists)
- QualitySourceResolver integrated
- Single Surrogate instance
- RuntimeConfig applied to agents
- Pydantic datetime (422 on invalid)
- Proper early ABSTAIN with UUID
- Singleton Orchestrator
- Proper /ready and /model/info
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from src.api.runtime_store import RuntimeStore, utc_now
from src.api.security import Identity, admin_access, engineer_access, operator_access
from src.api.topology import load_topology, annotation
from src.api.flow_diagnostics import flow_diagnostics
from src.api.operating_policy import operating_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "neftekod_http_requests_total",
    "HTTP requests handled by the NefteKod API",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "neftekod_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)
DECISIONS = Counter(
    "neftekod_decisions_total",
    "Operator decisions produced by the orchestrator",
    ["type"],
)
RUNTIME_READY = Gauge("neftekod_runtime_ready", "1 when the full prediction runtime is ready")
MODEL_READY = Gauge("neftekod_quality_model_ready", "1 when the quality model is loaded")
FEATURE_BUFFER_POINTS = Gauge("neftekod_feature_buffer_points", "Points currently stored in the feature buffer")
SURROGATE_READY = Gauge("neftekod_surrogate_ready", "1 when scenario simulation is available")
DATA_QUALITY = Gauge("neftekod_data_quality_score", "Latest input data quality score from 0 to 1")
SOURCE_AGE = Gauge("neftekod_source_age_minutes", "Age of latest source data", ["source"])
SULFUR_PREDICTION = Gauge("neftekod_sulfur_prediction_mg_kg", "Latest sulfur prediction")
VIOLATION_PROBABILITY = Gauge("neftekod_violation_probability", "Latest sulfur limit violation probability")
DECISION_DURATION = Histogram("neftekod_decision_cycle_duration_seconds", "Full decision cycle duration")
SCENARIOS = Counter("neftekod_scenarios_total", "What-if scenarios evaluated", ["result"])

_agents = {}
_control_registry = None
_feature_buffer = None
_state_builder = None
_quality_resolver = None
_orchestrator = None
_runtime_config = None
_runtime_store = None
_storage_ready = False
_q21_system = None
_q21_error = None


def _as_utc(value: datetime | None = None) -> datetime:
    value = value or utc_now()
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _init_runtime():
    global _control_registry, _feature_buffer, _state_builder
    global _quality_resolver, _orchestrator, _runtime_config, _runtime_store, _storage_ready
    global _q21_system, _q21_error

    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.surrogate.model import SurrogateModel
    from src.agents.orchestrator.agent import OrchestratorAgent
    from src.shared.tags.registry import ControlRegistry
    from src.shared.config.runtime import RuntimeConfig
    from src.feature_service.runtime_buffer import RuntimeFeatureBuffer
    from src.feature_service.state_builder import StateBuilder
    from src.feature_service.quality_source_resolver import QualitySourceResolver

    config_dir = os.environ.get("CONFIG_DIR", "configs")
    model_dir = os.environ.get("MODEL_DIR", "models")

    # Load config
    _runtime_config = RuntimeConfig(os.path.join(config_dir, "runtime.yaml"))

    # Create components
    _control_registry = ControlRegistry(os.path.join(config_dir, "controls.yaml"))
    _feature_buffer = RuntimeFeatureBuffer(max_history=100, min_duration_minutes=360, min_points=36)
    _state_builder = StateBuilder()  # No column lists — uses build_state_from_runtime
    _quality_resolver = QualitySourceResolver(os.path.join(config_dir, "quality_source_policy.yaml"))

    # Create agents and apply config
    dq = DataQualityAgent()
    _runtime_config.apply_to_data_quality_agent(dq)

    qa = QualityAgent(model_dir=model_dir)
    ra = ReliabilityAgent()
    surrogate = SurrogateModel(
        quality_model=qa.model,
        feature_names=qa.model_metadata.feature_names if qa.model_metadata else None,
        control_to_feature_map=_control_registry.build_control_to_feature_map(),
    )
    oa = OptimizationAgent(surrogate=surrogate, n_scenarios=5, seed=42)

    sa = SafetyAgent(control_registry=_control_registry)
    _runtime_config.apply_to_safety_agent(sa)

    # Singleton orchestrator
    _orchestrator = OrchestratorAgent(
        data_quality_agent=dq, quality_agent=qa, reliability_agent=ra,
        optimization_agent=oa, safety_agent=sa,
        controls=_control_registry.get_optimization_bounds(),
    )

    _agents["data_quality"] = dq
    _agents["quality"] = qa
    _agents["reliability"] = ra
    _agents["optimization"] = oa
    _agents["safety"] = sa
    _agents["surrogate"] = surrogate

    database_url = os.environ.get("DATABASE_URL", "sqlite:///data/neftekod.db")
    try:
        _runtime_store = RuntimeStore(database_url)
        restored = _feature_buffer.restore(_runtime_store.recent_telemetry(limit=100))
        _storage_ready = True
        logger.info("Restored %s runtime points from persistent storage", restored)
    except Exception as exc:
        _runtime_store = None
        _storage_ready = False
        logger.error("Persistent runtime store unavailable: %s", exc)

    # Export meaningful values from the first Prometheus scrape, even before
    # an operator opens /ready in the UI.
    MODEL_READY.set(1 if qa.is_ready else 0)
    FEATURE_BUFFER_POINTS.set(_feature_buffer.history_size)
    RUNTIME_READY.set(0)
    SURROGATE_READY.set(1 if surrogate.is_available else 0)

    logger.info(
        f"Runtime initialized: quality_ready={qa.is_ready}, "
        f"surrogate_available={surrogate.is_available}, "
        f"controls={len(_control_registry.get_control_candidates())}"
    )

    # The research bundle is independent from the legacy quality model. Load it
    # only when both checksum-pinned artifacts are present; never fake readiness.
    from src.inference.advisory_system import Q21AdvisorySystem
    default_q21_dir = Path(model_dir)
    q21_dir = Path(os.environ.get("Q21_MODEL_DIR", default_q21_dir))
    try:
        _q21_system = Q21AdvisorySystem(q21_dir, lambda_penalty=int(os.environ.get("Q21_RISK_LAMBDA", "25")))
        _q21_error = None
        logger.info("Q21 production bundle loaded from %s (5 horizons + h=1 risk/interval)", q21_dir)
    except Exception as exc:
        _q21_system = None
        _q21_error = str(exc)
        logger.warning("Q21 h=1 bundle unavailable: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_runtime()
    yield

app = FastAPI(title="NefteKod", version="0.6.0", lifespan=lifespan)

# Vite uses a separate origin in development. In production the compiled
# console is mounted below and ships with this API as one Python application.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_http_metrics(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    HTTP_DURATION.labels(request.method, route_path).observe(time.perf_counter() - started)
    HTTP_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
    response.headers["X-Request-ID"] = request_id
    return response


# ── Request Models ──────────────────────────────────────────────

class DecisionRequest(BaseModel):
    avt_mode: Literal["normal", "startup", "shutdown", "transition", "unknown"] = "unknown"
    u24_mode: Literal["normal", "startup", "shutdown", "transition", "unknown"] = "unknown"
    avt_telemetry: dict[str, float]
    unit_242000_telemetry: dict[str, float]
    timestamp: datetime | None = None
    avt_timestamp: datetime | None = None
    u24_timestamp: datetime | None = None
    pak_sulfur_value: float | None = None
    pak_sulfur_timestamp: datetime | None = None
    pak_density_value: float | None = None
    pak_density_timestamp: datetime | None = None
    lims_values: dict[str, float] | None = None
    lims_timestamp: datetime | None = None

class SafetyCheckRequest(BaseModel):
    predicted_sulfur: float
    sulfur_std: float
    violation_probability: float
    data_quality_score: float
    reliability_risk: float = 0.0
    ood_score: float = 0.0
    confidence: float | None = None
    model_available: bool = True
    action: dict[str, float] = Field(default_factory=dict)
    current_state: dict[str, float] = Field(default_factory=dict)

class ReadyResponse(BaseModel):
    ready: bool
    prediction_ready: bool
    quality_model_ready: bool
    history_ready: bool
    runtime_schema_ready: bool
    optimization_ready: bool
    surrogate_ready: bool
    storage_ready: bool


class ScenarioRequest(BaseModel):
    action: dict[str, float] = Field(min_length=1)
    baseline_timestamp: datetime

    model_config = {"allow_inf_nan": False}


class Q21TelemetryPoint(BaseModel):
    timestamp: datetime
    q21: float
    values: dict[str, float]
    model_config = {"allow_inf_nan": False, "extra": "forbid"}


class Q21AdvisoryRequest(BaseModel):
    operating_mode: Literal["normal", "startup", "shutdown", "transition", "unknown"]
    points: list[Q21TelemetryPoint] = Field(min_length=145, max_length=1000)
    model_config = {"extra": "forbid"}


class Q21IngestRequest(Q21TelemetryPoint):
    operating_mode: Literal["normal", "startup", "shutdown", "transition", "unknown"]
    ingestion_mode: Literal["live", "replay"] = "live"


class VakRequest(BaseModel):
    values: dict[str, float]
    models: list[str] | None = None
    model_config = {"allow_inf_nan": False, "extra": "forbid"}


def _q21_result(recommendation) -> dict[str, Any]:
    return {
        "timestamp": recommendation.timestamp.isoformat(),
        "plant_state": recommendation.plant_state.value,
        "q21_current": recommendation.q21_current,
        "q21_forecast_1h": recommendation.q21_forecast_1h,
        "exceedance_probability": recommendation.exceedance_probability,
        "exceedance_risk": recommendation.exceedance_risk,
        "action": recommendation.action,
        "reason_code": recommendation.reason_code,
        "message": recommendation.message,
        "confidence": recommendation.confidence,
        "details": recommendation.details or {},
        "validation_failures": [vars(item) for item in (recommendation.validation_failures or [])],
        "forecasts": [{"horizon_hours": horizon, "q21": value, "primary": horizon == 1.0}
                      for horizon, value in sorted((recommendation.multi_horizon_forecasts or {}).items())],
        "q21_interval_80": ({"lower": recommendation.q21_interval_80[0],
                             "upper": recommendation.q21_interval_80[1], "horizon_hours": 1.0,
                             "empirical_coverage": 0.7769953051643192}
                            if recommendation.q21_interval_80 else None),
        "extended_warnings": recommendation.extended_warnings or [],
        "interpretation": "observational_forecast",
        "automatic_control": False,
    }


def _readiness() -> dict[str, bool]:
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    model_ready = bool(qa and qa.is_ready)
    history_ready = bool(_feature_buffer and _feature_buffer.history_ready)
    schema_ready = False
    if model_ready and history_ready and qa.model_metadata:
        vector, error = _feature_buffer.build_feature_vector(qa.model_metadata.feature_names)
        schema_ready = vector is not None and error is None
    prediction_ready = model_ready and schema_ready
    optimization_ready = bool(sur and sur.is_available and prediction_ready)
    return {
        "ready": prediction_ready and _storage_ready,
        "prediction_ready": prediction_ready,
        "quality_model_ready": model_ready,
        "history_ready": history_ready,
        "runtime_schema_ready": schema_ready,
        "optimization_ready": optimization_ready,
        "surrogate_ready": bool(sur and sur.is_available),
        "storage_ready": _storage_ready,
    }


def _age_minutes(timestamp: str | datetime | None, now: datetime) -> float | None:
    if not timestamp:
        return None
    parsed = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
    return max(0.0, (now - _as_utc(parsed)).total_seconds() / 60)


def _freshness_state(age: float | None, warning: float, critical: float) -> str:
    if age is None:
        return "unknown"
    if age > critical:
        return "critical"
    if age > warning:
        return "stale"
    return "normal"


def _latest_persisted_point() -> dict[str, Any] | None:
    if _runtime_store:
        rows = _runtime_store.recent_telemetry(limit=1)
        if rows:
            return rows[0]
    return _feature_buffer.latest if _feature_buffer else None


def _build_latest_state():
    from src.shared.schemas.process_state import ProcessState

    latest = _feature_buffer.latest if _feature_buffer else None
    if not latest:
        return None
    timestamp = _as_utc(latest["timestamp"])
    return ProcessState(
        timestamp=timestamp,
        avt_telemetry={key: value for key, value in latest.items() if key.startswith("avt_")},
        unit_242000_telemetry={key: value for key, value in latest.items() if key.startswith("u24_")},
    )


# ── Health / Readiness ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": utc_now().isoformat()}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint for API and decision-runtime telemetry."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    state = _readiness()
    RUNTIME_READY.set(1 if state["ready"] else 0)
    MODEL_READY.set(1 if state["quality_model_ready"] else 0)
    SURROGATE_READY.set(1 if state["surrogate_ready"] else 0)
    FEATURE_BUFFER_POINTS.set(_feature_buffer.history_size if _feature_buffer else 0)
    return ReadyResponse(**state)


@app.get("/model/info")
async def model_info():
    qa = _agents.get("quality")
    if qa is None:
        return {"model_available": False}
    info = qa.get_model_info()
    info["history_size"] = _feature_buffer.history_size if _feature_buffer else 0
    info["history_duration_minutes"] = _feature_buffer.history_duration_minutes if _feature_buffer else 0
    info["history_ready"] = _feature_buffer.history_ready if _feature_buffer else False
    info["model_feature_count"] = len(qa.model_metadata.feature_names) if qa.model_metadata else 0
    return info


# ── Decision ────────────────────────────────────────────────────

@app.post("/decision")
async def make_decision(
    payload: DecisionRequest,
    http_request: Request,
    identity: Identity = Depends(engineer_access),
):
    from src.shared.tags.normalization import normalize_telemetry_dict
    from src.feature_service.quality_source_resolver import QualitySourceCandidate

    if _runtime_store:
        existing = _runtime_store.decision_by_request_id(http_request.state.request_id)
        if existing:
            return {
                "decision_id": existing["decision_id"],
                "recommendation_type": existing["recommendation_type"],
                "data": existing["data"],
                "idempotent_replay": True,
            }

    # 1. Normalize tags
    avt = normalize_telemetry_dict(payload.avt_telemetry, "avt")
    u24 = normalize_telemetry_dict(payload.unit_242000_telemetry, "u24")
    ts = _as_utc(payload.timestamp)

    # 2. Push to feature buffer
    accepted = _feature_buffer.push(
        timestamp=ts, avt=avt, u24=u24,
        pak_sulfur=payload.pak_sulfur_value,
        pak_density=payload.pak_density_value,
        lims=payload.lims_values,
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="Повторная или устаревшая точка телеметрии")
    if _runtime_store:
        _runtime_store.append_telemetry(ts, {
            "operating_modes": {"avt": payload.avt_mode, "u24": payload.u24_mode},
            **avt,
            **u24,
            "sulfur_mg_kg": payload.pak_sulfur_value,
            "density_15": payload.pak_density_value,
            **{f"lims_{key}": value for key, value in (payload.lims_values or {}).items()},
            "source_timestamps": {
                "avt": _as_utc(payload.avt_timestamp or ts).isoformat(),
                "u24": _as_utc(payload.u24_timestamp or ts).isoformat(),
                "pak": _as_utc(payload.pak_sulfur_timestamp).isoformat() if payload.pak_sulfur_timestamp else None,
                "lims": _as_utc(payload.lims_timestamp).isoformat() if payload.lims_timestamp else None,
            },
        })

    policy = operating_policy({
        "operating_modes": {"avt": payload.avt_mode, "u24": payload.u24_mode},
        "source_timestamps": {"avt": _as_utc(payload.avt_timestamp or ts), "u24": _as_utc(payload.u24_timestamp or ts)},
    }, ts)
    if not policy["allowed"]:
        did = str(uuid.uuid4())
        kind = policy["disposition"].lower()
        data = {"decision_id": did, "timestamp": ts.isoformat(), "reason": "; ".join(policy["reasons"]),
                "operating_policy": policy, "_audit": {"input": payload.model_dump(mode="json")}}
        if _runtime_store:
            _runtime_store.save_decision(did, ts, kind, data, http_request.state.request_id, identity.name)
        DECISIONS.labels(kind).inc()
        return {"decision_id": did, "recommendation_type": kind, "data": data}

    # 3. Build feature vector (or early ABSTAIN)
    qa = _agents["quality"]
    expected = qa.model_metadata.feature_names if qa.model_metadata else None
    if expected:
        fv, err = _feature_buffer.build_feature_vector(expected)
        if fv is None:
            did = str(uuid.uuid4())
            DECISIONS.labels("abstain").inc()
            response_payload = {
                "decision_id": did,
                "recommendation_type": "abstain",
                "data": {
                    "decision_id": did,
                    "timestamp": ts.isoformat(),
                    "reason": f"Feature buffer not ready: {err}",
                    "_audit": {"input": payload.model_dump(mode="json"), "request_id": http_request.state.request_id},
                },
            }
            if _runtime_store:
                _runtime_store.save_decision(did, ts, "abstain", response_payload["data"], http_request.state.request_id, identity.name)
            return response_payload
    else:
        fv = {**avt, **u24}

    # 4. Resolve quality sources
    quality_signals = {}
    if payload.pak_sulfur_value is not None and payload.pak_sulfur_timestamp:
        pak_ts = _as_utc(payload.pak_sulfur_timestamp)
        age = (ts - pak_ts).total_seconds() / 60
        candidates = [QualitySourceCandidate("PAK", payload.pak_sulfur_value, pak_ts, age, 0.9)]
        if payload.lims_values and payload.lims_timestamp:
            lims_ts = _as_utc(payload.lims_timestamp)
            lims_age = (ts - lims_ts).total_seconds() / 60
            for ind, val in payload.lims_values.items():
                if ind in ("sulfur_md", "sulfur_avg"):
                    candidates.append(QualitySourceCandidate("LIMS", val, lims_ts, lims_age, 0.95))
        resolved = _quality_resolver.resolve("sulfur", candidates, ts)
        if resolved:
            from src.shared.schemas.process_state import QualitySignal
            quality_signals["sulfur"] = QualitySignal(
                value=resolved.value, source=resolved.source,
                measurement_timestamp=pak_ts,
                age_minutes=resolved.age_minutes, confidence=resolved.confidence,
            )

    # 5. Build ProcessState via runtime method
    state = _state_builder.build_state_from_runtime(
        timestamp=ts, avt_telemetry=avt, unit_242000_telemetry=u24,
        quality=quality_signals,
        avt_ts=_as_utc(payload.avt_timestamp or ts),
        u24_ts=_as_utc(payload.u24_timestamp or ts),
        lims_ts=_as_utc(payload.lims_timestamp) if payload.lims_timestamp else None,
    )
    state.feature_vector = fv

    # 6. Run orchestrator (singleton)
    with DECISION_DURATION.time():
        result = _orchestrator.run_decision_cycle(state)
    result_type = "recommendation" if hasattr(result, "recommended_changes") else "abstain"
    DECISIONS.labels(result_type).inc()
    FEATURE_BUFFER_POINTS.set(_feature_buffer.history_size)
    dumped = result.model_dump(mode="json")
    dumped["_audit"] = {
        "input": payload.model_dump(mode="json"),
        "request_id": http_request.state.request_id,
        "model": qa.get_model_info(),
    }
    response_payload = {
        "decision_id": result.decision_id,
        "recommendation_type": result_type,
        "data": dumped,
    }
    if result_type == "recommendation":
        DATA_QUALITY.set(float(result.current_state.get("data_quality_score") or 0))
        sulfur = result.expected_quality.get("sulfur")
        if sulfur is not None:
            SULFUR_PREDICTION.set(sulfur)
    if _runtime_store:
        _runtime_store.save_decision(result.decision_id, ts, result_type, dumped, http_request.state.request_id, identity.name)
    return response_payload


# ── Safety ──────────────────────────────────────────────────────

@app.post("/safety/check")
async def safety_check(request: SafetyCheckRequest, _: Identity = Depends(engineer_access)):
    from src.shared.schemas.quality_prediction import QualityPrediction
    from src.shared.schemas.process_state import ProcessState
    from src.agents.optimization.agent import ScenarioEvaluation

    agent = _agents.get("safety")
    if agent is None:
        raise HTTPException(status_code=503, detail="Safety agent not initialized")

    quality_pred = QualityPrediction(
        indicator="sulfur", prediction=request.predicted_sulfur,
        violation_probability=request.violation_probability,
        confidence=request.confidence, model_available=request.model_available,
    )
    state = ProcessState(
        timestamp=utc_now(),
        avt_telemetry={k: v for k, v in request.current_state.items() if k.startswith("avt_")},
        unit_242000_telemetry={k: v for k, v in request.current_state.items() if k.startswith("u24_")},
    )
    scenario = ScenarioEvaluation(
        scenario_id="api_check", action=request.action,
        predicted_sulfur=request.predicted_sulfur, sulfur_std=request.sulfur_std,
        violation_probability=request.violation_probability,
        reliability_risk=request.reliability_risk, ood_score=request.ood_score,
    )
    result = agent.check_scenario(scenario, quality_pred, request.data_quality_score, state)
    return result.model_dump()


# ── Other Endpoints ─────────────────────────────────────────────

@app.post("/reliability/evaluate")
async def reliability_evaluate(request: dict[str, Any], _: Identity = Depends(engineer_access)):
    from src.shared.schemas.process_state import ProcessState
    from src.shared.tags.normalization import normalize_telemetry_dict
    avt = normalize_telemetry_dict(request.get("avt_telemetry", {}), "avt")
    u24 = normalize_telemetry_dict(request.get("unit_242000_telemetry", {}), "u24")
    state = ProcessState(timestamp=utc_now(), avt_telemetry=avt, unit_242000_telemetry=u24)
    return _agents["reliability"].evaluate(state).model_dump()


@app.get("/agents/status")
async def agents_status(_: Identity = Depends(engineer_access)):
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    return {
        "quality": {"model_ready": qa.is_ready if qa else False},
        "surrogate": {"available": sur.is_available if sur else False},
        "feature_buffer": {"size": _feature_buffer.history_size, "ready": _feature_buffer.history_ready},
        "control_registry": {"n_controls": len(_control_registry.get_control_candidates()) if _control_registry else 0},
        "single_surrogate": sur is _agents.get("optimization").surrogate if sur and _agents.get("optimization") else False,
    }


# ── Operator Console API ────────────────────────────────────────

@app.get("/operator/me")
async def operator_me(identity: Identity = Depends(operator_access)):
    return {"name": identity.name, "role": identity.role}


@app.get("/controls")
async def controls_catalog(_: Identity = Depends(operator_access)):
    topology = load_topology(os.environ.get("CONFIG_DIR", "configs"))
    latest = _feature_buffer.latest if _feature_buffer else None
    values = latest or {}
    controls = []
    for name, spec in _control_registry.get_control_candidates().items():
        low, high = spec.model_range or (None, None)
        controls.append({
            "id": name,
            "label": spec.semantic_name,
            "stage": spec.stage,
            "unit": spec.unit,
            "min": low,
            "max": high,
            "max_step": spec.max_step,
            "max_rate_of_change": spec.max_rate_of_change,
            "source": spec.source,
            "confidence": spec.confidence,
            "current": values.get(name),
            "snapshot_timestamp": values.get("timestamp"),
            "available": name in values,
            "topology": annotation(topology, name),
        })
    return {"controls": controls, "count": len(controls), "timestamp": utc_now().isoformat()}


@app.get("/q21/status")
async def q21_status(_: Identity = Depends(operator_access)):
    """Truthful inventory: only physically present, checksum-verified artifacts are ready."""
    if not _q21_system:
        return {"ready": False, "error": _q21_error, "available_horizons_hours": [],
                "risk_ready": False, "uncertainty_ready": False,
                "missing_artifacts": ["h=0.5", "h=1 quantiles", "h=2", "h=3", "h=6"]}
    bundle = _q21_system.model_bundle
    return {
        "ready": True,
        "available_horizons_hours": sorted(bundle.multi_models),
        "risk_ready": True,
        "uncertainty_ready": set(bundle.quantile_models) == {0.1, 0.9},
        "risk_lambda": _q21_system.lambda_penalty,
        "risk_threshold": _q21_system.risk_threshold,
        "models": {
            "forecast_h1": bundle.regression_meta.model_sha256,
            "risk_h1": bundle.risk_meta.model_sha256,
            **{f"forecast_h{horizon:g}_residual": bundle.EXPECTED_CHECKSUMS[f"multi_{horizon}"]
               for horizon in sorted(bundle.multi_models)},
            "interval_h1_q10": bundle.EXPECTED_CHECKSUMS["quantile_0.1"],
            "interval_h1_q90": bundle.EXPECTED_CHECKSUMS["quantile_0.9"],
        },
        "missing_artifacts": [],
        "mode": "shadow_advisory",
    }


@app.post("/q21/advisory")
async def q21_advisory(
    payload: Q21AdvisoryRequest,
    http_request: Request,
    identity: Identity = Depends(operator_access),
):
    """Checksum-pinned h=1 advisory; no control action is transmitted."""
    if not _q21_system:
        raise HTTPException(status_code=503, detail=f"Q21 model bundle unavailable: {_q21_error}")
    import pandas as pd
    from src.inference.state_detector import PlantState

    frame = pd.DataFrame([{"timestamp": p.timestamp, "Q21": p.q21, **p.values} for p in payload.points])
    recommendation = _q21_system.generate_advisory(
        frame,
        current_q21=payload.points[-1].q21,
        declared_state=PlantState(payload.operating_mode),
    )
    result = _q21_result(recommendation)
    if _runtime_store:
        decision_id = str(uuid.uuid4())
        _runtime_store.save_decision(decision_id, utc_now(), "q21_advisory", result,
                                     http_request.state.request_id, identity.name)
        result["decision_id"] = decision_id
    return result


@app.post("/q21/telemetry")
async def q21_telemetry(
    payload: Q21IngestRequest,
    http_request: Request,
    identity: Identity = Depends(engineer_access),
):
    """Persist one 10-minute point and automatically run shadow inference when warm."""
    if not _q21_system:
        raise HTTPException(status_code=503, detail=f"Q21 model bundle unavailable: {_q21_error}")
    if not _runtime_store:
        raise HTTPException(status_code=503, detail="Persistent storage unavailable")
    timestamp = _as_utc(payload.timestamp)
    if not _runtime_store.append_q21_point(timestamp, payload.operating_mode, payload.q21, payload.values):
        raise HTTPException(status_code=409, detail="Q21 point with this timestamp already exists")
    resolved = 0
    if 0 <= payload.q21 <= 50 and abs(payload.q21 - 307.0) >= 0.1:
        resolved = _runtime_store.resolve_q21_outcomes(timestamp, payload.q21)
    history = _runtime_store.recent_q21_points(limit=145)
    if len(history) < 145:
        return {"accepted": True, "state": "warmup", "points": len(history), "required_points": 145,
                "resolved_outcomes": resolved, "automatic_control": False}

    import pandas as pd
    from src.inference.state_detector import PlantState
    recommendation = _q21_system.generate_advisory(
        pd.DataFrame(history), current_q21=payload.q21, declared_state=PlantState(payload.operating_mode),
        reference_time=pd.Timestamp(timestamp) if payload.ingestion_mode == "replay" else None)
    result = _q21_result(recommendation)
    result.update({"accepted": True, "state": "evaluated", "points": len(history),
                   "resolved_outcomes": resolved, "ingestion_mode": payload.ingestion_mode})
    forecast_id = str(uuid.uuid4())
    if result["forecasts"]:
        bundle = _q21_system.model_bundle
        checksums = {h: (bundle.regression_meta.model_sha256 if h == 1.0
                         else bundle.EXPECTED_CHECKSUMS[f"multi_{h}"])
                     for h in bundle.multi_models}
        _runtime_store.save_q21_forecasts(forecast_id, timestamp, result["forecasts"],
                                          result["q21_interval_80"], checksums)
    _runtime_store.save_decision(forecast_id, timestamp, "q21_shadow", result,
                                 http_request.state.request_id, identity.name)
    result["decision_id"] = forecast_id
    return result


@app.get("/q21/runtime")
async def q21_runtime(_: Identity = Depends(operator_access)):
    if not _runtime_store:
        raise HTTPException(status_code=503, detail="Persistent storage unavailable")
    points = _runtime_store.recent_q21_points(limit=145)
    latest_timestamp = _as_utc(points[-1]["timestamp"]) if points else None
    data_state = ("empty" if latest_timestamp is None else
                  "live" if (utc_now() - latest_timestamp).total_seconds() <= 1800 else "historical")
    return {
        "points": len(points), "required_points": 145,
        "data_state": data_state,
        "latest_point": points[-1] if points else None,
        "latest_forecast": _runtime_store.latest_q21_forecast(),
        "shadow_metrics": _runtime_store.q21_shadow_metrics(),
    }


@app.post("/vak/evaluate")
async def vak_evaluate(payload: VakRequest, _: Identity = Depends(operator_access)):
    from src.inference.vak import VakInputError, evaluate_vak
    try:
        results = evaluate_vak(payload.values, payload.models)
    except VakInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "results": results,
        "source": "organizer_formuly_vak_2026-09-16",
        "interpretation": "deterministic_virtual_analyzer",
        "count": len(results),
    }


@app.get("/operator/snapshot")
async def operator_snapshot(_: Identity = Depends(operator_access)):
    now = utc_now()
    readiness = _readiness()
    latest = _latest_persisted_point()
    last_decision = _runtime_store.latest_decision() if _runtime_store else None
    recent = _runtime_store.recent_telemetry(limit=24) if _runtime_store else []
    flow_history = _runtime_store.telemetry_since(now - timedelta(days=30), now) if _runtime_store else []
    if latest and (not flow_history or flow_history[-1] != latest):
        flow_history.append(latest)
    timestamps = (latest or {}).get("source_timestamps") or {}
    source_specs = [
        ("lims", "ЛИМС", timestamps.get("lims"), 360, 720),
        ("pak", "ПАК", timestamps.get("pak"), 10, 30),
        ("avt", "Телеметрия АВТ", timestamps.get("avt"), 5, 15),
        ("u24", "Телеметрия 24—2000", timestamps.get("u24"), 5, 15),
    ]
    sources = []
    for source_id, label, timestamp, warning, critical in source_specs:
        age = _age_minutes(timestamp, now)
        if age is not None:
            SOURCE_AGE.labels(source_id).set(age)
        sources.append({
            "id": source_id,
            "label": label,
            "timestamp": timestamp,
            "age_minutes": age,
            "state": _freshness_state(age, warning, critical),
        })
    sulfur_value = None
    sulfur_source = None
    if latest:
        for key, source in (("sulfur_mg_kg", "ПАК"), ("lims_sulfur_avg", "ЛИМС"), ("lims_sulfur_md", "ЛИМС"), ("u24_W7", "ПАК"), ("u24_T6", "ПАК")):
            if latest.get(key) is not None:
                sulfur_value, sulfur_source = latest[key], source
                break
    trend = []
    for point in recent:
        value = next((point.get(key) for key in ("sulfur_mg_kg", "lims_sulfur_avg", "lims_sulfur_md", "u24_W7", "u24_T6") if point.get(key) is not None), None)
        if value is not None:
            trend.append({"timestamp": _as_utc(point["timestamp"]).isoformat(), "value": value})

    return {
        "timestamp": now.isoformat(),
        "mode": "live" if latest else "no_data",
        "readiness": readiness,
        "quality": {"value": sulfur_value, "unit": "mg/kg", "source": sulfur_source, "trend": trend},
        "sources": sources,
        "flow_diagnostics": flow_diagnostics(flow_history, now),
        "operating_policy": operating_policy(latest, now),
        "latest_decision": last_decision,
        "buffer": {
            "points": _feature_buffer.history_size if _feature_buffer else 0,
            "duration_minutes": _feature_buffer.history_duration_minutes if _feature_buffer else 0,
            "required_points": _feature_buffer.min_points if _feature_buffer else 36,
            "required_minutes": _feature_buffer.min_duration_minutes if _feature_buffer else 360,
        },
    }


@app.get("/decisions")
async def decisions_list(
    limit: int = Query(default=50, ge=1, le=200),
    _: Identity = Depends(operator_access),
):
    if not _runtime_store:
        raise HTTPException(status_code=503, detail="Журнал решений недоступен")
    rows = _runtime_store.decisions(limit)
    return {"decisions": rows, "count": len(rows)}


@app.post("/scenarios/evaluate")
async def evaluate_scenario(
    payload: ScenarioRequest,
    http_request: Request,
    identity: Identity = Depends(operator_access),
):
    from scipy.stats import norm
    from src.agents.optimization.agent import ScenarioEvaluation
    from src.shared.schemas.quality_prediction import QualityPrediction

    if _runtime_store:
        existing = _runtime_store.decision_by_request_id(http_request.state.request_id)
        if existing:
            return {**existing["data"], "idempotent_replay": True}

    state = _build_latest_state()
    latest = _feature_buffer.latest if _feature_buffer else None
    if not latest or _as_utc(payload.baseline_timestamp) != _as_utc(latest["timestamp"]):
        raise HTTPException(status_code=409, detail="Технологический срез изменился. Обновите параметры и повторите расчёт.")
    policy = operating_policy(_latest_persisted_point(), utc_now())
    if not policy["allowed"]:
        raise HTTPException(status_code=409, detail=f"{policy['disposition']}: " + "; ".join(policy["reasons"]))
    readiness = _readiness()
    if state is None:
        SCENARIOS.labels("unavailable_no_data").inc()
        raise HTTPException(status_code=409, detail="Нет актуального технологического среза")
    if not readiness["optimization_ready"]:
        SCENARIOS.labels("unavailable_runtime").inc()
        raise HTTPException(status_code=503, detail="Модель сценариев не готова; расчёт заблокирован")

    unknown = [name for name in payload.action if not _control_registry.is_control(name)]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Неизвестные параметры: {', '.join(unknown)}")

    qa = _agents["quality"]
    vector, error = _feature_buffer.build_feature_vector(qa.model_metadata.feature_names)
    if vector is None:
        raise HTTPException(status_code=503, detail=f"Вектор признаков недоступен: {error}")
    state.feature_vector = vector
    dq = _agents["data_quality"].evaluate(state)
    reliability = _agents["reliability"].evaluate(state)
    horizon = qa.model_metadata.prediction_horizon_minutes
    simulation = _agents["surrogate"].simulate(state, payload.action, horizon_minutes=horizon, feature_vector=vector)
    if simulation.status != "ok":
        SCENARIOS.labels(f"unavailable_{simulation.status}").inc()
        raise HTTPException(status_code=503, detail=simulation.availability_reason or "Расчёт недоступен")

    prediction = simulation.predictions["sulfur"]
    std = simulation.predictions["sulfur_std"]
    violation_probability = float(1 - norm.cdf(_agents["safety"].sulfur_limit, loc=prediction, scale=std))
    evaluation = ScenarioEvaluation(
        scenario_id=str(uuid.uuid4()),
        action=payload.action,
        predicted_sulfur=prediction,
        sulfur_std=std,
        violation_probability=violation_probability,
        reliability_risk=reliability.risk_score,
        uncertainty=std,
    )
    quality_prediction = QualityPrediction(
        indicator="sulfur",
        prediction=prediction,
        violation_probability=violation_probability,
        model_available=True,
    )
    safety = _agents["safety"].check_scenario(evaluation, quality_prediction, dq.score, state)
    result = {
        "scenario_id": evaluation.scenario_id,
        "timestamp": utc_now().isoformat(),
        "status": "safe" if safety.allowed else "rejected",
        "action": payload.action,
        "baseline_timestamp": payload.baseline_timestamp.isoformat(),
        "predicted_sulfur": prediction,
        "sulfur_std": std,
        "violation_probability": violation_probability,
        "reliability_risk": reliability.risk_score,
        "data_quality_score": dq.score,
        "constraints": safety.model_dump(mode="json"),
        "production_effect": None,
        "energy_effect": None,
        "model_version": qa.model_metadata.model_version,
        "horizon_minutes": horizon,
        "operating_policy": policy,
        "interpretation": "observational_what_if",
    }
    SCENARIOS.labels(result["status"]).inc()
    SULFUR_PREDICTION.set(prediction)
    VIOLATION_PROBABILITY.set(violation_probability)
    DATA_QUALITY.set(dq.score)
    if _runtime_store:
        _runtime_store.save_decision(
            evaluation.scenario_id,
            utc_now(),
            "scenario",
            result,
            http_request.state.request_id,
            identity.name,
        )
    return result


@app.post("/runtime/reset")
async def runtime_reset(_: Identity = Depends(admin_access)):
    """Reset runtime state (demo/test only)."""
    _feature_buffer.reset()
    _agents["data_quality"].reset_history()
    _agents["reliability"].reset_history()
    return {"status": "reset", "timestamp": utc_now().isoformat()}


@app.get("/models")
async def list_models(_: Identity = Depends(engineer_access)):
    models_dir = os.environ.get("MODEL_DIR", "models")
    models = []
    if os.path.exists(models_dir):
        for f in os.listdir(models_dir):
            if f.endswith(".pkl"):
                path = os.path.join(models_dir, f)
                models.append({"name": f, "size_bytes": os.path.getsize(path)})
    return {"models": models}


# Keep this mount last so API routes win over the SPA fallback.
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="operator-console")
