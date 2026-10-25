"""Environment Agency flood warnings in force near a point (England only; no key; OGL v3).

Two paths, same answer shape:
  1. Direct API (default for a point): /id/floods?lat=&long=&dist=10, through the cached
     client. EA measures the distance to each flood area's polygon, so long river and coast
     areas are found even when their centre is far away.
  2. Zetaris: CD_LIVE_EA_FLOODS holds two REST tables over the EA API, `floods` (every alert
     and warning in England right now) and `flood_areas` (each area's centre). One SQL query
     joins them and keeps areas whose CENTRE is within 10 km. Polygons are not available as
     a table, so this misses large areas (Great Langdale, 25 Oct 2026: API 2 alerts, centres
     11 and 13 km away); use it for England-wide or regional queries, or via="zetaris".

Severity levels: 1 severe flood warning, 2 flood warning, 3 flood alert, 4 warning no
longer in force (dropped). Outside England the answer is "not_covered", never an empty
list, so it cannot be mistaken for "no floods": SEPA (Scotland), NRW (Wales) and DfI
(Northern Ireland) run their own services, not wired in yet.
"""

from __future__ import annotations

import time

from coverage_detective.config import sample_mode
from coverage_detective.sources import live

SOURCE = "ea_flood_monitoring"
API = "https://environment.data.gov.uk/flood-monitoring/id/floods"
AREAS_API = "https://environment.data.gov.uk/flood-monitoring/id/floodAreas?_limit=10000"
TTL_S = 15 * 60
RADIUS_KM = 10
NOT_COVERED = "not covered (England only for now)"
SEVERITY = {1: "severe flood warning", 2: "flood warning", 3: "flood alert"}
ZETARIS_DB = "CD_LIVE_EA_FLOODS"

_zetaris_cache: dict[tuple, tuple[float, live.LiveResult]] = {}


def zetaris_sql(lat: float, lon: float, km: float = RADIUS_KM) -> str:
    # Haversine distance from the point to each flood area's centre, in km.
    dist = (f"2 * 6371 * asin(sqrt(pow(sin(radians(a.lat - {lat}) / 2), 2) + cos(radians({lat})) * "
            f"cos(radians(a.lat)) * pow(sin(radians(a.long - ({lon})) / 2), 2)))")
    return f"""SELECT f.floodAreaID AS flood_area_id, f.severityLevel AS severity_level, f.severity AS severity,
  f.description AS area, f.eaAreaName AS ea_area, f.floodArea.riverOrSea AS river_or_sea,
  f.timeRaised AS time_raised, f.timeSeverityChanged AS time_severity_changed,
  a.lat AS area_lat, a.long AS area_lon, round({dist}, 1) AS distance_km
FROM (SELECT explode(items) AS f FROM {ZETARIS_DB}.floods) x
JOIN (SELECT explode(items) AS a FROM {ZETARIS_DB}.flood_areas) y ON x.f.floodAreaID = y.a.notation
WHERE f.severityLevel BETWEEN 1 AND 3 AND {dist} <= {km}"""


def _item(f: dict, distance_km=None) -> dict:
    level = f["severity_level"]
    return {"severity_level": level, "severity": SEVERITY.get(level, f.get("severity")),
            "area": f.get("area"), "ea_area": f.get("ea_area"), "river_or_sea": f.get("river_or_sea"),
            "time_raised": f.get("time_raised"), "time_severity_changed": f.get("time_severity_changed"),
            "flood_area_id": f.get("flood_area_id"), "distance_km": distance_km}


def _summary(items: list[dict], via: str, sql: str | None = None) -> dict:
    items = sorted(items, key=lambda i: (i["severity_level"], i["distance_km"] or 0))
    return {"covered": True, "radius_km": RADIUS_KM, "via": via, "count": len(items), "warnings": items,
            "highest": items[0]["severity"] if items else None, **({"sql": sql} if sql else {})}


def via_zetaris(lat: float, lon: float) -> live.LiveResult:
    from coverage_detective.data.zetaris import query  # imported here: the API client is optional

    key = (round(lat, 3), round(lon, 3))
    hit = _zetaris_cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    sql = zetaris_sql(lat, lon)
    rows = query(sql, timeout=60)
    res = live.LiveResult(SOURCE, API, "live", live.now_iso())
    res.data = _summary([_item(r, r.get("distance_km")) for r in rows], "zetaris", sql)
    _zetaris_cache[key] = (time.time(), res)
    return res


def via_api(lat: float, lon: float) -> live.LiveResult:
    params = {"lat": round(lat, 4), "long": round(lon, 4), "dist": RADIUS_KM}
    res = live.get(SOURCE, API, params, ttl_s=TTL_S, sample=live.nearest_sample(lat, lon))
    if res.body is not None:
        items = [_item({"severity_level": f.get("severityLevel"), "severity": f.get("severity"),
                        "area": f.get("description"), "ea_area": f.get("eaAreaName"),
                        "river_or_sea": (f.get("floodArea") or {}).get("riverOrSea"),
                        "time_raised": f.get("timeRaised"), "time_severity_changed": f.get("timeSeverityChanged"),
                        "flood_area_id": f.get("floodAreaID")})
                 for f in res.body.get("items", []) if f.get("severityLevel") in SEVERITY]
        res.data = _summary(items, "api")
    return res


def near(lat: float, lon: float, country: str | None, via: str = "api") -> live.LiveResult:
    """Flood alerts and warnings in force within 10 km. `country` from postcodes.io.

    via="zetaris" queries CD_LIVE_EA_FLOODS (area centres) and falls back to the API."""
    if country and country != "England":
        res = live.LiveResult(SOURCE, API, "not_covered", live.now_iso())
        res.data = {"covered": False, "message": NOT_COVERED, "country": country}
        return res
    if via == "zetaris" and not sample_mode():
        try:
            return via_zetaris(lat, lon)
        except Exception as e:  # noqa: BLE001 - any Zetaris problem falls back to the direct API
            res = via_api(lat, lon)
            res.error = f"Zetaris path failed ({type(e).__name__}: {str(e)[:200]}); used the EA API directly"
            return res
    return via_api(lat, lon)
