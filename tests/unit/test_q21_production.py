from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.inference.advisory_system import Q21AdvisorySystem
from src.inference.feature_builder import FeatureContractError, Q21FeatureBuilder
from src.inference.state_detector import PlantState
from src.inference.vak import evaluate_vak


ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "project/models"


def production_history() -> pd.DataFrame:
    raw = pd.read_csv(ROOT / "data/242000_tags.csv").tail(145).copy()
    raw["timestamp"] = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=145, freq="10min")
    raw["F31"] = np.linspace(499.5, 500.5, len(raw))
    raw["T33"] = np.linspace(334.8, 335.2, len(raw))
    raw["T55"] = np.linspace(359.8, 360.2, len(raw))
    return raw


def test_feature_builder_requires_complete_24_hour_window():
    with pytest.raises(FeatureContractError, match="145"):
        Q21FeatureBuilder().build(pd.DataFrame({"timestamp": [pd.Timestamp.now()], "Q21": [8.0]}), [], [])


def test_checksum_pinned_h1_pipeline_runs_with_exact_features():
    system = Q21AdvisorySystem(MODELS, lambda_penalty=25)
    result = system.generate_advisory(production_history(), declared_state=PlantState.NORMAL)
    assert result.reason_code == "OK"
    assert np.isfinite(result.q21_forecast_1h)
    assert 0 <= result.exceedance_probability <= 1
    assert result.details["history_points"] == 145
    assert result.details["threshold"] == 0.248
    assert set(result.multi_horizon_forecasts) == {0.5, 1.0, 2.0, 3.0, 6.0}
    assert result.multi_horizon_forecasts[1.0] == result.q21_forecast_1h
    assert result.q21_interval_80[0] <= result.q21_interval_80[1]


def test_q21_307_produces_no_action_before_inference():
    system = Q21AdvisorySystem(MODELS)
    history = production_history()
    history.loc[history.index[-1], "Q21"] = 307.0
    result = system.generate_advisory(history, current_q21=307.0, declared_state=PlantState.NORMAL)
    assert result.action == "NO_ACTION"
    assert result.reason_code == "Q21_CODE_307"
    assert "known outlier" in result.message


def test_missing_declared_mode_fails_closed():
    system = Q21AdvisorySystem(MODELS)
    result = system.generate_advisory(production_history())
    assert result.action == "NO_ACTION"
    assert result.plant_state is PlantState.UNKNOWN


def test_vak_examples_match_organizer_sheet():
    values = {"F65": 789.54, "F32": 79.0, "F30": 98.97, "T66": 255.04, "T33": 335.41,
              "T42": 275.99, "T48": 354.43, "F31": 500.83, "F57": 23.84}
    result = {item["model"]: item for item in evaluate_vak(values, ["AVT6:240-350:D15", "AVT6:350:D15"])}
    assert result["AVT6:240-350:D15"]["value"] == pytest.approx(849.83, abs=.02)
    assert result["AVT6:350:D15"]["value"] == pytest.approx(878.25, abs=.02)


def test_vak_denominator_failure_is_explicit():
    result = evaluate_vak({"T42": 275.99, "T48": 354.43, "F31": 500.83, "F57": 0}, ["AVT6:350:D15"])[0]
    assert result["status"] == "invalid"
