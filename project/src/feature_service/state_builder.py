"""StateBuilder — constructs ProcessState.

Two methods:
- build_state_from_row(): batch pipeline (from DataFrame row + column lists)
- build_state_from_runtime(): runtime API (from pre-normalized telemetry dicts)
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from src.shared.schemas.process_state import ProcessState, QualitySignal, SourceFreshness

logger = logging.getLogger(__name__)


class StateBuilder:
    """Builds ProcessState from telemetry + quality data."""

    def __init__(self, avt_cols: list[str] | None = None, u24_cols: list[str] | None = None):
        self.avt_cols = avt_cols or []
        self.u24_cols = u24_cols or []

    # ── Runtime method (no column lists needed) ──────────────────

    def build_state_from_runtime(
        self,
        timestamp: datetime,
        avt_telemetry: dict[str, float],
        unit_242000_telemetry: dict[str, float],
        quality: dict[str, QualitySignal] | None = None,
        avt_ts: datetime | None = None,
        u24_ts: datetime | None = None,
        lims_ts: datetime | None = None,
        decision_id: str | None = None,
    ) -> ProcessState:
        """Build ProcessState from pre-normalized canonical telemetry dicts.

        Telemetry keys must already be canonical (avt_T1, u24_T5).
        Quality signals are passed as-is (resolved by QualitySourceResolver).
        """
        freshness = SourceFreshness(
            avt_minutes=(timestamp - avt_ts).total_seconds() / 60 if avt_ts else None,
            unit_242000_minutes=(timestamp - u24_ts).total_seconds() / 60 if u24_ts else None,
            lims_minutes=(timestamp - lims_ts).total_seconds() / 60 if lims_ts else None,
        )

        return ProcessState(
            timestamp=timestamp,
            avt_telemetry=dict(avt_telemetry),
            unit_242000_telemetry=dict(unit_242000_telemetry),
            quality=dict(quality) if quality else {},
            source_freshness=freshness,
            decision_id=decision_id,
        )

    # ── Batch method (for training pipeline) ─────────────────────

    def build_state_from_row(
        self,
        row: pd.Series,
        timestamp: datetime,
        sulfur_value: float | None = None,
        sulfur_ts: datetime | None = None,
        density_value: float | None = None,
        density_ts: datetime | None = None,
        lims_values: dict[str, float] | None = None,
        lims_ts: datetime | None = None,
        avt_ts: datetime | None = None,
        u24_ts: datetime | None = None,
        decision_id: str | None = None,
    ) -> ProcessState:
        """Build ProcessState from a DataFrame row + column lists (batch mode)."""
        now = timestamp

        avt_telemetry = {}
        for col in self.avt_cols:
            if col in row.index and pd.notna(row[col]):
                avt_telemetry[col] = float(row[col])

        u24_telemetry = {}
        for col in self.u24_cols:
            if col in row.index and pd.notna(row[col]):
                u24_telemetry[col] = float(row[col])

        quality = {}
        if sulfur_value is not None and sulfur_ts is not None:
            age = (now - sulfur_ts).total_seconds() / 60
            quality["sulfur"] = QualitySignal(
                value=sulfur_value, source="PAK",
                measurement_timestamp=sulfur_ts, age_minutes=age,
                confidence=max(0.1, 1.0 - age / 120),
            )
        if density_value is not None and density_ts is not None:
            age = (now - density_ts).total_seconds() / 60
            quality["density_15"] = QualitySignal(
                value=density_value, source="PAK",
                measurement_timestamp=density_ts, age_minutes=age,
                confidence=max(0.1, 1.0 - age / 120),
            )
        if lims_values and lims_ts:
            for indicator, value in lims_values.items():
                if pd.notna(value):
                    age = (now - lims_ts).total_seconds() / 60
                    quality[indicator] = QualitySignal(
                        value=float(value), source="LIMS",
                        measurement_timestamp=lims_ts, age_minutes=age,
                        confidence=max(0.1, 1.0 - age / 1440),
                    )

        freshness = SourceFreshness(
            avt_minutes=(now - avt_ts).total_seconds() / 60 if avt_ts else None,
            unit_242000_minutes=(now - u24_ts).total_seconds() / 60 if u24_ts else None,
            lims_minutes=(now - lims_ts).total_seconds() / 60 if lims_ts else None,
            pak_sulfur_minutes=(now - sulfur_ts).total_seconds() / 60 if sulfur_ts else None,
            pak_density_minutes=(now - density_ts).total_seconds() / 60 if density_ts else None,
        )

        return ProcessState(
            timestamp=timestamp,
            avt_telemetry=avt_telemetry,
            unit_242000_telemetry=u24_telemetry,
            quality=quality,
            source_freshness=freshness,
            decision_id=decision_id,
        )

    # Alias for backward compatibility
    build_state = build_state_from_row
