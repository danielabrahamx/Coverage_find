"""H3 grid over the UK, with WorldPop population and nation per cell."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
from rasterio.warp import transform_geom

from coverage_detective.config import CELLS_PATH


def load_nations(path: Path) -> gpd.GeoDataFrame:
    """The boundary file as one row per nation, columns `nation` and `geometry`, in WGS84.

    ONS files name the column after the vintage (CTRY23NM, CTRY24NM, ...), so take
    the first column ending in NM.
    """
    gdf = gpd.read_file(path).to_crs("EPSG:4326")
    name_col = next(c for c in gdf.columns if c.upper().startswith("CTRY") and c.upper().endswith("NM"))
    gdf = gdf.rename(columns={name_col: "nation"})[["nation", "geometry"]]
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf.dissolve("nation", as_index=False)


def covering_cells(geometry, resolution: int) -> set[str]:
    """Every cell that overlaps the geometry, so coastal cells are kept."""
    shape = h3.geo_to_h3shape(geometry.__geo_interface__)
    return set(h3.h3shape_to_cells_experimental(shape, resolution, contain="overlap"))


def population_by_cell(raster_path: Path, geometry, resolution: int) -> pd.Series:
    """Sum of raster pixels inside the geometry, grouped by the H3 cell of each pixel centre."""
    with rasterio.open(raster_path) as src:
        geom = geometry.__geo_interface__
        if src.crs and src.crs.to_epsg() != 4326:
            geom = transform_geom("EPSG:4326", src.crs, geom)
        data, transform = rasterio.mask.mask(src, [geom], crop=True, filled=False)
        band = data[0]
        values = np.ma.getdata(band).astype(float)
        keep = ~np.ma.getmaskarray(band) & np.isfinite(values) & (values > 0)
        if src.nodata is not None:
            keep &= values != src.nodata
        rows, cols = np.nonzero(keep)
        xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
        if src.crs and src.crs.to_epsg() != 4326:
            from rasterio.warp import transform as warp_transform

            xs, ys = warp_transform(src.crs, "EPSG:4326", xs, ys)
    cells = [h3.latlng_to_cell(lat, lon, resolution) for lon, lat in zip(xs, ys)]
    return pd.Series(values[rows, cols]).groupby(pd.Series(cells)).sum()


def connected_groups(cell_ids) -> list[set[str]]:
    """Groups of cells joined through H3 neighbours (islands, in practice)."""
    remaining = set(cell_ids)
    groups = []
    while remaining:
        start = remaining.pop()
        group = {start}
        queue = deque([start])
        while queue:
            for nb in h3.grid_ring(queue.popleft(), 1):
                if nb in remaining:
                    remaining.remove(nb)
                    group.add(nb)
                    queue.append(nb)
        groups.append(group)
    return groups


def build_cells(
    boundary_path: Path, raster_path: Path, resolution: int, min_island_population: float = 500
) -> tuple[pd.DataFrame, list[dict]]:
    """Cells covering the boundary with population and nation, minus small islands.

    A cell on a national border goes to the nation with most of its people (or,
    with nobody, the nation containing its centre). Returns the cells and a list
    of dropped islands.
    """
    nations = load_nations(boundary_path)
    rows = []
    for nation, geom in zip(nations.nation, nations.geometry):
        pop = population_by_cell(raster_path, geom, resolution)
        for cid in covering_cells(geom, resolution) | set(pop.index):
            lat, lon = h3.cell_to_latlng(cid)
            centre_inside = geom.contains(gpd.points_from_xy([lon], [lat])[0])
            rows.append((cid, nation, float(pop.get(cid, 0.0)), centre_inside))
    parts = pd.DataFrame(rows, columns=["cell_id", "nation", "population", "centre_inside"])

    totals = parts.groupby("cell_id")["population"].sum()
    owner = (
        parts.sort_values(["population", "centre_inside"], ascending=False)
        .drop_duplicates("cell_id")
        .set_index("cell_id")["nation"]
    )
    cells = pd.DataFrame({"population": totals, "nation": owner}).reset_index(names="cell_id")

    dropped = []
    pop = dict(zip(cells.cell_id, cells.population))
    for group in connected_groups(cells.cell_id):
        total = sum(pop[c] for c in group)
        if total < min_island_population:
            lat, lon = h3.cell_to_latlng(min(group))
            dropped.append({"cells": len(group), "population": total, "lat": lat, "lon": lon})
            cells = cells[~cells.cell_id.isin(group)]

    latlon = [h3.cell_to_latlng(c) for c in cells.cell_id]
    cells = cells.assign(lat=[p[0] for p in latlon], lon=[p[1] for p in latlon])
    cells = cells[["cell_id", "lat", "lon", "population", "nation"]]
    return cells.sort_values("cell_id").reset_index(drop=True), dropped


def load_cells() -> pd.DataFrame:
    if not CELLS_PATH.exists():
        raise FileNotFoundError(f"{CELLS_PATH} missing; run scripts/process/build_cells.py")
    return pd.read_parquet(CELLS_PATH)
