"""Phase 2: Ookla mobile speeds per H3 r7 cell, with the previous quarters for trends.

    python scripts/download/ookla.py      # first
    python scripts/process/build_ookla.py [--force]

Writes to data/processed/:
  ookla_mobile_r7.parquet          latest quarter per cell, tests/devices per 1,000 people,
                                   and the trend over all downloaded quarters
  ookla_mobile_history_r7.parquet  one row per (cell, quarter)
  ookla_mobile_tiles.parquet       UK tiles (~600 m) for every quarter, with their r7 cell
  ookla_meta.json                  quarters used
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import H3_RES, PROCESSED, RAW  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.data.grid import load_cells  # noqa: E402
from coverage_detective.sources.ookla import aggregate_cells, read_uk_tiles, trend  # noqa: E402

RAW_DIR = RAW / "ookla"
CELLS_OUT = PROCESSED / "ookla_mobile_r7.parquet"
HISTORY_OUT = PROCESSED / "ookla_mobile_history_r7.parquet"
TILES_OUT = PROCESSED / "ookla_mobile_tiles.parquet"
META_OUT = PROCESSED / "ookla_meta.json"
QUARTERS = 4  # latest quarter plus the previous three, for trends


def build() -> None:
    files = sorted(RAW_DIR.glob("*_mobile_tiles_uk.parquet"))[-QUARTERS:]
    if not files:
        sys.exit(f"No Ookla files in {RAW_DIR}; run scripts/download/ookla.py")
    cells = load_cells()
    grid = set(cells.cell_id)

    tiles = []
    for f in files:
        quarter = f.name.split("_")[0]
        t = read_uk_tiles(f, quarter, H3_RES)
        t = t[t.cell_id.isin(grid)]  # drops Ireland, France, sea
        print(f"  {quarter}: {len(t):,} UK tiles, {t.tests.sum():,} tests")
        tiles.append(t)
    tiles = pd.concat(tiles, ignore_index=True)
    quarters = sorted(tiles.quarter.unique())
    latest_q = quarters[-1]

    history = aggregate_cells(tiles)
    latest = history[history.quarter == latest_q].drop(columns="quarter")
    latest = latest.merge(cells[["cell_id", "population"]], on="cell_id", how="left")
    per_k = latest.population.where(latest.population >= 1) / 1000.0
    latest["tests_per_1k_pop"] = latest.tests / per_k
    latest["devices_per_1k_pop"] = latest.devices / per_k
    latest = latest.drop(columns="population").merge(trend(history), on="cell_id", how="left")
    latest.insert(1, "quarter", latest_q)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    latest.to_parquet(CELLS_OUT, index=False)
    history.to_parquet(HISTORY_OUT, index=False)
    tiles.to_parquet(TILES_OUT, index=False)
    META_OUT.write_text(json.dumps({"latest_quarter": latest_q, "quarters": quarters}, indent=2))
    manifest.record(
        "ookla", title="Ookla open data, mobile performance tiles", data_period=latest_q,
        downloaded={f.name: manifest.file_date(f) for f in files},
        outputs=[CELLS_OUT, HISTORY_OUT, TILES_OUT], refresh="quarterly (new quarter in ookla-open-data)",
        licence="CC BY-NC-SA 4.0", extra={"quarters": quarters},
    )
    print(f"wrote {CELLS_OUT.name}, {HISTORY_OUT.name}, {TILES_OUT.name}, {META_OUT.name}")


def check() -> None:
    meta = json.loads(META_OUT.read_text())
    cells = load_cells()
    ookla = pd.read_parquet(CELLS_OUT)
    df = cells.merge(ookla, on="cell_id", how="left")
    populated = df[df.population > 0]
    with_data = populated.tests.notna()
    print(f"latest quarter: {meta['latest_quarter']}   trend quarters: {', '.join(meta['quarters'])}")
    print(
        f"populated cells with Ookla data: {with_data.sum():,} / {len(populated):,} "
        f"({with_data.mean():.1%}), covering {populated.population[with_data].sum() / populated.population.sum():.1%} of people"
    )
    d = populated[with_data]
    print(f"UK median download (populated cells with data): {d.download_mbps.median():.1f} Mbps")
    weighted = (d.download_mbps * d.tests).sum() / d.tests.sum()
    print(f"UK test-weighted mean download: {weighted:.1f} Mbps over {int(d.tests.sum()):,} tests")
    trend_cells = d.download_trend_mbps_per_quarter.notna()
    print(
        f"cells with a trend (>= 3 quarters): {trend_cells.sum():,}; "
        f"median trend {d.download_trend_mbps_per_quarter.median():+.2f} Mbps/quarter"
    )
    cols = ["cell_id", "nation", "lat", "lon", "population", "download_mbps", "upload_mbps", "latency_ms", "tests", "devices"]
    fmt = {"lat": "{:.3f}".format, "lon": "{:.3f}".format, "population": "{:.0f}".format,
           "download_mbps": "{:.2f}".format, "upload_mbps": "{:.2f}".format, "latency_ms": "{:.0f}".format}
    print("\n10 slowest populated cells:")
    print(d.nsmallest(10, "download_mbps")[cols].to_string(index=False, formatters=fmt))
    print("\n10 slowest populated cells with >= 10 tests and >= 100 people:")
    solid = d[(d.tests >= 10) & (d.population >= 100)]
    print(solid.nsmallest(10, "download_mbps")[cols].to_string(index=False, formatters=fmt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even if the outputs exist")
    args = parser.parse_args()
    if args.force or not all(p.exists() for p in (CELLS_OUT, HISTORY_OUT, TILES_OUT, META_OUT)):
        build()
    else:
        print(f"{CELLS_OUT.name} exists (use --force to rebuild)")
    check()


if __name__ == "__main__":
    main()
