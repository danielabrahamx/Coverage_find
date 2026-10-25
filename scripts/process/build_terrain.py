"""Terrain per H3 r7 cell and line of sight from each populated cell centre to its nearest site.

    python scripts/process/build_terrain.py           # skips outputs that exist
    python scripts/process/build_terrain.py --force
    python scripts/process/build_terrain.py --los     # rebuild only los_r7 (after the mast tables change)

Inputs: Copernicus DEM GLO-30 tiles (scripts/download/dem.py), cells_r7, masts_r7.
Writes:
  terrain_r7.parquet  elevation mean / min / max / range / std per cell, sampled at the
                      centres of the cell's 343 H3 r10 children (~120 m apart)
  los_r7.parquet      populated cells only: line of sight from the cell centre (1.5 m above
                      ground) to the nearest approximate mast site (antenna height from
                      Ofcom's register when known, else 25 m). For the map; the evidence
                      API computes from the exact point instead. los_class: clear, marginal
                      (blocked by < 10 m: may be trees or buildings in the surface model) or
                      blocked (>= 10 m).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import CELLS_PATH, PROCESSED  # noqa: E402
from coverage_detective.data import manifest, terrain  # noqa: E402

TERRAIN_OUT = PROCESSED / "terrain_r7.parquet"
LOS_OUT = PROCESSED / "los_r7.parquet"
CHILD_RES = 10
# Obstructions under this height may be trees or buildings in the surface model, not terrain.
MARGINAL_M = 10.0
BATCH = 500  # cells per DEM lookup


def tile_order(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by DEM tile so few tiles are in memory at once."""
    return df.assign(_t=np.floor(df.lat) * 1000 + np.floor(df.lon)).sort_values(["_t", "lat"]).drop(columns="_t")


def build_terrain(cells: pd.DataFrame) -> pd.DataFrame:
    dem = terrain.dem()
    rows = []
    ordered = tile_order(cells)
    t0 = time.time()
    for start in range(0, len(ordered), BATCH):
        batch = ordered.cell_id.iloc[start:start + BATCH].tolist()
        children = [h3.cell_to_children(c, CHILD_RES) for c in batch]
        pts = np.array([h3.cell_to_latlng(ch) for kids in children for ch in kids])
        z = dem.elevation(pts[:, 0], pts[:, 1])
        i = 0
        for cid, kids in zip(batch, children):
            e = z[i:i + len(kids)]
            i += len(kids)
            rows.append((cid, float(e.mean()), float(e.min()), float(e.max()), float(e.std()), len(kids)))
        if start // BATCH % 20 == 0:
            print(f"    terrain {start + len(batch):,}/{len(ordered):,} cells  {time.time() - t0:.0f}s")
    out = pd.DataFrame(rows, columns=["cell_id", "elevation_mean_m", "elevation_min_m", "elevation_max_m",
                                      "elevation_std_m", "samples"])
    out["elevation_range_m"] = out.elevation_max_m - out.elevation_min_m
    for c in ["elevation_mean_m", "elevation_min_m", "elevation_max_m", "elevation_std_m", "elevation_range_m"]:
        out[c] = out[c].round(1)
    return out.sort_values("cell_id").reset_index(drop=True)


def build_los(cells: pd.DataFrame, masts: pd.DataFrame) -> pd.DataFrame:
    df = cells[cells.population > 0].merge(
        masts[["cell_id", "nearest_mast_id", "nearest_mast_lat", "nearest_mast_lon", "nearest_mast_km",
               "nearest_mast_antenna_height_m"]], on="cell_id")
    rows = []
    t0 = time.time()
    for n, r in enumerate(tile_order(df).itertuples(index=False)):
        los = terrain.line_of_sight(r.lat, r.lon, r.nearest_mast_lat, r.nearest_mast_lon,
                                    mast_height=r.nearest_mast_antenna_height_m)
        rows.append((r.cell_id, r.nearest_mast_id, los["blocked"], los["max_obstruction_m"],
                     los["obstruction_distance_m"], los["obstruction_lat"], los["obstruction_lon"],
                     los["path_length_m"], los["rx_ground_m"], los["site_ground_m"], los["mast_height_m"],
                     los["mast_height_source"]))
        if n % 10_000 == 0:
            print(f"    line of sight {n:,}/{len(df):,} cells  {time.time() - t0:.0f}s")
    out = pd.DataFrame(rows, columns=[
        "cell_id", "site_id", "blocked", "obstruction_m", "obstruction_distance_m", "obstruction_lat",
        "obstruction_lon", "path_length_m", "rx_ground_m", "site_ground_m", "mast_height_m",
        "mast_height_source"])
    out["los_class"] = np.select([~out.blocked, out.obstruction_m < MARGINAL_M], ["clear", "marginal"], "blocked")
    return out.sort_values("cell_id").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--los", action="store_true", help="rebuild only los_r7")
    args = parser.parse_args()
    if not any(terrain.DEM_DIR.glob("*.tif")):
        sys.exit(f"No DEM tiles in {terrain.DEM_DIR}; run scripts/download/dem.py")
    cells = pd.read_parquet(CELLS_PATH)

    if (args.force and not args.los) or not TERRAIN_OUT.exists():
        print("  terrain_r7 ...")
        t = build_terrain(cells)
        t.to_parquet(TERRAIN_OUT, index=False)
        print(f"  wrote {TERRAIN_OUT.name}: {len(t):,} cells; elevation range median "
              f"{t.elevation_range_m.median():.0f} m, max {t.elevation_range_m.max():.0f} m")
    if args.force or args.los or not LOS_OUT.exists():
        print("  los_r7 ...")
        los = build_los(cells, pd.read_parquet(PROCESSED / "masts_r7.parquet"))
        los.to_parquet(LOS_OUT, index=False)
        pop = cells.set_index("cell_id").population
        blocked = los[los.blocked]
        print("  " + ", ".join(f"{k} {v:,}" for k, v in los.los_class.value_counts().items()))
        print(f"  wrote {LOS_OUT.name}: {len(los):,} populated cells; blocked {len(blocked):,} "
              f"({len(blocked) / len(los):.1%}), {pop[blocked.cell_id].sum() / 1e6:.2f} m people; "
              f"antenna height from Ofcom's register for {(los.mast_height_source == 'ofcom_register').mean():.1%}")

    tiles = sorted(terrain.DEM_DIR.glob("*.tif"))
    manifest.record(
        "terrain", title="Copernicus DEM GLO-30: terrain per cell and line of sight to the nearest site",
        data_period="Copernicus DEM GLO-30 (2021 release; source data 2011-2015)",
        downloaded={"dem_tiles": manifest.file_date(tiles[0])},
        outputs=[TERRAIN_OUT, LOS_OUT], refresh="manual (static); los_r7 after mast tables change",
        licence="Copernicus DEM licence: free, attribution required. (c) DLR e.V. 2010-2014 and (c) Airbus "
                "Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA",
        extra={"tiles": len(tiles), "default_mast_height_m": terrain.DEFAULT_MAST_HEIGHT_M,
               "rx_height_m": terrain.RX_HEIGHT_M, "marginal_below_m": MARGINAL_M, "k_factor": "4/3", "sample_spacing_m": terrain.SAMPLE_SPACING_M},
    )


if __name__ == "__main__":
    main()
