"""Integration tests — full pipeline from ProcessState to Recommendation."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def full_orchestrator():
    """Create a fully wired orchestrator with all agents."""
    from src.agents.data_quality.agent import DataQualityAgent
    from src.agents.quality.agent import QualityAgent
    from src.agents.reliability.agent import ReliabilityAgent
    from src.agents.optimization.agent import OptimizationAgent
    from src.agents.safety.agent import SafetyAgent
    from src.agents.orchestrator.agent import OrchestratorAgent
    from src.agents.surrogate.model import SurrogateModel

    controls = {
        "T1": (100, 200),
        "T6": (200, 260),
        "T5": (340, 380),
    }

    return OrchestratorAgent(
        data_quality_agent=DataQualityAgent(min_avt_signals=2, min_u24_signals=2),
        quality_agent=QualityAgent(model_dir="models"),
        reliability_agent=ReliabilityAgent(),
        optimization_agent=OptimizationAgent(
            surrogate=SurrogateModel(),
            n_scenarios=5,
        ),
        safety_agent=SafetyAgent(),
        controls=controls,
    )


@pytest.fixture
def sample_state():
    """Create a realistic process state."""
    from src.shared.schemas.process_state import ProcessState, QualitySignal

    return ProcessState(
        timestamp=datetime(2023, 6, 15, 12, 0),
        avt_telemetry={
            "T1": 130.5, "T6": 234.2, "T33": 68.5, "T55": 380.1,
            "F3": 68.7, "F5": 103.9, "F7": 217.5, "F8": 211.7, "F9": 195.9,
            "T20": 56.1, "T40": 139.3,
        },
        unit_242000_telemetry={
            "T5": 365.1, "T6": 8.5, "W7": 7.2, "P8": 358.0,
            "F9": 171.1, "F15": 5.8, "T11": 363.6, "T16": 175.1,
            "F22": 7143.9, "P24": 0.595,
        },
        quality={
            "sulfur": QualitySignal(
                value=7.5,
                source="PAK",
                measurement_timestamp=datetime(2023, 6, 15, 11, 50),
                age_minutes=10,
                confidence=0.9,
            )
        },
    )


class TestFullPipeline:
    """Test the complete decision pipeline."""

    def test_health_endpoint(self):
        """Basic smoke test for the API health endpoint."""
        # This just verifies the module imports work
        from src.api.app import app
        assert app is not None

    def test_orchestrator_runs(self, full_orchestrator, sample_state):
        """Test that orchestrator produces a result (recommendation or abstain)."""
        result = full_orchestrator.run_decision_cycle(sample_state)

        # Should produce either Recommendation or AbstainRecommendation
        from src.shared.schemas.recommendation import Recommendation, AbstainRecommendation
        assert isinstance(result, (Recommendation, AbstainRecommendation))
        assert result.decision_id is not None
        assert result.timestamp is not None

    def test_decision_has_id(self, full_orchestrator, sample_state):
        """Every decision should have a unique decision_id."""
        result = full_orchestrator.run_decision_cycle(sample_state)
        assert len(result.decision_id) > 0

    def test_abstain_on_empty_state(self, full_orchestrator):
        """Should abstain when no data is available."""
        from src.shared.schemas.process_state import ProcessState

        empty_state = ProcessState(timestamp=datetime(2023, 6, 15, 12, 0))
        result = full_orchestrator.run_decision_cycle(empty_state)

        from src.shared.schemas.recommendation import AbstainRecommendation
        assert isinstance(result, AbstainRecommendation)

    def test_recommendation_schema(self, full_orchestrator, sample_state):
        """Verify recommendation has all required fields."""
        result = full_orchestrator.run_decision_cycle(sample_state)

        from src.shared.schemas.recommendation import Recommendation
        if isinstance(result, Recommendation):
            assert hasattr(result, "decision_id")
            assert hasattr(result, "timestamp")
            assert hasattr(result, "current_state")
            assert hasattr(result, "explanation")
            assert hasattr(result, "model_versions")
            assert isinstance(result.explanation, str)
            assert len(result.explanation) > 0


class TestDockerSmoke:
    """Tests that would run against Docker deployment."""

    @pytest.mark.skip(reason="Requires running Docker services")
    def test_health_endpoint_live(self):
        """Test health endpoint against running service."""
        import httpx
        resp = httpx.get("http://localhost:8000/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
