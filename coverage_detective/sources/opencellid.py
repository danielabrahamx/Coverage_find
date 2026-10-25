"""OpenCelliD: radio cells -> approximate mast sites.

OpenCelliD rows are individual radio cells (one per sector and technology), with a
position estimated from crowd-sourced measurements. Rows within ~150 m are grouped into
one approximate mast site. The data is crowd-sourced and incomplete, so "masts found" is
stronger evidence than "no masts found".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from coverage_detective.config import UK_BBOX

CSV_COLUMNS = [
    "radio", "mcc", "net", "area", "cell", "unit", "lon", "lat", "range",
    "samples", "changeable", "created", "updated", "averageSignal",
]
RADIOS = {"GSM", "UMTS", "LTE", "NR"}
# Codes whose reference entry is one of these are not public mobile networks with their
# own masts: MVNOs ride other networks; GSM-R is the railway; TETRA is the emergency services.
EXCLUDED_BANDS = {"MVNO", "GSM-R", "TETRA"}
MAIN_OPERATORS = ("EE", "O2", "Vodafone", "Three")


def read_cells(paths: list[Path], reference: pd.DataFrame, groups: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Radio cells inside the UK bbox, with the reference `label` and an `operator_group`
    (EE / O2 / Vodafone / Three, or "other"). Returns the cells and counts of rows dropped."""
    df = pd.concat(
        [pd.read_csv(p, header=None, names=CSV_COLUMNS, usecols=range(14), low_memory=False) for p in paths],
        ignore_index=True,
    )
    counts = {"rows_read": len(df)}
    df = df[df.radio.isin(RADIOS)]  # also drops a header row, if the file has one
    counts["other_radio"] = counts["rows_read"] - len(df)
    df = df.astype({"mcc": int, "net": int, "lat": float, "lon": float, "samples": float})
    b = UK_BBOX
    inside = df.lon.between(b["min_lon"], b["max_lon"]) & df.lat.between(b["min_lat"], b["max_lat"])
    counts["outside_bbox"] = int((~inside).sum())
    df = df[inside]

    ref = reference.rename(columns={"mnc": "net"})[["mcc", "net", "label", "bands"]]
    df = df.merge(ref, on=["mcc", "net"], how="left")
    unknown = df.label.isna()
    df.loc[unknown, "label"] = [f"unknown ({m}-{n:02d})" for m, n in zip(df.mcc[unknown], df.net[unknown])]
    excluded = df.bands.isin(EXCLUDED_BANDS)
    counts["excluded_networks"] = df[excluded].groupby("label").size().to_dict()
    df = df[~excluded]

    grp = groups.rename(columns={"mnc": "net"})[["mcc", "net", "operator_group"]]
    df = df.merge(grp, on=["mcc", "net"], how="left")
    df["operator_group"] = df.operator_group.fillna("other")
    counts["kept"] = len(df)
    cols = ["radio", "mcc", "net", "label", "operator_group", "lat", "lon", "samples"]
    return df[cols].reset_index(drop=True), counts


def _join(values) -> str:
    return ",".join(sorted(set(values)))


def cluster_sites(cells: pd.DataFrame, radius_m: float = 150.0) -> tuple[pd.DataFrame, np.ndarray]:
    """Group radio cells into approximate mast sites.

    Leader clustering: cells are taken in order of most samples first; each joins the
    nearest existing site whose leader is within radius_m, or starts a new site. Unlike
    single-linkage this cannot chain a dense city into one giant "site". Returns the
    sites and, for each input cell, its site index.
    """
    lat = cells.lat.to_numpy()
    lon = cells.lon.to_numpy()
    y = lat * 111_320.0
    x = lon * 111_320.0 * np.cos(np.radians(lat))
    order = np.argsort(-cells.samples.fillna(0).to_numpy(), kind="stable")

    bins: dict[tuple[int, int], list[int]] = {}
    leaders_x: list[float] = []
    leaders_y: list[float] = []
    site_of = np.empty(len(cells), dtype=np.int64)
    r2 = radius_m * radius_m
    for i in order:
        bx, by = int(x[i] // radius_m), int(y[i] // radius_m)
        best, best_d2 = -1, r2
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for s in bins.get((bx + dx, by + dy), ()):
                    d2 = (leaders_x[s] - x[i]) ** 2 + (leaders_y[s] - y[i]) ** 2
                    if d2 <= best_d2:
                        best, best_d2 = s, d2
        if best < 0:
            best = len(leaders_x)
            leaders_x.append(x[i])
            leaders_y.append(y[i])
            bins.setdefault((bx, by), []).append(best)
        site_of[i] = best

    c = cells.assign(site=site_of)
    sites = c.groupby("site").agg(
        lat=("lat", "mean"),
        lon=("lon", "mean"),
        radio_types=("radio", _join),
        operators=("operator_group", lambda s: _join(set(s) - {"other"})),
        operator_labels=("label", _join),
        cell_count=("radio", "size"),
        samples=("samples", "sum"),
    )
    return sites.reset_index(drop=True), site_of
