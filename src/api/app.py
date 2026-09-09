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
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_agents = {}
_control_registry = None
_feature_buffer = None
_state_builder = None
_quality_resolver = None
_orchestrator = None
_runtime_config = None


def _init_runtime():
    global _control_registry, _feature_buffer, _state_builder
    global _quality_resolver, _orchestrator, _runtime_config

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
    surrogate = SurrogateModel()  # Single instance
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

    logger.info(
        f"Runtime initialized: quality_ready={qa.is_ready}, "
        f"surrogate_available={surrogate.is_available}, "
        f"controls={len(_control_registry.get_control_candidates())}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_runtime()
    yield

app = FastAPI(title="NefteKod", version="0.5.0", lifespan=lifespan)


# ── Request Models ──────────────────────────────────────────────

class DecisionRequest(BaseModel):
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


# ── Health / Readiness ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    model_ready = qa is not None and qa.is_ready
    history_ready = _feature_buffer is not None and _feature_buffer.history_ready
    schema_ready = model_ready and history_ready  # TODO: verify actual feature count match
    prediction_ready = model_ready and schema_ready
    return ReadyResponse(
        ready=prediction_ready,
        prediction_ready=prediction_ready,
        quality_model_ready=model_ready,
        history_ready=history_ready,
        runtime_schema_ready=schema_ready,
        optimization_ready=sur is not None and sur.is_available,
        surrogate_ready=sur is not None and sur.is_available,
    )


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
async def make_decision(request: DecisionRequest):
    from src.shared.tags.normalization import normalize_telemetry_dict
    from src.feature_service.quality_source_resolver import QualitySourceCandidate

    # 1. Normalize tags
    avt = normalize_telemetry_dict(request.avt_telemetry, "avt")
    u24 = normalize_telemetry_dict(request.unit_242000_telemetry, "u24")
    ts = request.timestamp or datetime.utcnow()

    # 2. Push to feature buffer
    _feature_buffer.push(
        timestamp=ts, avt=avt, u24=u24,
        pak_sulfur=request.pak_sulfur_value,
        pak_density=request.pak_density_value,
        lims=request.lims_values,
    )

    # 3. Build feature vector (or early ABSTAIN)
    qa = _agents["quality"]
    expected = qa.model_metadata.feature_names if qa.model_metadata else None
    if expected:
        fv, err = _feature_buffer.build_feature_vector(expected)
        if fv is None:
            did = str(uuid.uuid4())
            return {
                "decision_id": did,
                "recommendation_type": "abstain",
                "data": {"decision_id": did, "timestamp": ts.isoformat(), "reason": f"Feature buffer not ready: {err}"},
            }
    else:
        fv = {**avt, **u24}

    # 4. Resolve quality sources
    quality_signals = {}
    if request.pak_sulfur_value is not None and request.pak_sulfur_timestamp:
        age = (ts - request.pak_sulfur_timestamp).total_seconds() / 60
        candidates = [QualitySourceCandidate("PAK", request.pak_sulfur_value, request.pak_sulfur_timestamp, age, 0.9)]
        if request.lims_values and request.lims_timestamp:
            lims_age = (ts - request.lims_timestamp).total_seconds() / 60
            for ind, val in request.lims_values.items():
                if ind in ("sulfur_md", "sulfur_avg"):
                    candidates.append(QualitySourceCandidate("LIMS", val, request.lims_timestamp, lims_age, 0.95))
        resolved = _quality_resolver.resolve("sulfur", candidates, ts)
        if resolved:
            from src.shared.schemas.process_state import QualitySignal
            quality_signals["sulfur"] = QualitySignal(
                value=resolved.value, source=resolved.source,
                measurement_timestamp=request.pak_sulfur_timestamp,
                age_minutes=resolved.age_minutes, confidence=resolved.confidence,
            )

    # 5. Build ProcessState via runtime method
    state = _state_builder.build_state_from_runtime(
        timestamp=ts, avt_telemetry=avt, unit_242000_telemetry=u24,
        quality=quality_signals,
        avt_ts=request.avt_timestamp or ts,
        u24_ts=request.u24_timestamp or ts,
        lims_ts=request.lims_timestamp,
    )
    state.feature_vector = fv

    # 6. Run orchestrator (singleton)
    result = _orchestrator.run_decision_cycle(state)
    return {
        "decision_id": result.decision_id,
        "recommendation_type": "recommendation" if hasattr(result, "recommended_changes") else "abstain",
        "data": result.model_dump(),
    }


# ── Safety ──────────────────────────────────────────────────────

@app.post("/safety/check")
async def safety_check(request: SafetyCheckRequest):
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
        timestamp=datetime.utcnow(),
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
async def reliability_evaluate(request: dict[str, Any]):
    from src.shared.schemas.process_state import ProcessState
    from src.shared.tags.normalization import normalize_telemetry_dict
    avt = normalize_telemetry_dict(request.get("avt_telemetry", {}), "avt")
    u24 = normalize_telemetry_dict(request.get("unit_242000_telemetry", {}), "u24")
    state = ProcessState(timestamp=datetime.utcnow(), avt_telemetry=avt, unit_242000_telemetry=u24)
    return _agents["reliability"].evaluate(state).model_dump()


@app.get("/agents/status")
async def agents_status():
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    return {
        "quality": {"model_ready": qa.is_ready if qa else False},
        "surrogate": {"available": sur.is_available if sur else False},
        "feature_buffer": {"size": _feature_buffer.history_size, "ready": _feature_buffer.history_ready},
        "control_registry": {"n_controls": len(_control_registry.get_control_candidates()) if _control_registry else 0},
        "single_surrogate": sur is _agents.get("optimization").surrogate if sur and _agents.get("optimization") else False,
    }


@app.post("/runtime/reset")
async def runtime_reset():
    """Reset runtime state (demo/test only)."""
    _feature_buffer._history.clear()
    _feature_buffer._df = None
    _agents["data_quality"].reset_history()
    _agents["reliability"].reset_history()
    return {"status": "reset", "timestamp": datetime.utcnow().isoformat()}


@app.get("/models")
async def list_models():
    models_dir = os.environ.get("MODEL_DIR", "models")
    models = []
    if os.path.exists(models_dir):
        for f in os.listdir(models_dir):
            if f.endswith(".pkl"):
                path = os.path.join(models_dir, f)
                models.append({"name": f, "size_bytes": os.path.getsize(path)})
    return {"models": models}
