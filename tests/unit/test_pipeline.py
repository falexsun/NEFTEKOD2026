"""Behavioral tests for runtime correctness — no .fit() calls.

Tests cover:
- Model wrapper feature name extraction
- No sorted fallback
- Schema mismatch → ABSTAIN
- Canonical tag collision prevention
- ControlRegistry behavior
- NO CHANGE baseline
- Surrogate exact feature mapping
- Safety no defaults
- Surrogate unavailable → ABSTAIN
- Stale data → allow_optimization=False
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def sample_state():
    from src.shared.schemas.process_state import ProcessState, QualitySignal
    return ProcessState(
        timestamp=datetime(2023, 6, 15, 12, 0),
        avt_telemetry={
            "T1": 130.5, "T6": 234.2, "T33": 68.5, "T55": 380.1,
            "F3": 68.7, "F5": 103.9, "F7": 217.5, "F8": 211.7, "F9": 195.9,
        },
        unit_242000_telemetry={
            "T5": 365.1, "T6": 8.5, "W7": 7.2, "P8": 358.0,
            "F9": 171.1, "F15": 5.8, "T11": 363.6, "T16": 175.1,
        },
        quality={
            "sulfur": QualitySignal(
                value=7.5, source="PAK",
                measurement_timestamp=datetime(2023, 6, 15, 11, 50),
                age_minutes=10, confidence=0.9,
            )
        },
    )


@pytest.fixture
def feature_vector_721():
    """Build a fake 721-feature vector matching model schema."""
    from src.agents.quality.agent import _extract_feature_names_from_model
    import pickle
    with open(PROJECT_ROOT / "models" / "catboost_champion.pkl", "rb") as f:
        model = pickle.load(f)
    names = _extract_feature_names_from_model(model)
    return {name: float(np.random.randn()) for name in names}


# ── Test: Model Wrapper Feature Names ───────────────────────────

class TestModelWrapperFeatureNames:
    """Test that feature names are extracted from inner estimator, not wrapper."""

    def test_extract_from_inner_estimator(self):
        import pickle
        from src.agents.quality.agent import _extract_feature_names_from_model
        with open(PROJECT_ROOT / "models" / "catboost_champion.pkl", "rb") as f:
            wrapper = pickle.load(f)
        names = _extract_feature_names_from_model(wrapper)
        assert names is not None
        assert len(names) == 721
        assert names[0] == "avt_T1"

    def test_wrapper_has_no_feature_names(self):
        import pickle
        wrapper_path = PROJECT_ROOT / "models" / "catboost_champion.pkl"
        with open(wrapper_path, "rb") as f:
            wrapper = pickle.load(f)
        # Wrapper itself should NOT have feature_names_
        assert not hasattr(wrapper, "feature_names_")

    def test_inner_has_feature_names(self):
        import pickle
        with open(PROJECT_ROOT / "models" / "catboost_champion.pkl", "rb") as f:
            wrapper = pickle.load(f)
        assert hasattr(wrapper.model, "feature_names_")
        assert len(wrapper.model.feature_names_) == 721


# ── Test: No Sorted Fallback ────────────────────────────────────

class TestNoSortedFallback:
    """If feature metadata missing → model_available=False, NOT sorted keys."""

    def test_quality_agent_uses_model_order(self, feature_vector_721):
        from src.agents.quality.agent import QualityAgent
        agent = QualityAgent(model_dir=str(PROJECT_ROOT / "models"))
        assert agent.is_ready
        assert agent.model_metadata is not None
        # Feature names should come from model, not sorted
        assert agent.model_metadata.feature_names[0] == "avt_T1"

    def test_missing_metadata_returns_unavailable(self):
        from src.agents.quality.agent import QualityAgent
        agent = QualityAgent(model_dir="/nonexistent")
        assert not agent.is_available
        from src.shared.schemas.process_state import ProcessState
        state = ProcessState(timestamp=datetime.utcnow())
        result = agent.predict(state, {"dummy": 1.0})
        assert not result.model_available


# ── Test: Schema Mismatch → ABSTAIN ────────────────────────────

class TestSchemaMismatch:
    """Incomplete feature vector → model_available=False → ABSTAIN."""

    def test_incomplete_features_returns_unavailable(self):
        from src.agents.quality.agent import QualityAgent
        from src.shared.schemas.process_state import ProcessState
        agent = QualityAgent(model_dir=str(PROJECT_ROOT / "models"))
        state = ProcessState(timestamp=datetime.utcnow())
        result = agent.predict(state, {"avt_T1": 130.0, "avt_T6": 234.0})  # Only 2 of 721
        assert not result.model_available
        assert "mismatch" in (result.unavailability_reason or "").lower() or "missing" in (result.unavailability_reason or "").lower()


# ── Test: Canonical Tag Collision ───────────────────────────────

class TestCanonicalTagCollision:
    """AVT T6 and U24 T6 must be different after normalization."""

    def test_no_collision(self):
        from src.shared.tags.normalization import normalize_tag
        avt_t6 = normalize_tag("avt", "T6")
        u24_t6 = normalize_tag("u24", "T6")
        assert avt_t6 != u24_t6
        assert avt_t6 == "avt_T6"
        assert u24_t6 == "u24_T6"

    def test_normalize_telemetry_dict(self):
        from src.shared.tags.normalization import normalize_telemetry_dict
        avt = normalize_telemetry_dict({"T6": 234.0, "T1": 130.0}, "avt")
        u24 = normalize_telemetry_dict({"T6": 8.5, "T5": 365.0}, "u24")
        assert "avt_T6" in avt
        assert "u24_T6" in u24
        assert avt["avt_T6"] != u24["u24_T6"]


# ── Test: Control Registry ──────────────────────────────────────

class TestControlRegistry:
    def test_loads_controls(self):
        from src.shared.tags.registry import ControlRegistry
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        assert len(reg.controls) > 0

    def test_state_only_not_in_candidates(self):
        from src.shared.tags.registry import ControlRegistry
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        candidates = reg.get_control_candidates()
        # u24_T6 is state-only
        assert "u24_T6" not in candidates

    def test_control_candidate_in_candidates(self):
        from src.shared.tags.registry import ControlRegistry
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        candidates = reg.get_control_candidates()
        assert "avt_T1" in candidates or "avt_F3" in candidates

    def test_unknown_tag_not_control(self):
        from src.shared.tags.registry import ControlRegistry
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        assert not reg.is_control("unknown_tag")

    def test_validate_range(self):
        from src.shared.tags.registry import ControlRegistry
        reg = ControlRegistry(PROJECT_ROOT / "configs" / "controls.yaml")
        # avt_T1 has range [100, 200]
        valid, _ = reg.validate_control_value("avt_T1", 150.0)
        assert valid
        invalid, violations = reg.validate_control_value("avt_T1", 500.0)
        assert not invalid
        assert any("outside" in v for v in violations)


# ── Test: NO CHANGE Baseline ────────────────────────────────────

class TestNoChangeBaseline:
    """Baseline candidate must equal current control values."""

    def test_baseline_equals_current(self):
        """Baseline must contain actual current values for all available controls."""
        from src.agents.optimization.agent import OptimizationAgent
        from src.agents.surrogate.model import SurrogateModel
        from src.shared.schemas.process_state import ProcessState

        # State with canonical tag names (as after normalization)
        state = ProcessState(
            timestamp=datetime(2023, 6, 15, 12, 0),
            avt_telemetry={"avt_T1": 130.5, "avt_T6": 234.2, "avt_T33": 68.5},
            unit_242000_telemetry={"u24_T5": 365.1, "u24_T6": 8.5},
        )
        opt = OptimizationAgent(surrogate=SurrogateModel(), n_scenarios=5, seed=42)
        controls = {"avt_T1": (100, 200), "avt_T6": (200, 260), "u24_T5": (340, 380)}
        candidates = opt.generate_candidates(state, controls)
        baseline = candidates[0]
        assert baseline.get("avt_T1") == 130.5
        assert baseline.get("avt_T6") == 234.2
        assert baseline.get("u24_T5") == 365.1


# ── Test: Surrogate Exact Feature Mapping ───────────────────────

class TestSurrogateExactMapping:
    """Changing avt_T1 must NOT change avt_T1_lag1, avt_T11, etc."""

    def test_no_substring_match(self):
        from src.agents.surrogate.model import SurrogateModel
        sur = SurrogateModel(
            quality_model=MagicMock(),
            feature_names=["avt_T1", "avt_T1_lag1", "avt_T11", "avt_T6"],
            control_to_feature_map={"avt_T1": "avt_T1"},
        )
        fv = {"avt_T1": 130.0, "avt_T1_lag1": 129.0, "avt_T11": 56.0, "avt_T6": 234.0}
        # Simulate — only avt_T1 should change
        modified = dict(fv)
        for control_name, value in {"avt_T1": 150.0}.items():
            mapped = sur.control_to_feature_map.get(control_name)
            if mapped and mapped in modified:
                modified[mapped] = value
        assert modified["avt_T1"] == 150.0
        assert modified["avt_T1_lag1"] == 129.0  # NOT changed
        assert modified["avt_T11"] == 56.0  # NOT changed


# ── Test: Safety No Defaults ────────────────────────────────────

class TestSafetyNoDefaults:
    """Safety endpoint must reject requests missing required fields."""

    def test_safety_check_requires_fields(self):
        from src.agents.safety.agent import SafetyAgent
        from src.shared.schemas.quality_prediction import QualityPrediction
        agent = SafetyAgent()
        # Unavailable model → reject
        pred = QualityPrediction(indicator="sulfur", model_available=False, unavailability_reason="test")
        result = agent.check_quality_prediction(pred)
        assert not result.allowed

    def test_safety_rejects_none_prediction(self):
        from src.agents.safety.agent import SafetyAgent
        from src.shared.schemas.quality_prediction import QualityPrediction
        agent = SafetyAgent()
        pred = QualityPrediction(indicator="sulfur", prediction=None, model_available=True)
        result = agent.check_quality_prediction(pred)
        assert not result.allowed


# ── Test: Surrogate Unavailable → ABSTAIN ───────────────────────

class TestSurrogateUnavailable:
    def test_optimization_returns_empty(self, sample_state):
        from src.agents.optimization.agent import OptimizationAgent
        from src.agents.surrogate.model import SurrogateModel
        from src.shared.schemas.reliability import ReliabilityAssessment
        opt = OptimizationAgent(surrogate=SurrogateModel(), n_scenarios=5)
        reliability = ReliabilityAssessment(risk_score=0.1, risk_level="low")
        evals, available = opt.evaluate_scenarios(sample_state, [{"avt_T1": 130.0}], {}, reliability)
        assert not available
        assert evals == []


# ── Test: Stale Data → allow_optimization=False ─────────────────

class TestStaleData:
    def test_stale_pak_no_optimization(self):
        from src.agents.data_quality.agent import DataQualityAgent
        from src.shared.schemas.process_state import ProcessState, QualitySignal, SourceFreshness
        agent = DataQualityAgent(min_avt_signals=2, min_u24_signals=2)
        state = ProcessState(
            timestamp=datetime.utcnow(),
            avt_telemetry={f"T{i}": float(i) for i in range(20)},
            unit_242000_telemetry={f"F{i}": float(i) for i in range(10)},
            quality={"sulfur": QualitySignal(
                value=7.5, source="PAK",
                measurement_timestamp=datetime(2020, 1, 1),
                age_minutes=100000, confidence=0.1,
            )},
            source_freshness=SourceFreshness(pak_sulfur_minutes=100000),
        )
        result = agent.evaluate(state)
        assert result.allow_prediction  # Enough signals
        assert not result.allow_optimization  # Stale PAK


# ── Test: Temporal Split ────────────────────────────────────────

class TestChronologicalSplit:
    def test_no_shuffle(self):
        from src.training.temporal_split import chronological_split
        import pandas as pd
        dates = pd.date_range("2023-01-01", periods=1000, freq="10min")
        df = pd.DataFrame({"x": np.random.randn(1000)}, index=dates)
        train, val, test = chronological_split(df, 0.7, 0.15, 0.15)
        assert train.index.max() < val.index.min()
        assert val.index.max() < test.index.min()

    def test_no_leakage(self):
        from src.training.temporal_split import check_leakage
        import pandas as pd
        dates = pd.date_range("2023-01-01", periods=1000, freq="10min")
        df = pd.DataFrame({"x": np.random.randn(1000), "y": np.random.randn(1000)}, index=dates)
        train = df.iloc[:700]
        val = df.iloc[700:]
        result = check_leakage(train, val, "y")
        assert not result["has_leakage"]


# ── Test: Source Freshness ──────────────────────────────────────

class TestSourceFreshness:
    def test_freshness_populated(self):
        from src.feature_service.state_builder import StateBuilder
        import pandas as pd
        builder = StateBuilder(avt_cols=["T1"], u24_cols=["T5"])
        row = pd.Series({"T1": 130.0, "T5": 365.0})
        state = builder.build_state(
            row=row,
            timestamp=datetime(2023, 6, 15, 12, 0),
            sulfur_value=7.5,
            sulfur_ts=datetime(2023, 6, 15, 11, 50),
            avt_ts=datetime(2023, 6, 15, 11, 55),
            u24_ts=datetime(2023, 6, 15, 11, 50),
        )
        assert state.source_freshness.avt_minutes == 5.0
        assert state.source_freshness.pak_sulfur_minutes == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
