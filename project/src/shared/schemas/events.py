"""Event envelope for Redis Streams."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
import uuid


class EventEnvelope(BaseModel):
    """Standard event wrapper for all Redis Stream events."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    event_timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_timestamp: datetime | None = None
    schema_version: str = "1.0"
    correlation_id: str | None = None
    decision_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
