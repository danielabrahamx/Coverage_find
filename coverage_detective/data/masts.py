"""Mast sites from OpenCelliD, OpenStreetMap and Ofcom's licence register, merged, and mast
figures per H3 cell.

Each site has `sources` (comma list of opencellid / osm / ofcom_wtr), `operators_inferred`
(from OpenCelliD network codes and OSM operator tags), `operators_confirmed` (from Ofcom's
Wireless Telegraphy Register) and `operators` (both together).
"""

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


def _join(*lists) -> str:
    return ",".join(sorted({v for s in lists for v in str(s or "").split(",") if v and v != "None"}))


def _nearest_within(from_lat, from_lon, to_lat, to_lon, radius_m: float) -> np.ndarray:
    """For each `from` point, the index of the nearest `to` point within radius_m, else -1."""
    match = np.full(len(from_lat), -1)
    if len(from_lat) and len(to_lat):
        dist, idx = cKDTree(_unit_vectors(to_lat, to_lon)).query(_unit_vectors(from_lat, from_lon), k=1)
        within = _chord_to_km(dist) * 1000.0 <= radius_m
        match[within] = idx[within]
    return match


def merge_sites(ocid: pd.DataFrame, osm: pd.DataFrame, radius_m: float = 200.0) -> pd.DataFrame:
    """OpenCelliD + OSM. Each OpenCelliD site joins its nearest OSM mast within radius_m;
    an OSM mast with matches becomes one site (sources "opencellid,osm") at the OSM position
    (mapped, so usually more accurate than OpenCelliD's estimate). Others keep one source."""
    match = _nearest_within(ocid.lat, ocid.lon, osm.lat, osm.lon, radius_m)
    matched = pd.Series(match, index=ocid.index)
    rows = []
    for j, o in osm.reset_index(drop=True).iterrows():
        mine = ocid[matched == j]
        rows.append(
            {
                "lat": o.lat, "lon": o.lon,
                "sources": "opencellid,osm" if len(mine) else "osm",
                "operators_inferred": _join(o.operators, *mine.operators),
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
                "operators_inferred": s.operators, "operator_labels": s.operator_labels,
                "radio_types": s.radio_types, "cell_count": int(s.cell_count),
                "osm_id": None, "osm_operator": None, "mobile_tagged": True,
            }
        )
    sites = pd.DataFrame(rows)
    sites["operators_confirmed"] = ""
    sites["operators"] = sites.operators_inferred
    sites["wtr_licensees"] = ""
    sites["wtr_links"] = 0
    sites["has_microwave_backhaul"] = False
    sites["antenna_height_m"] = np.nan
    return sites


def merge_wtr(sites: pd.DataFrame, wtr: pd.DataFrame, radius_m: float = 200.0) -> tuple[pd.DataFrame, dict]:
    """Add Ofcom licence-register sites. Each register site joins the nearest existing site
    within radius_m: that site gains the register's operators as confirmed, "ofcom_wtr" in
    its sources, the backhaul flag and antenna height, and moves to the register position if
    it had only OpenCelliD's estimated one. Unmatched register sites become new sites."""
    sites = sites.copy()
    match = _nearest_within(wtr.lat, wtr.lon, sites.lat, sites.lon, radius_m)
    for i, j in enumerate(match):
        w = wtr.iloc[i]
        if j < 0:
            continue
        s = sites.index[j]
        sites.at[s, "operators_confirmed"] = _join(sites.at[s, "operators_confirmed"], w.operators)
        sites.at[s, "wtr_licensees"] = _join(sites.at[s, "wtr_licensees"], w.licensees)
        sites.at[s, "wtr_links"] += int(w.links)
        sites.at[s, "has_microwave_backhaul"] = bool(sites.at[s, "has_microwave_backhaul"] or w.has_microwave_backhaul)
        sites.at[s, "antenna_height_m"] = np.nanmax([sites.at[s, "antenna_height_m"], w.antenna_height_m])
        if sites.at[s, "sources"] == "opencellid":  # register position is surveyed; OpenCelliD's is estimated
            sites.at[s, "lat"], sites.at[s, "lon"] = w.lat, w.lon
        if "ofcom_wtr" not in sites.at[s, "sources"]:
            sites.at[s, "sources"] = _join(sites.at[s, "sources"], "ofcom_wtr")
    new = wtr[match < 0]
    added = pd.DataFrame(
        {
            "lat": new.lat, "lon": new.lon, "sources": "ofcom_wtr",
            "operators_inferred": "", "operator_labels": "", "radio_types": "", "cell_count": 0,
            "osm_id": None, "osm_operator": None, "mobile_tagged": True,
            "operators_confirmed": new.operators, "wtr_licensees": new.licensees,
            "wtr_links": new.links.astype(int), "has_microwave_backhaul": new.has_microwave_backhaul,
            "antenna_height_m": new.antenna_height_m,
        }
    )
    sites = pd.concat([sites, added], ignore_index=True)
    sites["operators"] = [_join(a, b) for a, b in zip(sites.operators_inferred, sites.operators_confirmed)]
    stats = {"wtr_sites": len(wtr), "matched_existing": int((match >= 0).sum()), "new_sites": len(new)}
    return sites, stats


