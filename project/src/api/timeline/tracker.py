"""Timeline event tracker."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .models import TimelineEvent, EventType, EventSeverity


class TimelineTracker:
    """Track events for timeline visualization."""

    def __init__(self, max_events: int = 1000):
        self.events: list[TimelineEvent] = []
        self.max_events = max_events

    def add_event(
        self,
        event_type: EventType,
        severity: EventSeverity,
        title: str,
        description: str,
        data: dict[str, Any] | None = None,
    ) -> TimelineEvent:
        """Add event to timeline."""
        import uuid

        event = TimelineEvent(
            event_id=str(uuid.uuid4())[:8],
            timestamp=datetime.utcnow(),
            event_type=event_type,
            severity=severity,
            title=title,
            description=description,
            data=data or {},
        )

        self.events.append(event)

        # Keep only recent events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        return event

    def get_recent_events(
        self,
        limit: int = 50,
        since: datetime | None = None,
        event_types: list[EventType] | None = None,
        min_severity: EventSeverity | None = None,
    ) -> list[TimelineEvent]:
        """Get recent events with optional filters."""
        filtered = self.events

        if since:
            filtered = [e for e in filtered if e.timestamp >= since]

        if event_types:
            filtered = [e for e in filtered if e.event_type in event_types]

        if min_severity:
            severity_order = {"info": 0, "warning": 1, "critical": 2}
            min_level = severity_order[min_severity]
            filtered = [e for e in filtered if severity_order[e.severity] >= min_level]

        # Return most recent first
        return sorted(filtered, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_events_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[TimelineEvent]:
        """Get events in time range."""
        return [
            e for e in self.events
            if start <= e.timestamp <= end
        ]

    def get_root_cause_chain(
        self,
        target_timestamp: datetime,
        window_minutes: int = 60,
    ) -> list[TimelineEvent]:
        """Get chain of events leading to a specific moment."""
        start = target_timestamp - timedelta(minutes=window_minutes)
        chain = self.get_events_range(start, target_timestamp)

        # Sort chronologically
        return sorted(chain, key=lambda e: e.timestamp)

    def clear(self):
        """Clear all events."""
        self.events.clear()

    @property
    def event_count(self) -> int:
        """Get total event count."""
        return len(self.events)


# Global timeline tracker
_timeline = TimelineTracker()


def get_timeline() -> TimelineTracker:
    """Get global timeline tracker."""
    return _timeline
