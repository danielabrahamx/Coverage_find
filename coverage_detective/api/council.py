"""Council view API: gap zones in a scope, ranked by a priority score, and per-zone fixes.

  GET /api/council/scopes                        nations and local authorities (with zone counts)
  GET /api/council/zones?scope=&weights=&limit=  ranked zones with each factor's contribution
  GET /api/council/zones.csv?scope=&weights=     the same ranking as CSV
  GET /api/council/zones/{zone_id}               zone details, cells, evidence summary, fix, candidates
  GET /api/council/zones/{zone_id}/cells         just the zone's cells (for Explore's ?zone= outline)

scope: uk | nation:<England|Scotland|Wales|Northern Ireland> | la:<local authority code>.
weights: e.g. people:0.4,severity:0.3 (others keep their defaults; see planning/scoring.py).
All data comes through Zetaris (CD_GAP_ZONES, CD_GAP_ZONE_CELLS, CD_CELLS, CD_MASTS_SITES,
CD_OFCOM_AREA); every query is listed in the response.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from coverage_detective.data.zetaris import QUERY_LOG, ZetarisError, explain, query
from coverage_detective.planning import scoring, siting

router = APIRouter(prefix="/api/council")
NATIONS = ["England", "Scotland", "Wales", "Northern Ireland"]
SCOPE_RE = re.compile(r"^(uk|nation:(England|Scotland|Wales|Northern Ireland)|la:[EWSN]\d{8})$")
ZONE_RE = re.compile(r"^Z\d{5}$")
_plans: dict[str, dict] = {}  # zone_id -> plan (the DEM work is the slow part)


def _q(sql: str, log: list) -> list[dict]:
    try:
        rows = query(sql, timeout=60)
    except ZetarisError as e:
        raise HTTPException(502, f"Zetaris query failed: {explain(e)}") from e
    finally:
        log.append({k: QUERY_LOG[-1][k] for k in ("sql", "duration_ms", "rows", "error")})
    return rows


def scope_filter(scope: str, table: str = "") -> str:
    """SQL condition for a validated scope (the regex keeps values safe to inline)."""
    if not SCOPE_RE.match(scope):
        raise HTTPException(400, "scope must be uk, nation:<name> or la:<local authority code>")
    if scope == "uk":
        return "1 = 1"
    p = f"{table}." if table else ""
    kind, _, value = scope.partition(":")
    return f"{p}nation = '{value}'" if kind == "nation" else f"array_contains(split({p}la_codes, ','), '{value}')"


def _zones(scope: str, log: list) -> pd.DataFrame:
    rows = _q(f"SELECT * FROM CD_GAP_ZONES.gap_zones WHERE {scope_filter(scope)}", log)
    return pd.DataFrame(rows)


def _clean(v):
    return None if isinstance(v, float) and math.isnan(v) else v


def _zone_row(r: dict, cells: list[str] | None = None) -> dict:
    las = list(zip(str(r["la_codes"] or "").split(","), str(r["la_names"] or "").split("|")))
    out = {
        "rank": r.get("rank"), "zone_id": r["zone_id"], "name": r["name"], "place_type": _clean(r.get("place_type")),
        "nation": r["nation"], "council": r["primary_la_name"], "council_code": r["primary_la_code"],
        "councils": [{"code": c, "name": n} for c, n in las if c],
        "people": round(r["population"]), "cells": r["n_cells"],
        "centroid": {"lat": r["centroid_lat"], "lon": r["centroid_lon"]},
        "median_speed_mbps": _clean(r.get("median_cell_mbps")), "download_mbps": _clean(r.get("download_mbps")),
        "tests": r["tests"], "confidence": scoring.confidence(int(r["tests"] or 0)),
        "persistence": _clean(r.get("persistence")), "trend_pct": _clean(r.get("trend_pct")),
        "quarters_with_data": r.get("quarters_with_data"),
        "operators_mean": round(r["operators_mean"], 2), "operators_nearby": [o for o in str(r["operators_nearby"] or "").split(",") if o],
        "people_by_reason": {"slow": round(r["pop_slow"]), "no_site": round(r["pop_no_site"]), "blocked": round(r["pop_blocked"])},
        "score": r.get("score"), "breakdown": r.get("breakdown"),
        "links": {"explore": f"/?zone={r['zone_id']}&lat={r['centroid_lat']:.5f}&lon={r['centroid_lon']:.5f}&zoom=10.5",
                  "signal": f"/signal?lat={r['centroid_lat']:.5f}&lon={r['centroid_lon']:.5f}"},
    }
    if cells is not None:
        out["cell_ids"] = cells
    return out


def ranked(scope: str, weights_text: str | None, log: list) -> tuple[pd.DataFrame, dict]:
    try:
        weights = scoring.parse_weights(weights_text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    zones = _zones(scope, log)
    return scoring.score(zones, weights)


@router.get("/scopes")
@lru_cache(maxsize=1)  # the list only changes when the data is rebuilt
def scopes() -> dict:
    log: list = []
    las = _q("""SELECT a.laua_code, a.laua_name, c.nation, sum(c.population) AS population
