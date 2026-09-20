from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from src.training.lims_retraining import LabelledDataset, build_lims_dataset, compare_challenger


def _rows(count: int = 85):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        timestamp = start + timedelta(minutes=10 * index)
        rows.append({"timestamp": timestamp, "avt_T1": 150.0 + index / 10,
                     "source_timestamps": {"avt": timestamp.isoformat(), "u24": timestamp.isoformat(), "lims": None}})
    return rows


def test_lims_example_uses_only_prior_complete_feature_history():
    rows = _rows()
    sample = rows[60]["timestamp"]
    rows[60].update(lims_sulfur_avg=8.7, source_timestamps={**rows[60]["source_timestamps"], "lims": sample.isoformat()})
    rows[61].update(lims_sulfur_avg=8.7, source_timestamps={**rows[61]["source_timestamps"], "lims": sample.isoformat()})
    dataset = build_lims_dataset(rows, ["avt_T1", "avt_T1_lag1"], target_key="lims_sulfur_avg",
                                 champion_trained_through=rows[0]["timestamp"])
    assert len(dataset.labels) == 1
    assert dataset.lab_times == (sample,)
    assert dataset.origin_times == (rows[54]["timestamp"],)
    assert dataset.features.iloc[0].to_dict() == {"avt_T1": 155.4, "avt_T1_lag1": 155.3}


def test_lims_example_rejects_incomplete_history_and_unverified_timestamp():
    rows = _rows()
    rows[54]["avt_T1"] = None
    rows[60].update(lims_sulfur_avg=8.7, source_timestamps={**rows[60]["source_timestamps"], "lims": rows[60]["timestamp"].isoformat()})
    rows[70].update(lims_sulfur_avg=8.8, source_timestamps={**rows[70]["source_timestamps"], "lims": None})
    dataset = build_lims_dataset(rows, ["avt_T1", "avt_T1_lag1"], target_key="lims_sulfur_avg",
                                 champion_trained_through=rows[0]["timestamp"])
    assert len(dataset.labels) == 0
    assert dataset.rejected["incomplete_process_snapshot"] == 1
    assert dataset.rejected["invalid_lab_timestamp"] == 1


def test_missing_prior_auxiliary_metric_is_not_silently_imputed():
    rows = _rows()
    sample = rows[60]["timestamp"]
    rows[60].update(lims_sulfur_avg=8.7, source_timestamps={**rows[60]["source_timestamps"], "lims": sample.isoformat()})
    missing = build_lims_dataset(rows, ["avt_T1", "density_15"], target_key="lims_sulfur_avg",
                                 champion_trained_through=rows[0]["timestamp"])
    assert missing.rejected["missing_prior_auxiliary_metric"] == 1
    rows[53]["density_15"] = 840.0
    rows[53]["source_timestamps"]["pak_density"] = rows[53]["timestamp"].isoformat()
    complete = build_lims_dataset(rows, ["avt_T1", "density_15"], target_key="lims_sulfur_avg",
                                  champion_trained_through=rows[0]["timestamp"])
    assert len(complete.labels) == 1
    assert complete.features.iloc[0]["density_15"] == 840.0


def test_repeated_lab_value_does_not_make_old_source_fresh():
    rows = _rows()
    sample = rows[60]["timestamp"]
    rows[60].update(lims_sulfur_avg=8.7, source_timestamps={**rows[60]["source_timestamps"], "lims": sample.isoformat()})
    for row in rows[:55]:
        row["density_15"] = 840.0
        row["source_timestamps"]["pak_density"] = (rows[0]["timestamp"] - timedelta(days=2)).isoformat()
    dataset = build_lims_dataset(rows, ["avt_T1", "density_15"], target_key="lims_sulfur_avg",
                                 champion_trained_through=rows[0]["timestamp"])
    assert dataset.rejected["missing_prior_auxiliary_metric"] == 1


def test_stale_process_source_rejects_complete_looking_history():
    rows = _rows()
    sample = rows[60]["timestamp"]
    rows[60].update(lims_sulfur_avg=8.7, source_timestamps={**rows[60]["source_timestamps"], "lims": sample.isoformat()})
    rows[30]["source_timestamps"]["avt"] = rows[20]["timestamp"].isoformat()
    dataset = build_lims_dataset(rows, ["avt_T1", "avt_T1_lag1"], target_key="lims_sulfur_avg",
                                 champion_trained_through=rows[0]["timestamp"])
    assert dataset.rejected["stale_process_source"] == 1


def test_challenger_is_evaluated_on_later_holdout_without_auto_promotion():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    features = pd.DataFrame({"avt_T1": np.linspace(145, 155, 40)})
    labels = pd.Series(8 + np.linspace(0, 1, 40))
    times = tuple(start + timedelta(hours=index) for index in range(40))
    dataset = LabelledDataset(features, labels, times, times, {})
    champion = CatBoostRegressor(iterations=10, verbose=False, allow_writing_files=False)
    champion.fit(features.iloc[:20], labels.iloc[:20])
    candidate, report = compare_challenger(champion, dataset, iterations=5)
    assert candidate.tree_count_ > champion.tree_count_
    assert report["train_samples"] == 30
    assert report["holdout_samples"] == 10
    assert report["holdout_lab_from"] == times[30].isoformat()
    assert report["risk_gate_evaluable"] is False
    assert report["eligible_for_manual_promotion"] is False  # no >10 ppm cases to validate safety


def test_temporal_embargo_excludes_label_known_after_holdout_origin():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    features = pd.DataFrame({"avt_T1": np.linspace(145, 155, 40)})
    labels = pd.Series(8 + np.linspace(0, 1, 40))
    labs = tuple(start + timedelta(hours=index) for index in range(40))
    origins = tuple(lab - timedelta(hours=1) for lab in labs)
    champion = CatBoostRegressor(iterations=10, verbose=False, allow_writing_files=False)
    champion.fit(features.iloc[:20], labels.iloc[:20])
    _, report = compare_challenger(champion, LabelledDataset(features, labels, origins, labs, {}), iterations=5)
    assert report["train_samples"] == 29
    assert report["embargoed_samples"] == 1
    assert report["train_lab_until"] < report["holdout_lab_from"]
