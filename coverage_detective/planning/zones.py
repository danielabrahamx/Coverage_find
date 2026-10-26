"""Gap zones: connected clusters of poorly served populated cells, with the raw factors for scoring.

Per cell with >= 10 people (thresholds in config.py):
  (a) slow     test-weighted download over the cell + its 6 neighbours < 5 Mbps, >= 10 tests
  (b) no_site  no approximate mast site within 5 km, unless measurements contradict it
               (>= 10 tests at >= 5 Mbps over the cell + ring: then it is a gap in our site
               data, not in coverage, and is counted as `site_data_gap`, not as poor)
  (c) blocked  < 10 tests in the cell + ring, and the line of sight from the cell centre is
               blocked by >= 10 m to every site within 5 km (the 8 nearest are checked)
Cell severity (0-1): no_site 1.0; slow (5 - Mbps) / 5; blocked 0.75; the largest applies.

A zone is a set of poorly served cells connected through H3 neighbours, kept when it holds
>= 50 people in total (a per-cell threshold would miss sparse valleys). Per zone we keep
raw factors (scoring.py normalises them within the chosen scope):
  people        population of the zone's cells
  severity      population-weighted mean cell severity
  persistence   share of the last 4 quarters (with tests) in which the zone's test-weighted
                download was below 5 Mbps; None without tests
  trend         change in the zone's test-weighted download, oldest to latest quarter (%)
  operators     population-weighted mean of distinct operators with sites within 5 km
  tests         Ookla tests in the zone's cells, latest quarter (data confidence, not scored)
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from coverage_detective import config
from coverage_detective.data import terrain

METRES_PER_DEG = 111_320.0


def ring_speeds(cells: pd.DataFrame, ookla: pd.DataFrame) -> pd.DataFrame:
    """Test-weighted download over each cell and its neighbour ring (latest quarter)."""
    o = ookla.set_index("cell_id")
    mbps_tests = (o.download_mbps * o.tests).to_dict()
    tests = o.tests.to_dict()
    rows = []
    for cid in cells.cell_id:
        disk = h3.grid_disk(cid, 1)
        t = sum(tests.get(c, 0) for c in disk)
        mt = sum(mbps_tests.get(c, 0.0) for c in disk)
        rows.append((cid, mt / t if t else np.nan, t))
    return pd.DataFrame(rows, columns=["cell_id", "ring_mbps", "ring_tests"])


def blocked_to_all(cells: pd.DataFrame, sites: pd.DataFrame, radius_km: float = 5.0) -> pd.Series:
    """For each cell: True if every site within radius (the nearest few) is blocked by >= GAP_BLOCKED_M."""
    xy = lambda lat, lon: np.column_stack([lon * METRES_PER_DEG * np.cos(np.radians(lat)), lat * METRES_PER_DEG])  # noqa: E731
    tree = cKDTree(xy(sites.lat.to_numpy(), sites.lon.to_numpy()))
    order = cells.assign(_t=np.floor(cells.lat) * 1000 + np.floor(cells.lon)).sort_values(["_t", "lat"])
    out = {}
    s_lat, s_lon, s_h = sites.lat.to_numpy(), sites.lon.to_numpy(), sites.antenna_height_m.to_numpy()
    for r in order.itertuples(index=False):
        d, idx = tree.query(xy(np.array([r.lat]), np.array([r.lon]))[0], k=config.GAP_SITES_CHECKED,
                            distance_upper_bound=radius_km * 1000)
        idx = [i for i, dist in zip(np.atleast_1d(idx), np.atleast_1d(d)) if np.isfinite(dist)]
        if not idx:
            out[r.cell_id] = False  # no site: criterion (b), not (c)
            continue
        out[r.cell_id] = all(
            (los := terrain.line_of_sight(r.lat, r.lon, s_lat[i], s_lon[i],
                                          mast_height=None if np.isnan(s_h[i]) else s_h[i]))["blocked"]
            and los["max_obstruction_m"] >= config.GAP_BLOCKED_M
            for i in idx)
    return pd.Series(out, name="blocked_all")


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add slow / no_site / blocked / poor / severity columns to a per-cell frame."""
    populated = df.population >= config.GAP_MIN_CELL_POPULATION
    enough = df.ring_tests >= config.GAP_MIN_TESTS
    df["slow"] = populated & enough & (df.ring_mbps < config.GAP_SLOW_MBPS)
    no_sites = populated & (df.masts_within_5km.fillna(0) == 0)
    measured_ok = enough & (df.ring_mbps >= config.GAP_SLOW_MBPS)
    df["site_data_gap"] = no_sites & measured_ok  # e.g. Penzance: no site in OpenCelliD/OSM, 35 Mbps measured
    df["no_site"] = no_sites & ~measured_ok
    df["blocked"] = populated & ~enough & df.blocked_all.fillna(False).astype(bool) & ~df.no_site
    df["poor"] = df.slow | df.no_site | df.blocked
    sev = np.zeros(len(df))
    sev = np.where(df.blocked, 0.75, sev)
    slow_sev = np.clip((config.GAP_SLOW_MBPS - df.ring_mbps.fillna(config.GAP_SLOW_MBPS)) / config.GAP_SLOW_MBPS, 0, 1)
    sev = np.where(df.slow, np.maximum(sev, slow_sev), sev)
    df["severity"] = np.where(df.no_site, 1.0, sev)
    return df


