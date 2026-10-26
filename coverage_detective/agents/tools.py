"""Agent tools: thin wrappers over the existing evidence code, writing to Meterless.

Each tool computes evidence items in code (via Zetaris, the DEM, live sources or Meterless),
writes them to the run's case file in Meterless under stable ids (speed_cell, los_ee, ...;
calling a tool twice does not duplicate anything), records the call as a trace note, and
returns the items. The investigator chooses tools; it never states numbers itself.

    case = Case.for_point(run_id, query="LA22 9JY")       # or lat=, lon=
    run_tool(case, "line_of_sight", {"operator": "EE"}, round=1)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import h3

from coverage_detective import evidence as ev
from coverage_detective.config import H3_RES
from coverage_detective.memory.meterless import Meterless, memory as default_memory
from coverage_detective.sources import flood_warnings, live, met_office_warnings, weather

OPERATORS = ["EE", "O2", "Three", "Vodafone"]


@dataclass
class Case:
    """One run's working context: the point (or zone) and cached Zetaris results."""

    run_id: str
    scope: str
    point: dict
    memory: Meterless = default_memory
    zone_id: str | None = None
    bundle: ev.Bundle = field(default_factory=ev.Bundle)
    cache: dict = field(default_factory=dict)

    @property
    def lat(self) -> float:
        return self.point["lat"]

    @property
    def lon(self) -> float:
        return self.point["lon"]

    @property
    def cell_id(self) -> str:
        return h3.latlng_to_cell(self.lat, self.lon, H3_RES)

    @classmethod
    def for_point(cls, run_id: str, query: str | None = None, lat: float | None = None, lon: float | None = None,
                  memory: Meterless = default_memory) -> "Case":
        point, geo = ev.resolve(query, lat, lon)
        case = cls(run_id=run_id, scope="point", point=point, memory=memory)
        case.cache["geo"] = geo
        return case

    # ---------------------------------------------------- cached Zetaris queries

    def q(self, key: str):
        if key in self.cache:
            return self.cache[key]
        b = self.bundle
        if key == "Q1":
            sql, _ = ev.cell_sql(self.cell_id)
            rows = b.zetaris("Q1", sql)
            row = rows[0] if rows else None
            if row:
                row["history"] = sorted(json.loads(row.pop("history_json") or "[]"), key=lambda h: h["quarter"])
            self.cache[key] = row
        elif key == "Q2":
            sites = b.zetaris("Q2", ev.sites_sql(self.lat, self.lon))
            for s in sites:
                s["has_microwave_backhaul"] = ev._bool(s["has_microwave_backhaul"])
            self.cache[key] = sites
        elif key == "Q3":
            rows = b.zetaris("Q3", ev.UK_CONTEXT_SQL, cached=True)
            self.cache[key] = rows[0] if rows else None
        elif key == "Q4":
            quarter = ev._meta("ookla_mobile_r7")["data_period"]
            self.cache[key] = (b.zetaris("Q4", ev.tiles_sql(self.lat, self.lon, quarter, ev.TILE_MAP_RADIUS_KM)), quarter)
        return self.cache[key]

    def sql_for(self, ref: str) -> list[dict]:
        """The Zetaris queries an item's query_or_url refers to (e.g. 'zetaris:Q1, zetaris:Q3')."""
        ids = [p.split(":")[1].split()[0].strip(")") for p in ref.replace("(", " ").split() if p.startswith("zetaris:")]
        return [{"id": q["id"], "sql": q["sql"], "duration_ms": q["duration_ms"], "rows": q["rows"]}
                for q in self.bundle.queries if q["id"] in ids]


# ------------------------------------------------------------------- the tools


def _scratch(case: Case) -> ev.Bundle:
    b = ev.Bundle()
    b.queries = case.bundle.queries  # share the query log
    return b


def speeds_near(case: Case) -> list[dict]:
    """Measured Ookla speeds within 1 km, in the cell and its neighbours (latest quarter)."""
    b = _scratch(case)
    tiles, quarter = case.q("Q4")
    ev.nearby_speed_item(b, tiles, quarter, case.cell_id)
    cell = case.q("Q1")
    if cell:
        ev.speed_items(b, cell, case.cell_id, sorted(h3.grid_ring(case.cell_id, 1)), case.q("Q3"))
    return [i for i in b.items if i["id"] != "speed_trend"]


