"""Tag normalization and canonical naming.

Canonical format: {source}_{raw_name}
Examples: avt_T1, u24_T5, avt_F3, u24_F15

This matches the format used by trained models (avt_T1, u24_T5).
Source prefix prevents collision between AVT T6 and U24 T6.
"""
from __future__ import annotations


SOURCE_AVT = "avt"
SOURCE_U24 = "u24"
SOURCE_PAK = "pak"
SOURCE_LIMS = "lims"

VALID_SOURCES = {SOURCE_AVT, SOURCE_U24, SOURCE_PAK, SOURCE_LIMS}


def normalize_tag(source: str, raw_name: str) -> str:
    """Normalize a tag to canonical format: {source}_{raw_name}."""
    return f"{source.lower().strip()}_{raw_name.strip()}"


def denormalize_tag(canonical: str) -> tuple[str, str]:
    """Split canonical tag into (source, raw_name)."""
    parts = canonical.split("_", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", canonical)


def normalize_telemetry_dict(telemetry: dict[str, float], source: str) -> dict[str, float]:
    """Normalize all keys in a telemetry dict to canonical format."""
    return {normalize_tag(source, k): v for k, v in telemetry.items()}
