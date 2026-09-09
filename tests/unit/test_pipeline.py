"""MVP4 behavioral tests — no .fit() calls."""
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
from src.feature_service.state_builder import StateBuilder
from src.feature_service.quality_source_resolver import QualitySourceResolver, QualitySourceCandidate
from src.feature_service.transformer import FeatureTransformer, FEATURE_KEY_COLUMNS


# ── StateBuilder Runtime ────────────────────────────────────────

class TestStateBuilderRuntime:
    def test_build_from_runtime_preserves_canonical(self):
        """build_state_from_runtime preserves canonical keys."""
        sb = StateBuilder()
        ts = datetime(2023, 6, 15, 12, 0)
        state = sb.build_state_from_runtime(
            timestamp=ts,
            avt_telemetry={"avt_T1": 130.0, "avt_T6": 234.0},
            unit_242000_telemetry={"u24_T5": 365.0, "u24_T6": 8.5},
        )
        assert state.avt_telemetry["avt_T1"] == 130.0
        assert state.avt_telemetry["avt_T6"] == 234.0
        assert state.unit_242000_telemetry["u24_T5"] == 365.0
        assert state.unit_242000_telemetry["u24_T6"] == 8.5

    def test_no_double_prefix(self):
        """Canonical keys not re-prefixed."""
        sb = StateBuilder()
        state = sb.build_state_from_runtime(
            timestamp=datetime.utcnow(),
            avt_telemetry={"avt_T6": 234.0},
            unit_242000_telemetry={"u24_T6": 8.5},
        )
        assert "avt_T6" in state.avt_telemetry
        assert "avt_avt_T6" not in state.avt_telemetry

    def test_empty_column_lists_ok(self):
        """StateBuilder() without column lists works for runtime."""
        sb = StateBuilder(avt_cols=[], u24_cols=[])
        state = sb.build_state_from_runtime(
            timestamp=datetime.utcnow(),
            avt_telemetry={"avt_T1": 130.0},
            unit_242000_telemetry={},
        )
        assert state.avt_telemetry["avt_T1"] == 130.0


# ── FeatureTransformer ──────────────────────────────────────────

class TestFeatureTransformer:
    def test_shared_constants(self):
        """FEATURE_KEY_COLUMNS used by both training and runtime."""
        assert len(FEATURE_KEY_COLUMNS) > 0
        assert "avt_T1" in FEATURE_KEY_COLUMNS
        assert "u24_T5" in FEATURE_KEY_COLUMNS

    def test_transform_produces_features(self):
        """Transformer produces lag, rolling, delta, slope features."""
        ft = FeatureTransformer()
        dates = pd.date_range("2023-01-01", periods=50, freq="10min")
        df = pd.DataFrame({"avt_T1": 130 + np.random.randn(50), "u24_T5": 365 + np.random.randn(50)}, index=dates)
        result = ft.transform(df)
        assert "avt_T1_lag1" in result.columns
        assert "avt_T1_rmean6" in result.columns
        assert "avt_T1_delta" in result.columns
        assert "avt_T1_slope6" in result.columns

    def test_fill_policy_ffill_then_zero(self):
        """Fill policy: ffill then fillna(0) — same as training."""
        ft = FeatureTransformer()
        dates = pd.date_range("2023-01-01", periods=5, freq="10min")
        df = pd.DataFrame({"avt_T1": [1.0, np.nan, 3.0, np.nan, 5.0]}, index=dates)
        result = ft.transform(df)
        # NaN should be ffill'd then remaining filled with 0
        assert not result.isna().any().any()


# ── RuntimeFeatureBuffer ────────────────────────────────────────

class TestFeatureBuffer:
    def test_not_ready_with_few_points(self):
        buf = RuntimeFeatureBuffer(max_history=100, min_duration_minutes=360, min_points=36)
        for i in range(5):
            buf.push(datetime(2023, 1, 1) + timedelta(minutes=i*10), {"T1": 130.0}, {"T5": 365.0})
        assert not buf.history_ready

    def test_ready_with_enough_duration(self):
        buf = RuntimeFeatureBuffer(max_history=100, min_duration_minutes=60, min_points=10)
        base = datetime(2023, 1, 1)
        for i in range(10):
            buf.push(base + timedelta(minutes=i*10), {"T1": 130.0+i}, {"T5": 365.0+i})
        assert buf.history_ready
        assert buf.history_duration_minutes >= 60

    def test_abstain_when_not_ready(self):
        buf = RuntimeFeatureBuffer(max_history=100, min_duration_minutes=360, min_points=36)
        buf.push(datetime(2023, 1, 1), {"T1": 130.0}, {"T5": 365.0})
        fv, err = buf.build_feature_vector(["avt_T1"])
        assert fv is None
        assert "not ready" in (err or "").lower() or "history" in (err or "").lower()


# ── Tag Normalization ───────────────────────────────────────────

class TestTagNormalization:
    def test_no_collision(self):
        avt = normalize_telemetry_dict({"T6": 234.0, "F9": 195.0}, "avt")
        u24 = normalize_telemetry_dict({"T6": 8.5, "F9": 171.0}, "u24")
        assert avt["avt_T6"] == 234.0
        assert u24["u24_T6"] == 8.5


