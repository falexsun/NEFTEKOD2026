"""Small-sample cetane experiment with AVT density proxy and SHAP pruning.

Only 42 LIMS targets exist. Results are diagnostic and must not be presented as
production validation. Feature selection uses validation; 2026 stays evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import mean_absolute_error, mean_squared_error

from forensics_utils import parse_lims


def write_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    temp.replace(path)


def feature_frame(root: Path) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    hydro_path = root / "data" / "242000_tags.csv"
    avt_path = root / "data" / "avt_tags.csv"
    lims_path = next((root / "docs").glob("ЛИМС*.xlsx"))

    hydro = pd.read_csv(hydro_path, parse_dates=["date"]).set_index("date").sort_index()
    hydro = hydro.drop(columns=[c for c in hydro if c.startswith("Unnamed:")]).astype(float)
    process_parts = [hydro.add_suffix("_now")]
    for hours in [24, 72]:
        roll = hydro.rolling(f"{hours}h", min_periods=hours * 3)
        process_parts.extend([
            roll.mean().add_suffix(f"_mean_{hours}h"),
            roll.std().add_suffix(f"_std_{hours}h"),
            (hydro - hydro.shift(hours * 6)).add_suffix(f"_change_{hours}h"),
        ])
    process = pd.concat(process_parts, axis=1).astype("float32")

    avt = pd.read_csv(avt_path, usecols=["date", "F30", "W70"], parse_dates=["date"]).set_index("date").sort_index()
    density = 1000.0 * avt.W70 / avt.F30
    density = density.mask((avt.F30 <= 10) | (avt.W70 <= 0) | ~np.isfinite(density))
    density_features = pd.DataFrame({"density_proxy_now": density})
    for hours in [24, 48, 72]:
        density_features[f"density_proxy_lag_{hours}h"] = density.shift(hours * 6)
    for hours in [24, 72, 168]:
        roll = density.rolling(f"{hours}h", min_periods=hours * 3)
        density_features[f"density_proxy_mean_{hours}h"] = roll.mean()
        density_features[f"density_proxy_std_{hours}h"] = roll.std()
    density_features = density_features.astype("float32")

    labs = parse_lims(lims_path)
    labs = labs[
        (labs.installation == "Гидроочистка")
        & (labs.sampling_point == "2")
        & (labs.quality_parameter == "CetaneNumber")
    ][["timestamp", "value"]].groupby("timestamp", as_index=False).value.median().sort_values("timestamp")
    labs["previous_cetane"] = labs.value.shift(1)
    labs["previous3_cetane_median"] = labs.value.shift(1).rolling(3, min_periods=1).median()
    labs["days_since_previous_lims"] = labs.timestamp.diff().dt.total_seconds().div(86400)
    labs["days_from_start"] = (labs.timestamp - labs.timestamp.min()).dt.total_seconds().div(86400)

    data = pd.merge_asof(
        labs, process.reset_index(), left_on="timestamp", right_on="date",
        direction="backward", tolerance=pd.Timedelta("10min"),
    ).drop(columns=["date"])
    data = pd.merge_asof(
        data.sort_values("timestamp"), density_features.reset_index(), left_on="timestamp", right_on="date",
        direction="backward", tolerance=pd.Timedelta("10min"),
    ).drop(columns=["date"])
    history = ["previous_cetane", "previous3_cetane_median", "days_since_previous_lims", "days_from_start"]
    process_cols = list(process.columns)
    density_cols = list(density_features.columns)
    return data, history, process_cols, density_cols


def fit_model(x_train, y_train, x_validation, y_validation, seed: int, iterations: int):
    model = CatBoostRegressor(
        iterations=iterations, depth=4, learning_rate=0.025, l2_leaf_reg=20,
        random_strength=2, loss_function="MAE", eval_metric="MAE",
        task_type="GPU", devices="0", gpu_ram_part=0.35, random_seed=seed,
        verbose=False, allow_writing_files=False,
    )
    model.fit(x_train, y_train, eval_set=(x_validation, y_validation), early_stopping_rounds=180)
    return model


def metric_row(model, data, x, mask, variant, seed, split):
    prediction = model.predict(x.loc[mask])
    actual = data.loc[mask, "value"].to_numpy()
    return {
        "variant": variant, "seed": seed, "split": split, "n": len(actual), "trees": model.tree_count_,
        "mae": mean_absolute_error(actual, prediction),
        "rmse": mean_squared_error(actual, prediction) ** 0.5,
        "bias": float(np.mean(prediction - actual)),
        "actual_below_scenario_51": int(np.sum(actual < 51)),
        "predicted_below_scenario_51": int(np.sum(prediction < 51)),
    }, prediction


def main(args):
    root = args.root.resolve()
    out = root / "eda" / "experiments" / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "models").mkdir()
    started = time.time()
    data, history, process_cols, density_cols = feature_frame(root)
    data.to_csv(out / "matched_cetane_features.csv", index=False)
    masks = {
        "train": data.timestamp < "2025-01-01",
        "validation": (data.timestamp >= "2025-01-01") & (data.timestamp < "2026-01-01"),
        "evaluation": data.timestamp >= "2026-01-01",
    }
    sets = {
        "history_only": history,
        "process_no_density": history + process_cols,
        "process_plus_density": history + process_cols + density_cols,
        "density_history_only": history + density_cols,
    }
    write_json(out / "manifest.json", {
        "target": "LIMS hydrotreater point 2 CetaneNumber", "n": len(data),
        "split_counts": {k: int(v.sum()) for k, v in masks.items()},
        "feature_counts": {k: len(v) for k, v in sets.items()},
        "density_proxy": "1000*W70/F30; invalid when F30<=10 or W70<=0",
        "scenario_lower_limit": 51,
        "limitations": "Only 42 targets; reservoir park breaks known direct AVT-hydro lag; 51 is scenario, not organizer-confirmed product specification.",
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'data/242000_tags.csv', root/'data/avt_tags.csv', next((root/'docs').glob('ЛИМС*.xlsx'))]},
    })

    rows, predictions, shap_rows, selection_rows = [], [], [], []
    for seed in args.seeds:
        fitted = {}
        matrices = {}
        medians = {}
        for variant, columns in sets.items():
            med = data.loc[masks["train"], columns].median().fillna(0)
            x = data[columns].fillna(med).astype("float32")
            model = fit_model(x.loc[masks["train"]], data.loc[masks["train"], "value"], x.loc[masks["validation"]], data.loc[masks["validation"], "value"], seed, args.iterations)
            fitted[variant], matrices[variant], medians[variant] = model, x, med
            model.save_model(str(out / "models" / f"{variant}_s{seed}.cbm"))
            for split in ["validation", "evaluation"]:
                metric, pred = metric_row(model, data, x, masks[split], variant, seed, split)
                rows.append(metric)
                predictions.append(pd.DataFrame({"timestamp": data.loc[masks[split], "timestamp"], "actual": data.loc[masks[split], "value"], "prediction": pred, "variant": variant, "seed": seed, "split": split}))

        full_variant = "process_plus_density"
        full_model, full_x = fitted[full_variant], matrices[full_variant]
        shap = full_model.get_feature_importance(Pool(full_x.loc[masks["validation"]], data.loc[masks["validation"], "value"]), type="ShapValues")[:, :-1]
        ranking = pd.Series(np.abs(shap).mean(axis=0), index=full_x.columns).sort_values(ascending=False)
        for rank, (feature, importance) in enumerate(ranking.items(), 1):
            shap_rows.append({"seed": seed, "rank": rank, "feature": feature, "mean_abs_shap": importance, "is_density_proxy": feature in density_cols})

        for top_k in [5, 10, 20]:
            columns = list(ranking.head(top_k).index)
            variant = f"shap_top_{top_k}"
            med = data.loc[masks["train"], columns].median().fillna(0)
            x = data[columns].fillna(med).astype("float32")
            model = fit_model(x.loc[masks["train"]], data.loc[masks["train"], "value"], x.loc[masks["validation"]], data.loc[masks["validation"], "value"], seed, args.iterations)
            model.save_model(str(out / "models" / f"{variant}_s{seed}.cbm"))
            for split in ["validation", "evaluation"]:
                metric, pred = metric_row(model, data, x, masks[split], variant, seed, split)
                rows.append(metric)
                predictions.append(pd.DataFrame({"timestamp": data.loc[masks[split], "timestamp"], "actual": data.loc[masks[split], "value"], "prediction": pred, "variant": variant, "seed": seed, "split": split}))

        current = pd.DataFrame(rows)
        candidates = current[(current.seed == seed) & (current.split == "validation")]
        winner = candidates.sort_values(["mae", "variant"]).iloc[0]
        selection_rows.append({"seed": seed, "selected_variant": winner.variant, "validation_mae": winner.mae})
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)
        pd.concat(predictions, ignore_index=True).to_csv(out / "predictions.csv", index=False)
        pd.DataFrame(shap_rows).to_csv(out / "shap_importance.csv", index=False)
        pd.DataFrame(selection_rows).to_csv(out / "selected_on_validation.csv", index=False)
        print("finished seed", seed, "winner", winner.variant, flush=True)

    # Last-observation and train-median baselines.
    baseline = []
    for split in ["validation", "evaluation"]:
        m = masks[split]
        actual = data.loc[m, "value"]
        for name, pred in {
            "previous_lims": data.loc[m, "previous_cetane"],
            "train_median": pd.Series(data.loc[masks["train"], "value"].median(), index=actual.index),
        }.items():
            baseline.append({"variant": name, "split": split, "n": len(actual), "mae": mean_absolute_error(actual, pred), "rmse": mean_squared_error(actual, pred) ** .5})
    pd.DataFrame(baseline).to_csv(out / "baselines.csv", index=False)

    status = {"status": "complete", "elapsed_seconds": time.time() - started, "models": len(args.seeds) * 7, "targets": len(data)}
    write_json(out / "COMPLETE.json", status)
    print(json.dumps(status), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id", default="cetane_density_shap_20260915")
    parser.add_argument("--iterations", type=int, default=1800)
    parser.add_argument("--seeds", type=int, nargs="+", default=[17, 42, 101, 2026, 3407, 77, 314, 999, 2025, 2718])
    main(parser.parse_args())
