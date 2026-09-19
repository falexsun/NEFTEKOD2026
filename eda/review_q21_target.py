"""Review time-split Q21-target experiment and audit the Q21=307 code."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

import train_q21_target_a100 as engine


def main(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    out = root / "eda" / "experiments" / args.run_id
    frame, feature_sets = engine.prepare(root)
    cls = pd.read_csv(out / "classification_metrics.csv")

    # Freeze one model per horizon using validation AP only.
    selected = (
        cls[cls.split.eq("validation")]
        .sort_values(["horizon_h", "ap"], ascending=[True, False])
        .groupby("horizon_h", as_index=False)
        .first()
    )
    selected.to_csv(out / "selected_on_validation.csv", index=False)

    sensitivity_rows = []
    importance_rows = []
    baseline_rows = []
    for row in selected.itertuples(index=False):
        horizon = int(row.horizon_h)
        steps = horizon * 6
        d = frame.copy()
        d["target_time"] = d.index + pd.Timedelta(hours=horizon)
        d["y"] = d.Q21_target.shift(-steps)
        d = d.iloc[:-steps].copy()
        masks = engine.split_masks(d.target_time)
        columns = feature_sets[row.feature_set]
        medians = d.loc[masks["train"], columns].median().fillna(0)
        x = d[columns].fillna(medians)
        model = CatBoostClassifier()
        model.load_model(str(out / "models" / f"{row.model}.cbm"))

        for split in ["calibration", "evaluation"]:
            base = masks[split] & (d.y >= 0).to_numpy()
            p = model.predict_proba(x.loc[base])[:, 1]
            actual = d.loc[base, "y"].to_numpy()
            for population, keep in {
                "all_nonnegative": np.ones(len(actual), dtype=bool),
                "exclude_307": actual != 307,
                "normal_0_50": (actual >= 0) & (actual <= 50),
            }.items():
                y = actual[keep] > 10
                pp = p[keep]
                sensitivity_rows.append({
                    "model": row.model, "horizon_h": horizon, "feature_set": row.feature_set,
                    "split": split, "population": population, "n": len(y), "prevalence": y.mean(),
                    "ap": average_precision_score(y, pp), "roc_auc": roc_auc_score(y, pp),
                    "brier": brier_score_loss(y, pp),
                })

        # Recalibrate asymmetric thresholds after treating 307 as unknown.
        calibration = masks["calibration"] & d.y.between(0, 50).to_numpy()
        evaluation = masks["evaluation"] & d.y.between(0, 50).to_numpy()
        pc = model.predict_proba(x.loc[calibration])[:, 1]
        pe = model.predict_proba(x.loc[evaluation])[:, 1]
        yc = (d.loc[calibration, "y"].to_numpy() > 10)
        ye = (d.loc[evaluation, "y"].to_numpy() > 10)
        for penalty in [5, 10, 25, 50]:
            chosen = engine.choose_threshold(yc, pc, penalty)
            threshold = chosen["threshold"]
            alarm = pe >= threshold
            tp = int((alarm & ye).sum()); fp = int((alarm & ~ye).sum())
            fn = int((~alarm & ye).sum()); tn = int((~alarm & ~ye).sum())
            sensitivity_rows.append({
                "model": row.model, "horizon_h": horizon, "feature_set": row.feature_set,
                "split": "evaluation_threshold", "population": f"exclude_307_penalty_{penalty}",
                "n": len(ye), "prevalence": ye.mean(), "threshold": threshold,
                "recall": tp / max(1, tp + fn), "precision": tp / max(1, tp + fp),
                "fpr": fp / max(1, fp + tn), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "cost": (penalty * fn + fp) / len(ye),
            })

        for name, value in zip(columns, model.get_feature_importance()):
            importance_rows.append({"model": row.model, "horizon_h": horizon, "feature": name, "importance": value})

        # Honest persistence baseline: Q21 at origin predicts future Q21.
        evaluation = masks["evaluation"] & (d.y >= 0).to_numpy()
        actual = d.loc[evaluation, "y"].to_numpy()
        current = d.loc[evaluation, "Q21_target"].to_numpy()
        valid_reg = (actual <= 50) & (current >= 0) & (current <= 50)
        yb = actual > 10
        baseline_rows.append({
            "horizon_h": horizon, "n": len(actual), "prevalence": yb.mean(),
            "persistence_mae_0_50": np.mean(np.abs(actual[valid_reg] - current[valid_reg])),
            "persistence_ap": average_precision_score(yb, current),
            "persistence_roc_auc": roc_auc_score(yb, current),
            "persistence_recall_at_10": np.mean((current > 10)[yb]),
            "persistence_fpr_at_10": np.mean((current > 10)[~yb]),
        })

    pd.DataFrame(sensitivity_rows).to_csv(out / "q21_307_sensitivity.csv", index=False)
    pd.DataFrame(importance_rows).sort_values(["model", "importance"], ascending=[True, False]).to_csv(out / "selected_feature_importance.csv", index=False)
    pd.DataFrame(baseline_rows).to_csv(out / "persistence_baseline.csv", index=False)
    (out / "REVIEW_COMPLETE.json").write_text(json.dumps({"status": "complete", "selected_models": selected.model.tolist()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id", default="q21_target_asymmetric_v3_20260915")
    main(parser.parse_args())
