"""Diagnostic ratio only: no changes to model features or control policies."""
from datetime import datetime, timezone, timedelta
from math import isfinite
from statistics import median


def _stamp(point):
    raw = (point.get("source_timestamps") or {}).get("avt")
    try:
        ts = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if not isinstance(ts, datetime):
            return None
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    except ValueError:
        return None


def _stable(window):
    # Diagnostic assumptions, not industrial operating limits.
    return all((max(p[key] for _, p in window) - min(p[key] for _, p in window))
               / median(p[key] for _, p in window) <= .05 for key in ("avt_F30", "avt_W70"))


def _history(points, now, result):
    unique = {}
    for point in points:
        ts = _stamp(point)
        if ts and now - timedelta(days=30) <= ts <= now and all(
            isinstance(point.get(key), (int, float)) and isfinite(point[key]) and point[key] > 0
            for key in ("avt_F30", "avt_W70")
        ):
            unique[ts] = point
    ordered = sorted(unique.items())
    stable = []
    current_stable = None
    for i, (ts, point) in enumerate(ordered):
        window = ordered[max(0, i-5):i+1]
        covered = len(window) == 6 and 40*60 <= (ts-window[0][0]).total_seconds() <= 60*60
        covered = covered and all((b[0]-a[0]).total_seconds() <= 15*60 for a,b in zip(window, window[1:]))
        flag = _stable(window) if covered else None
        if i == len(ordered)-1:
            current_stable = flag
        if flag and ts < now-timedelta(hours=1):
            stable.append((ts, point["avt_W70"]/point["avt_F30"]))
    result["flow_stationary"] = current_stable
    # At most one contribution per 10-minute interval; dense bursts cannot
    # masquerade as seven days of baseline observations.
    bins = {int(ts.timestamp()//600): ratio for ts, ratio in stable}
    days = {}
    for slot in bins:
        day = slot // 144
        days[day] = days.get(day, 0)+1
    qualified = {day for day, count in days.items() if count >= 100}
    baseline = [ratio for slot, ratio in bins.items() if slot//144 in qualified]
    result.update(baseline_days=len(qualified), baseline_points=len(baseline))
    if len(qualified) < 7:
        result["reason"] = "Недостаточно истории: нужны 7 дней устойчивых расходов с покрытием не менее 70%"
        return
    center = median(baseline)
    mad = median(abs(v-center) for v in baseline)
    # Floor prevents division by zero for flat history; 1% is an explicit
    # engineering diagnostic assumption, not calibrated metrology.
    scale = max(1.4826*mad, abs(center)*.01)
    result.update(baseline_median=center, baseline_ready=True)
    if current_stable is not True:
        result["reason"] = "Расходы меняются или не хватает часовой истории: сравнение приостановлено"
        return
    score = (result["w70_f30_ratio"]-center)/scale
    alert = abs(score) > 3.5
    result.update(density_proxy_robust_z=score, flowmeter_disagreement=alert,
                  state="warning" if alert else "attention",
                  reason="Отношение расходов отклонилось от истории: проверьте состав потока и датчики" if alert else "Отношение согласуется с историей; единицы плотности не подтверждены")


def flow_diagnostics(points: list[dict], now: datetime) -> dict:
    result = {
        "state": "unknown", "reason": "Нет парных измерений F30 и W70",
        "w70_f30_ratio": None, "density_proxy_kg_m3": None,
        "density_proxy_valid": False, "units_confirmed": False,
        "timestamp": None, "f30": None, "w70": None,
        "flowmeter_disagreement": None,
        "flow_stationary": None, "baseline_ready": False,
        "baseline_days": 0, "baseline_points": 0,
        "baseline_median": None, "density_proxy_robust_z": None,
        "note": "Единицы не подтверждены. Proxy не является измерением плотности товарного ДТ.",
    }
    if not points:
        return result
    latest = points[-1]
    result.update(f30=latest.get("avt_F30"), w70=latest.get("avt_W70"))
    stamp = (latest.get("source_timestamps") or {}).get("avt")
    result["timestamp"] = stamp
    f30, w70 = result["f30"], result["w70"]
    if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (f30, w70)):
        return result
    if f30 <= 0 or w70 <= 0:
        result.update(state="warning", reason="Нулевой или отрицательный расход: отношение не рассчитывается")
        return result
    if not stamp:
        result["reason"] = "Нет времени измерения АВТ"
        return result
    ts = _stamp(latest)
    if ts is None:
        result.update(timestamp=None, reason="Некорректное время измерения АВТ")
        return result
    age = (now - ts).total_seconds()
    if age < -60 or age > 900:
        result.update(state="stale", reason="Время измерения некорректно или данные старше 15 минут")
        return result
    result.update(w70_f30_ratio=w70 / f30, state="attention",
                  reason="Отношение доступно; стационарность и единицы требуют подтверждения")
    _history(points, now, result)
    return result
