"""Data checks, run through Zetaris. Grows phase by phase.

    python scripts/check_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.config import H3_RES, SAMPLE_LOCATIONS  # noqa: E402
from coverage_detective.data.zetaris import QUERY_LOG, query  # noqa: E402

SLOWEST_SQL = """
SELECT c.cell_id, c.nation, round(c.lat, 3) AS lat, round(c.lon, 3) AS lon,
       round(c.population) AS population,
       round(o.download_mbps, 2) AS download_mbps, round(o.upload_mbps, 2) AS upload_mbps,
       round(o.latency_ms) AS latency_ms, o.tests, o.devices, o.quarter
FROM CD_CELLS.cells_r7 c
JOIN CD_OOKLA_MOBILE.ookla_mobile_r7 o ON o.cell_id = c.cell_id
WHERE c.population > 0 AND o.tests >= 10
ORDER BY o.download_mbps
LIMIT 10
"""


def table(rows: list[dict], columns: list[str]) -> str:
    """Rows as text, columns in the given order (Zetaris does not keep SELECT order)."""
    return pd.DataFrame(rows, columns=columns).to_string(index=False)


def check_phase_a() -> None:
    print("Phase A: 10 slowest populated cells with >= 10 tests (CD_CELLS x CD_OOKLA_MOBILE, via Zetaris)")
    rows = query(SLOWEST_SQL)
    print(table(rows, ["cell_id", "nation", "lat", "lon", "population", "download_mbps",
                       "upload_mbps", "latency_ms", "tests", "devices", "quarter"]))
    entry = QUERY_LOG[-1]
    print(f"  {entry['rows']} rows in {entry['duration_ms']} ms")


def check_phase_b() -> None:
    print("\nPhase B: approximate mast sites by source and operator (CD_MASTS_SITES, via Zetaris)")
    rows = query("SELECT sources, count(*) AS sites FROM CD_MASTS_SITES.masts_sites GROUP BY sources ORDER BY sites DESC")
    print(table(rows, ["sources", "sites"]))
    rows = query("""
        SELECT operator, count(*) AS sites
        FROM (SELECT explode(split(operators, ',')) AS operator FROM CD_MASTS_SITES.masts_sites)
        WHERE operator <> '' GROUP BY operator ORDER BY sites DESC""")
    print(table(rows, ["operator", "sites"]))

    print("\nPhase B: sample locations (CD_CELLS x CD_OOKLA_MOBILE x CD_MASTS, via Zetaris)")
    ids = {h3.latlng_to_cell(lat, lon, H3_RES): name for name, lat, lon in SAMPLE_LOCATIONS}
    in_list = ", ".join(f"'{c}'" for c in ids)
    rows = query(f"""
        SELECT c.cell_id, round(c.population) AS population,
               round(o.download_mbps, 1) AS download_mbps, o.tests,
               round(m.nearest_mast_km, 2) AS nearest_mast_km,
               round(m.nearest_mast_bearing_deg) AS bearing_deg, m.nearest_mast_sources,
               m.masts_within_5km, m.masts_known_operator_within_5km,
               m.masts_unknown_operator_within_5km, m.masts_osm_only_within_5km,
               m.distinct_operators_within_5km, m.operators_within_5km, m.operator_data_status
        FROM CD_CELLS.cells_r7 c
        JOIN CD_MASTS.masts_r7 m ON m.cell_id = c.cell_id
        LEFT JOIN CD_OOKLA_MOBILE.ookla_mobile_r7 o ON o.cell_id = c.cell_id
        WHERE c.cell_id IN ({in_list})""")
    for r in rows:
        r["place"] = ids[r["cell_id"]]
    print(table(rows, ["place", "population", "download_mbps", "tests", "nearest_mast_km", "bearing_deg",
                       "nearest_mast_sources", "masts_within_5km", "masts_known_operator_within_5km",
                       "masts_unknown_operator_within_5km", "masts_osm_only_within_5km",
                       "distinct_operators_within_5km", "operators_within_5km", "operator_data_status"]))


def check_phase_e() -> None:
    print("\nPhase E: Ofcom area coverage for the sample locations (CD_OFCOM_AREA, via Zetaris)")
    ids = {h3.latlng_to_cell(lat, lon, H3_RES): name for name, lat, lon in SAMPLE_LOCATIONS}
    in_list = ", ".join(f"'{c}'" for c in ids)
    rows = query(f"""
        SELECT cell_id, pcon_name, laua_name, g4_geo_out_0, g4_geo_out_1, g4_prem_in_0,
               g4_abrd_in_0, g5hc_prem_out_at_least_one, data_date
        FROM CD_OFCOM_AREA.ofcom_area_r7 WHERE cell_id IN ({in_list})""")
    for r in rows:
        r["place"] = ids[r["cell_id"]]
    print(table(rows, ["place", "pcon_name", "laua_name", "g4_geo_out_0", "g4_geo_out_1", "g4_prem_in_0",
                       "g4_abrd_in_0", "g5hc_prem_out_at_least_one", "data_date"]))
    rows = query("""
        SELECT location, operator, coverage_pct FROM CD_OFCOM_NATIONS.ofcom_nations
        WHERE technology = '4G' AND coverage_type = 'Geographic' AND rurality = 'Rural'
          AND operator IN ('EE', 'O2', 'Three', 'Vodafone') AND location <> 'UK'""")
    print("4G geographic coverage, rural, by operator (%):")
    print(pd.DataFrame(rows).pivot(index="location", columns="operator", values="coverage_pct").to_string())


def main() -> None:
    check_phase_a()
    check_phase_b()
    check_phase_e()


if __name__ == "__main__":
    main()
