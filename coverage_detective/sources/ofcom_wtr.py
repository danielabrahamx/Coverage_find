"""Ofcom Wireless Telegraphy Act Register (WTR): licensed transmitters, operator-labelled.

Mobile base stations are NOT in the register (operators plan their own sites within
national spectrum blocks). What it does hold for the mobile operators is their fixed
microwave links (point-to-point backhaul), each end with an exact location and antenna
height. Link ends are almost always at mast or hub sites, so they confirm which operator
uses a site, but only for sites with licensed microwave backhaul.

Licensees are matched to operators by exact (case-insensitive) legal name using
data/reference/wtr_operator_licensees.csv, never by loose word matching ("Three" would
match "East Anglia Three Limited").
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

from coverage_detective.config import UK_BBOX

GRID_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"  # no I
_GB = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)   # OSGB36 British National Grid
_IE = Transformer.from_crs("EPSG:29903", "EPSG:4326", always_xy=True)   # TM75 Irish Grid (Northern Ireland)

COLUMNS = ["Licence Number", "NGR", "Frequency (Hz)", "Station Type", "Height Above Sea Level", "Antenna Height",
           "Licencee Company", "Licencee First Name", "Licencee Surname", "Status", "Product Description",
           "Latitude(Deg)", "Longitude(Deg)"]


def grid_ref_to_en(ref: str) -> tuple[str, float, float] | None:
    """('GB'|'IE', easting, northing) for a 6-, 8- or 10-figure grid reference.

    Two letters = British National Grid (e.g. "SP 20632 91606"); one letter = Irish Grid
    (e.g. "J 3374 7428"). The point is the south-west corner of the square the reference
    names, plus half its size (the centre), so a 6-figure ref lands mid-square (±50 m).
    """
    ref = re.sub(r"\s+", "", str(ref)).upper()
    m = re.fullmatch(r"([A-HJ-Z]{1,2})(\d{6}|\d{8}|\d{10})", ref)
    if not m:
        return None
    letters, digits = m.groups()
    half = len(digits) // 2
    size = 10 ** (5 - half)
    e_off, n_off = int(digits[:half]) * size + size / 2, int(digits[half:]) * size + size / 2
    if len(letters) == 2:
        l1, l2 = GRID_LETTERS.index(letters[0]), GRID_LETTERS.index(letters[1])
        e100 = ((l1 - 2) % 5) * 5 + (l2 % 5)
        n100 = (19 - (l1 // 5) * 5) - (l2 // 5)
        return "GB", e100 * 100_000 + e_off, n100 * 100_000 + n_off
    idx = GRID_LETTERS.index(letters)
    return "IE", (idx % 5) * 100_000 + e_off, (4 - idx // 5) * 100_000 + n_off


def grid_ref_to_latlon(ref: str) -> tuple[float, float] | None:
    en = grid_ref_to_en(ref)
    if en is None:
        return None
    grid, e, n = en
    lon, lat = (_GB if grid == "GB" else _IE).transform(e, n)
    if not (np.isfinite(lat) and np.isfinite(lon)):
        return None
    return float(lat), float(lon)


def load_licensees(path: Path) -> dict[str, list[str]]:
    """Normalised legal name -> operator groups."""
    table = pd.read_csv(path)
    return {_norm(n): sorted(o.split(",")) for n, o in zip(table.licensee, table.operators)}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().upper()


def operators_for(licensee: str, licensees: dict[str, list[str]]) -> list[str]:
    return licensees.get(_norm(licensee), [])


def read_points(path: Path, licensees: dict[str, list[str]]) -> tuple[pd.DataFrame, dict]:
    """One row per (licence, location) for operator licensees: a link end or other station."""
    df = pd.read_csv(path, dtype=str, encoding="latin-1", usecols=COLUMNS)
    counts = {"register_rows": len(df)}
    company = df["Licencee Company"].fillna("").str.strip()
    person = (df["Licencee First Name"].fillna("") + " " + df["Licencee Surname"].fillna("")).str.strip()
    df["licensee"] = company.where(company != "", person)
    df["operators"] = [",".join(operators_for(n, licensees)) for n in df.licensee]
    df = df[(df.operators != "") & (df.Status == "Live")].copy()
    counts["operator_rows"] = len(df)
    # Satellite earth stations are not mast sites; keep fixed links (incl. self co-ordinated).
    satellite = df["Product Description"].fillna("").str.contains("Satellite", case=False)
    counts["satellite_rows_dropped"] = int(satellite.sum())
    df = df[~satellite]

    # Location: convert the grid reference; fall back to the register's own WGS84 lat/lon.
    converted = [grid_ref_to_latlon(r) for r in df.NGR.fillna("")]
    reg_lat = pd.to_numeric(df["Latitude(Deg)"], errors="coerce").to_numpy()
    reg_lon = pd.to_numeric(df["Longitude(Deg)"], errors="coerce").to_numpy()
    df["lat"] = [c[0] if c else la for c, la in zip(converted, reg_lat)]
    df["lon"] = [c[1] if c else lo for c, lo in zip(converted, reg_lon)]
    df["location_from"] = ["grid_ref" if c else "register_latlon" for c in converted]
    b = UK_BBOX
    inside = df.lat.between(b["min_lat"], b["max_lat"]) & df.lon.between(b["min_lon"], b["max_lon"])
    counts["no_location_or_outside_uk"] = int((~inside).sum())
    df = df[inside]

    df["frequency_ghz"] = pd.to_numeric(df["Frequency (Hz)"], errors="coerce") / 1e9
    df["antenna_height_m"] = pd.to_numeric(df["Antenna Height"], errors="coerce")
    df["height_asl_m"] = pd.to_numeric(df["Height Above Sea Level"], errors="coerce")
    df["key"] = df["Licence Number"] + "|" + df.lat.round(5).astype(str) + "," + df.lon.round(5).astype(str)
    pts = df.groupby("key").agg(
        link_id=("Licence Number", "first"),
        lat=("lat", "first"),
        lon=("lon", "first"),
        location_from=("location_from", "first"),
        ngr=("NGR", "first"),
        licensee=("licensee", "first"),
        operators=("operators", "first"),
        product=("Product Description", "first"),
        frequency_ghz=("frequency_ghz", "min"),
        antenna_height_m=("antenna_height_m", "max"),
        height_asl_m=("height_asl_m", "max"),
        station_types=("Station Type", lambda s: ",".join(sorted(set(s) - {"-"}))),
        register_rows=("Licence Number", "size"),
    ).reset_index(drop=True)
    pts["frequency_band"] = pts.frequency_ghz.round().astype("Int64").astype(str) + " GHz"
    pts["is_link_endpoint"] = pts["product"].str.strip().eq("Fixed Links")
    pts.insert(0, "point_id", [f"W{i:06d}" for i in range(len(pts))])
    counts["points"] = len(pts)
    return pts, counts


def group_sites(points: pd.DataFrame, radius_m: float = 50.0) -> pd.DataFrame:
    """Register points within radius_m of each other (several links on one mast) -> one site."""
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    from scipy.sparse import coo_matrix

    y = points.lat.to_numpy() * 111_320.0
    x = points.lon.to_numpy() * 111_320.0 * np.cos(np.radians(points.lat.to_numpy()))
    pairs = cKDTree(np.column_stack([x, y])).query_pairs(radius_m, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(points),) * 2)
    _, label = connected_components(graph, directed=False)
    p = points.assign(site=label)
    join = lambda s: ",".join(sorted({v for x in s for v in str(x).split(",") if v}))  # noqa: E731
    sites = p.groupby("site").agg(
        lat=("lat", "mean"), lon=("lon", "mean"),
        operators=("operators", join), licensees=("licensee", join),
        links=("link_id", "nunique"), microwave_links=("is_link_endpoint", "sum"),
        antenna_height_m=("antenna_height_m", "max"),
    ).reset_index(drop=True)
    sites["has_microwave_backhaul"] = sites.microwave_links > 0
    return sites