def finalise_sites(sites: pd.DataFrame) -> pd.DataFrame:
    sites = sites.reset_index(drop=True)
    sites.insert(0, "site_id", [f"S{i:06d}" for i in range(len(sites))])
    return sites


def masts_per_cell(cells: pd.DataFrame, sites: pd.DataFrame, radius_km: float = 5.0) -> pd.DataFrame:
    """For each grid cell centre: nearest site and the sites/operators within radius_km."""
    for col, default in [("operators_confirmed", ""), ("has_microwave_backhaul", False),
                         ("antenna_height_m", np.nan), ("operator_labels", "")]:
        if col not in sites:
            sites = sites.assign(**{col: default})
    tree = cKDTree(_unit_vectors(sites.lat, sites.lon))
    pts = _unit_vectors(cells.lat, cells.lon)
    chord, idx = tree.query(pts, k=1)
    near = sites.iloc[idx]
    within = tree.query_ball_point(pts, _km_to_chord(radius_km))

    def split(col):
        return [s.split(",") if s else [] for s in sites[col].fillna("")]

    ops, confirmed = split("operators"), split("operators_confirmed")
    sources = sites.sources.fillna("").to_numpy()
    osm_only = sources == "osm"
    wtr = np.array(["ofcom_wtr" in s for s in sources])
    backhaul = sites.has_microwave_backhaul.fillna(False).to_numpy(bool)
    # Unknown operator: no operator from any source (OSM-only sites without a recognisable
    # operator tag). Sites of "other" networks still count as known.
    unknown = ((sites.operators.fillna("") == "") & (sites.operator_labels.fillna("") == "")).to_numpy()

    ops_within = [sorted({o for j in js for o in ops[j]}) for js in within]
    confirmed_within = [sorted({o for j in js for o in confirmed[j]}) for js in within]
    count = lambda flags: np.array([int(flags[js].sum()) if js else 0 for js in within])  # noqa: E731
    n_sites = np.array([len(js) for js in within])
    n_unknown = count(unknown)
    n_known = n_sites - n_unknown
    has_confirmed = np.array([len(c) > 0 for c in confirmed_within])
    status = np.select(
        [n_sites == 0, has_confirmed, n_known > 0],
        ["no_sites_found", "confirmed", "inferred"],
        default="unknown",
    )
    return pd.DataFrame(
        {
            "cell_id": cells.cell_id.to_numpy(),
            "masts_within_5km": n_sites,
            "nearest_mast_km": _chord_to_km(chord),
            "nearest_mast_bearing_deg": bearing_deg(
                cells.lat.to_numpy(), cells.lon.to_numpy(), near.lat.to_numpy(), near.lon.to_numpy()
            ),
            "nearest_mast_id": near.site_id.to_numpy(),
            "nearest_mast_lat": near.lat.to_numpy(),
            "nearest_mast_lon": near.lon.to_numpy(),
            "nearest_mast_sources": near.sources.to_numpy(),
            "nearest_mast_operators": near.operators.to_numpy(),
            "nearest_mast_operators_confirmed": near.operators_confirmed.to_numpy(),
            "nearest_mast_antenna_height_m": near.antenna_height_m.to_numpy(),
            "distinct_operators_within_5km": [len(o) for o in ops_within],
            "operators_within_5km": [",".join(o) for o in ops_within],
            "operators_confirmed_within_5km": [",".join(o) for o in confirmed_within],
            "masts_osm_only_within_5km": count(osm_only),
            "masts_known_operator_within_5km": n_known,
            "masts_unknown_operator_within_5km": n_unknown,
            "wtr_sites_within_5km": count(wtr),
            "microwave_backhaul_sites_within_5km": count(backhaul),
            "operator_data_status": status,
        }
    )
