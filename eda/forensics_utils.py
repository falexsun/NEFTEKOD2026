"""Parsers and forensic checks for the Neftekod reference workbooks."""

from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


def parse_group_label(label: str) -> dict[str, str]:
    text = str(label)
    def grab(pattern: str) -> str:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else "UNKNOWN"
    return {
        "installation": grab(r"Установка\s+'([^']+)'"),
        "sampling_point": grab(r"Точка отбора\s+'([^']+)'"),
        "product": grab(r"Продукт\s+'([^']+)'"),
    }


def parse_lims(path: str | Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    parts = []
    group = None
    for date_col in range(0, raw.shape[1], 2):
        if pd.notna(raw.iat[0, date_col]):
            group = str(raw.iat[0, date_col])
        parameter = raw.iat[1, date_col]
        if pd.isna(parameter):
            continue
        unit = raw.iat[2, date_col]
        declared_count = raw.iat[3, date_col + 1]
        part = pd.DataFrame({
            "timestamp": pd.to_datetime(raw.iloc[4:, date_col], errors="coerce"),
            "value": pd.to_numeric(raw.iloc[4:, date_col + 1], errors="coerce"),
        }).dropna(subset=["timestamp", "value"])
        meta = parse_group_label(group)
        part = part.assign(
            installation=meta["installation"], sampling_point=meta["sampling_point"],
            product=meta["product"], quality_parameter=str(parameter), unit=str(unit),
            declared_count=declared_count, source=Path(path).name,
        )
        parts.append(part)
    return pd.concat(parts, ignore_index=True).sort_values("timestamp").reset_index(drop=True)


def parse_pak(path: str | Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    parts = []
    for date_col, value_col in ((0, 1), (3, 4)):
        tag, unit = raw.iat[0, date_col], raw.iat[1, date_col]
        if pd.isna(tag):
            continue
        part = pd.DataFrame({
            "timestamp": pd.to_datetime(raw.iloc[2:, date_col], errors="coerce"),
            "value": pd.to_numeric(raw.iloc[2:, value_col], errors="coerce"),
        }).dropna(subset=["timestamp", "value"])
        part = part.assign(tag=str(tag), unit=str(unit), source=Path(path).name)
        parts.append(part)
    return pd.concat(parts, ignore_index=True).sort_values(["tag", "timestamp"]).reset_index(drop=True)


def constant_episodes(data: pd.DataFrame, min_rows: int = 6) -> pd.DataFrame:
    records = []
    for tag, frame in data.groupby("tag", sort=False):
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        group = frame["value"].ne(frame["value"].shift()).cumsum()
        segments = frame.groupby(group).agg(
            start=("timestamp", "min"), end=("timestamp", "max"),
            value=("value", "first"), rows=("value", "size"), unit=("unit", "first"),
        )
        segments = segments[segments["rows"] >= min_rows].copy()
        segments["tag"] = tag
        segments["duration_hours"] = (segments["end"] - segments["start"]).dt.total_seconds() / 3600 + 1 / 6
        records.append(segments.reset_index(drop=True))
    if not records:
        return pd.DataFrame(columns=["tag", "start", "end", "value", "rows", "duration_hours", "unit"])
    return pd.concat(records, ignore_index=True).sort_values("duration_hours", ascending=False)


def read_tag_reference(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    kip = pd.read_excel(path, sheet_name="КИП", header=0)
    mappings = []
    for installation, desc_col, tag_col in (
        ("АВТ", kip.columns[0], kip.columns[1]),
        ("24-2000", kip.columns[2], kip.columns[3]),
    ):
        part = kip[[desc_col, tag_col]].dropna(subset=[tag_col]).copy()
        part.columns = ["description", "tag"]
        part["installation"] = installation
        mappings.append(part)
    mapping = pd.concat(mappings, ignore_index=True)
    pak_ref = pd.read_excel(path, sheet_name="ПАК", header=None)
    vak_ref = pd.read_excel(path, sheet_name="ВАК", header=None)
    return mapping, pak_ref, vak_ref


def expected_prefix(description: str) -> str:
    text = str(description).lower()
    if "температур" in text:
        return "T"
    if "давлен" in text or "перепад" in text or "вакуум" in text:
        return "P"
    if "расход" in text or "переток" in text or "производительност" in text:
        return "F/W/Q"
    if "анализатор" in text or "качество продукции" in text:
        return "Q"
    if "плотност" in text:
        return "D"
    if "уровен" in text:
        return "L"
    return "UNKNOWN"


def tag_mapping_audit(mapping: pd.DataFrame, telemetry: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for rec in mapping.itertuples(index=False):
        frame = telemetry[rec.installation]
        present = rec.tag in frame.columns
        series = pd.to_numeric(frame[rec.tag], errors="coerce") if present else pd.Series(dtype=float)
        prefix_match = re.match(r"[A-Za-z]+", str(rec.tag))
        actual_prefix = prefix_match.group(0).upper() if prefix_match else "UNKNOWN"
        expected = expected_prefix(rec.description)
        semantic_conflict = expected != "UNKNOWN" and actual_prefix not in expected.split("/")
        rows.append({
            "installation": rec.installation, "tag": rec.tag, "description": rec.description,
            "present_in_csv": present, "actual_prefix": actual_prefix,
            "expected_prefix_from_description": expected, "semantic_conflict": semantic_conflict,
            "median": series.median(), "p01": series.quantile(.01), "p99": series.quantile(.99),
            "min": series.min(), "max": series.max(),
        })
    return pd.DataFrame(rows)


def sulfur_matches(lims: pd.DataFrame, pak: pd.DataFrame, tolerance: str = "5min") -> pd.DataFrame:
    lab = lims.query("quality_parameter == 'Mg.Sulfur'")[["timestamp", "value"]].rename(
        columns={"timestamp": "lims_timestamp", "value": "lims_mg_kg"}
    ).sort_values("lims_timestamp")
    online = pak.query("tag == '24-2000:Mg.Sulfur'")[["timestamp", "value"]].rename(
        columns={"timestamp": "pak_timestamp", "value": "pak_ppm"}
    ).sort_values("pak_timestamp")
    matched = pd.merge_asof(
        lab, online, left_on="lims_timestamp", right_on="pak_timestamp",
        direction="nearest", tolerance=pd.Timedelta(tolerance),
    )
    matched["delta_t_minutes"] = (matched["pak_timestamp"] - matched["lims_timestamp"]).dt.total_seconds() / 60
    matched["pak_minus_lims"] = matched["pak_ppm"] - matched["lims_mg_kg"]
    matched["lims_over_10"] = matched["lims_mg_kg"] > 10
    matched["pak_over_10"] = matched["pak_ppm"] > 10
    return matched


def hydro_vak_predictions(hydro: pd.DataFrame) -> pd.DataFrame:
    h = hydro
    out = pd.DataFrame({"timestamp": h["date"]})
    out["90%.T"] = 162.998 + .12945*h.T12 + 59.57*h.F15 + .00036*h.W7 + .26366*h.T23 - 424.72638*h.F1/h.F26
    out["50%.T"] = 44.625 + 10.0224*h.P13 + .06981*h.F9 + .8052*h.T6
    out["I250"] = 84.585 - .21172*h.T5 + .12137*h.T11 - .00014*h.F25 + .56248*h.F14 - .16317*h.T23 + .20272*h.T16
    out["CloudPoint"] = h.F22 + .0021*h.W7 + .00008*h.F25 - .30656*h.F1 + .12018*h.T6 + .01916*h.F9 - 48.254 - .05249*h.T16 + .00011
    out["CFPP"] = .22088*h.T6 - 102.375 - 47.75834*h.P8 + .03862*h.F9 + 43.60207*h.W7 + 43.81849*h.P24
    out["IBP.T"] = 137.762 - .0653*h.F26 + .00011*h.F22 + 5.78137*h.P13 - 34.58028*h.P24 - .00993*h.F14 - .99962*h.W4 + .32232*h.T23 - .09406*h.T16
    return out.replace([np.inf, -np.inf], np.nan)


def validate_vak_against_lims(predictions: pd.DataFrame, lims: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for target in [c for c in predictions.columns if c != "timestamp"]:
        lab = lims.query(
            "installation == 'Гидроочистка' and sampling_point == '2' and quality_parameter == @target"
        )[["timestamp", "value"]].rename(columns={"timestamp": "lab_time", "value": "lab"}).sort_values("lab_time")
        pred = predictions[["timestamp", target]].dropna().rename(columns={"timestamp": "pred_time", target: "pred"}).sort_values("pred_time")
        matched = pd.merge_asof(
            lab, pred, left_on="lab_time", right_on="pred_time",
            direction="nearest", tolerance=pd.Timedelta("5min"),
        ).dropna()
        error = matched["pred"] - matched["lab"]
        rows.append({
            "target": target, "n_pairs": len(matched),
            "lab_median": matched["lab"].median(), "prediction_median": matched["pred"].median(),
            "median_absolute_error": error.abs().median(), "mean_absolute_error": error.abs().mean(),
            "bias": error.mean(), "spearman": matched[["lab", "pred"]].corr(method="spearman").iloc[0, 1],
        })
    return pd.DataFrame(rows)
