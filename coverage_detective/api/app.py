"""Data explorer API and web app.

    python run.py                     # checks Zetaris, then serves on http://localhost:8000

Routes:
  GET /health                  server, layers and Zetaris status
  GET /api/layers              map layers (from data/web/layers/index.json)
  GET /api/layer/{name}        [cell_id, value(, weak)] for every cell with a value
  GET /api/masts?bbox=         approximate mast sites in a bbox (max 5,000)
  GET /api/tiles?bbox=         Ookla tiles (latest quarter) in a small bbox
  GET /api/cell/{cell_id}      everything about one cell, via one Zetaris query
  GET /api/geocode?q=          postcode or place name (postcodes.io)
  /                            the web app (web/)
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache

import h3
import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from coverage_detective.config import H3_RES, PROCESSED, ROOT
from coverage_detective.data import manifest
from coverage_detective.data.zetaris import QUERY_LOG, ZetarisError, query

LAYERS_DIR = ROOT / "data" / "web" / "layers"
WEB_DIR = ROOT / "web"
POSTCODES_IO = "https://api.postcodes.io"
MAX_MASTS = 5000
MAX_TILE_BBOX_DEG2 = 0.6  # tiles only when zoomed in
POSTCODE_RE = re.compile(r"^[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}$")

app = FastAPI(title="Coverage Detective data explorer")


# --- static data held in memory ------------------------------------------------------------


@lru_cache(maxsize=1)
def mast_sites() -> pd.DataFrame:
    cols = ["site_id", "lat", "lon", "sources", "operators", "operators_inferred", "operators_confirmed",
            "operator_labels", "radio_types", "cell_count", "osm_operator", "mobile_tagged",
            "has_microwave_backhaul", "antenna_height_m", "wtr_links"]
    return pd.read_parquet(PROCESSED / "masts_sites.parquet", columns=cols)


def _quadkey_bounds(qk: str) -> tuple[float, float, float, float]:
    x = y = 0
    for ch in qk:
        d = int(ch)
        x, y = (x << 1) | (d & 1), (y << 1) | (d >> 1)
    n = 2 ** len(qk)
    lat = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))  # noqa: E731
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


@lru_cache(maxsize=1)
def latest_tiles() -> pd.DataFrame:
    tiles = pd.read_parquet(PROCESSED / "ookla_mobile_tiles.parquet")
    latest = tiles[tiles.quarter == tiles.quarter.max()].reset_index(drop=True)
    bounds = [_quadkey_bounds(q) for q in latest.quadkey]
    latest[["min_lon", "min_lat", "max_lon", "max_lat"]] = pd.DataFrame(bounds)
    return latest


def _bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(v) for v in bbox.split(","))
    except ValueError as err:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat") from err
    return w, s, e, n


# --- routes ---------------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    try:
        query("SELECT 1 AS ok", timeout=5)
        zetaris = "ok"
    except ZetarisError as e:
        zetaris = f"unreachable: {e}"
    layers = len(json.loads((LAYERS_DIR / "index.json").read_text())) if (LAYERS_DIR / "index.json").exists() else 0
    return {"status": "ok", "layers": layers, "zetaris": zetaris}


@app.get("/api/layers")
def layers() -> list[dict]:
    path = LAYERS_DIR / "index.json"
    if not path.exists():
        raise HTTPException(503, "No layers built; run scripts/process/build_web_layers.py")
    return json.loads(path.read_text())


@app.get("/api/layer/{name}")
def layer(name: str) -> FileResponse:
    if not re.fullmatch(r"[a-z0-9_]+", name) or not (LAYERS_DIR / f"{name}.json").exists():
        raise HTTPException(404, f"No layer {name!r}")
    return FileResponse(LAYERS_DIR / f"{name}.json", media_type="application/json",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/masts")
def masts(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat")) -> dict:
    w, s, e, n = _bbox(bbox)
    df = mast_sites()
    inside = df[df.lon.between(w, e) & df.lat.between(s, n)]
    truncated = len(inside) > MAX_MASTS
    inside = inside.sort_values("cell_count", ascending=False).head(MAX_MASTS)
    sites = json.loads(inside.to_json(orient="records"))
    return {"count": len(sites), "truncated": truncated, "sites": sites,
            **manifest.evidence_meta("masts_sites")}


@app.get("/api/tiles")
def tiles(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat")) -> dict:
    w, s, e, n = _bbox(bbox)
    if (e - w) * (n - s) > MAX_TILE_BBOX_DEG2:
        return {"count": 0, "tiles": [], "note": "zoom in to see Ookla tiles"}
    df = latest_tiles()
    inside = df[(df.max_lon >= w) & (df.min_lon <= e) & (df.max_lat >= s) & (df.min_lat <= n)]
    cols = ["quadkey", "min_lon", "min_lat", "max_lon", "max_lat", "download_mbps", "upload_mbps",
            "latency_ms", "tests", "devices"]
    return {"count": len(inside), "quarter": str(df.quarter.iloc[0]) if len(df) else None,
            "tiles": json.loads(inside[cols].round(4).to_json(orient="records"))}


def _optional_joins() -> tuple[list[str], list[str], list[str]]:
    """Extra sources (built in later phases) joined only when registered in the manifest."""
    sources = manifest.load()["sources"]
    cols, joins, tables = [], [], []
    if "terrain" in sources:
        cols += ["t.elevation_mean_m", "t.elevation_range_m"]
        joins.append("LEFT JOIN CD_TERRAIN.terrain_r7 t ON t.cell_id = c.cell_id")
        tables.append("terrain_r7")
    if "terrain" in sources and (PROCESSED / "los_r7.parquet").exists():
        cols += ["l.blocked AS los_blocked", "l.obstruction_m AS los_obstruction_m"]
        joins.append("LEFT JOIN CD_LOS.los_r7 l ON l.cell_id = c.cell_id")
        tables.append("los_r7")
    if "deprivation" in sources:
        cols += ["d.rural_urban_class", "d.deprivation_decile_within_nation"]
        joins.append("LEFT JOIN CD_DEPRIVATION.deprivation_r7 d ON d.cell_id = c.cell_id")
        tables.append("deprivation_r7")
    return cols, joins, tables


def cell_sql(cell_id: str) -> tuple[str, list[str]]:
    neighbours = ", ".join(f"'{n}'" for n in sorted(h3.grid_ring(cell_id, 1)))
    extra_cols, extra_joins, extra_tables = _optional_joins()
    extra_select = "".join(f",\n  {c}" for c in extra_cols)
    sql = f"""SELECT
  c.cell_id, c.lat, c.lon, c.population, c.nation,
  o.quarter, o.download_mbps, o.upload_mbps, o.latency_ms, o.tests, o.devices,
  o.tests_per_1k_pop, o.devices_per_1k_pop, o.quarters_with_data,
  o.download_mbps_oldest, o.download_change_pct, o.download_trend_mbps_per_quarter,
  hst.history_json,
  nb.neighbour_download_mbps, nb.neighbour_tests, nb.neighbour_cells_with_data,
  m.nearest_mast_km, m.nearest_mast_bearing_deg, m.nearest_mast_id, m.nearest_mast_lat,
  m.nearest_mast_lon, m.nearest_mast_sources, m.nearest_mast_operators,
  m.nearest_mast_operators_confirmed, m.nearest_mast_antenna_height_m, m.masts_within_5km,
  m.masts_known_operator_within_5km, m.masts_unknown_operator_within_5km,
  m.masts_osm_only_within_5km, m.distinct_operators_within_5km, m.operators_within_5km,
  m.operators_confirmed_within_5km, m.wtr_sites_within_5km, m.microwave_backhaul_sites_within_5km,
  m.operator_data_status,
  a.pcon_code, a.pcon_name, a.laua_code, a.laua_name, a.g4_geo_out_0, a.g4_geo_out_1,
  a.g4_prem_out_0, a.g4_prem_in_0, a.g4_abrd_in_0, a.g5hc_prem_out_at_least_one,
  a.laua_g4_geo_out_0, a.laua_g4_geo_out_1, a.data_date AS ofcom_data_date{extra_select}