def speed_trend(case: Case) -> list[dict]:
    """Download speed in the cell over the last 4 quarters."""
    b = _scratch(case)
    cell = case.q("Q1")
    if cell:
        ev.speed_items(b, cell, case.cell_id, sorted(h3.grid_ring(case.cell_id, 1)), case.q("Q3"))
    items = [i for i in b.items if i["id"] == "speed_trend"]
    if not items:
        b2 = _scratch(case)
        b2.add("speed_trend", "Ookla open data (Zetaris CD_OOKLA_MOBILE_HISTORY)", ev._meta("ookla_mobile_history_r7"),
               "zetaris:Q1", [case.cell_id], "Not enough quarters with Ookla tests in this cell for a trend.",
               {"history": (cell or {}).get("history", [])}, {"quarters": int((cell or {}).get("quarters_with_data") or 0)},
               "weak", ["capacity_strain", "insufficient_data"])
        items = b2.items
    return items


def sites_near(case: Case) -> list[dict]:
    """Approximate mast sites around the point: the nearest one and operators within 5 km."""
    b = _scratch(case)
    ev.site_items(b, case.q("Q2"), case.lat, case.lon, case.cell_id)
    return b.items


def line_of_sight(case: Case, operator: str) -> list[dict]:
    """Line of sight from the exact point to the operator's nearest identified site (within 10 km)."""
    if operator not in OPERATORS:
        raise ValueError(f"operator must be one of {OPERATORS}")
    b = _scratch(case)
    sites = case.q("Q2")
    site = next((s for s in sites if operator in ev._ops(s["operators"])), None)
    if site is None:
        ev.no_site_item(b, operator, sites, case.cell_id)
        return b.items
    los_cache = case.cache.setdefault("los", {})
    los_cache[site["site_id"]] = ev.los_item(b, site, [operator], case.lat, case.lon, case.cell_id,
                                             los=los_cache.get(site["site_id"]), item_id=f"los_{operator.lower()}")
    return b.items


def terrain(case: Case) -> list[dict]:
    """Elevation range in the point's cell."""
    b = _scratch(case)
    if case.q("Q1"):
        ev.terrain_item(b, case.q("Q1"), case.cell_id)
    return b.items


def ofcom_area(case: Case) -> list[dict]:
    """Ofcom Connected Nations figures for the constituency (area-level, predicted)."""
    b = _scratch(case)
    if case.q("Q1"):
        ev.ofcom_item(b, case.q("Q1"), case.cell_id)
    return b.items


def live_conditions(case: Case) -> list[dict]:
    """Weather now and next 24 h, Met Office warnings, flood warnings (live)."""
    b = _scratch(case)
    w = weather.forecast(case.lat, case.lon)
    m = met_office_warnings.for_place(case.point, case.lat, case.lon)
    f = flood_warnings.near(case.lat, case.lon, case.point.get("country"))
    ev.live_items(b, w, m, f, case.cell_id)
    return b.items


def prior_diagnoses_nearby(case: Case) -> list[dict]:
    """Earlier diagnoses within 10 km, from Meterless."""
    near = case.memory.diagnoses_near(case.lat, case.lon, km=10, exclude_run=case.run_id)
    b = _scratch(case)
    meta = {"data_period": "Meterless H-MEM (earlier runs)", "as_of": live.now_iso()}
    if near:
        parts = [f"{d['headline']} ({d['distance_km']:.1f} km away, run {d['run_id']}, {str(d.get('recorded', ''))[:10]})"
                 for d in near[:3]]
        finding = f"{len(near)} earlier diagnosis{'es' if len(near) > 1 else ''} within 10 km: " + "; ".join(parts) + "."
        strength = "moderate"
    else:
        finding, strength = "No earlier diagnoses within 10 km in Meterless.", "weak"
    b.add("prior_diagnoses", "Meterless H-MEM (earlier diagnoses)", meta, "meterless:/diagnoses/near",
          [case.cell_id], finding,
          [{k: d.get(k) for k in ("run_id", "headline", "distance_km", "causes", "recorded")} for d in near[:5]],
          {"diagnoses": len(near)}, strength, [])
    return b.items


