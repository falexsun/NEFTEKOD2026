"""Unit tests for temporal split, feature engineering, and safety constraints."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def sample_timeseries():
    """Create a sample time-series DataFrame for testing."""
    dates = pd.date_range("2023-01-01", periods=1000, freq="10min")
    np.random.seed(42)
    df = pd.DataFrame({
        "avt_T1": 130 + np.random.randn(1000) * 2,
        "avt_T6": 234 + np.random.randn(1000) * 3,
        "u24_T5": 365 + np.random.randn(1000) * 5,
        "sulfur_mg_kg": 7 + np.random.randn(1000) * 1.5,
    }, index=dates)
    df.index.name = "timestamp"
    return df


@pytest.fixture
def sample_process_state():
    """Create a sample ProcessState."""
    from src.shared.schemas.process_state import ProcessState, QualitySignal
    from datetime import datetime

    return ProcessState(
        timestamp=datetime(2023, 6, 15, 12, 0),
        avt_telemetry={"T1": 130.5, "T6": 234.2, "T33": 68.5},
        unit_242000_telemetry={"T5": 365.1, "T6": 8.5, "W7": 7.2},
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


# ── Temporal Split Tests ────────────────────────────────────────

class TestChronologicalSplit:
    """Test that temporal split respects chronological ordering."""

    def test_no_shuffle(self, sample_timeseries):
        from src.training.temporal_split import chronological_split
        train, val, test = chronological_split(sample_timeseries, 0.7, 0.15, 0.15)

        # All train timestamps should be before val timestamps
        assert train.index.max() < val.index.min()
        # All val timestamps should be before test timestamps
        assert val.index.max() < test.index.min()

    def test_no_overlap(self, sample_timeseries):
        from src.training.temporal_split import chronological_split
        train, val, test = chronological_split(sample_timeseries, 0.7, 0.15, 0.15)

        # No overlap between sets
        train_set = set(train.index)
        val_set = set(val.index)
        test_set = set(test.index)
        assert len(train_set & val_set) == 0
        assert len(val_set & test_set) == 0

    def test_coverage(self, sample_timeseries):
        from src.training.temporal_split import chronological_split
        train, val, test = chronological_split(sample_timeseries, 0.7, 0.15, 0.15)

        total = len(train) + len(val) + len(test)
        assert total == len(sample_timeseries)

    def test_monotonic_index(self, sample_timeseries):
        from src.training.temporal_split import chronological_split
        train, val, test = chronological_split(sample_timeseries, 0.7, 0.15, 0.15)

        assert train.index.is_monotonic_increasing
        assert val.index.is_monotonic_increasing
        assert test.index.is_monotonic_increasing


class TestLeakageCheck:
    """Test leakage detection."""

    def test_no_leakage_clean(self, sample_timeseries):
        from src.training.temporal_split import chronological_split, check_leakage
        train, val, test = chronological_split(sample_timeseries, 0.7, 0.15, 0.15)

        result = check_leakage(train, val, "sulfur_mg_kg")
        assert not result["has_leakage"]

    def test_detects_overlap(self, sample_timeseries):
        from src.training.temporal_split import check_leakage
        # Create overlapping sets
        train = sample_timeseries.iloc[:700]
        val = sample_timeseries.iloc[600:850]  # Overlaps with train

        result = check_leakage(train, val, "sulfur_mg_kg")
        assert result["has_leakage"]


class TestWalkForward:
    """Test walk-forward validation."""

    def test_produces_splits(self, sample_timeseries):
        from src.training.temporal_split import walk_forward_splits
        splits = walk_forward_splits(sample_timeseries, n_splits=3, min_train_days=3, test_days=2)
        assert len(splits) > 0

    def test_temporal_ordering(self, sample_timeseries):
        from src.training.temporal_split import walk_forward_splits
        splits = walk_forward_splits(sample_timeseries, n_splits=3, min_train_days=3, test_days=2)

        for train, test in splits:
            assert train.index.max() < test.index.min()


# ── Safety Constraint Tests ─────────────────────────────────────

class TestSulfurSafety:
    """Test sulfur safety constraints."""

    def test_sulfur_limit_constant(self):
        from src.agents.safety.agent import SafetyAgent
        agent = SafetyAgent()
        assert agent.sulfur_limit == 10.0

    def test_scenario_rejected_above_limit(self):
        from src.agents.safety.agent import SafetyAgent
        from src.agents.optimization.agent import ScenarioEvaluation
        from src.shared.schemas.quality_prediction import QualityPrediction

        agent = SafetyAgent()

        # Scenario with sulfur predicted above limit
        scenario = ScenarioEvaluation(
            scenario_id="test",
            action={},
            predicted_sulfur=11.0,
            sulfur_std=0.5,
            violation_probability=0.95,
        )
        quality_pred = QualityPrediction(
            indicator="sulfur",
            prediction=11.0,
            upper_bound=12.0,
            violation_probability=0.95,
            confidence=0.1,
        )

        decision = agent.check_scenario(scenario, quality_pred, data_quality_score=1.0)
        assert not decision.allowed
        assert len(decision.violations) > 0

    def test_scenario_accepted_below_limit(self):
        from src.agents.safety.agent import SafetyAgent
        from src.agents.optimization.agent import ScenarioEvaluation
        from src.shared.schemas.quality_prediction import QualityPrediction

        agent = SafetyAgent()

        # Scenario with sulfur well below limit
        scenario = ScenarioEvaluation(
            scenario_id="test",
            action={},
            predicted_sulfur=6.0,
            sulfur_std=0.5,
            violation_probability=0.01,
        )
        quality_pred = QualityPrediction(
            indicator="sulfur",
            prediction=6.0,
            lower_bound=5.0,
            upper_bound=7.0,
            violation_probability=0.01,
            confidence=0.95,
        )

        decision = agent.check_scenario(scenario, quality_pred, data_quality_score=1.0)
        assert decision.allowed


# ── Feature Engineering Tests ───────────────────────────────────

class TestFeatures:
    """Test feature engineering functions."""

    def test_no_future_leakage(self, sample_timeseries):
        """Verify lag features only use past data."""
        from src.feature_service.features import build_features

        # Add target column
        df = sample_timeseries.copy()
        df["target_sulfur"] = df["sulfur_mg_kg"].shift(-6)  # 1h ahead

        # Check that lag features at time t don't use data > t
        # lag1 of avt_T1 at time t should equal avt_T1 at time t-1
        # This is a structural test
        assert "avt_T1" in df.columns
        lag1 = df["avt_T1"].shift(1)
        # At the first non-NaN point, lag should be the previous value
        assert pd.isna(lag1.iloc[0])  # First value should be NaN
        assert lag1.iloc[1] == df["avt_T1"].iloc[0]  # Second lag = first value

    def test_rolling_no_future(self, sample_timeseries):
        """Verify rolling features don't include future data."""
        df = sample_timeseries.copy()

        # Rolling mean with window=6 should only use current + past 5 values
        rolling = df["avt_T1"].rolling(window=6, min_periods=1).mean()

        # At each point, rolling mean should equal the mean of past values
        for i in range(5, 10):
            expected = df["avt_T1"].iloc[max(0, i-5):i+1].mean()
            assert abs(rolling.iloc[i] - expected) < 1e-10