FROM CD_CELLS.cells_r7 c
LEFT JOIN CD_OOKLA_MOBILE.ookla_mobile_r7 o ON o.cell_id = c.cell_id
LEFT JOIN (
  SELECT cell_id, to_json(collect_list(named_struct('quarter', quarter, 'download_mbps', download_mbps,
         'tests', tests))) AS history_json
  FROM CD_OOKLA_MOBILE_HISTORY.ookla_mobile_history_r7 WHERE cell_id = '{cell_id}' GROUP BY cell_id
) hst ON hst.cell_id = c.cell_id
CROSS JOIN (
  SELECT sum(download_mbps * tests) / sum(tests) AS neighbour_download_mbps,
         sum(tests) AS neighbour_tests, count(*) AS neighbour_cells_with_data
  FROM CD_OOKLA_MOBILE.ookla_mobile_r7 WHERE cell_id IN ({neighbours})
) nb
LEFT JOIN CD_MASTS.masts_r7 m ON m.cell_id = c.cell_id
LEFT JOIN CD_OFCOM_AREA.ofcom_area_r7 a ON a.cell_id = c.cell_id{"".join(chr(10) + j for j in extra_joins)}
WHERE c.cell_id = '{cell_id}'"""
    tables = ["cells_r7", "ookla_mobile_r7", "ookla_mobile_history_r7", "masts_r7", "ofcom_area_r7", *extra_tables]
    return sql, tables


def _place_name(lat: float, lon: float) -> str | None:
    """Nearest postcode's parish / ward and district, best effort."""
    try:
        r = httpx.get(f"{POSTCODES_IO}/postcodes", params={"lat": lat, "lon": lon, "radius": 2000, "limit": 1}, timeout=4)
        result = (r.json().get("result") or [None])[0]
    except (httpx.HTTPError, ValueError):
        return None
    if not result:
        return None
    local = result.get("parish") or result.get("admin_ward")
    if local and "unparished" in local.lower():
        local = result.get("admin_ward")
    parts = [p for p in (local, result.get("admin_district")) if p]
    return ", ".join(dict.fromkeys(parts)) or None


