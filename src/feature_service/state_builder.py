"""StateBuilder — constructs ProcessState from aligned data.

PROPERLY populates SourceFreshness with real values.
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from src.shared.schemas.process_state import ProcessState, QualitySignal, SourceFreshness

logger = logging.getLogger(__name__)


class StateBuilder:
    """Builds ProcessState objects from aligned telemetry + quality data."""

    def __init__(self, avt_cols: list[str], u24_cols: list[str]):
        self.avt_cols = avt_cols
        self.u24_cols = u24_cols

    def build_state(
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
        """Build a single ProcessState from a row of aligned data.

        Properly computes SourceFreshness for all sources.
        """
        now = timestamp

        # Extract AVT telemetry
        avt_telemetry = {}
        for col in self.avt_cols:
            if col in row.index and pd.notna(row[col]):
                avt_telemetry[col] = float(row[col])

        # Extract 24-2000 telemetry
        u24_telemetry = {}
        for col in self.u24_cols:
            if col in row.index and pd.notna(row[col]):
                u24_telemetry[col] = float(row[col])

        # Build quality signals
        quality = {}

        if sulfur_value is not None and sulfur_ts is not None:
            age = (now - sulfur_ts).total_seconds() / 60
            quality["sulfur"] = QualitySignal(
                value=sulfur_value,
                source="PAK",
                measurement_timestamp=sulfur_ts,
                age_minutes=age,
                confidence=max(0.1, 1.0 - age / 120),
            )

        if density_value is not None and density_ts is not None:
            age = (now - density_ts).total_seconds() / 60
            quality["density_15"] = QualitySignal(
                value=density_value,
                source="PAK",
                measurement_timestamp=density_ts,
                age_minutes=age,
                confidence=max(0.1, 1.0 - age / 120),
            )

        if lims_values and lims_ts:
            for indicator, value in lims_values.items():
                if pd.notna(value):
                    age = (now - lims_ts).total_seconds() / 60
                    quality[indicator] = QualitySignal(
                        value=float(value),
                        source="LIMS",
                        measurement_timestamp=lims_ts,
                        age_minutes=age,
                        confidence=max(0.1, 1.0 - age / 1440),
                    )

        # Build source freshness — PROPERLY POPULATED
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

    def build_feature_vector(self, row: pd.Series, feature_cols: list[str]) -> dict[str, float]:
        """Extract feature vector from a feature-engineered row."""
        vector = {}
        for col in feature_cols:
            if col in row.index and pd.notna(row[col]):
                vector[col] = float(row[col])
        return vector
