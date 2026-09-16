"""Operating permission from explicit source modes, never inferred from two flows."""
from datetime import datetime, timezone

MODES = {"normal": "Рабочий режим", "startup": "Пуск", "shutdown": "Останов",
         "transition": "Переходный режим", "unknown": "Не определён"}


def operating_policy(point: dict | None, now: datetime) -> dict:
    point = point or {}
    declarations = point.get("operating_modes") or {}
    timestamps = point.get("source_timestamps") or {}
    units, reasons = [], []
    for unit, title in (("avt", "АВТ"), ("u24", "24-2000")):
        mode = declarations.get(unit, "unknown")
        if mode not in MODES:
            mode = "unknown"
        raw = timestamps.get(unit)
        fresh = False
        try:
            ts = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
            if isinstance(ts, datetime):
                ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                fresh = -60 <= (now-ts).total_seconds() <= 900
        except ValueError:
            pass
        if not fresh:
            mode = "unknown"
        units.append({"id": unit, "label": title, "mode": mode, "mode_label": MODES[mode], "fresh": fresh})
        if mode != "normal":
            reasons.append(f"{title}: {MODES[mode].lower()}" + ("; нет свежего статуса" if not fresh else ""))
    modes = [unit["mode"] for unit in units]
    disposition = "ABSTAIN" if "unknown" in modes else "NO_ACTION" if reasons else "EVALUATE"
    return {"units": units, "disposition": disposition, "allowed": disposition == "EVALUATE",
            "reasons": reasons, "source": "ingestion_declaration",
            "description": "Режим передаётся источником телеметрии; устойчивость F30/W70 не определяет режим всей установки."}
