"""FastAPI application — HTTP API for all agents.

Uses singleton agent instances (created at startup, not per request).
Each agent has /health and /ready distinction.
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

# ── Singleton agents (created once at startup) ──────────────────
_agents = {}


def _init_agents():
    """Initialize singleton agent instances."""
    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.surrogate.model import SurrogateModel

    model_dir = os.environ.get("MODEL_DIR", "models")

    quality_agent = QualityAgent(model_dir=model_dir)
    reliability_agent = ReliabilityAgent()
    dq_agent = DataQualityAgent()
    surrogate = SurrogateModel()  # No model loaded — will report unavailable
    optimization_agent = OptimizationAgent(surrogate=surrogate, n_scenarios=5, seed=42)
    safety_agent = SafetyAgent()

    _agents["data_quality"] = dq_agent
    _agents["quality"] = quality_agent
    _agents["reliability"] = reliability_agent
    _agents["optimization"] = optimization_agent
    _agents["safety"] = safety_agent
    _agents["surrogate"] = surrogate

    logger.info(
        f"Agents initialized: quality_available={quality_agent.is_available}, "
        f"surrogate_available={surrogate.is_available}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_agents()
    yield


app = FastAPI(
    title="NefteKod — Diesel Fuel Quality Control System",
    description="Multi-agent system for diesel fuel quality prediction and optimization",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Request/Response models ─────────────────────────────────────

class PredictRequest(BaseModel):
    feature_vector: dict[str, float]
    timestamp: str | None = None

class PredictResponse(BaseModel):
    indicator: str
    prediction: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    violation_probability: float | None = None
    confidence: float
    model_version: str
    model_available: bool
    unavailability_reason: str | None = None

class DecisionRequest(BaseModel):
    avt_telemetry: dict[str, float]
    unit_242000_telemetry: dict[str, float]
    timestamp: str | None = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    service: str = "gateway"

class ReadyResponse(BaseModel):
    ready: bool
    services: dict[str, bool]
    timestamp: str


# ── Health / Readiness ──────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", timestamp=datetime.utcnow().isoformat())


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    """Readiness check: are all agents loaded and ready?"""
    services = {
        "data_quality": "data_quality" in _agents,
        "quality": _agents.get("quality", None) is not None and _agents["quality"].is_available,
        "reliability": "reliability" in _agents,
        "optimization": "optimization" in _agents,
        "safety": "safety" in _agents,
    }
    all_ready = all(services.values())
    return ReadyResponse(ready=all_ready, services=services, timestamp=datetime.utcnow().isoformat())


# ── Endpoints ───────────────────────────────────────────────────

@app.post("/quality/predict", response_model=PredictResponse)
async def quality_predict(request: PredictRequest):
    """Predict quality indicators using the quality agent."""
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


@app.post("/reliability/evaluate")
async def reliability_evaluate(request: DecisionRequest):
    """Evaluate reliability risk."""
    from src.shared.schemas.process_state import ProcessState

    agent = _agents.get("reliability")
    if agent is None:
        raise HTTPException(status_code=503, detail="Reliability agent not initialized")

    state = ProcessState(
        timestamp=datetime.utcnow(),
        avt_telemetry=request.avt_telemetry,
        unit_242000_telemetry=request.unit_242000_telemetry,
    )
    result = agent.evaluate(state)
    return result.model_dump()


@app.post("/safety/check")
async def safety_check(
    predicted_sulfur: float = 7.0,
    sulfur_std: float = 1.5,
    violation_probability: float = 0.1,
    confidence: float = 0.5,
    data_quality: float = 1.0,
    model_available: bool = True,
):
    """Run safety checks on a prediction."""
    from src.shared.schemas.quality_prediction import QualityPrediction
    from src.agents.safety.agent import SafetyAgent

    agent = _agents.get("safety")
    if agent is None:
        raise HTTPException(status_code=503, detail="Safety agent not initialized")

    quality_pred = QualityPrediction(
        indicator="sulfur",
        prediction=predicted_sulfur,
        lower_bound=predicted_sulfur - 1.96 * sulfur_std,
        upper_bound=predicted_sulfur + 1.96 * sulfur_std,
        violation_probability=violation_probability,
        confidence=confidence,
        model_available=model_available,
    )
    result = agent.check_quality_prediction(quality_pred)
    return result.model_dump()


@app.post("/decision")
async def make_decision(request: DecisionRequest):
    """Run full decision pipeline."""
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

    # Build controls from config, not from telemetry ±20%
    # For now, use a minimal set — will be replaced by ControlRegistry
    controls = _build_controls_from_config()

    orchestrator = OrchestratorAgent(
        data_quality_agent=dq,
        quality_agent=qa,
        reliability_agent=ra,
        optimization_agent=oa,
        safety_agent=sa,
        controls=controls,
    )

    result = orchestrator.run_decision_cycle(state)

    return {
        "decision_id": result.decision_id,
        "recommendation_type": "recommendation" if hasattr(result, "recommended_changes") else "abstain",
        "data": result.model_dump(),
    }


def _build_controls_from_config() -> dict[str, tuple[float, float]]:
    """Build controls from configs/controls.yaml (not from telemetry)."""
    import yaml
    config_path = os.path.join(os.environ.get("CONFIG_DIR", "configs"), "controls.yaml")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        controls = {}
        for name, spec in config.get("variables", {}).items():
            if "control_candidate" in spec.get("role", []):
                pr = spec.get("plausible_range")
                if pr and len(pr) == 2:
                    controls[name] = (pr[0], pr[1])
        return controls
    return {}


@app.get("/models")
async def list_models():
    """List available models."""
    models_dir = os.environ.get("MODEL_DIR", "models")
    models = []
    if os.path.exists(models_dir):
        for f in os.listdir(models_dir):
            if f.endswith(".pkl"):
                path = os.path.join(models_dir, f)
                models.append({
                    "name": f,
                    "size_bytes": os.path.getsize(path),
                    "modified": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                })
    return {"models": models}


@app.get("/agents/status")
async def agents_status():
    """Get status of all agents."""
    return {
        "data_quality": {"initialized": "data_quality" in _agents},
        "quality": {
            "initialized": "quality" in _agents,
            "model_available": _agents.get("quality", None) is not None and _agents["quality"].is_available,
            "model_type": getattr(_agents.get("quality"), "model_type", None),
        },
        "reliability": {"initialized": "reliability" in _agents},
        "optimization": {"initialized": "optimization" in _agents},
        "safety": {"initialized": "safety" in _agents},
        "surrogate": {
            "initialized": "surrogate" in _agents,
            "available": _agents.get("surrogate", None) is not None and _agents["surrogate"].is_available,
        },
    }