@app.get("/api/cell/{cell_id}")
def cell(cell_id: str) -> dict:
    if not h3.is_valid_cell(cell_id) or h3.get_resolution(cell_id) != H3_RES:
        raise HTTPException(400, f"{cell_id!r} is not an H3 resolution-{H3_RES} cell")
    sql, tables = cell_sql(cell_id)
    try:
        rows = query(sql, timeout=60)
    except ZetarisError as e:
        raise HTTPException(502, f"Zetaris query failed: {e}") from e
    if not rows:
        raise HTTPException(404, f"Cell {cell_id} is not in the UK grid")
    data = rows[0]
    history = json.loads(data.pop("history_json") or "[]")
    data["history"] = sorted(history, key=lambda h: h["quarter"])
    data["place"] = _place_name(data["lat"], data["lon"])
    data["neighbours"] = sorted(h3.grid_ring(cell_id, 1))
    log = QUERY_LOG[-1]
    data_dates = {}
    for t in tables:
        try:
            data_dates[t] = manifest.evidence_meta(t)
        except KeyError:
            pass
    return {"cell": data, "zetaris": {"sql": sql, "duration_ms": log["duration_ms"], "rows": log["rows"]},
            "data_dates": data_dates}


def _places(q: str) -> list[dict]:
    r = httpx.get(f"{POSTCODES_IO}/places", params={"q": q, "limit": 6}, timeout=5)
    return [{"label": p["name_1"], "detail": p.get("county_unitary") or p.get("region"),
             "lat": p["latitude"], "lon": p["longitude"]} for p in (r.json().get("result") or [])]


@app.get("/api/geocode")
def geocode(q: str = Query(..., min_length=2)) -> dict:
    q = q.strip()
    try:
        if POSTCODE_RE.match(q):
            r = httpx.get(f"{POSTCODES_IO}/postcodes/{q.replace(' ', '')}", timeout=5)
            res = r.json().get("result")
            results = [{"label": res["postcode"], "detail": res.get("admin_district"),
                        "lat": res["latitude"], "lon": res["longitude"]}] if res else []
        else:
            results = _places(q)
            words = [w for w in re.split(r"\s+", q) if len(w) > 3]
            if not results and len(words) > 1:
                # postcodes.io's place list misses some names (e.g. "Great Langdale"); retry
                # with the most distinctive word and mark the matches as approximate.
                results = [{**p, "approximate": True} for p in _places(max(words, key=len))]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise HTTPException(502, f"postcodes.io lookup failed: {e}") from e
    for item in results:
        item["cell_id"] = h3.latlng_to_cell(item["lat"], item["lon"], H3_RES)
    return {"query": q, "results": results}


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
