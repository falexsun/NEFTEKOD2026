"""Load all raw data sources into DataFrames."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# ── Tag CSV loader ──────────────────────────────────────────────

def load_avt_tags(path: str | Path) -> pd.DataFrame:
    """Load AVT unit telemetry from CSV."""
    df = pd.read_csv(path, index_col=0)
    # Drop duplicate index column if present
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # Ensure all tag columns are numeric
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(f"Loaded AVT tags: {df.shape}, range {df.index.min()} – {df.index.max()}")
    return df


def load_242000_tags(path: str | Path) -> pd.DataFrame:
    """Load 24-2000 (hydrofining) unit telemetry from CSV."""
    df = pd.read_csv(path, index_col=0)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(f"Loaded 24-2000 tags: {df.shape}, range {df.index.min()} – {df.index.max()}")
    return df


# ── PAK loader (Excel) ──────────────────────────────────────────

def load_pak_sulfur(path: str | Path) -> pd.DataFrame:
    """Load PAK sulfur online analyzer data.

    Returns DataFrame with columns: ['sulfur_mg_kg'] indexed by datetime.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Header row 0: tag names, row 1: units
    # Data starts at row 2, alternating (timestamp, value) pairs per column
    # Columns 0-1: sulfur (24-2000:Mg.Sulfur, timestamp+value)
    # Columns 3-4: density (24-2000:D15, timestamp+value)

    records = []
    for row in rows[2:]:  # Skip header rows
        ts = row[0]
        val = row[1]
        if ts is not None and val is not None:
            records.append({"timestamp": ts, "sulfur_mg_kg": val})

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    logger.info(f"Loaded PAK sulfur: {len(df)} records, range {df.index.min()} – {df.index.max()}")
    return df


def load_pak_density(path: str | Path) -> pd.DataFrame:
    """Load PAK density online analyzer data.

    Returns DataFrame with columns: ['density_15'] indexed by datetime.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    records = []
    for row in rows[2:]:
        ts = row[3]  # Density timestamp in column 3
        val = row[4]  # Density value in column 4
        if ts is not None and val is not None:
            records.append({"timestamp": ts, "density_15": val})

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No PAK density data found")
        return pd.DataFrame(columns=["density_15"])

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    logger.info(f"Loaded PAK density: {len(df)} records, range {df.index.min()} – {df.index.max()}")
    return df


# ── LIMS loader (Excel) ─────────────────────────────────────────

# LIMS column structure (from Теги_хакатон.xlsx ЛА sheet):
# 6 sampling points, each with N quality indicators
# Columns alternate: timestamp, value, timestamp, value, ...

# Sampling point descriptions and their indicators (count per point):
LIMS_SAMPLING_POINTS = [
    {
        "name": "AVT_point1_FRAC_DIZ",
        "unit": "АВТ", "point": "1", "product": "ФРАКЦ_ДИЗ",
        "indicators": ["PTF", "T90", "T50", "cloud_point_350", "EBP", "pour_point",
                        "density_avg", "I350", "cloud_point", "cloud_point_350b", "T95", "IBP"],
        "n_indicators": 12,
    },
    {
        "name": "AVT_point2_DT",
        "unit": "АВТ", "point": "2", "product": "Дизельное топливо",
        "indicators": ["T50", "EBP", "density_avg", "cloud_point", "IBP", "T90", "T95"],
        "n_indicators": 7,
    },
    {
        "name": "AVT_point2_1_DT",
        "unit": "АВТ", "point": "2.1", "product": "Дизельное топливо",
        "indicators": ["cloud_point", "EBP", "density_avg", "IBP", "T90", "T95"],
        "n_indicators": 6,
    },
    {
        "name": "AVT_point3_DT",
        "unit": "АВТ", "point": "3", "product": "Дизельное топливо",
        "indicators": ["T90", "T50", "PTF", "T95", "IBP", "EBP", "cloud_point", "density_avg"],
        "n_indicators": 8,
    },
    {
        "name": "Hydrofining_point1_FRAC_DIZ",
        "unit": "Гидроочистка", "point": "1", "product": "ФРАКЦ_ДИЗ",
        "indicators": ["PTF", "T90", "cloud_point", "density_15", "sulfur_avg", "IBP", "T95",
                        "EBP", "cloud_point2", "pour_point", "T50", "cetane_number", "T90b"],
        "n_indicators": 13,
    },
    {
        "name": "Hydrofining_point2_DT",
        "unit": "Гидроочистка", "point": "2", "product": "Дизельное топливо",
        "indicators": ["cloud_point", "density_15", "flash_point", "TNK", "ODIS_250", "T98",
                        "sulfur_md", "PTF", "pour_point", "T50", "cetane_number", "T90", "ODIS_350"],
        "n_indicators": 13,
    },
]


def load_lims(path: str | Path) -> pd.DataFrame:
    """Load LIMS laboratory measurements.

    Returns a long-format DataFrame with columns:
        timestamp, sampling_point, indicator, value
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Build column index: each sampling point has n_indicators pairs of (timestamp, value)
    col_offset = 0
    column_map = []  # list of (sampling_point_name, indicator_name, ts_col, val_col)
    for sp in LIMS_SAMPLING_POINTS:
        for i, indicator in enumerate(sp["indicators"]):
            ts_col = col_offset + i * 2
            val_col = col_offset + i * 2 + 1
            column_map.append((sp["name"], indicator, ts_col, val_col))
        col_offset += sp["n_indicators"] * 2

    records = []
    for row in rows[1:]:  # Skip header
        for sp_name, indicator, ts_col, val_col in column_map:
            if ts_col >= len(row) or val_col >= len(row):
                continue
            ts = row[ts_col]
            val = row[val_col]
            if ts is not None and val is not None:
                try:
                    # Validate timestamp is actually a datetime
                    if not isinstance(ts, (pd.Timestamp, type(pd.NaT))):
                        import datetime as _dt
                        if not isinstance(ts, (_dt.datetime, _dt.date)):
                            continue  # Skip non-date rows (e.g. summary rows)
                    records.append({
                        "timestamp": ts,
                        "sampling_point": sp_name,
                        "indicator": indicator,
                        "value": float(val) if not isinstance(val, (int, float)) else val,
                    })
                except (ValueError, TypeError):
                    pass

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No LIMS data found")
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp")
    logger.info(f"Loaded LIMS: {len(df)} records, {df['sampling_point'].nunique()} sampling points, "
                f"{df['indicator'].nunique()} indicators, range {df['timestamp'].min()} – {df['timestamp'].max()}")
    return df