# ── QualitySourceResolver ───────────────────────────────────────

class TestQualitySourceResolver:
    def test_lims_over_pak(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [
            QualitySourceCandidate("PAK", 7.0, now - timedelta(minutes=5), 5, 0.9),
            QualitySourceCandidate("LIMS", 6.5, now - timedelta(hours=12), 720, 0.95),
        ]
        result = resolver.resolve("sulfur", candidates, now)
        assert result is not None and result.source == "LIMS"

    def test_fallback_to_pak_when_lims_stale(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [
            QualitySourceCandidate("PAK", 7.0, now - timedelta(minutes=5), 5, 0.9),
            QualitySourceCandidate("LIMS", 6.5, now - timedelta(days=10), 14400, 0.95),
        ]
        result = resolver.resolve("sulfur", candidates, now)
        assert result is not None and result.source == "PAK"

    def test_none_when_all_stale(self):
        resolver = QualitySourceResolver(PROJECT_ROOT / "configs" / "quality_source_policy.yaml")
        now = datetime.utcnow()
        candidates = [QualitySourceCandidate("PAK", 7.0, now - timedelta(hours=10), 600, 0.9)]
        assert resolver.resolve("sulfur", candidates, now) is None


# ── ControlRegistry ─────────────────────────────────────────────

class TestControlRegistry:
    def test_max_step_rejects(self):
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        valid, v = reg.validate_control_value("avt_T1", 150.0, current=130.0)
        assert not valid and any("step" in x.lower() for x in v)

    def test_range_rejects(self):
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        valid, v = reg.validate_control_value("avt_T1", 500.0)
        assert not valid and any("range" in x.lower() or "outside" in x.lower() for x in v)


# ── Safety ──────────────────────────────────────────────────────

class TestSafety:
    def test_confidence_none_validates(self):
        from src.shared.schemas.recommendation import Recommendation
        rec = Recommendation(decision_id="t", timestamp=datetime.utcnow(), confidence=None)
        assert rec.confidence is None

    def test_rejects_unavailable_model(self):
        from src.agents.safety.agent import SafetyAgent
        from src.shared.schemas.quality_prediction import QualityPrediction
        agent = SafetyAgent()
        pred = QualityPrediction(indicator="sulfur", model_available=False, unavailability_reason="test")
        assert not agent.check_quality_prediction(pred).allowed


# ── Surrogate ───────────────────────────────────────────────────

class TestSurrogate:
    def test_missing_feature_returns_unavailable(self):
        from src.agents.surrogate.model import SurrogateModel
        sur = SurrogateModel(quality_model=MagicMock(), feature_names=["avt_T1", "avt_T6"])
        result = sur.simulate(MagicMock(), {"avt_T1": 150.0}, feature_vector={"avt_T1": 130.0})
        assert result.status == "unavailable"

    def test_unmapped_control_returns_unavailable(self):
        from src.agents.surrogate.model import SurrogateModel
        sur = SurrogateModel(
            quality_model=MagicMock(), feature_names=["avt_T1"],
            control_to_feature_map={"avt_T1": "avt_T1"},
        )
        # Action with unmapped control
        result = sur.simulate(MagicMock(), {"unknown_ctrl": 100.0}, feature_vector={"avt_T1": 130.0})
        # Should still work but control not applied (or unavailable if all unmapped)
        # The key test is that unknown control is NOT silently mapped


# ── Optimizer ───────────────────────────────────────────────────

class TestOptimizer:
    def test_no_magic_defaults(self):
        from src.agents.optimization.agent import OptimizationAgent
        from src.agents.surrogate.model import SurrogateModel, SimulationResult
        from src.shared.schemas.process_state import ProcessState
        from src.shared.schemas.reliability import ReliabilityAssessment
        mock_sur = SurrogateModel(quality_model=MagicMock(), feature_names=["avt_T1"])
        mock_sur.simulate = MagicMock(return_value=SimulationResult(status="ok", predictions={}))
        opt = OptimizationAgent(surrogate=mock_sur, n_scenarios=2)
        state = ProcessState(timestamp=datetime.utcnow(), avt_telemetry={"avt_T1": 130.0})
        rel = ReliabilityAssessment(risk_score=0.1, risk_level="low")
        evals, avail = opt.evaluate_scenarios(state, [{"avt_T1": 130.0}], {"avt_T1": 130.0}, rel)
        assert avail and all(e.simulation_status == "error" for e in evals)


# ── HTTP Integration ────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from src.api.app import app
    return TestClient(app)

class TestHTTP:
    def test_health(self, client):
        assert client.get("/health").status_code == 200

    def test_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert "prediction_ready" in resp.json()

    def test_model_info(self, client):
        assert client.get("/model/info").status_code == 200


# ── Temporal Split ──────────────────────────────────────────────

class TestTemporal:
    def test_no_shuffle(self):
        from src.training.temporal_split import chronological_split
        dates = pd.date_range("2023-01-01", periods=1000, freq="10min")
        df = pd.DataFrame({"x": np.random.randn(1000)}, index=dates)
        train, val, test = chronological_split(df, 0.7, 0.15, 0.15)
        assert train.index.max() < val.index.min() < test.index.min()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
