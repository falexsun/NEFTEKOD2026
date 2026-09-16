"""
State detection for plant operation modes.
Identifies normal, shutdown, startup, transition, and unknown states.
"""
from enum import Enum
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd


class PlantState(Enum):
    """Operation state of the plant."""
    NORMAL = "normal"
    SHUTDOWN = "shutdown"
    STARTUP = "startup"
    TRANSITION = "transition"
    UNKNOWN = "unknown"


class StateDetector:
    """Detect operation state from telemetry."""

    def __init__(
        self,
        key_flow_tags: Optional[list] = None,
        key_temp_tags: Optional[list] = None,
        normal_flow_threshold: float = 0.3,
        normal_temp_threshold: float = 0.2
    ):
        """
        Initialize state detector.

        Args:
            key_flow_tags: List of critical flow measurement tags
            key_temp_tags: List of critical temperature tags
            normal_flow_threshold: Fraction of key flows that must be active
            normal_temp_threshold: Fraction of key temps in operating range
        """
        self.key_flow_tags = key_flow_tags or ["F31", "F30", "F19"]
        self.key_temp_tags = key_temp_tags or ["T33", "T55", "T11"]
        self.normal_flow_threshold = normal_flow_threshold
        self.normal_temp_threshold = normal_temp_threshold

        # Operating ranges learned from training data (placeholders)
        self.flow_ranges = {}
        self.temp_ranges = {}

    def detect(self, data: pd.DataFrame) -> Tuple[PlantState, Dict[str, float]]:
        """
        Detect current plant state.

        Args:
            data: Recent telemetry window

        Returns:
            Tuple of (state, confidence_scores)
        """
        if data.empty:
            return PlantState.UNKNOWN, {"unknown": 1.0}

        # Check for missing critical tags
        available_flows = [t for t in self.key_flow_tags if t in data.columns]
        available_temps = [t for t in self.key_temp_tags if t in data.columns]

        if not available_flows or not available_temps:
            return PlantState.UNKNOWN, {"missing_tags": 1.0}

        # Calculate activity metrics
        flow_activity = self._check_flow_activity(data, available_flows)
        temp_stability = self._check_temp_stability(data, available_temps)

        # State detection logic
        if flow_activity < 0.1:
            return PlantState.SHUTDOWN, {"flow_activity": flow_activity}

        if flow_activity > self.normal_flow_threshold and temp_stability > self.normal_temp_threshold:
            return PlantState.NORMAL, {
                "flow_activity": flow_activity,
                "temp_stability": temp_stability
            }

        # Check for startup pattern (increasing flow, unstable temps)
        if self._is_startup_pattern(data, available_flows, available_temps):
            return PlantState.STARTUP, {"pattern": "increasing_flow"}

        return PlantState.TRANSITION, {
            "flow_activity": flow_activity,
            "temp_stability": temp_stability
        }

    def _check_flow_activity(self, data: pd.DataFrame, flow_tags: list) -> float:
        """Calculate fraction of flows in normal operating range."""
        active_count = 0
        for tag in flow_tags:
            if tag not in data.columns:
                continue
            values = data[tag].dropna()
            if len(values) > 0:
                # Simple threshold: > 5th percentile of training data
                if values.iloc[-1] > 0.1:  # Placeholder threshold
                    active_count += 1

        return active_count / len(flow_tags) if flow_tags else 0.0

    def _check_temp_stability(self, data: pd.DataFrame, temp_tags: list) -> float:
        """Calculate temperature stability metric."""
        stable_count = 0
        for tag in temp_tags:
            if tag not in data.columns:
                continue
            values = data[tag].dropna()
            if len(values) > 1:
                # Check coefficient of variation
                cv = values.std() / (values.mean() + 1e-6)
                if cv < 0.05:  # Stable if CV < 5%
                    stable_count += 1

        return stable_count / len(temp_tags) if temp_tags else 0.0

    def _is_startup_pattern(self, data: pd.DataFrame, flow_tags: list, temp_tags: list) -> bool:
        """Detect startup pattern: increasing flows, variable temps."""
        if len(data) < 3:
            return False

        # Check for increasing trend in flows
        for tag in flow_tags[:1]:  # Check primary flow
            if tag not in data.columns:
                continue
            values = data[tag].dropna().values
            if len(values) >= 3:
                # Simple trend check
                if values[-1] > values[-2] > values[-3]:
                    return True

        return False
