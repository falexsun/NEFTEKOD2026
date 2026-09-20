#!/usr/bin/env python3
"""Create an isolated LIMS-labelled challenger; never overwrite the champion."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import uuid

from catboost import CatBoostError

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from src.agents.quality.agent import _extract_feature_names_from_model
from src.api.runtime_store import RuntimeStore
from src.training.lims_retraining import build_lims_dataset, compare_challenger
from src.training.models import CatBoostModel, load_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a LIMS-labelled candidate without changing the deployed model")
    parser.add_argument("--champion-trained-through", required=True,
                        help="Documented UTC timestamp beyond the champion's training period")
    parser.add_argument("--target", choices=("lims_sulfur_avg", "lims_sulfur_md"), default="lims_sulfur_avg")
    parser.add_argument("--required-lims-field", action="append", default=[],
                        help="Additional lab indicator that must be present on each labelled result")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "sqlite:///data/neftekod.db"))
    parser.add_argument("--champion", type=Path, default=PROJECT / "models/catboost_champion.pkl")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "reports/lims_retraining")
    parser.add_argument("--until", help="UTC end timestamp; defaults to now")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.champion_trained_through.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        parser.error("--champion-trained-through must contain a UTC offset")
    cutoff = cutoff.astimezone(timezone.utc)
    until = datetime.fromisoformat(args.until.replace("Z", "+00:00")) if args.until else datetime.now(timezone.utc)
    if until.tzinfo is None:
        parser.error("--until must contain a UTC offset")
    until = until.astimezone(timezone.utc)
    if cutoff >= until:
        parser.error("Champion cutoff must precede the end of the training period")

    loaded = load_model(args.champion)
    if not isinstance(loaded, CatBoostModel):
        parser.error("The deployed legacy champion must be a CatBoostModel artifact")
    feature_names = _extract_feature_names_from_model(loaded)
    if not feature_names:
        parser.error("Champion feature schema is unavailable")
    champion_sha = hashlib.sha256(args.champion.read_bytes()).hexdigest()
    required_lims = [name if name.startswith("lims_") else f"lims_{name}" for name in args.required_lims_field]
    # A rolling window caps memory used by the wide feature matrix. Keep
    # enough lead-in history for the first eligible label in that window.
    window_start = max(cutoff, until - timedelta(days=90))
    store = RuntimeStore(args.database_url, initialize_schema=False)
    try:
        rows = store.training_telemetry(window_start - timedelta(hours=8), until)
    finally:
        store.engine.dispose()
    dataset = build_lims_dataset(rows, feature_names, target_key=args.target,
                                 champion_trained_through=cutoff,
                                 required_lims_fields=required_lims)
    report = {
        "status": "insufficient_data", "created_at": datetime.now(timezone.utc).isoformat(),
        "target": args.target, "horizon_minutes": 60,
        "training_window_from": window_start.isoformat(), "training_window_until": until.isoformat(),
        "champion_original_target": "PAK sulfur_mg_kg (one-hour forecast)",
        "candidate_target": f"LIMS {args.target} (one-hour forecast)",
        "target_changed_from_champion": True,
        "champion_sha256": champion_sha, "champion_trained_through": cutoff.isoformat(),
        "complete_lims_samples": len(dataset.labels), "rejected": dataset.rejected,
        "required_lims_fields": required_lims, "deployed_model_changed": False,
    }
    candidate = None
    try:
        candidate, evaluation = compare_challenger(loaded.model, dataset, iterations=args.iterations)
        report.update(evaluation)
        report["status"] = "evaluated"
    except (ValueError, CatBoostError) as exc:
        report["reason"] = str(exc)
        if isinstance(exc, CatBoostError):
            report["status"] = "training_failed"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    if candidate is not None:
        wrapper = CatBoostModel({"iterations": args.iterations})
        wrapper.model = candidate
        artifact = run_dir / "challenger.pkl"
        temporary = run_dir / "challenger.pkl.tmp"
        with temporary.open("wb") as handle:
            pickle.dump(wrapper, handle)
        temporary.replace(artifact)
        report["challenger_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    temporary_report = run_dir / "report.json.tmp"
    temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_report.replace(run_dir / "report.json")
    print(json.dumps({"run_dir": str(run_dir), **report}, ensure_ascii=False, indent=2))
    return 0 if candidate is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
