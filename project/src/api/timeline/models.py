"""Timeline event models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


EventType = Literal[
    "q21_change",
    "forecast_generated",
    "alert_triggered",
    "parameter_change",
    "anomaly_detected",
    "operator_action",
    "model_prediction",
    "threshold_crossed",
]

EventSeverity = Literal["info", "warning", "critical"]


class TimelineEvent(BaseModel):
    """Timeline event model."""
    event_id: str
    timestamp: datetime
    event_type: EventType
    severity: EventSeverity
    title: str
    description: str
    data: dict[str, Any] = {}

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
