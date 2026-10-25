"""OpenCelliD: radio cells -> approximate mast sites -> per-H3-cell mast figures.

OpenCelliD rows are individual radio cells (one per sector and technology), with a
position estimated from crowd-sourced measurements. Rows within ~150 m are grouped into
one approximate mast site. The data is crowd-sourced and incomplete, so "masts found" is
stronger evidence than "no masts found".
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from coverage_detective.config import UK_BBOX

EARTH_RADIUS_KM = 6371.0
CSV_COLUMNS = [
    "radio", "mcc", "net", "area", "cell", "unit", "lon", "lat", "range",
    "samples", "changeable", "created", "updated", "averageSignal",
]
RADIOS = {"GSM", "UMTS", "LTE", "NR"}
# Codes whose reference entry is one of these are not public mobile networks with their
# own masts: MVNOs ride other networks; GSM-R is the railway; TETRA is the emergency services.
EXCLUDED_BANDS = {"MVNO", "GSM-R", "TETRA"}


def read_cells(paths: list[Path], reference: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Radio cells inside the UK bbox, labelled with the operator from the reference.

    Returns the cells and counts of rows dropped at each step.
    """
    df = pd.concat(
        [pd.read_csv(p, header=None, names=CSV_COLUMNS, usecols=range(14), low_memory=False) for p in paths],
        ignore_index=True,
    )
    dropped = {"rows_read": len(df)}
    if df.radio.iloc[0] == "radio":  # a file with its own header row
        df = df[df.radio != "radio"]
    df = df[df.radio.isin(RADIOS)]
    dropped["other_radio"] = dropped["rows_read"] - len(df)
    df = df.astype({"mcc": int, "net": int, "lat": float, "lon": float, "samples": float})
    b = UK_BBOX
    inside = df.lon.between(b["min_lon"], b["max_lon"]) & df.lat.between(b["min_lat"], b["max_lat"])
    dropped["outside_bbox"] = int((~inside).sum())
    df = df[inside]

    ref = reference.rename(columns={"mnc": "net"})[["mcc", "net", "label", "bands"]]
    df = df.merge(ref, on=["mcc", "net"], how="left")
    unknown = df.label.isna()
    df.loc[unknown, "label"] = [f"unknown ({m}-{n:02d})" for m, n in zip(df.mcc[unknown], df.net[unknown])]
    excluded = df.bands.isin(EXCLUDED_BANDS)
    dropped["excluded_networks"] = df[excluded].groupby("label").size().to_dict()
    df = df[~excluded]
    dropped["kept"] = len(df)
    return df[["radio", "mcc", "net", "label", "lat", "lon", "samples"]].reset_index(drop=True), dropped


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
        radio_types=("radio", lambda s: ",".join(sorted(set(s)))),
        operators=("label", lambda s: ",".join(sorted(set(s)))),
        operator_count=("label", "nunique"),
        cell_count=("radio", "size"),
        samples=("samples", "sum"),
    )
    sites = sites.reset_index(drop=True)
    sites.insert(0, "site_id", [f"S{i:06d}" for i in range(len(sites))])
    return sites, site_of


def _unit_vectors(lat, lon) -> np.ndarray:
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def _km_to_chord(km: float) -> float:
    return 2.0 * math.sin(km / EARTH_RADIUS_KM / 2.0)


def _chord_to_km(chord) -> np.ndarray:
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.clip(np.asarray(chord) / 2.0, 0, 1))


def bearing_deg(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def masts_per_cell(cells: pd.DataFrame, sites: pd.DataFrame, radius_km: float = 5.0) -> pd.DataFrame:
    """For each grid cell centre: nearest site and the sites/operators within radius_km."""
    tree = cKDTree(_unit_vectors(sites.lat, sites.lon))
    pts = _unit_vectors(cells.lat, cells.lon)
    chord, idx = tree.query(pts, k=1)
    near = sites.iloc[idx]
    within = tree.query_ball_point(pts, _km_to_chord(radius_km))
    ops = sites.operators.str.split(",").to_list()
    ops_within = [sorted({o for j in js for o in ops[j]}) for js in within]
    return pd.DataFrame(
        {
            "cell_id": cells.cell_id.to_numpy(),
            "masts_within_5km": [len(js) for js in within],
            "nearest_mast_km": _chord_to_km(chord),
            "nearest_mast_bearing_deg": bearing_deg(cells.lat.to_numpy(), cells.lon.to_numpy(), near.lat.to_numpy(), near.lon.to_numpy()),
            "nearest_mast_id": near.site_id.to_numpy(),
            "nearest_mast_lat": near.lat.to_numpy(),
            "nearest_mast_lon": near.lon.to_numpy(),
            "nearest_mast_operators": near.operators.to_numpy(),
            "distinct_operators_within_5km": [len(o) for o in ops_within],
            "operators_within_5km": [",".join(o) for o in ops_within],
        }
    )
