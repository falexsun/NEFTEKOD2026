from datetime import datetime, timedelta, timezone
from src.api.flow_diagnostics import flow_diagnostics


def history():
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    points = [{"avt_F30": 100., "avt_W70": 78., "source_timestamps": {
        "avt": (now-timedelta(minutes=10*i)).isoformat()}}
        for i in reversed(range(144*10))]
    return now, points


def test_history_and_drift():
    now, points = history()
    normal = flow_diagnostics(points, now)
    assert normal['baseline_ready'] and normal['flow_stationary']
    assert normal['flowmeter_disagreement'] is False
    for point in points[-6:]:
        point['avt_W70'] = 90.
    drift = flow_diagnostics(points, now)
    assert drift['flowmeter_disagreement'] is True
    assert drift['density_proxy_kg_m3'] is None


def test_sparse_and_duplicate_history_not_baseline():
    now, points = history()
    sparse = points[::144]+[points[-1]]
    assert not flow_diagnostics(sparse, now)['baseline_ready']
    assert not flow_diagnostics([points[-1]]*2000, now)['baseline_ready']


def test_invalid_and_stale():
    now, points = history()
    points[-1]['avt_F30'] = 0
    assert flow_diagnostics(points, now)['w70_f30_ratio'] is None
    points[-1]['avt_F30'] = 100
    assert flow_diagnostics(points, now+timedelta(hours=1))['state'] == 'stale'
    points[-1]['source_timestamps']['avt'] = 'broken'
    assert flow_diagnostics(points, now)['state'] == 'unknown'
