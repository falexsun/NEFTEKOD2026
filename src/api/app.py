"""FastAPI application — HTTP API for all agents.

Uses singleton agents (created at startup).
/model/info for model metadata.
/ready checks is_ready (model + schema), not just is_available.
/safety/check uses typed Pydantic request (no magic defaults).
/decision uses ControlRegistry for controls.
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


def _init_agents():
    global _control_registry
    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.surrogate.model import SurrogateModel
    from src.shared.tags.registry import ControlRegistry

    model_dir = os.environ.get("MODEL_DIR", "models")
    config_dir = os.environ.get("CONFIG_DIR", "configs")

    _control_registry = ControlRegistry(os.path.join(config_dir, "controls.yaml"))

    quality_agent = QualityAgent(model_dir=model_dir)
    reliability_agent = ReliabilityAgent()
    dq_agent = DataQualityAgent()
    surrogate = SurrogateModel()
    optimization_agent = OptimizationAgent(surrogate=surrogate, n_scenarios=5, seed=42)
    safety_agent = SafetyAgent(control_registry=_control_registry)

    _agents["data_quality"] = dq_agent
    _agents["quality"] = quality_agent
    _agents["reliability"] = reliability_agent
    _agents["optimization"] = optimization_agent
    _agents["safety"] = safety_agent
    _agents["surrogate"] = surrogate

    logger.info(
        f"Agents initialized: quality_ready={quality_agent.is_ready}, "
        f"surrogate_available={surrogate.is_available}, "
        f"controls={len(_control_registry.get_control_candidates())}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_agents()
    yield

app = FastAPI(
    title="NefteKod — Diesel Fuel Quality Control System",
    version="0.3.0",
    lifespan=lifespan,
)


# ── Request/Response Models ─────────────────────────────────────

class PredictRequest(BaseModel):
    feature_vector: dict[str, float]

class PredictResponse(BaseModel):
    indicator: str
    prediction: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    violation_probability: float | None = None
    confidence: float | None = None
    model_version: str
    model_available: bool
    unavailability_reason: str | None = None

class DecisionRequest(BaseModel):
    avt_telemetry: dict[str, float]
    unit_242000_telemetry: dict[str, float]
    timestamp: str | None = None
    sulfur_value: float | None = None
    sulfur_ts: str | None = None

class SafetyCheckRequest(BaseModel):
    """Typed safety check request — no magic defaults."""
    predicted_sulfur: float
    sulfur_std: float
    violation_probability: float
    confidence: float | None = None
    data_quality_score: float
    model_available: bool = True
    action: dict[str, float] = Field(default_factory=dict)

class ReadyResponse(BaseModel):
    ready: bool
    prediction_ready: bool
    optimization_ready: bool
    services: dict[str, bool]


# ── Health / Readiness ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")

    prediction_ready = qa is not None and qa.is_ready
    optimization_ready = sur is not None and sur.is_available

    services = {
        "data_quality": "data_quality" in _agents,
        "quality_ready": prediction_ready,
        "reliability": "reliability" in _agents,
        "optimization": "optimization" in _agents,
        "safety": "safety" in _agents,
        "surrogate_available": optimization_ready,
    }

    return ReadyResponse(
        ready=prediction_ready,  # Gateway is ready if prediction works
        prediction_ready=prediction_ready,
        optimization_ready=optimization_ready,
        services=services,
    )


# ── Model Info ──────────────────────────────────────────────────

@app.get("/model/info")
async def model_info():
    qa = _agents.get("quality")
    if qa is None:
        return {"model_available": False, "model_ready": False}
    return qa.get_model_info()


# ── Quality Prediction ──────────────────────────────────────────

@app.post("/quality/predict", response_model=PredictResponse)
async def quality_predict(request: PredictRequest):
    from src.shared.schemas.process_state import ProcessState

    agent = _agents.get("quality")
    if agent is None:
        raise HTTPException(status_code=503, detail="Quality agent not initialized")

    state = ProcessState(timestamp=datetime.utcnow())
    result = agent.predict(state, request.feature_vector)

    return PredictResponse(
        indicator=result.indicator,
        prediction=result.prediction,
        lower_bound=result.lower_bound,
        upper_bound=result.upper_bound,
        violation_probability=result.violation_probability,
        confidence=result.confidence,
        model_version=result.model_version,
        model_available=result.model_available,
        unavailability_reason=result.unavailability_reason,
    )


# ── Reliability ─────────────────────────────────────────────────

@app.post("/reliability/evaluate")
async def reliability_evaluate(request: DecisionRequest):
    from src.shared.schemas.process_state import ProcessState
    agent = _agents.get("reliability")
    if agent is None:
        raise HTTPException(status_code=503, detail="Reliability agent not initialized")

    state = ProcessState(
        timestamp=datetime.utcnow(),
        avt_telemetry=request.avt_telemetry,
        unit_242000_telemetry=request.unit_242000_telemetry,
    )
    return agent.evaluate(state).model_dump()


# ── Safety Check ────────────────────────────────────────────────

@app.post("/safety/check")
async def safety_check(request: SafetyCheckRequest):
    """Safety check with typed request — NO magic defaults."""
    from src.shared.schemas.quality_prediction import QualityPrediction
    from src.agents.optimization.agent import ScenarioEvaluation

    agent = _agents.get("safety")
    if agent is None:
        raise HTTPException(status_code=503, detail="Safety agent not initialized")

    quality_pred = QualityPrediction(
        indicator="sulfur",
        prediction=request.predicted_sulfur,
        lower_bound=request.predicted_sulfur - 1.96 * request.sulfur_std,
        upper_bound=request.predicted_sulfur + 1.96 * request.sulfur_std,
        violation_probability=request.violation_probability,
        confidence=request.confidence,
        model_available=request.model_available,
    )
    result = agent.check_quality_prediction(quality_pred)
    return result.model_dump()


# ── Decision ────────────────────────────────────────────────────

@app.post("/decision")
async def make_decision(request: DecisionRequest):
    from src.shared.schemas.process_state import ProcessState
    from src.agents.orchestrator.agent import OrchestratorAgent

    dq = _agents.get("data_quality")
    qa = _agents.get("quality")
    ra = _agents.get("reliability")
    oa = _agents.get("optimization")
    sa = _agents.get("safety")

    if not all([dq, qa, ra, oa, sa]):
        raise HTTPException(status_code=503, detail="Not all agents initialized")

    state = ProcessState(
        timestamp=datetime.utcnow(),
        avt_telemetry=request.avt_telemetry,
        unit_242000_telemetry=request.unit_242000_telemetry,
    )

    # Build feature vector — for now, use raw telemetry as canonical keys
    # Full runtime feature pipeline requires history buffer (Phase 3)
    state.feature_vector = {**request.avt_telemetry, **request.unit_242000_telemetry}

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


# ── Agents Status ───────────────────────────────────────────────

@app.get("/agents/status")
async def agents_status():
    qa = _agents.get("quality")
    sur = _agents.get("surrogate")
    return {
        "data_quality": {"initialized": "data_quality" in _agents},
        "quality": {
            "initialized": qa is not None,
            "model_available": qa.is_available if qa else False,
            "model_ready": qa.is_ready if qa else False,
        },
        "reliability": {"initialized": "reliability" in _agents},
        "optimization": {"initialized": "optimization" in _agents},
        "safety": {"initialized": "safety" in _agents},
        "surrogate": {
            "initialized": sur is not None,
            "available": sur.is_available if sur else False,
        },
        "control_registry": {
            "loaded": _control_registry is not None,
            "n_controls": len(_control_registry.get_control_candidates()) if _control_registry else 0,
        },
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
