"""Phase 3: OpenCelliD radio cells -> mast sites -> per-cell mast figures.

    python scripts/download/mcc_mnc.py     # operator reference (committed; only if missing)
    python scripts/download/opencellid.py  # needs OPENCELLID_TOKEN
    python scripts/process/build_masts.py [--force]

Writes data/processed/masts.parquet (one row per approximate site) and
data/processed/masts_r7.parquet (one row per grid cell). Without OpenCelliD files it
prints instructions and exits without failing.

List-like columns (radio_types, operators, operators_within_5km) are comma-separated
strings, which every SQL engine can read.
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

from coverage_detective.config import H3_RES, PROCESSED, RAW, ROOT  # noqa: E402
from coverage_detective.data.grid import load_cells  # noqa: E402
from coverage_detective.sources.opencellid import cluster_sites, masts_per_cell, read_cells  # noqa: E402

RAW_DIR = RAW / "opencellid"
REFERENCE = ROOT / "data" / "reference" / "mcc_mnc_uk.csv"
SITES_OUT = PROCESSED / "masts.parquet"
CELLS_OUT = PROCESSED / "masts_r7.parquet"
META_OUT = PROCESSED / "masts_meta.json"
LANGDALE = (54.445, -3.105)


def build(files: list[Path]) -> None:
    reference = pd.read_csv(REFERENCE)
    radio_cells, counts = read_cells(files, reference)
    print(f"  radio cells: {counts['rows_read']:,} read, {counts['kept']:,} kept")
    print(f"  dropped: {counts['other_radio']:,} other radio types, {counts['outside_bbox']:,} outside the UK bbox")
    for label, n in sorted(counts["excluded_networks"].items(), key=lambda kv: -kv[1]):
        print(f"  dropped {n:,} cells of non-public/MVNO network {label!r}")
    sites, _ = cluster_sites(radio_cells)
    print(f"  clustered into {len(sites):,} approximate sites (150 m)")
    sites["cell_id"] = [h3.latlng_to_cell(la, lo, H3_RES) for la, lo in zip(sites.lat, sites.lon)]

    per_cell = masts_per_cell(load_cells(), sites)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    sites.to_parquet(SITES_OUT, index=False)
    per_cell.to_parquet(CELLS_OUT, index=False)
    downloaded = {f.name: date.fromtimestamp(f.stat().st_mtime).isoformat() for f in files}
    META_OUT.write_text(json.dumps({"downloaded": downloaded, **counts}, indent=2))
    print(f"wrote {SITES_OUT.name}, {CELLS_OUT.name}, {META_OUT.name}")


def check() -> None:
    sites = pd.read_parquet(SITES_OUT)
    per_cell = pd.read_parquet(CELLS_OUT)
    cells = load_cells().merge(per_cell, on="cell_id")
    print(f"sites: {len(sites):,} from {int(sites.cell_count.sum()):,} radio cells")

    print("\nsites per operator (a site can list several operators):")
    per_op = sites.operators.str.split(",").explode().value_counts()
    print(per_op.to_string())

    pop = cells[cells.population > 0]
    q = pop.nearest_mast_km.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
    print(f"\nnearest_mast_km for {len(pop):,} populated cells:")
    print("  " + "  ".join(f"p{int(k * 100)}={v:.2f}" for k, v in q.items()) + f"  max={pop.nearest_mast_km.max():.1f}")
    for km in (2, 5, 10):
        far = pop.nearest_mast_km > km
        print(f"  > {km:>2} km: {far.sum():,} cells, {pop.population[far].sum():,.0f} people")
    print("  distinct_operators_within_5km (people): " + ", ".join(
        f"{k}: {v:,.0f}" for k, v in pop.groupby("distinct_operators_within_5km").population.sum().items()))

    cid = h3.latlng_to_cell(*LANGDALE, H3_RES)
    row = cells[cells.cell_id == cid]
    print(f"\nGreat Langdale {LANGDALE} -> cell {cid}")
    if row.empty:
        print("  not in the grid")
    else:
        r = row.iloc[0]
        print(
            f"  nearest mast {r.nearest_mast_id}: {r.nearest_mast_km:.2f} km at {r.nearest_mast_bearing_deg:.0f}°, "
            f"operators {r.nearest_mast_operators}"
        )
        print(f"  masts within 5 km: {r.masts_within_5km}; operators within 5 km ({r.distinct_operators_within_5km}): {r.operators_within_5km or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even if the outputs exist")
    args = parser.parse_args()
    files = sorted(RAW_DIR.glob("*.csv.gz"))
    if not files and not SITES_OUT.exists():
        print(f"No OpenCelliD files in {RAW_DIR}; skipping Phase 3.")
        print("Run: python scripts/download/opencellid.py  (needs OPENCELLID_TOKEN in .env)")
        return
    if files and (args.force or not (SITES_OUT.exists() and CELLS_OUT.exists())):
        build(files)
    check()


if __name__ == "__main__":
    main()