FROM CD_OFCOM_AREA.ofcom_area_r7 a JOIN CD_CELLS.cells_r7 c ON c.cell_id = a.cell_id
WHERE a.laua_code IS NOT NULL GROUP BY a.laua_code, a.laua_name, c.nation""", log)
    zones = _q("SELECT zone_id, nation, la_codes, population FROM CD_GAP_ZONES.gap_zones", log)
    per_la: dict[str, int] = {}
    for z in zones:
        for code in str(z["la_codes"] or "").split(","):
            per_la[code] = per_la.get(code, 0) + 1
    # A council straddling a border is listed under the nation holding most of its people.
    best: dict[str, dict] = {}
    for r in las:
        if r["laua_code"] not in best or r["population"] > best[r["laua_code"]]["population"]:
            best[r["laua_code"]] = r
    councils = sorted(({"scope": f"la:{r['laua_code']}", "code": r["laua_code"], "name": r["laua_name"],
                        "nation": r["nation"], "zones": per_la.get(r["laua_code"], 0)} for r in best.values()),
                      key=lambda x: (x["nation"], x["name"]))
    nations = [{"scope": f"nation:{n}", "name": n, "zones": sum(1 for z in zones if z["nation"] == n)} for n in NATIONS]
    return {"uk": {"scope": "uk", "name": "United Kingdom", "zones": len(zones)}, "nations": nations,
            "councils": councils, "zetaris_queries": log}


@router.get("/zones")
def zones(scope: str = "uk", weights: str | None = None, limit: int = Query(500, ge=1, le=2000)) -> dict:
    log: list = []
    t = time.time()
    scored, summary = ranked(scope, weights, log)
    cells = _q(f"""SELECT c.zone_id, c.cell_id FROM CD_GAP_ZONE_CELLS.gap_zone_cells c
JOIN CD_GAP_ZONES.gap_zones z ON z.zone_id = c.zone_id WHERE {scope_filter(scope, "z")}""", log)
    by_zone: dict[str, list[str]] = {}
    for r in cells:
        by_zone.setdefault(r["zone_id"], []).append(r["cell_id"])
    rows = [_zone_row(r, by_zone.get(r["zone_id"], [])) for r in scored.head(limit).to_dict("records")]
    return {"scope": scope, "zones_in_scope": len(scored), "people_in_zones": round(float(scored.population.sum())) if len(scored) else 0,
            "scoring": summary, "zones": rows, "duration_ms": round((time.time() - t) * 1000), "zetaris_queries": log}


@router.get("/zones.csv")
def zones_csv(scope: str = "uk", weights: str | None = None) -> Response:
    log: list = []
    scored, summary = ranked(scope, weights, log)
    buf = io.StringIO()
    w = csv.writer(buf)
    factors = summary["factors_used"]
    w.writerow(["rank", "zone_id", "name", "council", "nation", "people", "cells", "median_speed_mbps", "tests",
                "confidence", "persistence", "trend_pct", "operators_mean", "operators_nearby", "score",
                *[f"{f}_contribution" for f in factors], "centroid_lat", "centroid_lon"])
    for r in scored.to_dict("records"):
        z = _zone_row(r)
        w.writerow([z["rank"], z["zone_id"], z["name"], z["council"], z["nation"], z["people"], z["cells"],
                    z["median_speed_mbps"], z["tests"], z["confidence"], z["persistence"], z["trend_pct"],
                    z["operators_mean"], " ".join(z["operators_nearby"]), z["score"],
                    *[r["breakdown"][f]["contribution"] for f in factors], round(r["centroid_lat"], 5), round(r["centroid_lon"], 5)])
    name = scope.replace(":", "_").replace(" ", "_")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="gap_zones_{name}.csv"'})


def _summary(z: dict, cells: list[dict]) -> list[str]:
    """Plain sentences computed from the zone's numbers (the agents will write the narrative)."""
    r = z["people_by_reason"]
    out = [f"{z['people']:,} people in {z['cells']} H3 cells ({z['council']}, {z['nation']})."]
    parts = []
    if r["no_site"]:
        parts.append(f"{r['no_site']:,} with no identified site within 5 km")
    if r["blocked"]:
        parts.append(f"{r['blocked']:,} where terrain blocks the line to every site within 5 km")
    if r["slow"]:
        parts.append(f"{r['slow']:,} measured below 5 Mbps")
    if parts:
        out.append("Poorly served: " + "; ".join(parts) + ".")
    if z["tests"]:
        speed = f" averaging {z['download_mbps']:.1f} Mbps" if z["download_mbps"] is not None else ""
        out.append(f"{z['tests']} Ookla test{'s' if z['tests'] != 1 else ''} in the latest quarter{speed} "
                   f"(data confidence: {z['confidence']}).")
    else:
        out.append("No Ookla tests in the latest quarter (data confidence: low).")
    if z["persistence"] is not None:
        out.append(f"Below 5 Mbps in {z['persistence']:.0%} of the {z['quarters_with_data']} quarters with tests.")
    if z["trend_pct"] is not None:
        out.append(f"Speed {'fell' if z['trend_pct'] < 0 else 'rose'} {abs(z['trend_pct']):.0f}% from the oldest to the latest quarter.")
    ops = z["operators_nearby"]
    out.append(f"On average {z['operators_mean']:.1f} operators have approximate sites within 5 km of its cells"
               + (f" ({', '.join(ops)} somewhere nearby)." if ops else "; none identified."))
    return out


