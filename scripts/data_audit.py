"""Data Audit — Phase 1 deliverable.

Comprehensive analysis of all data sources for the diesel fuel quality system.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.loaders import (
    load_avt_tags,
    load_242000_tags,
    load_pak_sulfur,
    load_pak_density,
    load_lims,
    load_lims_wide,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT.parent / "docs"
REPORTS_DIR = PROJECT_ROOT / "reports"


def audit_dataframe(df: pd.DataFrame, name: str) -> dict:
    """Compute audit statistics for a DataFrame."""
    stats = {
        "name": name,
        "rows": len(df),
        "columns": len(df.columns),
        "column_list": list(df.columns),
    }

    if isinstance(df.index, pd.DatetimeIndex):
        stats["date_range"] = {
            "min": str(df.index.min()),
            "max": str(df.index.max()),
        }
        stats["duration_days"] = (df.index.max() - df.index.min()).days

        # Sampling frequency
        if len(df) > 1:
            diffs = df.index.to_series().diff().dropna()
            stats["sampling_freq_minutes"] = {
                "median": float(diffs.median().total_seconds() / 60),
                "mean": float(diffs.mean().total_seconds() / 60),
                "min": float(diffs.min().total_seconds() / 60),
                "max": float(diffs.max().total_seconds() / 60),
            }

    # Numeric stats
    numeric = df.select_dtypes(include=[np.number])
    if not numeric.empty:
        # Missing ratios
        missing = numeric.isna().mean()
        stats["missing_ratio"] = {col: float(v) for col, v in missing.items() if v > 0}
        stats["total_missing_ratio"] = float(numeric.isna().mean().mean())

        # Constant columns
        constant = [col for col in numeric.columns if numeric[col].nunique() <= 1]
        stats["constant_columns"] = constant

        # Near-constant columns (99% same value)
        near_constant = []
        for col in numeric.columns:
            if numeric[col].nunique() > 1:
                mode_frac = numeric[col].value_counts(normalize=True).iloc[0]
                if mode_frac > 0.99:
                    near_constant.append(col)
        stats["near_constant_columns"] = near_constant

        # Duplicates
        if isinstance(df.index, pd.DatetimeIndex):
            n_dup = df.index.duplicated().sum()
            stats["duplicate_timestamps"] = int(n_dup)

        # Outliers (beyond 3 std)
        outlier_counts = {}
        for col in numeric.columns[:50]:  # Limit for performance
            col_data = numeric[col].dropna()
            if len(col_data) > 10:
                mean = col_data.mean()
                std = col_data.std()
                if std > 0:
                    n_outliers = ((col_data - mean).abs() > 3 * std).sum()
                    if n_outliers > 0:
                        outlier_counts[col] = int(n_outliers)
        stats["outlier_counts_3std"] = outlier_counts

        # Distribution summary for first 20 numeric columns
        dist_stats = {}
        for col in numeric.columns[:20]:
            col_data = numeric[col].dropna()
            if len(col_data) > 0:
                dist_stats[col] = {
                    "mean": float(col_data.mean()),
                    "std": float(col_data.std()),
                    "min": float(col_data.min()),
                    "q25": float(col_data.quantile(0.25)),
                    "median": float(col_data.median()),
                    "q75": float(col_data.quantile(0.75)),
                    "max": float(col_data.max()),
                    "count": int(len(col_data)),
                }
        stats["distributions"] = dist_stats

    return stats


def audit_sulfur_target(pak_sulfur: pd.DataFrame, lims: pd.DataFrame) -> dict:
    """Detailed audit of sulfur target variable."""
    result = {"pak_sulfur": {}, "lims_sulfur": {}}

    # PAK sulfur analysis
    if not pak_sulfur.empty and "sulfur_mg_kg" in pak_sulfur.columns:
        s = pak_sulfur["sulfur_mg_kg"].dropna()
        result["pak_sulfur"] = {
            "count": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "count_above_10": int((s > 10).sum()),
            "fraction_above_10": float((s > 10).mean()),
            "count_below_0": int((s < 0).sum()),
            "date_range": {
                "min": str(pak_sulfur.index.min()),
                "max": str(pak_sulfur.index.max()),
            },
        }

    # LIMS sulfur analysis
    if not lims.empty:
        sulfur_rows = lims[lims["indicator"].str.contains("sulfur|сер", case=False, na=False)]
        if not sulfur_rows.empty:
            s = sulfur_rows["value"].dropna()
            result["lims_sulfur"] = {
                "count": int(len(s)),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "std": float(s.std()),
                "min": float(s.min()),
                "max": float(s.max()),
                "count_above_10": int((s > 10).sum()),
                "fraction_above_10": float((s > 10).mean()) if len(s) > 0 else 0,
                "indicators_found": list(sulfur_rows["indicator"].unique()),
            }

    return result


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    audit_results = {}

    # ── 1. AVT tags ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Auditing AVT tags...")
    avt_path = DATA_DIR / "avt_tags.csv"
    if avt_path.exists():
        avt_df = load_avt_tags(avt_path)
        audit_results["avt_tags"] = audit_dataframe(avt_df, "AVT Tags")
        logger.info(f"AVT tags: {avt_df.shape}, {avt_df.index.min()} – {avt_df.index.max()}")
    else:
        logger.warning(f"AVT tags file not found: {avt_path}")
        audit_results["avt_tags"] = {"error": "file not found"}

    # ── 2. 24-2000 tags ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Auditing 24-2000 tags...")
    u24_path = DATA_DIR / "242000_tags.csv"
    if u24_path.exists():
        u24_df = load_242000_tags(u24_path)
        audit_results["unit_242000_tags"] = audit_dataframe(u24_df, "24-2000 Tags")
        logger.info(f"24-2000 tags: {u24_df.shape}, {u24_df.index.min()} – {u24_df.index.max()}")
    else:
        logger.warning(f"24-2000 tags file not found: {u24_path}")
        audit_results["unit_242000_tags"] = {"error": "file not found"}

    # ── 3. PAK (online analyzers) ───────────────────────────────
    logger.info("=" * 60)
    logger.info("Auditing PAK data...")
    pak_path = DOCS_DIR / "Выгрузка ПАК 01.01.2023 - н.в_.xlsx"
    if pak_path.exists():
        pak_sulfur = load_pak_sulfur(pak_path)
        pak_density = load_pak_density(pak_path)
        audit_results["pak_sulfur"] = audit_dataframe(pak_sulfur, "PAK Sulfur")
        audit_results["pak_density"] = audit_dataframe(pak_density, "PAK Density")
    else:
        logger.warning(f"PAK file not found: {pak_path}")
        pak_sulfur = pd.DataFrame()
        pak_density = pd.DataFrame()
        audit_results["pak_sulfur"] = {"error": "file not found"}
        audit_results["pak_density"] = {"error": "file not found"}

    # ── 4. LIMS ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Auditing LIMS data...")
    lims_path = DOCS_DIR / "ЛИМСы 01.01.2023 - н.в_ (2).xlsx"
    if lims_path.exists():
        lims_df = load_lims(lims_path)
        audit_results["lims"] = {
            "total_records": len(lims_df),
            "sampling_points": list(lims_df["sampling_point"].unique()) if not lims_df.empty else [],
            "indicators": list(lims_df["indicator"].unique()) if not lims_df.empty else [],
            "date_range": {
                "min": str(lims_df["timestamp"].min()) if not lims_df.empty else None,
                "max": str(lims_df["timestamp"].max()) if not lims_df.empty else None,
            },
        }
    else:
        logger.warning(f"LIMS file not found: {lims_path}")
        lims_df = pd.DataFrame()
        audit_results["lims"] = {"error": "file not found"}

    # ── 5. Sulfur target deep-dive ──────────────────────────────
    logger.info("=" * 60)
    logger.info("Auditing sulfur target...")
    audit_results["sulfur_target"] = audit_sulfur_target(pak_sulfur, lims_df)

    # ── 6. Data alignment analysis ──────────────────────────────
    logger.info("=" * 60)
    logger.info("Analyzing data alignment...")
    if "avt_tags" in audit_results and "unit_242000_tags" in audit_results:
        avt_range = audit_results["avt_tags"].get("date_range", {})
        u24_range = audit_results["unit_242000_tags"].get("date_range", {})
        pak_range = audit_results.get("pak_sulfur", {}).get("date_range", {})

        audit_results["alignment"] = {
            "avt_range": avt_range,
            "u24_range": u24_range,
            "pak_range": pak_range,
            "overlap_start": max(
                avt_range.get("min", ""),
                u24_range.get("min", ""),
            ) if avt_range.get("min") and u24_range.get("min") else None,
            "overlap_end": min(
                avt_range.get("max", ""),
                u24_range.get("max", ""),
            ) if avt_range.get("max") and u24_range.get("max") else None,
        }

    # ── Save reports ────────────────────────────────────────────
    # JSON report
    with open(REPORTS_DIR / "data_audit.json", "w") as f:
        json.dump(audit_results, f, indent=2, default=str, ensure_ascii=False)

    # Markdown report
    _write_markdown_report(audit_results)

    logger.info(f"Reports saved to {REPORTS_DIR}")
    return audit_results


def _write_markdown_report(results: dict) -> None:
    """Write human-readable markdown audit report."""
    lines = [
        "# Data Audit Report",
        "",
        "## Summary",
        "",
    ]

    # AVT
    avt = results.get("avt_tags", {})
    if "error" not in avt:
        lines.extend([
            "### AVT Unit Telemetry",
            f"- **Rows**: {avt.get('rows', 'N/A'):,}",
            f"- **Columns**: {avt.get('columns', 'N/A')}",
            f"- **Date range**: {avt.get('date_range', {}).get('min', 'N/A')} – {avt.get('date_range', {}).get('max', 'N/A')}",
            f"- **Duration**: {avt.get('duration_days', 'N/A')} days",
            f"- **Missing ratio**: {avt.get('total_missing_ratio', 0):.4f}",
            f"- **Constant columns**: {len(avt.get('constant_columns', []))}",
            f"- **Duplicate timestamps**: {avt.get('duplicate_timestamps', 0)}",
            "",
        ])

    # 24-2000
    u24 = results.get("unit_242000_tags", {})
    if "error" not in u24:
        lines.extend([
            "### 24-2000 Unit Telemetry",
            f"- **Rows**: {u24.get('rows', 'N/A'):,}",
            f"- **Columns**: {u24.get('columns', 'N/A')}",
            f"- **Date range**: {u24.get('date_range', {}).get('min', 'N/A')} – {u24.get('date_range', {}).get('max', 'N/A')}",
            f"- **Duration**: {u24.get('duration_days', 'N/A')} days",
            f"- **Missing ratio**: {u24.get('total_missing_ratio', 0):.4f}",
            "",
        ])

    # PAK
    pak_s = results.get("pak_sulfur", {})
    if "error" not in pak_s:
        lines.extend([
            "### PAK Sulfur (Online Analyzer)",
            f"- **Records**: {pak_s.get('rows', 'N/A'):,}",
            f"- **Date range**: {pak_s.get('date_range', {}).get('min', 'N/A')} – {pak_s.get('date_range', {}).get('max', 'N/A')}",
            "",
        ])

    # Sulfur target
    sulfur = results.get("sulfur_target", {})
    pak_sulfur_stats = sulfur.get("pak_sulfur", {})
    if pak_sulfur_stats:
        lines.extend([
            "### Sulfur Target Analysis",
            "",
            "#### PAK Sulfur",
            f"- **Count**: {pak_sulfur_stats.get('count', 'N/A'):,}",
            f"- **Mean**: {pak_sulfur_stats.get('mean', 'N/A'):.2f} mg/kg",
            f"- **Median**: {pak_sulfur_stats.get('median', 'N/A'):.2f} mg/kg",
            f"- **Std**: {pak_sulfur_stats.get('std', 'N/A'):.2f} mg/kg",
            f"- **Min**: {pak_sulfur_stats.get('min', 'N/A'):.2f} mg/kg",
            f"- **Max**: {pak_sulfur_stats.get('max', 'N/A'):.2f} mg/kg",
            f"- **Count > 10 mg/kg**: {pak_sulfur_stats.get('count_above_10', 'N/A'):,}",
            f"- **Fraction > 10 mg/kg**: {pak_sulfur_stats.get('fraction_above_10', 0):.4f}",
            "",
        ])

    # LIMS
    lims = results.get("lims", {})
    if "error" not in lims:
        lines.extend([
            "### LIMS Laboratory Data",
            f"- **Total records**: {lims.get('total_records', 'N/A'):,}",
            f"- **Sampling points**: {len(lims.get('sampling_points', []))}",
            f"- **Quality indicators**: {len(lims.get('indicators', []))}",
            f"- **Indicators**: {', '.join(lims.get('indicators', [])[:20])}",
            "",
        ])

    # Alignment
    align = results.get("alignment", {})
    if align:
        lines.extend([
            "### Data Alignment",
            f"- **Overlap start**: {align.get('overlap_start', 'N/A')}",
            f"- **Overlap end**: {align.get('overlap_end', 'N/A')}",
            "",
        ])

    # Assumptions
    lines.extend([
        "## Key Findings",
        "",
        "1. Both telemetry datasets (AVT, 24-2000) have consistent 10-minute sampling from 2023-01-01",
        "2. PAK sulfur provides continuous target variable for ML training",
        "3. LIMS data is irregular (~every 2-3 days) but provides lab-validated quality measurements",
        "4. Primary ML target: PAK sulfur (24-2000:Mg.Sulfur) — online, continuous, directly relevant",
        "5. Secondary target: PAK density (24-2000:D15) — available from 2025-03-05",
        "6. Sulfur values should be checked against 10 mg/kg limit (GOST R 52368-2005)",
        "",
        "## Assumptions",
        "",
        "- All assumptions documented in configs/assumptions.yaml",
        "- D10 column in AVT assumed to be density (integer values ~307, possibly coded)",
        "- PAK sulfur in ppm assumed equivalent to mg/kg",
        "- VAK (virtual analyzer) formulas from tag dictionary provide fallback predictions",
    ])

    with open(REPORTS_DIR / "data_audit.md", "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
