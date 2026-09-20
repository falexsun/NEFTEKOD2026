"""
Test suite for Q21 Advisory System inference components.
"""
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

from src.inference.model_bundle import Q21ModelBundle
from src.inference.state_detector import PlantState, StateDetector
from src.inference.quality_gates import QualityGates, ValidationResult
from src.inference.advisory_system import Q21AdvisorySystem


@pytest.fixture
def models_dir():
    """Get models directory path."""
    return Path(__file__).resolve().parents[1] / "models"


@pytest.fixture
def sample_telemetry():
    """Generate sample telemetry data."""
    timestamps = pd.date_range(end=pd.Timestamp.now(), periods=12, freq='10min')
    return pd.DataFrame({
        'timestamp': timestamps,
        'Q21': [8.2, 8.5, 8.7, 9.1, 9.3, 9.5, 9.8, 10.2, 10.5, 10.8, 11.1, 11.3],
        'F30': [100.5] * 12,
        'F31': [45.2] * 12,
        'W70': [78.5] * 12,
        'T33': [285.3] * 12,
        'T55': [365.7] * 12,
        'F19': [25.0] * 12,
        'T11': [180.5] * 12
    })


class TestModelBundle:
    """Test Q21ModelBundle."""

    def test_model_loading(self, models_dir):
        """Test that models can be loaded."""
        if not models_dir.exists():
            pytest.skip("Models directory not found")

        bundle = Q21ModelBundle(models_dir)
        bundle.load_models()

        assert bundle.regression_model is not None
        assert bundle.risk_model is not None
        assert bundle.regression_meta is not None
        assert bundle.risk_meta is not None

    def test_expected_checksums(self, models_dir):
        """Verify model checksums match expected values."""
        if not models_dir.exists():
            pytest.skip("Models directory not found")

        bundle = Q21ModelBundle(models_dir)

        assert bundle.EXPECTED_CHECKSUMS["regression"] == "95469b40d8b550fa1dbf16e7faba4ed400c0a9398fe015f8042c00259d478eee"
        assert bundle.EXPECTED_CHECKSUMS["risk"] == "a0ef98b61af8ba439260e546da13e787c171f0ec90ebd5c300d6b89d18f3e496"


class TestStateDetector:
    """Test StateDetector."""

    def test_normal_state_detection(self, sample_telemetry):
        """Test detection of normal operating state."""
        detector = StateDetector()
        state, confidence = detector.detect(sample_telemetry)

        assert state in [PlantState.NORMAL, PlantState.TRANSITION]
        assert isinstance(confidence, dict)

    def test_empty_data_returns_unknown(self):
        """Test that empty data returns UNKNOWN state."""
        detector = StateDetector()
        state, confidence = detector.detect(pd.DataFrame())

        assert state == PlantState.UNKNOWN

    def test_shutdown_detection(self):
        """Test detection of shutdown state."""
        detector = StateDetector()

        # Create data with low flow activity
        data = pd.DataFrame({
            'F30': [0.01] * 12,
            'F31': [0.01] * 12,
            'F19': [0.01] * 12,
            'T33': [50.0] * 12,
            'T55': [50.0] * 12,
            'T11': [50.0] * 12
        })

        state, confidence = detector.detect(data)
        assert state in [PlantState.SHUTDOWN, PlantState.TRANSITION]


class TestQualityGates:
    """Test QualityGates."""

    def test_q21_code_307_detection(self):
        """Test detection of Q21 unreliable code 307."""
        gates = QualityGates()

        result = gates.check_q21_reliability(307.0)
        assert not result.passed
        assert result.reason_code == "Q21_CODE_307"

    def test_q21_normal_value(self):
        """Test that normal Q21 values pass reliability check."""
        gates = QualityGates()

        result = gates.check_q21_reliability(8.5)
        assert result.passed
        assert result.reason_code == "OK"

    def test_frozen_sensor_detection(self):
        """Test frozen sensor detection."""
        gates = QualityGates()

        # Create data with frozen sensor
        data = pd.DataFrame({
            'F30': [100.5] * 20,
            'Q21': [8.2] * 20
        })

        result = gates.check_frozen_sensors(data)
        assert not result.passed
        assert result.reason_code == "FROZEN_SENSOR"

    def test_zero_denominator_detection(self):
        """Test zero denominator detection."""
        gates = QualityGates()

        data = pd.DataFrame({
            'F30': [0.0],
            'W70': [78.5]
        })

        result = gates.check_zero_denominators(data)
        assert not result.passed
        assert result.reason_code == "ZERO_DENOMINATOR"

    def test_freshness_check_stale_data(self):
        """Test freshness check with stale data."""
        gates = QualityGates(max_staleness_minutes=30)

        # Create data from 2 hours ago
        old_time = pd.Timestamp.now(tz="UTC").tz_localize(None) - timedelta(hours=2)
        data = pd.DataFrame({
            'timestamp': [old_time],
            'Q21': [8.5]
        })

        result = gates.check_freshness(data)
        assert not result.passed
        assert result.reason_code == "STALE_DATA"

    def test_freshness_check_naive_utc_from_storage(self):
        """SQLite drops timezone metadata; recent UTC data must remain fresh."""
        gates = QualityGates(max_staleness_minutes=30)
        recent_utc = pd.Timestamp.now(tz="UTC").tz_localize(None) - timedelta(minutes=5)
        data = pd.DataFrame({'timestamp': [recent_utc], 'Q21': [8.5]})

        result = gates.check_freshness(data)
        assert result.passed
        assert result.reason_code == "OK"


class TestAdvisorySystem:
    """Test Q21AdvisorySystem integration."""

    def test_advisory_generation(self, models_dir, sample_telemetry):
        """Test full advisory generation pipeline."""
        if not models_dir.exists():
            pytest.skip("Models directory not found")

        system = Q21AdvisorySystem(models_dir, lambda_penalty=25)
        advisory = system.generate_advisory(sample_telemetry, current_q21=8.5)

        assert advisory.timestamp is not None
        assert advisory.plant_state is not None
        assert advisory.action in ["MONITOR", "NO_ACTION", "INVESTIGATE", "ADJUST"]
        assert advisory.reason_code is not None

    def test_no_action_on_abnormal_state(self, models_dir):
        """Test that NO_ACTION is returned for abnormal plant state."""
        if not models_dir.exists():
            pytest.skip("Models directory not found")

        system = Q21AdvisorySystem(models_dir)

        # Create shutdown telemetry
        data = pd.DataFrame({
            'F30': [0.01] * 12,
            'F31': [0.01] * 12,
            'T33': [50.0] * 12
        })

        advisory = system.generate_advisory(data)
        assert advisory.action == "NO_ACTION"