def components(cell_ids: list[str]) -> list[list[str]]:
    """Connected clusters of cells (H3 neighbours)."""
    remaining, out = set(cell_ids), []
    while remaining:
        seed = remaining.pop()
        group, stack = [seed], [seed]
        while stack:
            for n in h3.grid_ring(stack.pop(), 1):
                if n in remaining:
                    remaining.remove(n)
                    group.append(n)
                    stack.append(n)
        out.append(sorted(group))
    return out


def zone_quarters(cells: list[str], history: pd.DataFrame) -> tuple[float | None, float | None, int]:
    """(persistence, trend %, quarters with data) from the per-quarter cell history."""
    h = history[history.cell_id.isin(cells)]
    if h.empty:
        return None, None, 0
    q = h.assign(w=h.download_mbps * h.tests).groupby("quarter")[["w", "tests"]].sum()
    q = q[q.tests > 0].sort_index()
    mbps = q.w / q.tests
    persistence = float((mbps < config.GAP_SLOW_MBPS).mean())
    trend = float((mbps.iloc[-1] - mbps.iloc[0]) / mbps.iloc[0] * 100) if len(mbps) >= 2 and mbps.iloc[0] > 0 else None
    return persistence, trend, len(mbps)


def name_zone(cells: list[str], places: pd.DataFrame | None, lat: float, lon: float) -> tuple[str | None, str | None]:
    """The zone's largest place (city > town > village > hamlet, then OSM population); with no
    place inside, "near" the closest place within 5 km of the zone's centre."""
    if places is None:
        return None, None
    p = places[places.cell_id.isin(cells)]
    if not p.empty:
        top = p.assign(pop=p.population_tag.fillna(0)).sort_values(["rank", "pop"], ascending=False).iloc[0]
        return top["name"], top["place"]
    d = terrain.distance_m(lat, lon, places.lat.to_numpy(), places.lon.to_numpy())
    i = int(np.argmin(d))
    return (f"near {places.name.iloc[i]}", "near") if d[i] <= 5000 else (None, None)


def build(df: pd.DataFrame, history: pd.DataFrame, places: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(zones, zone_cells) from the classified per-cell frame."""
    poor = df[df.poor].set_index("cell_id")
    groups = components(poor.index.tolist())
    rows, cell_rows = [], []
    for cells in groups:
        z = poor.loc[cells]
        pop = float(z.population.sum())
        if pop < config.GAP_MIN_ZONE_POPULATION:
            continue
        w = z.population / pop if pop else np.full(len(z), 1 / len(z))
        lat, lon = float((z.lat * w).sum()), float((z.lon * w).sum())
        persistence, trend, quarters = zone_quarters(cells, history)
        tests = int(z.tests.fillna(0).sum())
        speed_cells = z[z.tests.fillna(0) > 0]
        mbps = float((speed_cells.download_mbps * speed_cells.tests).sum() / speed_cells.tests.sum()) if len(speed_cells) else None
        las = z.groupby(["laua_code", "laua_name"]).population.sum().sort_values(ascending=False)
        ops = sorted({o for v in z.operators_within_5km.fillna("") for o in v.split(",") if o})
        name, place_type = name_zone(cells, places, lat, lon)
        rows.append({
            "cells": cells, "n_cells": len(cells), "population": pop, "centroid_lat": lat, "centroid_lon": lon,
            "nation": z.nation.mode().iloc[0], "la_codes": ",".join(c for c, _ in las.index),
            "la_names": "|".join(n for _, n in las.index), "primary_la_code": las.index[0][0] if len(las) else None,
            "primary_la_name": las.index[0][1] if len(las) else None, "place_name": name, "place_type": place_type,
            "pop_slow": float(z.population[z.slow].sum()), "pop_no_site": float(z.population[z.no_site].sum()),
            "pop_blocked": float(z.population[z.blocked].sum()),
            "severity": float((z.severity * w).sum()), "persistence": persistence, "trend_pct": trend,
            "quarters_with_data": quarters,
            "operators_mean": float((z.distinct_operators_within_5km.fillna(0) * w).sum()), "operators_nearby": ",".join(ops),
            "tests": tests, "download_mbps": mbps,
            "median_cell_mbps": float(speed_cells.download_mbps.median()) if len(speed_cells) else None,
            "ring_mbps": float((z.ring_mbps * z.ring_tests).sum() / z.ring_tests.sum()) if z.ring_tests.sum() else None,
            "ring_tests": int(z.ring_tests.sum()),
        })
    zones = pd.DataFrame(rows).sort_values("population", ascending=False).reset_index(drop=True)
    zones.insert(0, "zone_id", [f"Z{i + 1:05d}" for i in range(len(zones))])
    zones["name"] = [(n[0].upper() + n[1:]) if pd.notna(n) else f"Area in {la}" if pd.notna(la) else "Unnamed area"
                     for n, la in zip(zones.place_name, zones.primary_la_name)]
    for zid, cells in zip(zones.zone_id, zones.cells):
        for c in cells:
            r = poor.loc[c]
            cell_rows.append({"cell_id": c, "zone_id": zid, "population": float(r.population), "lat": r.lat, "lon": r.lon,
                              "slow": bool(r.slow), "no_site": bool(r.no_site), "blocked": bool(r.blocked),
                              "severity": float(r.severity), "ring_mbps": r.ring_mbps, "ring_tests": int(r.ring_tests),
                              "tests": int(r.tests) if pd.notna(r.tests) else 0, "laua_code": r.laua_code})
    return zones.drop(columns="cells"), pd.DataFrame(cell_rows)
