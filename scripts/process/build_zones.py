"""Gap zones and improvement opportunities (Council view): populated cells, clustered into zones.

    python scripts/process/build_zones.py

Inputs: cells_r7, ookla_mobile_r7 + history, masts_r7, masts_sites, ofcom_area_r7 (local
authority per cell), places (zone names), Copernicus DEM (line of sight for criterion c).
Writes gap_zones.parquet (one row per zone, raw factors) and gap_zone_cells.parquet (one row
per poorly served cell), and opportunity_zones.parquet / opportunity_zone_cells.parquet (cells
that are not poorly served but have a measurable weakness; planning/opportunities.py). Scoring is done per request (coverage_detective/planning/scoring.py)
so weights can change. Rules and thresholds: coverage_detective/planning/zones.py, config.py.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective import config  # noqa: E402
from coverage_detective.config import CELLS_PATH, PROCESSED  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.planning import opportunities as O  # noqa: E402
from coverage_detective.planning import zones as Z  # noqa: E402

ZONES_OUT = PROCESSED / "gap_zones.parquet"
CELLS_OUT = PROCESSED / "gap_zone_cells.parquet"
OPP_OUT = PROCESSED / "opportunity_zones.parquet"
OPP_CELLS_OUT = PROCESSED / "opportunity_zone_cells.parquet"


def main() -> None:
    t0 = time.time()
    cells = pd.read_parquet(CELLS_PATH)
    ookla = pd.read_parquet(PROCESSED / "ookla_mobile_r7.parquet",
                            columns=["cell_id", "download_mbps", "tests", "devices_per_1k_pop", "quarters_with_data",
                                     "download_change_pct"])
    history = pd.read_parquet(PROCESSED / "ookla_mobile_history_r7.parquet", columns=["cell_id", "quarter", "download_mbps", "tests"])
    masts = pd.read_parquet(PROCESSED / "masts_r7.parquet",
                            columns=["cell_id", "masts_within_5km", "distinct_operators_within_5km", "operators_within_5km",
                                     "masts_unknown_operator_within_5km"])
    sites = pd.read_parquet(PROCESSED / "masts_sites.parquet", columns=["site_id", "lat", "lon", "antenna_height_m"])
    area = pd.read_parquet(PROCESSED / "ofcom_area_r7.parquet", columns=["cell_id", "laua_code", "laua_name"])
    places_path = PROCESSED / "places.parquet"
    places = pd.read_parquet(places_path) if places_path.exists() else None

    df = (cells.merge(ookla, on="cell_id", how="left").merge(masts, on="cell_id", how="left")
          .merge(area, on="cell_id", how="left"))
    df = df.merge(Z.ring_speeds(df, ookla[["cell_id", "download_mbps", "tests"]]), on="cell_id")
    print(f"  ring speeds: {time.time() - t0:.0f}s")

    # Criterion (c) needs line of sight; only for cells it could apply to.
    candidates = df[(df.population >= config.GAP_MIN_CELL_POPULATION) & (df.ring_tests < config.GAP_MIN_TESTS)
                    & (df.masts_within_5km.fillna(0) > 0)]
    print(f"  line of sight to up to {config.GAP_SITES_CHECKED} sites for {len(candidates):,} thinly tested cells ...")
    blocked = Z.blocked_to_all(candidates, sites)
    df["blocked_all"] = df.cell_id.map(blocked).fillna(False)
    print(f"  line of sight: {time.time() - t0:.0f}s")

    df = Z.classify(df)
    zones, zone_cells = Z.build(df, history, places)
    zones.to_parquet(ZONES_OUT, index=False)
    zone_cells.to_parquet(CELLS_OUT, index=False)

    uk_median, la_median = O.medians(df)
    df = O.classify(df, uk_median, la_median, float(df.devices_per_1k_pop.quantile(0.9)))
    opp_zones, opp_cells = O.build(df, history, places, uk_median)
    opp_zones.to_parquet(OPP_OUT, index=False)
    opp_cells.to_parquet(OPP_CELLS_OUT, index=False)

    populated = df[df.population >= config.GAP_MIN_CELL_POPULATION]
    print(f"  cells with >= {config.GAP_MIN_CELL_POPULATION} people: {len(populated):,} (poor cells counted before the "
          f"zone threshold of {config.GAP_MIN_ZONE_POPULATION} people)")
    for c in ["slow", "no_site", "blocked", "poor", "site_data_gap"]:
        print(f"    {c:<8} {int(df[c].sum()):>6,} cells, {df.loc[df[c], 'population'].sum() / 1e6:5.2f} m people")
    print(f"  wrote {ZONES_OUT.name}: {len(zones):,} zones; {CELLS_OUT.name}: {len(zone_cells):,} cells "
          f"({time.time() - t0:.0f}s)")
    print(f"  opportunities (UK median {uk_median:.1f} Mbps): " + ", ".join(
        f"{r} {int(df[f'opp_{r}'].sum()):,} cells" for r in O.REASONS)
          + f"; wrote {OPP_OUT.name}: {len(opp_zones):,} zones, {opp_zones.population.sum() / 1e6:.2f} m people, "
          f"{int(opp_zones.limited_data.sum()):,} with limited data")
    print("  largest zones:")
    print(zones.head(10)[["zone_id", "name", "primary_la_name", "n_cells", "population", "severity", "tests"]].to_string(index=False))

    manifest.record(
        "opportunity_zones", title="Improvement opportunities: clusters of populated cells with a measurable weakness",
        data_period=f"built from Ookla {manifest.evidence_meta('ookla_mobile_r7')['data_period']} and mast sites "
                    f"{manifest.evidence_meta('masts_sites')['as_of']}",
        downloaded={}, outputs=[OPP_OUT, OPP_CELLS_OUT], refresh="after Ookla or mast refreshes",
        licence="derived from the sources above (see their licences)",
        extra={"rules": {"shortfall": config.OPP_SHORTFALL, "fall_pct": config.OPP_FALL_PCT,
                         "fall_quarters": config.OPP_FALL_QUARTERS, "capacity_min_pop": config.OPP_CAPACITY_MIN_POP,
                         "capacity_speed": config.OPP_CAPACITY_SPEED, "capacity_fall_pct": config.OPP_CAPACITY_FALL_PCT,
                         "uk_median_mbps": round(uk_median, 1)}},
    )
    manifest.record(
        "zones", title="Gap zones: clusters of poorly served populated cells",
        data_period=f"built from Ookla {manifest.evidence_meta('ookla_mobile_r7')['data_period']} and mast sites "
                    f"{manifest.evidence_meta('masts_sites')['as_of']}",
        downloaded={}, outputs=[ZONES_OUT, CELLS_OUT], refresh="after Ookla or mast refreshes",
        licence="derived from the sources above (see their licences)",
        extra={"rules": {"min_cell_population": config.GAP_MIN_CELL_POPULATION,
                         "min_zone_population": config.GAP_MIN_ZONE_POPULATION, "slow_mbps": config.GAP_SLOW_MBPS,
                         "min_tests": config.GAP_MIN_TESTS, "blocked_m": config.GAP_BLOCKED_M,
                         "sites_checked": config.GAP_SITES_CHECKED}},
    )


if __name__ == "__main__":
    main()
