"""FastAPI application — full runtime integration.

/decision flow:
  DecisionRequest → normalize tags → StateBuilder → QualitySourceResolver
  → RuntimeFeatureBuffer → ProcessState → Orchestrator → Recommendation/ABSTAIN
"""
from __future__ import annotations

import logging
import os
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


def _init_runtime():
    global _control_registry, _feature_buffer, _state_builder, _quality_resolver
    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.surrogate.model import SurrogateModel
    from src.shared.tags.registry import ControlRegistry
    from src.feature_service.runtime_buffer import RuntimeFeatureBuffer
    from src.feature_service.state_builder import StateBuilder
    from src.feature_service.quality_source_resolver import QualitySourceResolver

    model_dir = os.environ.get("MODEL_DIR", "models")
    config_dir = os.environ.get("CONFIG_DIR", "configs")

    _control_registry = ControlRegistry(os.path.join(config_dir, "controls.yaml"))
    _feature_buffer = RuntimeFeatureBuffer(max_history=100)
    _state_builder = StateBuilder(avt_cols=[], u24_cols=[])  # Columns set dynamically
    _quality_resolver = QualitySourceResolver(os.path.join(config_dir, "quality_source_policy.yaml"))

    quality_agent = QualityAgent(model_dir=model_dir)
    _agents["data_quality"] = DataQualityAgent()
    _agents["quality"] = quality_agent
    _agents["reliability"] = ReliabilityAgent()
    _agents["optimization"] = OptimizationAgent(
        surrogate=SurrogateModel(), n_scenarios=5, seed=42
    )
    _agents["safety"] = SafetyAgent(control_registry=_control_registry)
    _agents["surrogate"] = SurrogateModel()

    logger.info(
        f"Runtime initialized: quality_ready={quality_agent.is_ready}, "
        f"controls={len(_control_registry.get_control_candidates())}, "
        f"buffer_size={_feature_buffer.history_size}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_runtime()
    yield

app = FastAPI(
    title="NefteKod — Diesel Fuel Quality Control System",
    version="0.4.0",
    lifespan=lifespan,
)


# ── Request/Response Models ─────────────────────────────────────

class DecisionRequest(BaseModel):
    avt_telemetry: dict[str, float]
    unit_242000_telemetry: dict[str, float]
    timestamp: str | None = None
    avt_timestamp: str | None = None
    u24_timestamp: str | None = None
    pak_sulfur_value: float | None = None
    pak_sulfur_timestamp: str | None = None
    pak_density_value: float | None = None
    pak_density_timestamp: str | None = None
    lims_values: dict[str, float] | None = None
    lims_timestamp: str | None = None

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
    feature_history_ready: bool
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
    history_ready = _feature_buffer is not None and _feature_buffer.feature_ready
    prediction_ready = model_ready and history_ready
    return ReadyResponse(
        ready=prediction_ready,
        prediction_ready=prediction_ready,
        quality_model_ready=model_ready,
        feature_history_ready=history_ready,
        optimization_ready=sur is not None and sur.is_available,
        surrogate_ready=sur is not None and sur.is_available,
    )


# ── Model Info ──────────────────────────────────────────────────

@app.get("/model/info")
async def model_info():
    qa = _agents.get("quality")
    if qa is None:
        return {"model_available": False}
    info = qa.get_model_info()
    info["runtime_feature_count"] = _feature_buffer.history_size if _feature_buffer else 0
    info["history_ready"] = _feature_buffer.feature_ready if _feature_buffer else False
    return info


# ── Decision (full integration) ─────────────────────────────────

@app.post("/decision")
async def make_decision(request: DecisionRequest):
    import pandas as pd
    from src.shared.tags.normalization import normalize_telemetry_dict
    from src.shared.schemas.process_state import ProcessState
    from src.agents.orchestrator.agent import OrchestratorAgent

    dq = _agents.get("data_quality")
    qa = _agents.get("quality")
    ra = _agents.get("reliability")
    oa = _agents.get("optimization")
    sa = _agents.get("safety")
    if not all([dq, qa, ra, oa, sa]):
        raise HTTPException(status_code=503, detail="Not all agents initialized")

    # 1. Normalize tags
    avt = normalize_telemetry_dict(request.avt_telemetry, "avt")
    u24 = normalize_telemetry_dict(request.unit_242000_telemetry, "u24")

    # 2. Parse timestamps
    ts = _parse_ts(request.timestamp) or datetime.utcnow()
    avt_ts = _parse_ts(request.avt_timestamp)
    u24_ts = _parse_ts(request.u24_timestamp)
    sulfur_ts = _parse_ts(request.pak_sulfur_timestamp)
    density_ts = _parse_ts(request.pak_density_timestamp)
    lims_ts = _parse_ts(request.lims_timestamp)

    # 3. Push to feature buffer
    _feature_buffer.push(
        timestamp=ts, avt=avt, u24=u24,
        pak_sulfur=request.pak_sulfur_value,
        pak_density=request.pak_density_value,
        lims=request.lims_values,
    )

    # 4. Build feature vector (or ABSTAIN if not ready)
    expected_features = qa.model_metadata.feature_names if qa.model_metadata else None
    if expected_features:
        fv, err = _feature_buffer.build_feature_vector(expected_features)
        if fv is None:
            return _abstain_response(f"Feature buffer not ready: {err}")
    else:
        # No model metadata — use what we have
        fv = {**avt, **u24}

    # 5. Build ProcessState via StateBuilder
    state = _state_builder.build_state(
        row=pd.Series({**avt, **u24}),
        timestamp=ts,
        sulfur_value=request.pak_sulfur_value,
        sulfur_ts=sulfur_ts,
        density_value=request.pak_density_value,
        density_ts=density_ts,
        lims_values=request.lims_values,
        lims_ts=lims_ts,
        avt_ts=avt_ts or ts,
        u24_ts=u24_ts or ts,
    )
    state.feature_vector = fv

    # 6. Run orchestrator
    controls = _control_registry.get_optimization_bounds() if _control_registry else {}
    orchestrator = OrchestratorAgent(
        data_quality_agent=dq, quality_agent=qa, reliability_agent=ra,
        optimization_agent=oa, safety_agent=sa, controls=controls,
    )
    result = orchestrator.run_decision_cycle(state)
    return {
        "decision_id": result.decision_id,
        "recommendation_type": "recommendation" if hasattr(result, "recommended_changes") else "abstain",
        "data": result.model_dump(),
    }


def _abstain_response(reason: str) -> dict:
    return {
        "decision_id": "N/A",
        "recommendation_type": "abstain",
        "data": {"reason": reason},
    }


def _parse_ts(ts: str | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromisoformat(ts)
    except:
        return None


# ── Safety Check (with action validation) ───────────────────────

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

    # Build a ProcessState from current_state for max_step checking
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

@app.post("/quality/predict")
async def quality_predict(request: dict[str, Any]):
    from src.shared.schemas.process_state import ProcessState
    agent = _agents.get("quality")
    if agent is None:
        raise HTTPException(status_code=503, detail="Quality agent not initialized")
    state = ProcessState(timestamp=datetime.utcnow())
    result = agent.predict(state, request.get("feature_vector", {}))
    return result.model_dump()


@app.post("/reliability/evaluate")
async def reliability_evaluate(request: dict[str, Any]):
    from src.shared.schemas.process_state import ProcessState
    from src.shared.tags.normalization import normalize_telemetry_dict
    agent = _agents.get("reliability")
    if agent is None:
        raise HTTPException(status_code=503, detail="Reliability agent not initialized")
    avt = normalize_telemetry_dict(request.get("avt_telemetry", {}), "avt")
    u24 = normalize_telemetry_dict(request.get("unit_242000_telemetry", {}), "u24")
    state = ProcessState(timestamp=datetime.utcnow(), avt_telemetry=avt, unit_242000_telemetry=u24)
    return agent.evaluate(state).model_dump()


@app.get("/agents/status")
async def agents_status():
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    return {
        "quality": {"model_ready": qa.is_ready if qa else False},
        "surrogate": {"available": sur.is_available if sur else False},
        "feature_buffer": {"size": _feature_buffer.history_size, "ready": _feature_buffer.feature_ready},
        "control_registry": {"n_controls": len(_control_registry.get_control_candidates()) if _control_registry else 0},
    }


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
