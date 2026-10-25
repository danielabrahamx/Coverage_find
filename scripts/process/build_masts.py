"""Phase B: mast sites from OpenCelliD + OpenStreetMap, and mast figures per H3 cell.

    python scripts/download/opencellid.py   # needs OPENCELLID_TOKEN
    python scripts/download/osm.py          # Geofabrik GB + Ireland extracts
    python scripts/process/build_masts.py [--force]

Writes to data/processed/:
  osm_masts.parquet    communication masts extracted from OSM (cached; slow to rebuild)
  masts_sites.parquet  merged sites: site_id, lat, lon, sources (opencellid / osm / both),
                       operators (EE/O2/Vodafone/Three), operator_labels (as in the
                       reference table), radio_types, cell_count, osm_id, osm_operator,
                       mobile_tagged, cell_id
  masts_r7.parquet     per grid cell: nearest mast, masts and operators within 5 km,
                       OSM-only masts within 5 km
  masts_meta.json      inputs and counts

List-like columns are comma-separated strings, which every SQL engine can read.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import H3_RES, PROCESSED, RAW, ROOT, SAMPLE_LOCATIONS  # noqa: E402
from coverage_detective.data.grid import load_cells  # noqa: E402
from coverage_detective.data.masts import masts_per_cell, merge_sites  # noqa: E402
from coverage_detective.sources import osm_masts  # noqa: E402
from coverage_detective.sources.opencellid import MAIN_OPERATORS, cluster_sites, read_cells  # noqa: E402

OCID_DIR = RAW / "opencellid"
OSM_DIR = RAW / "osm"
REFERENCE = ROOT / "data" / "reference" / "mcc_mnc_uk.csv"
GROUPS = ROOT / "data" / "reference" / "operator_groups.csv"
OSM_OUT = PROCESSED / "osm_masts.parquet"
SITES_OUT = PROCESSED / "masts_sites.parquet"
CELLS_OUT = PROCESSED / "masts_r7.parquet"
META_OUT = PROCESSED / "masts_meta.json"


def osm_sites(force: bool) -> pd.DataFrame:
    pbfs = sorted(OSM_DIR.glob("*.osm.pbf"))
    if not pbfs:
        sys.exit(f"No OSM extracts in {OSM_DIR}; run scripts/download/osm.py")
    if OSM_OUT.exists() and not force:
        return pd.read_parquet(OSM_OUT)
    parts = []
    for pbf in pbfs:
        print(f"  extracting masts from {pbf.name} ...", flush=True)
        part = osm_masts.extract(pbf)
        print(f"    {len(part):,} communication masts/towers")
        parts.append(part)
    # GB and Ireland extracts overlap around Northern Ireland: keep each object once.
    df = pd.concat(parts, ignore_index=True).drop_duplicates("osm_id").reset_index(drop=True)
    df.to_parquet(OSM_OUT, index=False)
    return df


def build(force: bool) -> None:
    files = sorted(OCID_DIR.glob("*.csv.gz"))
    if not files:
        sys.exit(f"No OpenCelliD files in {OCID_DIR}; run scripts/download/opencellid.py (needs OPENCELLID_TOKEN)")
    radio_cells, counts = read_cells(files, pd.read_csv(REFERENCE), pd.read_csv(GROUPS))
    print(f"  OpenCelliD: {counts['rows_read']:,} radio cells read, {counts['kept']:,} kept "
          f"({counts['other_radio']:,} other radio types, {counts['outside_bbox']:,} outside the UK bbox)")
    for label, n in sorted(counts["excluded_networks"].items(), key=lambda kv: -kv[1]):
        print(f"    dropped {n:,} cells of non-public/MVNO network {label!r}")
    ocid, _ = cluster_sites(radio_cells)
    print(f"  OpenCelliD: {len(ocid):,} approximate sites (150 m clusters)")

    osm = osm_sites(force)
    print(f"  OSM: {len(osm):,} communication masts/towers ({int(osm.mobile_tagged.sum()):,} tagged mobile)")

    sites = merge_sites(ocid, osm)
    sites["cell_id"] = [h3.latlng_to_cell(la, lo, H3_RES) for la, lo in zip(sites.lat, sites.lon)]
    per_cell = masts_per_cell(load_cells(), sites)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    sites.to_parquet(SITES_OUT, index=False)
    per_cell.to_parquet(CELLS_OUT, index=False)
    inputs = {f.name: date.fromtimestamp(f.stat().st_mtime).isoformat() for f in files + sorted(OSM_DIR.glob("*.osm.pbf"))}
    META_OUT.write_text(json.dumps({"inputs_downloaded": inputs, "opencellid": counts,
                                    "opencellid_sites": len(ocid), "osm_masts": len(osm)}, indent=2))
    print(f"wrote {SITES_OUT.name}, {CELLS_OUT.name}, {META_OUT.name}")


def check() -> None:
    sites = pd.read_parquet(SITES_OUT)
    cells = load_cells().merge(pd.read_parquet(CELLS_OUT), on="cell_id")
    print(f"\nsites: {len(sites):,}")
    print(sites.sources.value_counts().rename_axis("sources").to_frame("sites").to_string())

    print("\nsites per operator (a site can carry several operators):")
    ops = sites.operators.fillna("").str.split(",").explode()
    print(ops[ops.isin(MAIN_OPERATORS)].value_counts().rename_axis("operator").to_frame("sites").to_string())
    print(f"  sites with no main operator identified: {(sites.operators.fillna('') == '').sum():,} "
          f"(mostly OSM masts without operator tags)")

    print("\noriginal OpenCelliD labels behind each group (radio-cell sites):")
    pairs = sites.assign(label=sites.operator_labels.fillna("").str.split(",")).explode("label")
    pairs = pairs[pairs.label != ""]
    print(pairs.label.value_counts().rename_axis("operator_label").to_frame("sites").to_string())

    pop = cells[cells.population > 0]
    q = pop.nearest_mast_km.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
    print(f"\nnearest_mast_km for {len(pop):,} populated cells:")
    print("  " + "  ".join(f"p{int(k * 100)}={v:.2f}" for k, v in q.items()) + f"  max={pop.nearest_mast_km.max():.1f}")
    for km in (2, 5, 10):
        far = pop.nearest_mast_km > km
        print(f"  > {km:>2} km: {far.sum():,} cells, {pop.population[far].sum():,.0f} people")
    print("  people by distinct operators with approximate mast sites within 5 km: " + ", ".join(
        f"{k}: {v / 1e6:.2f} m" for k, v in pop.groupby("distinct_operators_within_5km").population.sum().items()))
    by_status = pop.groupby("operator_data_status").agg(cells=("cell_id", "size"), people=("population", "sum"))
    by_status["people_m"] = (by_status.pop("people") / 1e6).round(2)
    print("\noperator_data_status for populated cells:")
    print(by_status.to_string())

    print("\nsample locations:")
    for name, lat, lon in SAMPLE_LOCATIONS:
        cid = h3.latlng_to_cell(lat, lon, H3_RES)
        r = cells[cells.cell_id == cid]
        if r.empty:
            print(f"  {name}: cell {cid} not in the grid")
            continue
        r = r.iloc[0]
        print(f"  {name} ({cid}): nearest approximate mast site {r.nearest_mast_id} ({r.nearest_mast_sources}) "
              f"{r.nearest_mast_km:.2f} km at {r.nearest_mast_bearing_deg:.0f}°, operators '{r.nearest_mast_operators}'; "
              f"within 5 km: {r.masts_within_5km} sites ({r.masts_known_operator_within_5km} with known operator, "
              f"{r.masts_unknown_operator_within_5km} unknown, {r.masts_osm_only_within_5km} OSM-only), "
              f"{r.distinct_operators_within_5km} operators '{r.operators_within_5km}', status {r.operator_data_status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild, including the OSM extraction")
    args = parser.parse_args()
    if args.force or not (SITES_OUT.exists() and CELLS_OUT.exists()):
        build(args.force)
    check()


if __name__ == "__main__":
    main()
