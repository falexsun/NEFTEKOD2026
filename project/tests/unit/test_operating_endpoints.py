import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.runtime_store import RuntimeStore
from src.api.security import Identity
from src.feature_service.runtime_buffer import RuntimeFeatureBuffer
from src.shared.tags.registry import ControlRegistry

api = importlib.import_module("src.api.app")


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    buffer = RuntimeFeatureBuffer()
    store = RuntimeStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    monkeypatch.setattr(api, "_feature_buffer", buffer)
    monkeypatch.setattr(api, "_runtime_store", store)
    return buffer, store


@pytest.mark.parametrize("mode,expected", [("startup", "no_action"), ("shutdown", "no_action"), ("transition", "no_action"), ("unknown", "abstain")])
def test_ingestion_records_policy_without_running_models(runtime, mode, expected):
    _, store = runtime
    payload = api.DecisionRequest(avt_telemetry={}, unit_242000_telemetry={}, avt_mode=mode, u24_mode="normal")
    response = asyncio.run(api.make_decision(payload, SimpleNamespace(state=SimpleNamespace(request_id="mode-test")), Identity("test", "engineer")))
    assert response["recommendation_type"] == expected
    assert store.latest_decision()["recommendation_type"] == expected
    assert store.recent_telemetry()[0]["operating_modes"]["avt"] == mode


def test_scenario_rejects_changed_baseline_before_inference(runtime):
    buffer, _ = runtime
    now = datetime.now(timezone.utc)
    buffer.push(now, {"avt_T1": 148}, {})
    payload = api.ScenarioRequest(action={"avt_T1": 149}, baseline_timestamp=now-timedelta(minutes=10))
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.evaluate_scenario(payload, SimpleNamespace(state=SimpleNamespace(request_id="stale-test")), Identity("test", "operator")))
    assert error.value.status_code == 409
    assert "срез изменился" in error.value.detail


def test_scenario_rejects_missing_regime(runtime):
    buffer, _ = runtime
    now = datetime.now(timezone.utc)
    buffer.push(now, {"avt_T1": 148}, {})
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.evaluate_scenario(api.ScenarioRequest(action={"avt_T1": 149}, baseline_timestamp=now), SimpleNamespace(state=SimpleNamespace(request_id="unknown-test")), Identity("test", "operator")))
    assert error.value.status_code == 409
    assert "ABSTAIN" in error.value.detail


def test_controls_hide_out_of_range_baseline(runtime, monkeypatch):
    buffer, _ = runtime
    monkeypatch.setattr(api, "_control_registry", ControlRegistry("configs/controls.yaml"))
    buffer.push(datetime.now(timezone.utc), {"avt_T1": 150, "avt_T33": 335}, {})

    controls = asyncio.run(api.controls_catalog(Identity("test", "operator")))["controls"]
    by_id = {item["id"]: item for item in controls}
    assert by_id["avt_T1"]["available"] is True
    assert by_id["avt_T33"]["available"] is False
    assert by_id["avt_T33"]["availability_reason"] == "Текущее значение вне модельного диапазона"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_scenario_rejects_nonfinite_input(value):
    with pytest.raises(ValidationError):
        api.ScenarioRequest(action={"avt_T1": value}, baseline_timestamp=datetime.now(timezone.utc))
