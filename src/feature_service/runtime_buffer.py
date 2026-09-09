"""RuntimeFeatureBuffer — uses shared FeatureTransformer for feature construction.

Stores history, builds full model schema, checks readiness by duration + coverage.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd

from src.feature_service.transformer import FeatureTransformer

logger = logging.getLogger(__name__)


class RuntimeFeatureBuffer:
    """Maintains history buffer and builds full feature vectors using shared FeatureTransformer."""

    def __init__(self, max_history: int = 100, min_duration_minutes: float = 360,
                 min_points: int = 36, expected_interval_minutes: float = 10):
        self.max_history = max_history
        self.min_duration_minutes = min_duration_minutes
        self.min_points = min_points
        self.expected_interval_minutes = expected_interval_minutes
        self._history: deque[dict] = deque(maxlen=max_history)
        self._df: pd.DataFrame | None = None
        self._transformer = FeatureTransformer()

    @property
    def history_size(self) -> int:
        return len(self._history)

    @property
    def history_duration_minutes(self) -> float:
        if len(self._history) < 2:
            return 0.0
        first = self._history[0].get("timestamp")
        last = self._history[-1].get("timestamp")
        if first and last:
            return (last - first).total_seconds() / 60
        return 0.0

    @property
    def history_ready(self) -> bool:
        """History has enough points AND temporal coverage."""
        return (self.history_size >= self.min_points
                and self.history_duration_minutes >= self.min_duration_minutes)

    def push(self, timestamp: datetime, avt: dict[str, float], u24: dict[str, float],
             pak_sulfur: float | None = None, pak_density: float | None = None,
             lims: dict[str, float] | None = None):
        row = {"timestamp": timestamp}
        row.update(avt)
        row.update(u24)
        if pak_sulfur is not None:
            row["sulfur_mg_kg"] = pak_sulfur
        if pak_density is not None:
            row["density_15"] = pak_density
        if lims:
            for k, v in lims.items():
                row[f"lims_{k}"] = v
        self._history.append(row)
        self._df = None

    def build_feature_vector(self, expected_features: list[str]) -> tuple[dict[str, float] | None, str | None]:
        """Build feature vector using shared FeatureTransformer."""
        if not self.history_ready:
            return None, f"History not ready: {self.history_size} pts, {self.history_duration_minutes:.0f} min"

        df = self._to_dataframe()
        if df is None:
            return None, "Failed to build DataFrame"

        # Use shared transformer — same as training
        features_df = self._transformer.transform(df)
        if features_df is None or features_df.empty:
            return None, "Feature transformation failed"

        last_row = features_df.iloc[-1]
        vector = {}
        missing = []
        for name in expected_features:
            if name in last_row.index and pd.notna(last_row[name]):
                vector[name] = float(last_row[name])
            else:
                missing.append(name)

        if missing:
            return None, f"Missing {len(missing)} features: {missing[:5]}..."

        return vector, None

    def _to_dataframe(self) -> pd.DataFrame | None:
        if self._df is not None:
            return self._df
        if not self._history:
            return None
        df = pd.DataFrame(list(self._history))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        self._df = df
        return df
