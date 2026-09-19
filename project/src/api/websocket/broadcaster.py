"""WebSocket broadcast functions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .manager import manager


async def broadcast_q21_update(
    q21_current: float,
    q21_forecast: float | None,
    exceedance_probability: float | None,
    risk_level: str,
    mae: float | None,
    coverage: float | None,
    timestamp: datetime,
):
    """Broadcast Q21 update to all connected clients."""
    message = {
        "type": "q21_update",
        "timestamp": timestamp.isoformat(),
        "data": {
            "q21_current": q21_current,
            "q21_forecast_1h": q21_forecast,
            "exceedance_probability": exceedance_probability,
            "risk_level": risk_level,
            "shadow_mae": mae,
            "shadow_coverage": coverage,
        }
    }
    await manager.broadcast(message)


async def broadcast_alert(
    alert_type: str,
    severity: str,
    message: str,
    data: dict[str, Any] | None = None,
):
    """Broadcast alert to all connected clients."""
    alert_message = {
        "type": "alert",
        "timestamp": datetime.utcnow().isoformat(),
        "alert": {
            "type": alert_type,
            "severity": severity,
            "message": message,
            "data": data or {},
        }
    }
    await manager.broadcast(alert_message)


async def broadcast_event(
    event_type: str,
    description: str,
    data: dict[str, Any] | None = None,
):
    """Broadcast event to timeline."""
    event_message = {
        "type": "timeline_event",
        "timestamp": datetime.utcnow().isoformat(),
        "event": {
            "event_type": event_type,
            "description": description,
            "data": data or {},
        }
    }
    await manager.broadcast(event_message)
