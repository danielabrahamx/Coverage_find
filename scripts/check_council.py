"""Council view check: top zones UK-wide and in Westmorland and Furness, and the Great Langdale zone's fixes.

    python scripts/check_council.py

Calls the council API in-process (all data through Zetaris).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import h3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from coverage_detective.api.app import app  # noqa: E402
from coverage_detective.data.zetaris import query  # noqa: E402

client = TestClient(app)
GREAT_LANGDALE = (54.445, -3.105)


def top(scope: str, n: int = 10) -> None:
    t = time.time()
    r = client.get("/api/council/zones", params={"scope": scope}).json()
    print(f"\n== {scope}: {r['zones_in_scope']} zones, {r['people_in_zones']:,} people ({time.time() - t:.1f}s)")
    print(f"   weights {r['scoring']['weights']}; left out: {r['scoring']['omitted']}")
    for z in r["zones"][:n]:
        bars = " ".join(f"{k[:5]} {v['contribution']:>4}" for k, v in z["breakdown"].items())
        speed = f"{z['median_speed_mbps']:.1f}" if z["median_speed_mbps"] is not None else "–"
        pers = f"{z['persistence']:.0%}" if z["persistence"] is not None else "–"
        print(f"  {z['rank']:>3} {z['zone_id']} {z['name'][:22]:<22} {z['council'][:20]:<20} {z['people']:>6,} ppl "
              f"median {speed:>5} Mbps pers {pers:>4} ops {z['operators_mean']:.1f} tests {z['tests']:>4} "
              f"({z['confidence']}) score {z['score']:>5} | {bars}")


def main() -> None:
    top("uk")
    top("la:E06000064")
    cell = h3.latlng_to_cell(*GREAT_LANGDALE, 7)
    hit = query(f"SELECT zone_id FROM CD_GAP_ZONE_CELLS.gap_zone_cells WHERE cell_id = '{cell}'")
    if not hit:
        print(f"\nGreat Langdale's cell {cell} is not in a gap zone")
        return
    zid = hit[0]["zone_id"]
    t = time.time()
    r = client.get(f"/api/council/zones/{zid}").json()
    z = r["zone"]
    print(f"\n== Great Langdale zone {zid} '{z['name']}': {z['people']} people, {z['cells']} cells; "
          + "; ".join(f"rank {v['rank']}/{v['of']} in {k}" for k, v in r["ranks"].items()))
    for s in r["summary"]:
        print("   " + s)
    print(f"   Fix: {r['fix']['label']}" + (f", then {r['fix']['secondary_label']}" if r["fix"]["secondary"] else ""))
    for w in r["fix"]["why"]:
        print("     - " + w)
    print(f"   Evaluated {r['evaluated']['new_sites']} high points and {r['evaluated']['existing_sites']} existing sites:")
    for c in r["candidates"] + r["existing_sites"]:
        what = f"new site on high ground ({c['ground_m']:.0f} m)" if c["kind"] == "new_site" else \
            f"existing site {c['site_id']} ({', '.join(c['operators']) or 'operator unknown'})"
        print(f"     {what} at {c['lat']:.4f}, {c['lon']:.4f}: this zone's people gaining a clear line "
              f"{c['zone_people_gaining']}, poorly served people gaining {c['poor_people_gaining']}, "
              f"everyone reached {c['people_reached']} ({len(c['reached'])} of {c['cells_checked']} cells)")
    print(f"   Runtime: {time.time() - t:.1f}s for the request (planning {r['planning_ms']} ms, "
          f"{len(r['zetaris_queries'])} Zetaris queries)")


if __name__ == "__main__":
    main()