def network_comparison(case: Case) -> list[dict]:
    """Rule-based comparison of the four networks from the line-of-sight results (code, not an LLM)."""
    sites = case.q("Q2")
    los_cache = case.cache.setdefault("los", {})
    for op in OPERATORS:  # make sure every operator with a site has a line of sight computed
        s = next((x for x in sites if op in ev._ops(x["operators"])), None)
        if s and s["site_id"] not in los_cache:
            line_of_sight(case, op)
    rows = ev.operator_comparison(sites, los_cache, case.lat, case.lon)
    best = ev.likely_best(rows)
    b = _scratch(case)
    b.add("network_comparison", "Rule-based network comparison (computed from line of sight and sites)",
          {"data_period": ev._meta("masts_sites")["data_period"], "as_of": ev._meta("masts_sites")["as_of"]},
          "zetaris:Q2", [case.cell_id], best["text"], {"operators": rows, "likely_best": best},
          {"operators_with_site": sum(1 for r in rows if r["site"])}, "moderate", ["single_operator", "distance_to_mast"])
    return b.items


# ------------------------------------------------------------------- zone tools


def _zone(case: Case) -> dict:
    if "zone" not in case.cache:
        from coverage_detective.api.council import zone_detail
        case.cache["zone"] = zone_detail(case.zone_id)
        for q in case.cache["zone"]["zetaris_queries"]:
            case.bundle.queries.append({"id": f"Z{len(case.bundle.queries) + 1}", "cached": False, **q})
    return case.cache["zone"]


def zone_summary(case: Case) -> list[dict]:
    """The zone's people, why its cells are poorly served, data confidence, rank and score."""
    d = _zone(case)
    z, b = d["zone"], _scratch(case)
    meta = {"data_period": ev._meta("gap_zones")["data_period"], "as_of": ev._meta("gap_zones")["as_of"]}
    ref = "zetaris:CD_GAP_ZONES, zetaris:CD_GAP_ZONE_CELLS"
    b.add("zone_overview", "Gap zones (Zetaris CD_GAP_ZONES)", meta, ref, z["cell_ids"], " ".join(d["summary"]),
          {k: z[k] for k in ("people", "cells", "people_by_reason", "median_speed_mbps", "persistence", "trend_pct",
                             "operators_mean", "operators_nearby", "council", "nation")},
          {"tests": z["tests"], "cells": z["cells"]}, {"high": "strong", "medium": "moderate"}.get(z["confidence"], "weak"),
          ["distance_to_mast", "terrain_blocking", "single_operator", "capacity_strain", "insufficient_data"])
    ranks = "; ".join(f"rank {r['rank']} of {r['of']} in {k}" for k, r in d["ranks"].items())
    b.add("zone_priority", "Priority score (computed, planning/scoring.py)", meta, ref, z["cell_ids"],
          f"Priority: {ranks}.", d["ranks"], None, "moderate", [])
    f = d["fix"]
    b.add("fix_rule", "Rule-based fix suggestion (planning/siting.py)", meta, ref, z["cell_ids"],
          f"Rule-based fix: {f['label']}" + (f", then {f['secondary_label'].lower()}" if f.get("secondary") else "")
          + ". " + " ".join(f["why"]), f, None, "moderate", [])
    return b.items


