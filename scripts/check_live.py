"""Phase D check: live context for the sample places, the Zetaris REST source, offline mode.

    python scripts/check_live.py              # live calls, then the same with SAMPLE_MODE=true
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from coverage_detective.api.app import app  # noqa: E402
from coverage_detective.config import SAMPLE_LOCATIONS  # noqa: E402
from coverage_detective.data.zetaris import QUERY_LOG, ZetarisError, query  # noqa: E402
from coverage_detective.sources import flood_warnings  # noqa: E402

client = TestClient(app)


def show(name: str, lat: float, lon: float, flood_via: str = "api") -> None:
    t = time.time()
    L = client.get("/api/live", params={"lat": lat, "lon": lon, "flood_via": flood_via}).json()
    w, m, f = L["weather"], L["met_office_warnings"], L["flood_warnings"]
    print(f"\n{name}  ({lat}, {lon})  -> {L['place']['name']} [{L['place']['postcode']}], {L['place']['country']}"
          f"   {time.time() - t:.1f}s")
    if w["data"]:
        d = w["data"]
        print(f"  weather [{w['status']}, {w['as_of']}]: {d['severity'].upper()} {d['reasons']}; now {d['now']['weather']}, "
              f"gusts {d['now']['gust_kmh']} km/h, rain {d['now']['precipitation_mm_h']} mm/h; next 24 h max gust "
              f"{d['next_24h']['max_gust_kmh']} km/h, max rain {d['next_24h']['max_precipitation_mm_h']} mm/h")
    else:
        print(f"  weather [{w['status']}]: {w['error']}")
    print(f"  Met Office [{m['status']}, {m['as_of']}] {m['data'].get('region')}: {m['data'].get('count')} warnings")
    for x in m["data"].get("warnings", []):
        print(f"    {x['level']:<6} {','.join(x['types']):<10} {'in force' if x['in_force'] else 'upcoming':<8} "
              f"until {x['valid_to']}  {'covers this district' if x['district_listed'] else 'elsewhere in region'}")
    if f["status"] == "not_covered":
        print(f"  floods [{f['status']}]: {f['data']['message']}")
    else:
        print(f"  floods [{f['status']}, via {f['data'].get('via')}]: {f['data'].get('count')} within "
              f"{f['data'].get('radius_km')} km")
        for x in f["data"].get("warnings", []):
            print(f"    {x['severity']:<14} {x['area']}  (raised {x['time_raised']})")
    print(f"  all calm: {L['all_calm']}")


def zetaris_rest() -> None:
    print("\nZetaris REST source CD_LIVE_EA_FLOODS (each query calls the EA API live):")
    try:
        n = query("SELECT size(items) AS n FROM CD_LIVE_EA_FLOODS.floods")[0]["n"]
        print(f"  floods: {n} items in England right now ({QUERY_LOG[-1]['duration_ms']} ms)")
        for name, lat, lon in SAMPLE_LOCATIONS:
            res = flood_warnings.via_zetaris(lat, lon)
            print(f"  {name}: {res.data['count']} with area centre within 10 km "
                  f"({QUERY_LOG[-1]['duration_ms']} ms, {QUERY_LOG[-1]['rows']} rows)")
    except ZetarisError as e:
        print(f"  FAILED: {e}")


def main() -> None:
    print("=== live ===")
    for name, lat, lon in SAMPLE_LOCATIONS:
        show(name, lat, lon)
    zetaris_rest()
    print("\n=== SAMPLE_MODE=true (offline) ===")
    os.environ["SAMPLE_MODE"] = "true"
    for name, lat, lon in SAMPLE_LOCATIONS:
        show(name, lat, lon)


if __name__ == "__main__":
    main()
