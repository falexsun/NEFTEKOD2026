"""Reusable, non-destructive EDA helpers for the Neftekod telemetry notebooks."""

from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


EXPECTED_SOURCES = {
    "avt_telemetry": "avt_tags.csv",
    "hydrotreating_telemetry": "242000_tags.csv",
    "lims": "ЛИМС*.xlsx",
    "pak": "Выгрузка ПАК*.xlsx",
    "tag_dictionary": "Теги_хакатон*.xlsx",
    "avt_scheme": "АВТ_схемы*.pdf",
    "requirements": "ТЗ_нефтекод*.docx",
}

PREFIX_CATEGORY = {
    "T": "temperature",
    "P": "pressure",
    "F": "flow",
    "L": "level",
    "Q": "quality_or_calculated",
    "D": "unknown",
    "W": "unknown",
}


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop CSV-export index columns only; never alter process observations."""
    drop = [c for c in df.columns if str(c).strip() == "" or str(c).startswith("Unnamed:")]
    return df.drop(columns=drop, errors="ignore")


def load_telemetry(path: str | Path) -> pd.DataFrame:
    df = clean_columns(pd.read_csv(path, low_memory=False))
    if "date" not in df.columns:
        raise ValueError(f"No 'date' column in {path}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def infer_frequency(ts: pd.Series) -> str:
    delta = ts.dropna().sort_values().drop_duplicates().diff().dropna()
    if delta.empty:
        return "UNKNOWN"
    return str(delta.median())


def source_inventory(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_dir = Path(data_dir)
    records = []
    for path in sorted(data_dir.iterdir()):
        if not path.is_file():
            continue
        rec = {
            "source": path.name,
            "format": path.suffix.lower(),
            "size_mb": path.stat().st_size / 1024**2,
            "sheets": None,
            "rows": None,
            "columns": None,
            "start_date": pd.NaT,
            "end_date": pd.NaT,
            "frequency": None,
            "unique_timestamps": None,
            "duplicated_timestamps": None,
            "missingness_pct": None,
            "main_fields": None,
            "notes": "",
        }
        try:
            if path.suffix.lower() == ".csv":
                df = clean_columns(pd.read_csv(path, low_memory=False))
                rec["rows"], rec["columns"] = df.shape
                rec["main_fields"] = ", ".join(map(str, df.columns[:12]))
                rec["missingness_pct"] = 100 * df.isna().to_numpy().mean()
                if "date" in df:
                    ts = pd.to_datetime(df["date"], errors="coerce")
                    rec.update(
                        start_date=ts.min(), end_date=ts.max(),
                        frequency=infer_frequency(ts),
                        unique_timestamps=int(ts.nunique()),
                        duplicated_timestamps=int(ts.duplicated().sum()),
                    )
            elif path.suffix.lower() in {".xlsx", ".xls"}:
                xls = pd.ExcelFile(path)
                rec["sheets"] = ", ".join(xls.sheet_names)
                rec["notes"] = "Workbook detected; detailed parsing requires a source-specific schema."
            else:
                rec["notes"] = "Binary/reference file; not treated as tabular observations."
        except Exception as exc:
            rec["notes"] = f"READ ERROR: {type(exc).__name__}: {exc}"
        records.append(rec)

    availability = []
    for kind, pattern in EXPECTED_SOURCES.items():
        matches = sorted(p.name for p in data_dir.glob(pattern))
        availability.append({
            "expected_source": kind,
            "pattern": pattern,
            "available_in_data": bool(matches),
            "matched_files": ", ".join(matches) if matches else "MISSING",
        })
    return pd.DataFrame(records), pd.DataFrame(availability)


def longest_run(mask: pd.Series) -> int:
    mask = pd.Series(mask, dtype=bool).reset_index(drop=True)
    if not mask.any():
        return 0
    groups = mask.ne(mask.shift(fill_value=False)).cumsum()
    return int(mask.groupby(groups).sum().max())


def telemetry_summary(df: pd.DataFrame, source: str) -> pd.DataFrame:
    rows = []
    ts = df["date"]
    median_step_min = ts.sort_values().diff().dt.total_seconds().median() / 60
    numeric = df.drop(columns="date").apply(pd.to_numeric, errors="coerce")
    for col in numeric.columns:
        s = numeric[col].replace([np.inf, -np.inf], np.nan)
        valid = s.dropna()
        diff = valid.diff().abs().dropna()
        mad_diff = (diff - diff.median()).abs().median() if not diff.empty else np.nan
        jump_threshold = diff.median() + 10 * mad_diff if pd.notna(mad_diff) else np.nan
        jump_count = int((diff > jump_threshold).sum()) if pd.notna(jump_threshold) and jump_threshold > 0 else 0
        const_run = longest_run(s.eq(s.shift()) & s.notna()) + 1 if s.notna().any() else 0
        nan_run = longest_run(s.isna())
        quant = valid.quantile([.01, .05, .5, .95, .99]) if not valid.empty else pd.Series(dtype=float)
        rows.append({
            "source": source,
            "tag": col,
            "description": "UNKNOWN (tag dictionary unavailable in data/)",
            "unit": "UNKNOWN",
            "category_inferred_from_prefix": PREFIX_CATEGORY.get(re.sub(r"[^A-Za-z].*$", "", str(col)).upper(), "unknown"),
            "missing_pct": 100 * s.isna().mean(),
            "inf_count": int(np.isinf(pd.to_numeric(df[col], errors="coerce")).sum()),
            "non_numeric_count": int(df[col].notna().sum() - pd.to_numeric(df[col], errors="coerce").notna().sum()),
            "unique_count": int(valid.nunique()),
            "mean": valid.mean(), "std": valid.std(), "median": quant.get(.5, np.nan),
            "p01": quant.get(.01, np.nan), "p05": quant.get(.05, np.nan),
            "p95": quant.get(.95, np.nan), "p99": quant.get(.99, np.nan),
            "min": valid.min(), "max": valid.max(),
            "zero_pct": 100 * s.eq(0).mean(),
            "longest_nan_gap_rows": nan_run,
            "longest_nan_gap_hours": nan_run * median_step_min / 60,
            "longest_constant_interval_rows": const_run,
            "longest_constant_interval_hours": const_run * median_step_min / 60,
            "abrupt_jump_count_robust": jump_count,
            "diff_mad": mad_diff,
            "noise_ratio_diff_std_to_signal_std": diff.std() / valid.std() if valid.std() not in (0, np.nan) else np.nan,
            "is_constant": valid.nunique() <= 1,
            "is_near_constant": valid.value_counts(normalize=True, dropna=True).iloc[0] >= .995 if not valid.empty else True,
        })
    return pd.DataFrame(rows)


def timestamp_audit(df: pd.DataFrame, source: str, expected_minutes: int = 10) -> dict:
    ts = df["date"]
    valid = ts.dropna().sort_values()
    delta_min = valid.drop_duplicates().diff().dt.total_seconds().div(60).dropna()
    expected = pd.date_range(valid.min(), valid.max(), freq=f"{expected_minutes}min") if not valid.empty else []
    missing = pd.Index(expected).difference(pd.DatetimeIndex(valid.unique()))
    return {
        "source": source,
        "rows": len(df), "bad_timestamps": int(ts.isna().sum()),
        "duplicated_timestamps": int(ts.duplicated().sum()),
        "start": valid.min(), "end": valid.max(),
        "median_step_min": delta_min.median(), "p90_step_min": delta_min.quantile(.9),
        "max_step_min": delta_min.max(), "missing_expected_10min_points": len(missing),
        "coverage_pct_on_10min_grid": 100 * valid.nunique() / len(expected) if len(expected) else np.nan,
    }


def monthly_availability(df: pd.DataFrame, source: str) -> pd.DataFrame:
    tmp = df.dropna(subset=["date"]).set_index("date")
    numeric = tmp.apply(pd.to_numeric, errors="coerce")
    out = numeric.notna().resample("MS").mean().mean(axis=1).mul(100).rename("availability_pct").reset_index()
    out["source"] = source
    return out


def select_variable_tags(df: pd.DataFrame, n: int = 8) -> list[str]:
    x = df.drop(columns="date").apply(pd.to_numeric, errors="coerce")
    scale = x.std().replace(0, np.nan)
    score = x.diff().abs().median().div(scale).replace([np.inf, -np.inf], np.nan)
    return score.nlargest(n).index.tolist()


def lagged_cross_installation_associations(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_tags: list[str],
    right_tags: list[str],
    lags_minutes: list[int],
    tolerance: str = "5min",
) -> pd.DataFrame:
    """Associate upstream X(t-lag) to downstream Y(t), matched strictly by time."""
    base_right = right[["date", *right_tags]].sort_values("date")
    records = []
    for lag in lags_minutes:
        shifted = left[["date", *left_tags]].copy()
        shifted["date"] = shifted["date"] + pd.Timedelta(minutes=lag)
        joined = pd.merge_asof(
            base_right, shifted.sort_values("date"), on="date",
            direction="nearest", tolerance=pd.Timedelta(tolerance), suffixes=("_right", "_left"),
        )
        xcols = {x: (f"{x}_left" if x in right_tags else x) for x in left_tags}
        ycols = {y: (f"{y}_right" if y in left_tags else y) for y in right_tags}
        analysis_cols = list(dict.fromkeys([*xcols.values(), *ycols.values()]))
        corr_pearson = joined[analysis_cols].corr(method="pearson", min_periods=30)
        corr_spearman = joined[analysis_cols].corr(method="spearman", min_periods=30)
        for x in left_tags:
            xcol = xcols[x]
            for y in right_tags:
                ycol = ycols[y]
                n_pairs = int(joined[[xcol, ycol]].notna().all(axis=1).sum())
                records.append({
                    "upstream_tag": x, "downstream_tag": y, "lag_minutes": lag,
                    "n_pairs": n_pairs,
                    "pearson": corr_pearson.loc[xcol, ycol] if n_pairs >= 30 else np.nan,
                    "spearman": corr_spearman.loc[xcol, ycol] if n_pairs >= 30 else np.nan,
                })
    return pd.DataFrame(records)