def candidate_sites(case: Case) -> list[dict]:
    """Top candidate new sites (DEM high points) and existing sites, with people gaining a clear line."""
    d = _zone(case)
    b = _scratch(case)
    meta = {"data_period": ev._meta("terrain_r7")["data_period"], "as_of": ev._meta("masts_sites")["as_of"]}
    for i, c in enumerate(d["candidates"], 1):
        b.add(f"cand_{i}", "Candidate site (line of sight over Copernicus DEM, planning/siting.py)", meta,
              "zetaris:CD_CELLS, zetaris:CD_GAP_ZONE_CELLS", sorted({r["cell_id"] for r in c["reached"]}),
              f"Candidate {i}: a new 25 m mast on high ground ({c['ground_m']:.0f} m, "
              f"{'inside' if c['in_zone'] else 'near'} the zone) would give {c['zone_people_gaining']} of the zone's "
              f"people a clear line of sight ({c['poor_people_gaining']} poorly served people in all; "
              f"{c['people_reached']} people reached in {len(c['reached'])} of {c['cells_checked']} cells checked).",
              {k: c[k] for k in ("lat", "lon", "ground_m", "zone_people_gaining", "poor_people_gaining", "people_reached")},
              {"cells_checked": c["cells_checked"]}, "moderate", ["terrain_blocking", "distance_to_mast"])
    for i, s in enumerate(d["existing_sites"], 1):
        b.add(f"existing_{i}", "Existing site (line of sight over Copernicus DEM, planning/siting.py)", meta,
              "zetaris:CD_MASTS_SITES", sorted({r["cell_id"] for r in s["reached"]}),
              f"Existing site {s['site_id']} ({', '.join(s['operators']) or 'operator unknown'}, "
              f"{s['distance_to_zone_km']:.1f} km from the zone) reaches {s['zone_people_gaining']} of the zone's people "
              f"with a clear line ({s['people_reached']} people in all).",
              {k: s[k] for k in ("site_id", "lat", "lon", "operators", "zone_people_gaining", "people_reached")},
              {"cells_checked": s["cells_checked"]}, "moderate", ["single_operator"])
    return b.items


TOOLS = {f.__name__: f for f in [speeds_near, speed_trend, sites_near, line_of_sight, terrain, ofcom_area,
                                 live_conditions, prior_diagnoses_nearby, zone_summary, candidate_sites]}
POINT_TOOLS = ["speeds_near", "speed_trend", "sites_near", "line_of_sight", "terrain", "ofcom_area",
               "live_conditions", "prior_diagnoses_nearby"]
ZONE_TOOLS = ["zone_summary", "candidate_sites", "prior_diagnoses_nearby"]


def tool_specs(names: list[str]) -> list[dict]:
    """OpenAI-style function definitions for the investigator."""
    out = []
    for name in names:
        params = {"type": "object", "properties": {}, "required": []}
        if name == "line_of_sight":
            params = {"type": "object", "properties": {"operator": {"type": "string", "enum": OPERATORS}},
                      "required": ["operator"]}
        out.append({"type": "function", "function": {"name": name, "description": TOOLS[name].__doc__.strip(),
                                                     "parameters": params}})
    return out


def run_tool(case: Case, name: str, args: dict | None = None, round: int = 1, by: str = "investigator") -> list[dict]:
    """Run a tool, write its items to Meterless (stable ids), and log the call as a trace note."""
    args = {k: v for k, v in (args or {}).items() if v is not None}
    t0 = time.monotonic()
    n_queries = len(case.bundle.queries)
    try:
        items = TOOLS[name](case, **args)
    except Exception as e:  # noqa: BLE001 - recorded, then raised for the caller's fallback
        case.memory.add_note(case.run_id, "tool_error", f"{name}({args}) failed: {type(e).__name__}: {str(e)[:200]}",
                             by=by, tool=name, args=args, round=round)
        raise
    written = []
    for item in items:
        res = case.memory.add_evidence(case.run_id, {**item, "evidence_id": item["id"], "tool": name, "round": round,
                                                     "zetaris": case.sql_for(item["query_or_url"])}, by=by)
        written.append({**item, "created": res.get("created", True)})
    queries = [{k: q[k] for k in ("id", "duration_ms", "rows") if k in q} for q in case.bundle.queries[n_queries:]]
    case.memory.add_note(case.run_id, "tool_call", f"{name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> "
                         f"{', '.join(i['id'] for i in written) or 'no items'}", by=by, tool=name, args=args, round=round,
                         evidence_ids=[i["id"] for i in written], new=[i["id"] for i in written if i["created"]],
                         duration_ms=round_ms(t0), zetaris_queries=queries)
    return written


def round_ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)
