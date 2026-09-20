"""Persistent operational audit and telemetry storage.

SQLite is the safe zero-configuration default for local development. Production
uses the same schema through PostgreSQL by setting ``DATABASE_URL``.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint, create_engine, desc, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stored_utc(value: datetime) -> datetime:
    """Restore UTC metadata stripped by SQLite's datetime round trip."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class TelemetryPoint(Base):
    __tablename__ = "telemetry_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recommendation_type: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="runtime")
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Q21Point(Base):
    __tablename__ = "q21_points"
    __table_args__ = (UniqueConstraint("timestamp", name="uq_q21_point_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    operating_mode: Mapped[str] = mapped_column(String(24), index=True)
    q21: Mapped[float] = mapped_column(Float)
    values: Mapped[dict[str, Any]] = mapped_column(JSON)


class Q21Forecast(Base):
    __tablename__ = "q21_forecasts"
    __table_args__ = (UniqueConstraint("origin_timestamp", "horizon_hours", name="uq_q21_forecast_origin_horizon"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[str] = mapped_column(String(64), index=True)
    origin_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    horizon_hours: Mapped[float] = mapped_column(Float)
    predicted_q21: Mapped[float] = mapped_column(Float)
    lower_q21: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_q21: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_q21: Mapped[float | None] = mapped_column(Float, nullable=True)
    absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_sha256: Mapped[str] = mapped_column(String(64))


class RuntimeStore:
    """Small synchronous repository used from the FastAPI runtime."""

    def __init__(self, database_url: str, *, initialize_schema: bool = True):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self._lock = threading.RLock()
        if initialize_schema:
            Base.metadata.create_all(self.engine)
        logger.info("Runtime store connected: %s", self.engine.url.render_as_string(hide_password=True))

    def append_telemetry(self, timestamp: datetime, payload: dict[str, Any]) -> None:
        with self._lock, self.Session.begin() as session:
            session.add(TelemetryPoint(timestamp=timestamp, payload=payload))

    def recent_telemetry(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(TelemetryPoint).order_by(desc(TelemetryPoint.timestamp)).limit(limit)
            ).all()
        return [{"timestamp": _stored_utc(row.timestamp), **row.payload} for row in reversed(rows)]

    def telemetry_since(self, since: datetime, until: datetime) -> list[dict]:
        with self.Session() as session:
            rows = session.scalars(select(TelemetryPoint).where(
                TelemetryPoint.timestamp >= since, TelemetryPoint.timestamp <= until
            ).order_by(desc(TelemetryPoint.timestamp)).limit(10000)).all()
        return [{"timestamp": _stored_utc(row.timestamp), **row.payload} for row in reversed(rows)]

    def training_telemetry(self, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """Read the complete bounded period; inference's 10k-point cap is unsafe here."""
        if since >= until:
            raise ValueError("Training period must have a positive duration")
        with self.Session() as session:
            rows = session.scalars(select(TelemetryPoint).where(
                TelemetryPoint.timestamp >= since, TelemetryPoint.timestamp <= until
            ).order_by(TelemetryPoint.timestamp)).all()
        return [{"timestamp": _stored_utc(row.timestamp), **row.payload} for row in rows]

    def save_decision(
        self,
        decision_id: str,
        timestamp: datetime,
        recommendation_type: str,
        payload: dict[str, Any],
        request_id: str,
        actor: str,
    ) -> None:
        with self._lock, self.Session.begin() as session:
            session.add(DecisionRecord(
                decision_id=decision_id,
                timestamp=timestamp,
                recommendation_type=recommendation_type,
                payload=payload,
                request_id=request_id,
                actor=actor,
            ))

    def decisions(self, limit: int = 50, recommendation_type: str | None = None) -> list[dict[str, Any]]:
        query = select(DecisionRecord)
        if recommendation_type is not None:
            query = query.where(DecisionRecord.recommendation_type == recommendation_type)
        with self.Session() as session:
            rows = session.scalars(
                query.order_by(desc(DecisionRecord.timestamp)).limit(limit)
            ).all()
        return [
            {
                "decision_id": row.decision_id,
                "timestamp": _stored_utc(row.timestamp),
                "recommendation_type": row.recommendation_type,
                "actor": row.actor,
                "request_id": row.request_id,
                "data": row.payload,
            }
            for row in rows
        ]

    def latest_decision(self, recommendation_type: str | None = None) -> dict[str, Any] | None:
        rows = self.decisions(limit=1, recommendation_type=recommendation_type)
        return rows[0] if rows else None

    def decision_by_request_id(self, request_id: str) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(
                select(DecisionRecord).where(DecisionRecord.request_id == request_id).limit(1)
            )
        if row is None:
            return None
        return {
            "decision_id": row.decision_id,
            "timestamp": _stored_utc(row.timestamp),
            "recommendation_type": row.recommendation_type,
            "actor": row.actor,
            "request_id": row.request_id,
            "data": row.payload,
        }

    def append_q21_point(self, timestamp: datetime, operating_mode: str, q21: float,
                         values: dict[str, float]) -> bool:
        with self._lock, self.Session.begin() as session:
            existing = session.scalar(select(Q21Point.id).where(Q21Point.timestamp == timestamp).limit(1))
            if existing is not None:
                return False
            session.add(Q21Point(timestamp=timestamp, operating_mode=operating_mode, q21=q21, values=values))
        return True

    def recent_q21_points(self, limit: int = 145) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(select(Q21Point).order_by(desc(Q21Point.timestamp)).limit(limit)).all()
        return [{"timestamp": _stored_utc(row.timestamp), "Q21": row.q21, "operating_mode": row.operating_mode,
                 **row.values} for row in reversed(rows)]

    def resolve_q21_outcomes(self, timestamp: datetime, actual_q21: float) -> int:
        with self._lock, self.Session.begin() as session:
            rows = session.scalars(select(Q21Forecast).where(
                Q21Forecast.target_timestamp == timestamp, Q21Forecast.actual_q21.is_(None)
            )).all()
            for row in rows:
                row.actual_q21 = actual_q21
                row.absolute_error = abs(row.predicted_q21 - actual_q21)
            return len(rows)

    def save_q21_forecasts(self, forecast_id: str, origin: datetime, forecasts: list[dict[str, Any]],
                           interval: dict[str, float] | None, checksums: dict[float, str]) -> None:
        from datetime import timedelta
        with self._lock, self.Session.begin() as session:
            for item in forecasts:
                horizon = float(item["horizon_hours"])
                session.add(Q21Forecast(
                    forecast_id=forecast_id, origin_timestamp=origin,
                    target_timestamp=origin + timedelta(hours=horizon), horizon_hours=horizon,
                    predicted_q21=float(item["q21"]),
                    lower_q21=float(interval["lower"]) if interval and horizon == 1.0 else None,
                    upper_q21=float(interval["upper"]) if interval and horizon == 1.0 else None,
                    model_sha256=checksums[horizon],
                ))

    def latest_q21_forecast(self) -> dict[str, Any] | None:
        with self.Session() as session:
            origin = session.scalar(select(Q21Forecast.origin_timestamp).order_by(desc(Q21Forecast.origin_timestamp)).limit(1))
            if origin is None:
                return None
            rows = session.scalars(select(Q21Forecast).where(Q21Forecast.origin_timestamp == origin)
                                   .order_by(Q21Forecast.horizon_hours)).all()
        return {"origin_timestamp": _stored_utc(origin), "forecast_id": rows[0].forecast_id,
                "forecasts": [{"horizon_hours": row.horizon_hours, "target_timestamp": _stored_utc(row.target_timestamp),
                               "q21": row.predicted_q21, "lower": row.lower_q21, "upper": row.upper_q21,
                               "actual": row.actual_q21, "absolute_error": row.absolute_error}
                              for row in rows]}

    def q21_shadow_metrics(self, limit: int = 5000) -> dict[str, Any]:
        with self.Session() as session:
            rows = session.scalars(select(Q21Forecast).where(Q21Forecast.actual_q21.is_not(None))
                                   .order_by(desc(Q21Forecast.target_timestamp)).limit(limit)).all()
        by_horizon: dict[float, list[Q21Forecast]] = {}
        for row in rows:
            by_horizon.setdefault(row.horizon_hours, []).append(row)
        return {"resolved": len(rows), "by_horizon": [{
            "horizon_hours": horizon, "n": len(items),
            "mae": sum(item.absolute_error or 0 for item in items) / len(items),
            "interval_coverage": (sum(item.lower_q21 <= item.actual_q21 <= item.upper_q21 for item in items
                                      if item.lower_q21 is not None and item.upper_q21 is not None) /
                                  max(1, sum(item.lower_q21 is not None and item.upper_q21 is not None for item in items)))
                                 if any(item.lower_q21 is not None for item in items) else None,
        } for horizon, items in sorted(by_horizon.items())]}