def load_lims_wide(path: str | Path) -> pd.DataFrame:
    """Load LIMS and pivot to wide format for the hydrofining output point.

    Focuses on Hydrofining_point2_DT (final product quality).
    Returns DataFrame indexed by timestamp with indicator columns.
    """
    df = load_lims(path)
    if df.empty:
        return df

    # Focus on hydrofining output point 2 (final diesel fuel)
    hp2 = df[df["sampling_point"] == "Hydrofining_point2_DT"].copy()
    if hp2.empty:
        # Fallback to any hydrofining point
        hp2 = df[df["sampling_point"].str.startswith("Hydrofining")].copy()

    wide = hp2.pivot_table(index="timestamp", columns="indicator", values="value", aggfunc="last")
    wide = wide.sort_index()
    logger.info(f"LIMS wide format: {wide.shape}, columns: {list(wide.columns)}")
    return wide


# ── Tags dictionary loader ──────────────────────────────────────

def load_tags_dictionary(path: str | Path) -> dict[str, dict[str, str]]:
    """Load the tag dictionary from Теги_хакатон.xlsx КИП sheet.

    Returns dict: {tag_name: {"description": ..., "unit": ...}}
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["КИП"]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    tags = {}
    # AVT tags: columns 0 (description), 1 (tag_name)
    for row in rows[1:]:  # Skip header
        desc, tag = row[0], row[1]
        if tag and desc and isinstance(tag, str) and len(tag) <= 4:
            prefix = tag[0]
            tags[tag] = {"description": str(desc), "unit_type": prefix}

    # 24-2000 tags: columns 2 (description), 3 (tag_name)
    for row in rows[1:]:
        desc, tag = row[2], row[3]
        if tag and desc and isinstance(tag, str) and len(tag) <= 4:
            tags[tag] = {"description": str(desc), "unit": "24-2000"}

    logger.info(f"Loaded {len(tags)} tags from dictionary")
    return tags
