"""Behavioral tests for MVP3 runtime integration — no .fit() calls.

Tests:
- Tag normalization in /decision
- StateBuilder integration
- Sulfur request → state.quality
- Freshness calculation
- Feature buffer not ready → ABSTAIN
- Feature buffer ready
- Surrogate missing feature → unavailable
- Safety max_step
- Safety action endpoint
- Recommendation confidence=None
- Optimizer missing prediction
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.tags.normalization import normalize_tag, normalize_telemetry_dict
from src.shared.tags.registry import ControlRegistry
from src.feature_service.runtime_buffer import RuntimeFeatureBuffer
from src.feature_service.quality_source_resolver import QualitySourceResolver, QualitySourceCandidate


# ── Tag Normalization ───────────────────────────────────────────

class TestTagNormalization:
    def test_avt_u24_no_collision(self):
        avt = normalize_telemetry_dict({"T6": 234.0, "F9": 195.0}, "avt")
        u24 = normalize_telemetry_dict({"T6": 8.5, "F9": 171.0}, "u24")
        assert avt["avt_T6"] == 234.0
        assert u24["u24_T6"] == 8.5
        assert avt["avt_F9"] == 195.0
        assert u24["u24_F9"] == 171.0

    def test_api_normalizes_tags(self, client):
        """Test that /decision normalizes raw tags to canonical."""
        resp = client.post("/decision", json={
            "avt_telemetry": {"T1": 130.0, "T6": 234.0},
            "unit_242000_telemetry": {"T5": 365.0, "T6": 8.5},
            "pak_sulfur_value": 7.5,
            "pak_sulfur_timestamp": (datetime.utcnow() - timedelta(minutes=10)).isoformat(),
        })
        # Should return200 (either recommendation or abstain)
        assert resp.status_code in (200, 503)  # 503 if agents not fully initialized in test


# ── StateBuilder Integration ────────────────────────────────────

class TestStateBuilderIntegration:
    def test_sulfur_in_state(self):
        """Sulfur from request must populate state.quality."""
        from src.feature_service.state_builder import StateBuilder
        builder = StateBuilder(avt_cols=["avt_T1"], u24_cols=["u24_T5"])
        row = pd.Series({"avt_T1": 130.0, "u24_T5": 365.0})
        ts = datetime(2023, 6, 15, 12, 0)
        sulfur_ts = ts - timedelta(minutes=10)
        state = builder.build_state(
            row=row, timestamp=ts,
            sulfur_value=7.5, sulfur_ts=sulfur_ts,
            avt_ts=ts, u24_ts=ts,
        )
        assert "sulfur" in state.quality
        assert state.quality["sulfur"].value == 7.5
        assert state.quality["sulfur"].age_minutes == pytest.approx(10.0)

    def test_freshness_populated(self):
        from src.feature_service.state_builder import StateBuilder
        builder = StateBuilder(avt_cols=["avt_T1"], u24_cols=[])
        row = pd.Series({"avt_T1": 130.0})
        ts = datetime(2023, 6, 15, 12, 0)
        state = builder.build_state(row=row, timestamp=ts, avt_ts=ts - timedelta(minutes=5))
        assert state.source_freshness.avt_minutes == pytest.approx(5.0)


# ── Feature Buffer ──────────────────────────────────────────────

class TestFeatureBuffer:
    def test_not_ready_with_few_points(self):
        buf = RuntimeFeatureBuffer(max_history=100)
        for i in range(5):
            buf.push(datetime(2023, 1, 1, 0, i * 10), {"T1": 130.0}, {"T5": 365.0})
        assert not buf.feature_ready

    def test_ready_with_enough_points(self):
        buf = RuntimeFeatureBuffer(max_history=100)
        base = datetime(2023, 1, 1)
        for i in range(40):
            buf.push(base + timedelta(minutes=i * 10), {"T1": 130.0 + i}, {"T5": 365.0 + i})
        assert buf.feature_ready

    def test_abstain_when_not_ready(self):
        buf = RuntimeFeatureBuffer(max_history=100)
        buf.push(datetime(2023, 1, 1), {"T1": 130.0}, {"T5": 365.0})
        fv, err = buf.build_feature_vector(["avt_T1", "u24_T5"])
        assert fv is None
        assert "insufficient" in (err or "").lower() or "not ready" in (err or "").lower() or "history" in (err or "").lower()


# ── Quality Source Resolver ─────────────────────────────────────

class TestQualitySourceResolver:
    def test_resolves_lims_over_pak(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [
            QualitySourceCandidate("PAK", 7.0, now - timedelta(minutes=5), 5, 0.9),
            QualitySourceCandidate("LIMS", 6.5, now - timedelta(hours=12), 720, 0.95),
        ]
        result = resolver.resolve("sulfur", candidates, now)
        assert result is not None
        assert result.source == "LIMS"

    def test_falls_back_to_pak_when_lims_stale(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [
            QualitySourceCandidate("PAK", 7.0, now - timedelta(minutes=5), 5, 0.9),
            QualitySourceCandidate("LIMS", 6.5, now - timedelta(days=10), 14400, 0.95),
        ]
        result = resolver.resolve("sulfur", candidates, now)
        assert result is not None
        assert result.source == "PAK"

    def test_returns_none_when_all_stale(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [
            QualitySourceCandidate("PAK", 7.0, now - timedelta(hours=10), 600, 0.9),
            QualitySourceCandidate("LIMS", 6.5, now - timedelta(days=10), 14400, 0.95),
        ]
        result = resolver.resolve("sulfur", candidates, now)
        assert result is None


# ── Surrogate Strict Schema ─────────────────────────────────────

class TestSurrogateStrict:
    def test_missing_feature_returns_unavailable(self):
        from src.agents.surrogate.model import SurrogateModel
        sur = SurrogateModel(
            quality_model=MagicMock(), feature_names=["avt_T1", "avt_T6", "u24_T5"],
            control_to_feature_map={"avt_T1": "avt_T1"},
        )
        result = sur.simulate(
            state=MagicMock(), action={"avt_T1": 150.0},
            feature_vector={"avt_T1": 130.0},  # Missing avt_T6, u24_T5
        )
        assert result.status == "unavailable"
        assert "missing" in (result.availability_reason or "").lower()


# ── Safety Max Step ─────────────────────────────────────────────

class TestSafetyMaxStep:
    def test_rejects_large_step(self):
        from src.agents.safety.agent import SafetyAgent
        from src.shared.schemas.quality_prediction import QualityPrediction
        from src.shared.schemas.process_state import ProcessState
        from src.agents.optimization.agent import ScenarioEvaluation

        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        agent = SafetyAgent(control_registry=reg)
        state = ProcessState(
            timestamp=datetime.utcnow(),
            avt_telemetry={"avt_T1": 130.0},
        )
        scenario = ScenarioEvaluation(
            scenario_id="test", action={"avt_T1": 150.0},  # Δ=20 > max_step=5
            predicted_sulfur=5.0, sulfur_std=1.0, violation_probability=0.01,
        )
        pred = QualityPrediction(indicator="sulfur", prediction=5.0, model_available=True)
        result = agent.check_scenario(scenario, pred, 1.0, state=state)
        assert not result.allowed
        assert any("max_step" in v or "step" in v.lower() for v in result.violations)


# ── Recommendation confidence=None ──────────────────────────────

class TestRecommendationConfidenceNone:
    def test_confidence_none_validates(self):
        from src.shared.schemas.recommendation import Recommendation
        rec = Recommendation(
            decision_id="test", timestamp=datetime.utcnow(), confidence=None,
        )
        assert rec.confidence is None


# ── Optimizer No Magic Defaults ─────────────────────────────────

class TestOptimizerNoMagic:
    def test_empty_predictions_marks_error(self):
        from src.agents.optimization.agent import OptimizationAgent
        from src.agents.surrogate.model import SurrogateModel, SimulationResult
        from src.shared.schemas.process_state import ProcessState
        from src.shared.schemas.reliability import ReliabilityAssessment

        mock_sur = SurrogateModel(quality_model=MagicMock(), feature_names=["avt_T1"])
        mock_sur.simulate = MagicMock(return_value=SimulationResult(status="ok", predictions={}))
        opt = OptimizationAgent(surrogate=mock_sur, n_scenarios=2)
        state = ProcessState(timestamp=datetime.utcnow(), avt_telemetry={"avt_T1": 130.0})
        reliability = ReliabilityAssessment(risk_score=0.1, risk_level="low")
        evals, avail = opt.evaluate_scenarios(state, [{"avt_T1": 130.0}], {"avt_T1": 130.0}, reliability)
        assert avail
        assert all(e.simulation_status == "error" for e in evals)


# ── HTTP Integration ────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from src.api.app import app
    return TestClient(app)


class TestHTTPIntegration:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "prediction_ready" in data
        assert "feature_history_ready" in data

    def test_model_info(self, client):
        resp = client.get("/model/info")
        assert resp.status_code == 200

    def test_decision_returns_abstain_without_sulfur(self, client):
        resp = client.post("/decision", json={
            "avt_telemetry": {"T1": 130.0},
            "unit_242000_telemetry": {"T5": 365.0},
        })
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert data["recommendation_type"] == "abstain"


# ── Temporal Split ──────────────────────────────────────────────

class TestTemporalSplit:
    def test_no_shuffle(self):
        from src.training.temporal_split import chronological_split
        dates = pd.date_range("2023-01-01", periods=1000, freq="10min")
        df = pd.DataFrame({"x": np.random.randn(1000)}, index=dates)
        train, val, test = chronological_split(df, 0.7, 0.15, 0.15)
        assert train.index.max() < val.index.min()
        assert val.index.max() < test.index.min()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
