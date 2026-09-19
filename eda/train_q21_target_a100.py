"""Train Q21 sulfur surrogate and exceedance-risk models on an NVIDIA GPU.

Q21 is the target and is excluded from every input feature.  The experiment is
time-split.  Thresholds are selected on calibration only; 2026 is evaluation.
The asymmetric decision cost is for downstream operating recommendations and
does not replace forecast accuracy metrics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, mean_absolute_error, roc_auc_score


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    tmp.replace(path)


def pinball(y: np.ndarray, p: np.ndarray, alpha: float) -> float:
    error = y - p
    return float(np.mean(np.maximum(alpha * error, (alpha - 1) * error)))


def prepare(root: Path) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    source = root / "data" / "242000_tags.csv"
    raw = pd.read_csv(source, parse_dates=["date"]).set_index("date").sort_index()
    raw = raw.drop(columns=[c for c in raw if c.startswith("Unnamed:")]).astype(float)
    assert raw.index.is_unique
    assert (raw.index.to_series().diff().dropna() == pd.Timedelta(minutes=10)).all()

    target = raw["Q21"].copy()
    process = raw.drop(columns=["Q21"]).replace([np.inf, -np.inf], np.nan)
    features = process.add_suffix("_now")
    for hours in [1, 3, 6, 12, 24]:
        shift = hours * 6
        roll = process.rolling(f"{hours}h", min_periods=shift)
        features = features.join(roll.mean().add_suffix(f"_mean_{hours}h"))
        features = features.join(roll.std().add_suffix(f"_std_{hours}h"))
        features = features.join((process - process.shift(shift)).add_suffix(f"_change_{hours}h"))
    features = features.astype("float32")

    # For future horizons, current/past Q21 is a legitimate state signal rather
    # than the future target. Keep the off-scale code separate from its value.
    q_clean = target.mask((target < 0) | (target > 50))
    q_history = pd.DataFrame(
        {"Q21_origin": q_clean, "Q21_invalid_or_offscale": ((target < 0) | (target > 50)).astype("float32")},
        index=raw.index,
    )
    for hours in [1, 3, 6, 12, 24]:
        shift = hours * 6
        roll = q_clean.rolling(f"{hours}h", min_periods=shift)
        q_history[f"Q21_past_mean_{hours}h"] = roll.mean()
        q_history[f"Q21_past_std_{hours}h"] = roll.std()
        q_history[f"Q21_past_change_{hours}h"] = q_clean - q_clean.shift(shift)
    features = features.join(q_history.astype("float32"))
    q_columns = list(q_history.columns)
    process_columns = [c for c in features if c not in q_columns]
    controls = [c for c in process_columns if c.split("_", 1)[0] in {"P8", "T11", "F19"}]
    sets = {
        "all_no_q21": process_columns,
        "no_q21_no_f25": [c for c in process_columns if not c.startswith("F25_")],
        "control_candidates": controls,
        "q21_history_only": q_columns,
        "controls_plus_q21_history": controls + q_columns,
        "all_plus_q21_history": process_columns + q_columns,
    }
    frame = features.copy()
    frame["Q21_target"] = target
    frame.index.name = "origin_time"
    return frame, sets


def split_masks(target_time: pd.Series) -> dict[str, np.ndarray]:
    return {
        "train": (target_time < pd.Timestamp("2025-01-01")).to_numpy(),
        "validation": ((target_time >= pd.Timestamp("2025-01-04")) & (target_time < pd.Timestamp("2025-07-01"))).to_numpy(),
        "calibration": ((target_time >= pd.Timestamp("2025-07-04")) & (target_time < pd.Timestamp("2026-01-01"))).to_numpy(),
        "evaluation": (target_time >= pd.Timestamp("2026-01-04")).to_numpy(),
    }


def classifier_metrics(y: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    return {
        "n": int(len(y)),
        "prevalence": float(y.mean()),
        "ap": float(average_precision_score(y, probability)),
        "roc_auc": float(roc_auc_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "logloss": float(log_loss(y, probability, labels=[0, 1])),
    }


def choose_threshold(y: np.ndarray, probability: np.ndarray, fn_penalty: float) -> dict[str, float]:
    best = None
    for threshold in np.linspace(0, 1, 1001):
        alarm = probability >= threshold
        fn = int(((~alarm) & y).sum())
        fp = int((alarm & (~y)).sum())
        cost = (fn_penalty * fn + fp) / len(y)
        candidate = (cost, fn, fp, -threshold)
        if best is None or candidate < best[0]:
            best = (candidate, threshold, alarm)
    _, threshold, alarm = best
    tp = int((alarm & y).sum())
    tn = int(((~alarm) & (~y)).sum())
    fn = int(((~alarm) & y).sum())
    fp = int((alarm & (~y)).sum())
    return {
        "fn_penalty": fn_penalty,
        "threshold": float(threshold),
        "cost_per_observation": float((fn_penalty * fn + fp) / len(y)),
        "recall": float(tp / max(1, tp + fn)),
        "precision": float(tp / max(1, tp + fp)),
        "fpr": float(fp / max(1, fp + tn)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def main(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    out = root / "eda" / "experiments" / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "models").mkdir()
    started = time.time()
    frame, feature_sets = prepare(root)
    source = root / "data" / "242000_tags.csv"
    manifest = {
        "run_id": args.run_id,
        "started_utc": utc(),
        "python": platform.python_version(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "target": "Q21 sulfur in kerosene, ppm",
        "future_target_removed_from_features": True,
        "current_and_past_q21_variants": ["q21_history_only", "controls_plus_q21_history", "all_plus_q21_history"],
        "horizons_hours": args.horizons,
        "feature_sets": {key: len(value) for key, value in feature_sets.items()},
        "decision_objective": "J(q)=max(10-q,0)^2 + lambda*max(q-10,0)^2; lambda in [5,10,25,50]",
        "warning": "Predictive observational model. It does not identify causal effects of operator actions.",
    }
    write_json(out / "manifest.json", manifest)

    regression_rows: list[dict] = []
    classifier_rows: list[dict] = []
    threshold_rows: list[dict] = []
    importance_rows: list[dict] = []

    for horizon in args.horizons:
        steps = int(horizon * 6)
        d = frame.copy()
        d["target_time"] = d.index + pd.Timedelta(hours=horizon)
        d["y"] = d["Q21_target"].shift(-steps)
        d = d.iloc[:-steps].copy()
        masks = split_masks(d["target_time"])

        for feature_set, columns in feature_sets.items():
            medians = d.loc[masks["train"], columns].median().fillna(0)
            x = d[columns].fillna(medians)

            # Continuous target: code 307 and negative values are handled as
            # invalid/off-scale for regression, while classification reports a
            # sensitivity analysis with and without 307.
            valid_reg = d.y.between(0, 50).to_numpy()
            for alpha in [0.5, 0.8, 0.9]:
                train = masks["train"] & valid_reg
                validation = masks["validation"] & valid_reg
                calibration = masks["calibration"] & valid_reg
                evaluation = masks["evaluation"] & valid_reg
                model = CatBoostRegressor(
                    iterations=args.iterations,
                    depth=7,
                    learning_rate=0.04,
                    l2_leaf_reg=10,
                    random_strength=1,
                    border_count=128,
                    loss_function=f"Quantile:alpha={alpha}",
                    eval_metric=f"Quantile:alpha={alpha}",
                    task_type="GPU",
                    devices="0",
                    gpu_ram_part=0.82,
                    random_seed=42,
                    verbose=False,
                    allow_writing_files=False,
                )
                model.fit(x.loc[train], d.loc[train, "y"], eval_set=(x.loc[validation], d.loc[validation, "y"]), early_stopping_rounds=150)
                stem = f"reg_h{horizon}_{feature_set}_q{int(alpha*100)}"
                model.save_model(str(out / "models" / f"{stem}.cbm"))
                for split_name, mask in [("validation", validation), ("calibration", calibration), ("evaluation", evaluation)]:
                    y = d.loc[mask, "y"].to_numpy()
                    pred = model.predict(x.loc[mask])
                    regression_rows.append({
                        "model": stem, "horizon_h": horizon, "feature_set": feature_set, "alpha": alpha,
                        "split": split_name, "n": len(y), "trees": model.tree_count_,
                        "mae": mean_absolute_error(y, pred), "pinball": pinball(y, pred, alpha),
                        "underprediction_rate": float(np.mean(pred < y)),
                        "violation_underprediction_rate": float(np.mean(pred[y > 10] < y[y > 10])) if np.any(y > 10) else np.nan,
                    })
                for name, value in zip(columns, model.get_feature_importance()):
                    importance_rows.append({"model": stem, "kind": "regression", "feature": name, "importance": float(value)})

            # Classification target includes 307 as a conservative exceedance.
            valid_cls = (d.y >= 0).to_numpy()
            y_binary = (d.y > 10).to_numpy()
            for seed in [17, 42, 2026]:
                train = masks["train"] & valid_cls
                validation = masks["validation"] & valid_cls
                calibration = masks["calibration"] & valid_cls
                evaluation = masks["evaluation"] & valid_cls
                model = CatBoostClassifier(
                    iterations=args.iterations,
                    depth=7,
                    learning_rate=0.04,
                    l2_leaf_reg=10,
                    random_strength=1,
                    border_count=128,
                    loss_function="Logloss",
                    # AP is calculated after fitting. Logloss keeps per-tree
                    # early-stopping evaluation on GPU instead of CPU PRAUC.
                    eval_metric="Logloss",
                    class_weights=[1, 10],
                    task_type="GPU",
                    devices="0",
                    gpu_ram_part=0.82,
                    random_seed=seed,
                    verbose=False,
                    allow_writing_files=False,
                )
                model.fit(x.loc[train], y_binary[train], eval_set=(x.loc[validation], y_binary[validation]), early_stopping_rounds=150)
                stem = f"risk_h{horizon}_{feature_set}_s{seed}"
                model.save_model(str(out / "models" / f"{stem}.cbm"))
                probabilities = {}
                for split_name, mask in [("validation", validation), ("calibration", calibration), ("evaluation", evaluation)]:
                    probability = model.predict_proba(x.loc[mask])[:, 1]
                    probabilities[split_name] = probability
                    metrics = classifier_metrics(y_binary[mask], probability)
                    classifier_rows.append({"model": stem, "horizon_h": horizon, "feature_set": feature_set, "seed": seed, "split": split_name, "trees": model.tree_count_, **metrics})
                for fn_penalty in [5, 10, 25, 50]:
                    calibrated = choose_threshold(y_binary[calibration], probabilities["calibration"], fn_penalty)
                    threshold = calibrated["threshold"]
                    alarm = probabilities["evaluation"] >= threshold
                    y_eval = y_binary[evaluation]
                    tp = int((alarm & y_eval).sum()); fp = int((alarm & ~y_eval).sum())
                    fn = int((~alarm & y_eval).sum()); tn = int((~alarm & ~y_eval).sum())
                    threshold_rows.append({
                        "model": stem, "horizon_h": horizon, "feature_set": feature_set, "seed": seed,
                        "fn_penalty": fn_penalty, "threshold": threshold,
                        "calibration_cost": calibrated["cost_per_observation"],
                        "evaluation_cost": (fn_penalty * fn + fp) / len(y_eval),
                        "evaluation_recall": tp / max(1, tp + fn), "evaluation_precision": tp / max(1, tp + fp),
                        "evaluation_fpr": fp / max(1, fp + tn), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                    })
                for name, value in zip(columns, model.get_feature_importance()):
                    importance_rows.append({"model": stem, "kind": "classifier", "feature": name, "importance": float(value)})

            pd.DataFrame(regression_rows).to_csv(out / "regression_metrics.csv", index=False)
            pd.DataFrame(classifier_rows).to_csv(out / "classification_metrics.csv", index=False)
            pd.DataFrame(threshold_rows).to_csv(out / "asymmetric_threshold_metrics.csv", index=False)
            pd.DataFrame(importance_rows).to_csv(out / "feature_importance.csv", index=False)
            write_json(out / "status.json", {"phase": "training", "horizon": horizon, "feature_set": feature_set, "updated_utc": utc()})
            print(utc(), "finished", horizon, feature_set, flush=True)

    status = {"status": "complete", "finished_utc": utc(), "elapsed_minutes": (time.time() - started) / 60,
              "regression_models": len(set(r["model"] for r in regression_rows)),
              "classifier_models": len(set(r["model"] for r in classifier_rows))}
    write_json(out / "COMPLETE.json", status)
    write_json(out / "status.json", status)
    print(json.dumps(status, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id", default="q21_target_asymmetric_20260915")
    parser.add_argument("--horizons", type=int, nargs="+", default=[1, 3, 6])
    parser.add_argument("--iterations", type=int, default=1600)
    main(parser.parse_args())