@router.get("/zones/{zone_id}/cells")
def zone_cells(zone_id: str) -> dict:
    if not ZONE_RE.match(zone_id):
        raise HTTPException(400, "zone_id looks like Z00001")
    log: list = []
    rows = _q(f"""SELECT c.cell_id, z.name FROM CD_GAP_ZONE_CELLS.gap_zone_cells c
JOIN CD_GAP_ZONES.gap_zones z ON z.zone_id = c.zone_id WHERE c.zone_id = '{zone_id}'""", log)
    if not rows:
        raise HTTPException(404, f"No zone {zone_id}")
    return {"zone_id": zone_id, "name": rows[0]["name"], "cell_ids": [r["cell_id"] for r in rows], "zetaris_queries": log}


@router.get("/zones/{zone_id}")
def zone_detail(zone_id: str, weights: str | None = None) -> dict:
    if not ZONE_RE.match(zone_id):
        raise HTTPException(400, "zone_id looks like Z00001")
    log: list = []
    t = time.time()
    rows = _q(f"SELECT * FROM CD_GAP_ZONES.gap_zones WHERE zone_id = '{zone_id}'", log)
    if not rows:
        raise HTTPException(404, f"No zone {zone_id}")
    z = rows[0]
    # Rank and breakdown within the zone's main council and the UK.
    ranks = {}
    for scope in ["uk", f"la:{z['primary_la_code']}"]:
        scored, _ = ranked(scope, weights, log)
        hit = scored[scored.zone_id == zone_id]
        if len(hit):
            ranks[scope] = {"rank": int(hit["rank"].iloc[0]), "of": len(scored), "score": float(hit["score"].iloc[0]),
                            "breakdown": hit["breakdown"].iloc[0]}
    cells = _q(f"SELECT * FROM CD_GAP_ZONE_CELLS.gap_zone_cells WHERE zone_id = '{zone_id}'", log)
    for c in cells:
        for k in ("slow", "no_site", "blocked"):
            c[k] = str(c[k]).lower() == "true"
    lats, lons = [c["lat"] for c in cells], [c["lon"] for c in cells]
    pad_lat = (siting.BUFFER_KM + siting.REACH_KM + 2) / 111.0
    pad_lon = pad_lat / math.cos(math.radians(sum(lats) / len(lats)))
    box = (min(lats) - pad_lat, max(lats) + pad_lat, min(lons) - pad_lon, max(lons) + pad_lon)
    area = _q(f"""SELECT c.cell_id, c.lat, c.lon, c.population, g.zone_id
FROM CD_CELLS.cells_r7 c LEFT JOIN CD_GAP_ZONE_CELLS.gap_zone_cells g ON g.cell_id = c.cell_id
WHERE c.population >= 10 AND c.lat BETWEEN {box[0]:.5f} AND {box[1]:.5f} AND c.lon BETWEEN {box[2]:.5f} AND {box[3]:.5f}""", log)
    for a in area:
        a["poor"] = a.get("zone_id") is not None
    pad = siting.EXISTING_KM / 111.0
    sites = _q(f"""SELECT site_id, lat, lon, operators, operators_confirmed, sources, antenna_height_m
FROM CD_MASTS_SITES.masts_sites
WHERE lat BETWEEN {min(lats) - pad:.5f} AND {max(lats) + pad:.5f}
  AND lon BETWEEN {min(lons) - pad / math.cos(math.radians(lats[0])):.5f} AND {max(lons) + pad / math.cos(math.radians(lats[0])):.5f}""", log)
    zone = _zone_row({**z, **(ranks.get("uk") or {})}, [c["cell_id"] for c in cells])
    planning_t = time.time()
    if zone_id not in _plans:
        _plans[zone_id] = siting.plan(z, cells, area, sites)
    plan = _plans[zone_id]
    return {"zone": zone, "ranks": ranks, "summary": _summary(zone, cells),
            "cells": [{k: c[k] for k in ("cell_id", "population", "slow", "no_site", "blocked", "severity", "ring_mbps",
                                          "ring_tests", "lat", "lon")} for c in cells],
            **plan, "planning_ms": round((time.time() - planning_t) * 1000),
            "duration_ms": round((time.time() - t) * 1000), "zetaris_queries": log}
