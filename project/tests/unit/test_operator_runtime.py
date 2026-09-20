from datetime import datetime, timedelta, timezone

import pytest
import pandas as pd
from fastapi import HTTPException

from src.api.runtime_store import RuntimeStore
from src.api.security import require_role
from src.feature_service.runtime_buffer import RuntimeFeatureBuffer
from src.feature_service.transformer import FeatureTransformer


def test_runtime_store_persists_decision_and_telemetry(tmp_path):
    store = RuntimeStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    now = datetime.now(timezone.utc)
    store.append_telemetry(now, {"avt_T1": 148.0, "source_timestamps": {"avt": now.isoformat()}})
    store.save_decision("decision-1", now, "abstain", {"reason": "warmup"}, "request-1", "test")

    assert store.recent_telemetry()[0]["avt_T1"] == 148.0
    assert store.recent_telemetry()[0]["timestamp"].utcoffset() == timedelta(0)
    assert store.latest_decision()["data"]["reason"] == "warmup"
    assert store.latest_decision()["timestamp"].utcoffset() == timedelta(0)


def test_runtime_store_persists_q21_history_forecasts_and_outcomes(tmp_path):
    store = RuntimeStore(f"sqlite:///{tmp_path / 'q21.db'}")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    assert store.append_q21_point(now, "normal", 8.4, {"F1": 1.0}) is True
    assert store.append_q21_point(now, "normal", 8.5, {"F1": 2.0}) is False
    assert store.recent_q21_points()[0]["Q21"] == 8.4
    assert store.recent_q21_points()[0]["timestamp"].utcoffset() == timedelta(0)

    forecasts = [{"horizon_hours": 0.5, "q21": 8.7}, {"horizon_hours": 1.0, "q21": 9.0}]
    interval = {"lower": 7.5, "upper": 10.2}
    store.save_q21_forecasts("forecast-1", now, forecasts, interval,
                             {0.5: "a" * 64, 1.0: "b" * 64})
    latest = store.latest_q21_forecast()
    assert len(latest["forecasts"]) == 2
    assert latest["forecasts"][1]["lower"] == 7.5
    assert latest["origin_timestamp"].utcoffset() == timedelta(0)

    assert store.resolve_q21_outcomes(now + timedelta(hours=1), 9.2) == 1
    metrics = store.q21_shadow_metrics()
    assert metrics["resolved"] == 1
    assert metrics["by_horizon"][0]["mae"] == pytest.approx(0.2)
    assert metrics["by_horizon"][0]["interval_coverage"] == 1.0


def test_transformer_builds_deployed_t33_t55_derived_features():
    frame = pd.DataFrame({"avt_T33": range(37), "avt_T55": range(100, 137)})
    transformed = FeatureTransformer().transform(frame)
    for tag in ("avt_T33", "avt_T55"):
        for suffix in ("lag12", "rmean36", "delta6", "slope12", "missing"):
            assert f"{tag}_{suffix}" in transformed.columns

def test_runtime_buffer_rejects_duplicate_and_out_of_order_points():
    buffer = RuntimeFeatureBuffer()
    now = datetime.now(timezone.utc)
    assert buffer.push(now, {"avt_T1": 148.0}, {}) is True
    assert buffer.push(now, {"avt_T1": 149.0}, {}) is False
    assert buffer.push(now - timedelta(minutes=10), {"avt_T1": 147.0}, {}) is False
    assert buffer.history_size == 1


def test_admin_endpoint_dependency_rejects_operator_key(monkeypatch):
    monkeypatch.setenv("NEFTEKOD_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEFTEKOD_OPERATOR_API_KEY", "operator-secret")
    dependency = require_role("admin")
    with pytest.raises(HTTPException) as error:
        dependency("operator-secret")
    assert error.value.status_code == 403


def test_operator_dependency_accepts_operator_key(monkeypatch):
    monkeypatch.setenv("NEFTEKOD_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEFTEKOD_OPERATOR_API_KEY", "operator-secret")
    identity = require_role("operator")("operator-secret")
    assert identity.role == "operator"
