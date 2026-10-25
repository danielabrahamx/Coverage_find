"""Ofcom Connected Nations 2025 mobile coverage (reference date 1 July 2025).

Area files give, per local authority / constituency, the % of premises, land (100 m
pixels) or road pixels with coverage from exactly 0, 1, 2, 3 or 4 operators (Ofcom,
"About this data: mobile coverage", 2025). Within a group the five values sum to 100; a
blank means 0 when the rest of the group has values, and "not applicable" when the whole
group is blank (e.g. motorways in an area without any).

This is *predicted* coverage for an area, never coverage at an exact location.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

DATA_DATE = "2025-07"
RELEASE = "202507_mobile_coverage_r01"

# Ofcom column family -> our column prefix (SQL-friendly: no leading digit).
FAMILIES = {
    "4G_prem_out": "g4_prem_out",
    "4G_prem_in": "g4_prem_in",
    "4G_geo_out": "g4_geo_out",
    "4G_abrd_in": "g4_abrd_in",
    "4G_mway_in": "g4_mway_in",
    "5G_high_confidence_prem_out": "g5hc_prem_out",
    "5G_high_confidence_geo_out": "g5hc_geo_out",
}


def read_csv(zip_path: Path, part: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(f"{RELEASE}/{RELEASE.replace('_r01', '')}_{part}_r01.csv")
    return pd.read_csv(io.BytesIO(raw), encoding="latin-1")


def area_table(df: pd.DataFrame, code_col: str, name_col: str) -> pd.DataFrame:
    """One row per area: code, name, counts and the coverage families, blanks resolved."""
    out = pd.DataFrame({"code": df[code_col], "name": df[name_col],
                        "prem_count": df.prem_count, "pixel_count": df.pixel_count})
    for family, prefix in FAMILIES.items():
        cols = [f"{family}_{i}" for i in range(5)]
        block = df[cols].copy()
        has_any = block.notna().any(axis=1)
        block.loc[has_any] = block.loc[has_any].fillna(0.0)
        for i, c in enumerate(cols):
            out[f"{prefix}_{i}"] = block[c].to_numpy()
        out[f"{prefix}_at_least_one"] = 100.0 - out[f"{prefix}_0"]
    return out


def nations_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per-operator coverage by nation and urban/rural, tidy column names."""
    out = df.rename(
        columns={"Location": "location", "Technology": "technology", "Coverage type": "coverage_type",
                 "Rurality": "rurality", "MNO": "operator", "Coverage percentage": "coverage_pct",
                 "Coverage volume": "coverage_volume", "Date": "date"}
    )
    out["coverage_pct"] = pd.to_numeric(out.coverage_pct, errors="coerce")
    # Ofcom's MNO value "None" (no operator) is read by pandas as missing; restore it.
    out["operator"] = out.operator.fillna("None")
    return out