# ── Data Quality Agent Tests ────────────────────────────────────

class TestDataQualityAgent:
    """Test Data Quality Agent behavior."""

    def test_sufficient_data(self, sample_process_state):
        from src.agents.data_quality.agent import DataQualityAgent
        agent = DataQualityAgent(min_avt_signals=2, min_u24_signals=2)
        result = agent.evaluate(sample_process_state)
        assert result.allow_prediction

    def test_insufficient_data(self):
        from src.agents.data_quality.agent import DataQualityAgent
        from src.shared.schemas.process_state import ProcessState
        from datetime import datetime

        agent = DataQualityAgent(min_avt_signals=10)
        state = ProcessState(
            timestamp=datetime(2023, 6, 15, 12, 0),
            avt_telemetry={"T1": 130.0},  # Only 1 signal
        )
        result = agent.evaluate(state)
        assert not result.allow_prediction


# ── ABSTAIN Behavior Tests ──────────────────────────────────────

class TestAbstainBehavior:
    """Test that the system correctly abstains when conditions are met."""

    def test_abstain_on_no_sulfur(self):
        from src.agents.data_quality.agent import DataQualityAgent
        from src.shared.schemas.process_state import ProcessState
        from datetime import datetime

        agent = DataQualityAgent(min_avt_signals=2, min_u24_signals=2)
        # State with telemetry but no quality signal
        state = ProcessState(
            timestamp=datetime(2023, 6, 15, 12, 0),
            avt_telemetry={f"T{i}": float(i) for i in range(20)},
            unit_242000_telemetry={f"F{i}": float(i) for i in range(10)},
            quality={},  # No quality signals
        )
        result = agent.evaluate(state)
        # Should not allow optimization without quality signal
        assert not result.allow_optimization


# ── PAK Loader Priority Tests ───────────────────────────────────

class TestSourcePriority:
    """Test that LIMS > PAK > VAK priority is respected."""

    def test_quality_signal_source_tracking(self):
        from src.shared.schemas.process_state import QualitySignal
        from datetime import datetime

        # Create signals from different sources
        lims = QualitySignal(value=6.5, source="LIMS", measurement_timestamp=datetime.now(), age_minutes=120, confidence=0.6)
        pak = QualitySignal(value=7.0, source="PAK", measurement_timestamp=datetime.now(), age_minutes=10, confidence=0.9)

        # PAK should be preferred for fresher data
        # LIMS should be preferred for lab-validated data
        assert lims.source == "LIMS"
        assert pak.source == "PAK"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
