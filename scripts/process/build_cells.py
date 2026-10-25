"""Phase 1: H3 r7 cells over the UK with WorldPop population.

    python scripts/process/build_cells.py [--force]

Reads data/raw/boundary/uk_countries.geojson and data/raw/population/population.tif,
writes data/processed/cells_r7.parquet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import BOUNDARY_PATH, CELLS_PATH, H3_RES, POPULATION_PATH  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.data.grid import build_cells  # noqa: E402


def check(cells) -> None:
    print(f"cells: {len(cells):,}   populated (>0): {(cells.population > 0).sum():,}")
    print(f"total population: {cells.population.sum() / 1e6:.2f} million")
    by_nation = cells.groupby("nation").agg(cells=("cell_id", "size"), population=("population", "sum"))
    by_nation["population"] = (by_nation.population / 1e6).round(2)
    print(by_nation.rename(columns={"population": "population_m"}).to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even if the output exists")
    args = parser.parse_args()

    missing = [p for p in (BOUNDARY_PATH, POPULATION_PATH) if not p.exists()]
    if missing:
        sys.exit("Missing input file(s):\n  " + "\n  ".join(map(str, missing)))

    if CELLS_PATH.exists() and not args.force:
        import pandas as pd

        print(f"{CELLS_PATH} exists (use --force to rebuild)")
        check(pd.read_parquet(CELLS_PATH))
        return

    cells, dropped = build_cells(BOUNDARY_PATH, POPULATION_PATH, H3_RES)
    for d in dropped:
        print(f"  dropped island: {d['cells']} cell(s), {d['population']:.0f} people near ({d['lat']:.2f}, {d['lon']:.2f})")
    print(f"dropped {len(dropped)} island(s) under 500 people, {sum(d['population'] for d in dropped):,.0f} people in total")
    CELLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(CELLS_PATH, index=False)
    manifest.record(
        "cells", title="H3 r7 grid with WorldPop population and nation",
        data_period="WorldPop 2020 (1 km, UN-adjusted); ONS countries December 2023",
        downloaded={p.name: manifest.file_date(p) for p in (BOUNDARY_PATH, POPULATION_PATH)},
        outputs=[CELLS_PATH], refresh="manual (WorldPop, ONS boundaries)",
        licence="WorldPop CC BY 4.0; ONS boundaries OGL v3.0",
    )
    print(f"wrote {CELLS_PATH}")
    check(cells)


if __name__ == "__main__":
    main()
