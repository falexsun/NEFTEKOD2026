"""Predict cetane change from the previous LIMS value; density/SHAP ablation."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import Pool
from sklearn.metrics import mean_absolute_error, mean_squared_error

import train_cetane_density_shap_a100 as base


def main(args):
    root = args.root.resolve()
    out = root / "eda" / "experiments" / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "models").mkdir()
    started = time.time()
    data, history, process_cols, density_cols = base.feature_frame(root)
    data = data[data.previous_cetane.notna()].reset_index(drop=True)
    data["delta"] = data.value - data.previous_cetane
    masks = {
        "train": data.timestamp < "2025-01-01",
        "validation": (data.timestamp >= "2025-01-01") & (data.timestamp < "2026-01-01"),
        "evaluation": data.timestamp >= "2026-01-01",
    }
    sets = {
        "residual_history_only": history,
        "residual_process_no_density": history + process_cols,
        "residual_process_plus_density": history + process_cols + density_cols,
        "residual_density_history_only": history + density_cols,
    }
    base.write_json(out / "manifest.json", {
        "target": "CetaneNumber minus previous CetaneNumber",
        "split_counts": {k: int(v.sum()) for k, v in masks.items()},
        "feature_counts": {k: len(v) for k, v in sets.items()},
        "density_proxy": "1000*W70/F30",
        "selection": "SHAP ranking and variant choice on validation; 2026 evaluation untouched",
    })
    rows, predictions, shap_rows, selected = [], [], [], []
    for seed in args.seeds:
        fitted = {}
        matrices = {}
        for variant, columns in sets.items():
            median = data.loc[masks["train"], columns].median().fillna(0)
            x = data[columns].fillna(median).astype("float32")
            model = base.fit_model(x.loc[masks["train"]], data.loc[masks["train"], "delta"], x.loc[masks["validation"]], data.loc[masks["validation"], "delta"], seed, args.iterations)
            fitted[variant], matrices[variant] = model, x
            model.save_model(str(out / "models" / f"{variant}_s{seed}.cbm"))
            for split in ["validation", "evaluation"]:
                correction = model.predict(x.loc[masks[split]])
                prediction = data.loc[masks[split], "previous_cetane"].to_numpy() + correction
                actual = data.loc[masks[split], "value"].to_numpy()
                rows.append({"variant": variant, "seed": seed, "split": split, "n": len(actual), "trees": model.tree_count_, "mae": mean_absolute_error(actual, prediction), "rmse": mean_squared_error(actual, prediction) ** .5, "bias": float(np.mean(prediction-actual))})
                predictions.append(pd.DataFrame({"timestamp":data.loc[masks[split],"timestamp"],"actual":actual,"previous_lims":data.loc[masks[split],"previous_cetane"],"prediction":prediction,"correction":correction,"variant":variant,"seed":seed,"split":split}))

        full_variant = "residual_process_plus_density"
        model, x = fitted[full_variant], matrices[full_variant]
        shap = model.get_feature_importance(Pool(x.loc[masks["validation"]], data.loc[masks["validation"], "delta"]), type="ShapValues")[:, :-1]
        ranking = pd.Series(np.abs(shap).mean(axis=0), index=x.columns).sort_values(ascending=False)
        for rank, (feature, importance) in enumerate(ranking.items(), 1):
            shap_rows.append({"seed":seed,"rank":rank,"feature":feature,"mean_abs_shap":importance,"is_density_proxy":feature in density_cols})
        for k in [5,10,20]:
            columns=list(ranking.head(k).index); variant=f"residual_shap_top_{k}"
            median=data.loc[masks["train"],columns].median().fillna(0); xx=data[columns].fillna(median).astype("float32")
            model=base.fit_model(xx.loc[masks["train"]],data.loc[masks["train"],"delta"],xx.loc[masks["validation"]],data.loc[masks["validation"],"delta"],seed,args.iterations)
            model.save_model(str(out/"models"/f"{variant}_s{seed}.cbm"))
            for split in ["validation","evaluation"]:
                correction=model.predict(xx.loc[masks[split]]); previous=data.loc[masks[split],"previous_cetane"].to_numpy(); actual=data.loc[masks[split],"value"].to_numpy(); prediction=previous+correction
                rows.append({"variant":variant,"seed":seed,"split":split,"n":len(actual),"trees":model.tree_count_,"mae":mean_absolute_error(actual,prediction),"rmse":mean_squared_error(actual,prediction)**.5,"bias":float(np.mean(prediction-actual))})
                predictions.append(pd.DataFrame({"timestamp":data.loc[masks[split],"timestamp"],"actual":actual,"previous_lims":previous,"prediction":prediction,"correction":correction,"variant":variant,"seed":seed,"split":split}))
        current=pd.DataFrame(rows); candidate=current[(current.seed==seed)&current.split.eq("validation")].sort_values(["mae","variant"]).iloc[0]
        selected.append({"seed":seed,"selected_variant":candidate.variant,"validation_mae":candidate.mae})
        pd.DataFrame(rows).to_csv(out/"metrics.csv",index=False);pd.concat(predictions,ignore_index=True).to_csv(out/"predictions.csv",index=False);pd.DataFrame(shap_rows).to_csv(out/"shap_importance.csv",index=False);pd.DataFrame(selected).to_csv(out/"selected_on_validation.csv",index=False)
        print("finished",seed,candidate.variant,flush=True)
    prediction_frame = pd.concat(predictions, ignore_index=True)
    interval_rows = []
    for (variant, seed), group in prediction_frame.groupby(["variant", "seed"]):
        calibration = group[group.split.eq("validation")]
        evaluation = group[group.split.eq("evaluation")]
        residual = np.abs(calibration.actual - calibration.prediction).to_numpy()
        rank = min(len(residual), int(np.ceil((len(residual) + 1) * 0.9)))
        halfwidth = float(np.sort(residual)[rank - 1])
        alarm = (evaluation.prediction - halfwidth) < 51
        violation = evaluation.actual < 51
        interval_rows.append({"variant":variant,"seed":seed,"halfwidth90":halfwidth,"coverage90":float(np.mean(np.abs(evaluation.actual-evaluation.prediction)<=halfwidth)),"alarms":int(alarm.sum()),"tp":int((alarm&violation).sum()),"fp":int((alarm&~violation).sum()),"fn":int((~alarm&violation).sum())})
    pd.DataFrame(interval_rows).to_csv(out/"scenario_51_intervals.csv",index=False)
    base.write_json(out/"COMPLETE.json",{"status":"complete","elapsed_seconds":time.time()-started,"models":len(args.seeds)*7})


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument("--run-id",default="cetane_residual_density_shap_20260915");parser.add_argument("--iterations",type=int,default=1800);parser.add_argument("--seeds",type=int,nargs="+",default=[17,42,101,2026,3407,77,314,999,2025,2718]);main(parser.parse_args())
