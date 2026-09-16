from datetime import datetime, timedelta, timezone

import pytest

from src.api.operating_policy import operating_policy


@pytest.mark.parametrize("mode,disposition", [
    ("normal", "EVALUATE"), ("startup", "NO_ACTION"),
    ("shutdown", "NO_ACTION"), ("transition", "NO_ACTION"),
    ("unknown", "ABSTAIN"), ("invalid", "ABSTAIN"),
])
def test_declared_modes(mode, disposition):
    now = datetime.now(timezone.utc)
    result = operating_policy({"operating_modes": {"avt": mode, "u24": "normal"},
                               "source_timestamps": {"avt": now.isoformat(), "u24": now}}, now)
    assert result["disposition"] == disposition
    assert result["allowed"] == (disposition == "EVALUATE")


@pytest.mark.parametrize("age", [901, -61])
def test_stale_or_future_status_blocks_normal_mode(age):
    now = datetime.now(timezone.utc)
    result = operating_policy({"operating_modes": {"avt": "normal", "u24": "normal"},
                               "source_timestamps": {"avt": now - timedelta(seconds=age), "u24": now}}, now)
    assert result["disposition"] == "ABSTAIN"
    assert not result["units"][0]["fresh"]


def test_missing_mode_does_not_assume_normal():
    assert operating_policy(None, datetime.now(timezone.utc))["disposition"] == "ABSTAIN"
