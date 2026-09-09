"""FastAPI application — HTTP API for all agents."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NefteKod — Diesel Fuel Quality Control System",
    description="Multi-agent system for diesel fuel quality prediction and optimization",
    version="0.1.0",
)

# ── Health ──────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Request/Response models ─────────────────────────────────────

class PredictRequest(BaseModel):
    feature_vector: dict[str, float]
    timestamp: str | None = None

class PredictResponse(BaseModel):
    indicator: str
    prediction: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    violation_probability: float | None = None
    confidence: float
    model_version: str

class DecisionRequest(BaseModel):
    avt_telemetry: dict[str, float]
    unit_242000_telemetry: dict[str, float]
    timestamp: str | None = None

class DecisionResponse(BaseModel):
    decision_id: str
    recommendation_type: str  # recommendation | abstain
    data: dict[str, Any]


# ── Endpoints ───────────────────────────────────────────────────

@app.post("/quality/predict", response_model=PredictResponse)
async def quality_predict(request: PredictRequest):
    """Predict quality indicators using the quality agent."""
    from src.agents.quality.agent import QualityAgent
    from src.shared.schemas.process_state import ProcessState

    try:
        agent = QualityAgent(model_dir="models")
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
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reliability/evaluate")
async def reliability_evaluate(request: DecisionRequest):
    """Evaluate reliability risk."""
    from src.agents.reliability.agent import ReliabilityAgent
    from src.shared.schemas.process_state import ProcessState

    try:
        agent = ReliabilityAgent()
        state = ProcessState(
            timestamp=datetime.utcnow(),
            avt_telemetry=request.avt_telemetry,
            unit_242000_telemetry=request.unit_242000_telemetry,
        )
        result = agent.evaluate(state)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/safety/check")
async def safety_check(request: dict[str, Any]):
    """Run safety checks on a scenario."""
    from src.agents.safety.agent import SafetyAgent

    try:
        agent = SafetyAgent()
        # Simplified safety check
        from src.shared.schemas.quality_prediction import QualityPrediction
        from src.agents.optimization.agent import ScenarioEvaluation

        scenario = ScenarioEvaluation(
            scenario_id="api_check",
            action=request.get("action", {}),
            predicted_sulfur=request.get("predicted_sulfur", 7.0),
            sulfur_std=request.get("sulfur_std", 1.5),
            violation_probability=request.get("violation_probability", 0.1),
        )
        quality_pred = QualityPrediction(
            indicator="sulfur",
            prediction=request.get("predicted_sulfur", 7.0),
            confidence=request.get("confidence", 0.5),
        )
        result = agent.check_scenario(scenario, quality_pred, request.get("data_quality", 1.0))
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/decision")
async def make_decision(request: DecisionRequest):
    """Run full decision pipeline."""
    from src.shared.schemas.process_state import ProcessState
    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.orchestrator.agent import OrchestratorAgent
    from src.agents.surrogate.model import SurrogateModel

    try:
        state = ProcessState(
            timestamp=datetime.utcnow(),
            avt_telemetry=request.avt_telemetry,
            unit_242000_telemetry=request.unit_242000_telemetry,
        )

        # Build simple controls from telemetry
        controls = {}
        for name, val in {**request.avt_telemetry, **request.unit_242000_telemetry}.items():
            controls[name] = (val * 0.8, val * 1.2)

        orchestrator = OrchestratorAgent(
            data_quality_agent=DataQualityAgent(),
            quality_agent=QualityAgent(model_dir="models"),
            reliability_agent=ReliabilityAgent(),
            optimization_agent=OptimizationAgent(
                surrogate=SurrogateModel(),
                n_scenarios=5,
            ),
            safety_agent=SafetyAgent(),
            controls=controls,
        )

        result = orchestrator.run_decision_cycle(state)

        return {
            "decision_id": result.decision_id,
            "recommendation_type": "recommendation" if hasattr(result, "recommended_changes") else "abstain",
            "data": result.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models")
async def list_models():
    """List available models."""
    import os
    models_dir = "models"
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
