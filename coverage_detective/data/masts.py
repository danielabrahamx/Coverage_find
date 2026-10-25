"""Mast sites from OpenCelliD and OpenStreetMap, merged, and mast figures per H3 cell."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_RADIUS_KM = 6371.0


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


def _join(*lists: str) -> str:
    return ",".join(sorted({v for s in lists for v in str(s or "").split(",") if v}))


def merge_sites(ocid: pd.DataFrame, osm: pd.DataFrame, radius_m: float = 200.0) -> pd.DataFrame:
    """One sites table. Each OpenCelliD site joins its nearest OSM mast within radius_m;
    an OSM mast with any OpenCelliD sites becomes one site with sources "both", at the OSM
    position (mapped, so usually more accurate than OpenCelliD's estimate). Everything else
    keeps its own source ("opencellid" or "osm")."""
    match = np.full(len(ocid), -1)
    if len(osm) and len(ocid):
        dist, idx = cKDTree(_unit_vectors(osm.lat, osm.lon)).query(_unit_vectors(ocid.lat, ocid.lon), k=1)
        within = _chord_to_km(dist) * 1000.0 <= radius_m
        match[within] = idx[within]

    rows = []
    matched = pd.Series(match, index=ocid.index)
    for j, o in osm.reset_index(drop=True).iterrows():
        mine = ocid[matched == j]
        rows.append(
            {
                "lat": o.lat, "lon": o.lon,
                "sources": "both" if len(mine) else "osm",
                "operators": _join(o.operators, *mine.operators),
                "operator_labels": _join(*mine.operator_labels),
                "radio_types": _join(*mine.radio_types),
                "cell_count": int(mine.cell_count.sum()),
                "osm_id": o.osm_id,
                "osm_operator": o.osm_operator,
                "mobile_tagged": bool(o.mobile_tagged) or len(mine) > 0,
            }
        )
    for _, s in ocid[matched < 0].iterrows():
        rows.append(
            {
                "lat": s.lat, "lon": s.lon, "sources": "opencellid",
                "operators": s.operators, "operator_labels": s.operator_labels,
                "radio_types": s.radio_types, "cell_count": int(s.cell_count),
                "osm_id": None, "osm_operator": None, "mobile_tagged": True,
            }
        )
    sites = pd.DataFrame(rows)
    sites.insert(0, "site_id", [f"S{i:06d}" for i in range(len(sites))])
    return sites


def masts_per_cell(cells: pd.DataFrame, sites: pd.DataFrame, radius_km: float = 5.0) -> pd.DataFrame:
    """For each grid cell centre: nearest site and the sites/operators within radius_km."""
    tree = cKDTree(_unit_vectors(sites.lat, sites.lon))
    pts = _unit_vectors(cells.lat, cells.lon)
    chord, idx = tree.query(pts, k=1)
    near = sites.iloc[idx]
    within = tree.query_ball_point(pts, _km_to_chord(radius_km))
    ops = [s.split(",") if s else [] for s in sites.operators.fillna("")]
    osm_only = (sites.sources == "osm").to_numpy()
    ops_within = [sorted({o for j in js for o in ops[j]}) for js in within]
    return pd.DataFrame(
        {
            "cell_id": cells.cell_id.to_numpy(),
            "masts_within_5km": [len(js) for js in within],
            "nearest_mast_km": _chord_to_km(chord),
            "nearest_mast_bearing_deg": bearing_deg(
                cells.lat.to_numpy(), cells.lon.to_numpy(), near.lat.to_numpy(), near.lon.to_numpy()
            ),
            "nearest_mast_id": near.site_id.to_numpy(),
            "nearest_mast_lat": near.lat.to_numpy(),
            "nearest_mast_lon": near.lon.to_numpy(),
            "nearest_mast_sources": near.sources.to_numpy(),
            "nearest_mast_operators": near.operators.to_numpy(),
            "distinct_operators_within_5km": [len(o) for o in ops_within],
            "operators_within_5km": [",".join(o) for o in ops_within],
            "masts_osm_only_within_5km": [int(osm_only[js].sum()) if js else 0 for js in within],
        }
    )
