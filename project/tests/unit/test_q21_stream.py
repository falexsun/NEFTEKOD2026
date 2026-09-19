import json

import pytest

from src.ingestion.q21_stream import InvalidTelemetryEvent, decode_event


def test_decode_redis_q21_event():
    event = {"source_timestamp": "2026-09-16T10:00:00Z", "u24_mode": "normal",
             "unit_242000_telemetry": {"Q21": 8.4, "F1": 2.1, "P8": 0.12},
             "avt_telemetry": {"F31": 42.0, "T33": 271.0, "T55": 198.0, "F1": 999.0}}
    payload = decode_event(json.dumps(event).encode())
    assert payload == {"timestamp": "2026-09-16T10:00:00Z", "q21": 8.4,
                       "operating_mode": "normal", "values": {"F1": 2.1, "P8": 0.12,
                                                                  "F31": 42.0, "T33": 271.0,
                                                                  "T55": 198.0}}


@pytest.mark.parametrize("event", [{}, {"source_timestamp": "x", "values": {}},
                                     {"timestamp": "x", "values": {"Q21": "bad"}}])
def test_decode_rejects_incomplete_event(event):
    with pytest.raises(InvalidTelemetryEvent):
        decode_event(event)
