"""Build leakage-safe LIMS-labelled examples and evaluate a CatBoost challenger.

This module does not mutate the deployed champion. A lab result is a target only
after its sample timestamp, and features are taken from an earlier telemetry
origin at the model's forecast horizon.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
import warnings
from typing import Any, Sequence

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.feature_service.transformer import DOMAIN_FEATURES, FEATURE_KEY_COLUMNS, FeatureTransformer


_DERIVED = re.compile(r"_(?:lag\d+|r(?:mean|std|min|max)\d+|delta6?|slope\d+|missing)$")


@dataclass(frozen=True)
class LabelledDataset:
    features: pd.DataFrame
    labels: pd.Series
    origin_times: tuple[datetime, ...]
    lab_times: tuple[datetime, ...]
    rejected: dict[str, int]


def _utc(value: Any) -> datetime | None:
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return None
        return timestamp.to_pydatetime().replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.to_pydatetime().astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _source_time(row: dict[str, Any], source: str) -> datetime | None:
    stamps = row.get("source_timestamps") or {}
    return _utc(stamps.get(source)) if isinstance(stamps, dict) else None


def build_lims_dataset(
    rows: Sequence[dict[str, Any]], feature_names: Sequence[str], *,
    target_key: str, champion_trained_through: datetime,
    horizon_minutes: int = 60, cadence_minutes: int = 10,
    history_minutes: int = 360, origin_tolerance_minutes: int = 10,
    required_lims_fields: Sequence[str] = (),
) -> LabelledDataset:
    """Use only complete, post-champion lab samples with past-only features.

    The lab sample time comes from ``source_timestamps.lims``, not the API
    ingestion timestamp. Repeated publications of one sample count once.
    """
    if not target_key.startswith("lims_"):
        raise ValueError("The target must be an explicit LIMS indicator")
    cutoff = _utc(champion_trained_through)
    if cutoff is None:
        raise ValueError("A valid champion training cutoff is required")
    if horizon_minutes <= 0 or cadence_minutes <= 0 or history_minutes < cadence_minutes:
        raise ValueError("Invalid horizon, cadence or history duration")
    ordered = sorted(((ts, row) for row in rows if (ts := _utc(row.get("timestamp"))) is not None), key=lambda pair: pair[0])
    times = [ts for ts, _ in ordered]
    if len(times) != len(set(times)):
        raise ValueError("Duplicate telemetry timestamps are not valid training data")
    required_process = [name for name in feature_names if name.startswith(("avt_", "u24_"))
                        and not _DERIVED.search(name) and name not in DOMAIN_FEATURES]
    auxiliary_inputs = [name for name in feature_names if not name.startswith(("avt_", "u24_"))
                        and not _DERIVED.search(name)]
    derived_bases = [name for name in FEATURE_KEY_COLUMNS if any(
        feature == name or feature.startswith(name + "_") for feature in feature_names)]
    history_bases = set(required_process) | set(derived_bases)
    process_sources = {"avt" if name.startswith("avt_") else "u24" for name in history_bases}
    history_points = history_minutes // cadence_minutes + 1
    rejected: dict[str, int] = {}
    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    if not ordered:
        return LabelledDataset(pd.DataFrame(columns=feature_names), pd.Series(dtype=float), (), (), rejected)
    frame = pd.DataFrame([row for _, row in ordered], index=pd.DatetimeIndex(times))
    frame = frame.drop(columns=["timestamp", "source_timestamps", "operating_modes"], errors="ignore")
    for name in frame.columns:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    # The shared transformer intentionally builds a wide matrix column by
    # column. Pandas warns once per column about fragmentation; that is useful
    # for development, but would flood a scheduled training job's logs.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PerformanceWarning)
        transformed = FeatureTransformer().transform(frame)
    sample_records: dict[datetime, tuple[datetime, float]] = {}
    for ingested_at, row in ordered:
        label = row.get(target_key)
        if not _finite(label) or not 0 <= float(label) <= 50:
            continue
        source = row.get("source_timestamps") or {}
        lab_at = _utc(source.get("lims")) if isinstance(source, dict) else None
        if lab_at is None or lab_at > ingested_at:
            reject("invalid_lab_timestamp")
            continue
        if lab_at <= cutoff:
            reject("already_in_champion_period")
            continue
        if any(not _finite(row.get(field)) for field in required_lims_fields):
            reject("incomplete_lims_panel")
            continue
        previous = sample_records.get(lab_at)
        if previous is not None:
            if not math.isclose(previous[1], float(label), abs_tol=1e-6):
                raise ValueError(f"Conflicting LIMS results for sample {lab_at.isoformat()}")
            continue
        sample_records[lab_at] = (ingested_at, float(label))

    selected: list[dict[str, float]] = []
    labels: list[float] = []
    origins: list[datetime] = []
    labs: list[datetime] = []
    cadence = timedelta(minutes=cadence_minutes)
    for lab_at, (_, label) in sorted(sample_records.items()):
        target_origin = lab_at - timedelta(minutes=horizon_minutes)
        position = bisect_right(times, target_origin) - 1
        if position < history_points - 1 or target_origin - times[position] > timedelta(minutes=origin_tolerance_minutes):
            reject("missing_origin_or_history")
            continue
        window_times = times[position - history_points + 1:position + 1]
        if any(right - left != cadence for left, right in zip(window_times, window_times[1:])):
            reject("incomplete_cadence")
            continue
        window_rows = ordered[position - history_points + 1:position + 1]
        if any((source_at := _source_time(row, source)) is None or
               source_at > observed_at or observed_at - source_at > cadence
               for observed_at, row in window_rows for source in process_sources):
            reject("stale_process_source")
            continue
        origin_row = ordered[position][1]
        if any(not _finite(origin_row.get(name)) for name in required_process):
            reject("incomplete_process_snapshot")
            continue
        history_frame = frame.iloc[position - history_points + 1:position + 1]
        if any(name not in history_frame or not np.isfinite(history_frame[name].to_numpy(dtype=float)).all()
               for name in history_bases):
            reject("incomplete_process_history")
            continue
        # A repeated lab value is not fresh just because it appears in a new
        # telemetry row. Check the source's own measurement time, not merely
        # the row timestamp used by the feature transformer.
        def auxiliary_is_fresh(name: str) -> bool:
            if name not in frame:
                return False
            prior = frame[name].iloc[:position + 1].last_valid_index()
            if prior is None:
                return False
            source = "lims" if name.startswith("lims_") else "pak_density" if name == "density_15" else "pak"
            observed_at = prior.to_pydatetime().astimezone(timezone.utc)
            source_at = _source_time(ordered[bisect_right(times, observed_at) - 1][1], source)
            return (source_at is not None and source_at <= observed_at and
                    times[position] - source_at <= timedelta(hours=24))
        if any(not auxiliary_is_fresh(name) for name in auxiliary_inputs):
            reject("missing_prior_auxiliary_metric")
            continue
        if any(name not in transformed for name in feature_names):
            reject("feature_schema_mismatch")
            continue
        vector = transformed.iloc[position].loc[list(feature_names)]
        if not np.isfinite(vector.to_numpy(dtype=float)).all():
            reject("nonfinite_feature")
            continue
        selected.append({name: float(vector[name]) for name in feature_names})
        labels.append(label)
        origins.append(times[position])
        labs.append(lab_at)
    return LabelledDataset(pd.DataFrame(selected, columns=feature_names), pd.Series(labels, dtype=float),
                           tuple(origins), tuple(labs), rejected)


def compare_challenger(
    champion: CatBoostRegressor, dataset: LabelledDataset, *, iterations: int = 100,
    min_samples: int = 30, holdout_fraction: float = 0.2, min_improvement: float = 0.02,
) -> tuple[CatBoostRegressor, dict[str, Any]]:
    """Adapt the PAK-trained model to LIMS; compare on a later LIMS holdout."""
    count = len(dataset.labels)
    holdout = max(10, math.ceil(count * holdout_fraction))
    if count < min_samples or count - holdout < 20:
        raise ValueError(f"Need >= {min_samples} complete new LIMS samples (>=20 train, >=10 holdout); got {count}")
    if iterations < 1 or not 0 < holdout_fraction < 0.5:
        raise ValueError("Invalid training iterations or holdout fraction")
    split = count - holdout
    # Purge samples whose lab result was not yet known at the first holdout
    # feature origin. Splitting solely by lab timestamp can still leak here.
    first_holdout_origin = dataset.origin_times[split]
    train_end = next((index for index in range(split) if dataset.lab_times[index] >= first_holdout_origin), split)
    if train_end < 20:
        raise ValueError(f"Only {train_end} training samples remain after the temporal embargo; need >=20")
    train_x, test_x = dataset.features.iloc[:train_end], dataset.features.iloc[split:]
    train_y, test_y = dataset.labels.iloc[:train_end], dataset.labels.iloc[split:]
    model = CatBoostRegressor(iterations=iterations, learning_rate=0.03, loss_function="RMSE",
                              random_seed=42, verbose=False, allow_writing_files=False)
    model.fit(train_x, train_y, init_model=champion, verbose=False)
    current_pred = np.asarray(champion.predict(test_x), dtype=float)
    candidate_pred = np.asarray(model.predict(test_x), dtype=float)
    old_mae = float(mean_absolute_error(test_y, current_pred))
    new_mae = float(mean_absolute_error(test_y, candidate_pred))
    old_rmse = float(math.sqrt(mean_squared_error(test_y, current_pred)))
    new_rmse = float(math.sqrt(mean_squared_error(test_y, candidate_pred)))
    violations = test_y.to_numpy() >= 10
    risk_evaluable = int(violations.sum()) >= 3 and int((~violations).sum()) >= 3
    old_missed = int(np.sum(violations & (current_pred < 10)))
    new_missed = int(np.sum(violations & (candidate_pred < 10)))
    improvement = (old_mae - new_mae) / old_mae if old_mae > 0 else 0.0
    gate = improvement >= min_improvement and new_rmse <= old_rmse and new_missed <= old_missed
    report = {
        "train_samples": train_end, "holdout_samples": holdout,
        "embargoed_samples": split - train_end,
        "train_lab_until": dataset.lab_times[train_end - 1].isoformat(),
        "holdout_lab_from": dataset.lab_times[split].isoformat(),
        "champion_mae": old_mae, "challenger_mae": new_mae,
        "champion_rmse": old_rmse, "challenger_rmse": new_rmse,
        "mae_improvement_fraction": improvement,
        "holdout_exceedances": int(violations.sum()),
        "risk_gate_evaluable": risk_evaluable,
        "champion_missed_exceedances": old_missed,
        "challenger_missed_exceedances": new_missed,
        "quality_gate_passed": bool(gate),
        "eligible_for_manual_promotion": bool(gate and risk_evaluable),
        "reason": "Holdout needs at least 3 exceedances and 3 non-exceedances for a safety check" if not risk_evaluable
                  else "Candidate passed holdout gates" if gate else "Candidate failed holdout gates",
    }
    return model, report
