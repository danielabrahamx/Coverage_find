"""Ookla open data: mobile performance tiles aggregated onto the H3 grid.

Tiles are zoom-16 web-mercator quadkeys (about 350-400 m at UK latitudes). Each tile's centroid
is mapped to an H3 r7 cell; per-cell figures are test-weighted means.
"""

from __future__ import annotations

import math
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from coverage_detective.config import UK_BBOX

COLUMNS = ["quadkey", "avg_d_kbps", "avg_u_kbps", "avg_lat_ms", "tests", "devices"]


def quadkey_centre(quadkey: str) -> tuple[float, float]:
    """(lat, lon) of a quadkey tile's centre."""
    x = y = 0
    for ch in quadkey:
        d = int(ch)
        x = (x << 1) | (d & 1)
        y = (y << 1) | (d >> 1)
    n = 2 ** len(quadkey)
    lon = (x + 0.5) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return lat, lon


def read_uk_tiles(path: Path, quarter: str, resolution: int) -> pd.DataFrame:
    """One quarter's tiles whose centre is in the UK bounding box, with their H3 cell."""
    table = pq.read_table(path)
    names = set(table.column_names)
    has_xy = {"tile_x", "tile_y"} <= names
    df = table.select(COLUMNS + (["tile_x", "tile_y"] if has_xy else [])).to_pandas()
    if has_xy:
        df = df.rename(columns={"tile_x": "lon", "tile_y": "lat"})
    else:
        centres = [quadkey_centre(q) for q in df.quadkey]
        df["lat"] = [c[0] for c in centres]
        df["lon"] = [c[1] for c in centres]
    b = UK_BBOX
    df = df[df.lon.between(b["min_lon"], b["max_lon"]) & df.lat.between(b["min_lat"], b["max_lat"])]
    return pd.DataFrame(
        {
            "quarter": quarter,
            "quadkey": df.quadkey.values,
            "lat": df.lat.values,
            "lon": df.lon.values,
            "cell_id": [h3.latlng_to_cell(la, lo, resolution) for la, lo in zip(df.lat, df.lon)],
            "download_mbps": df.avg_d_kbps.values / 1000.0,
            "upload_mbps": df.avg_u_kbps.values / 1000.0,
            "latency_ms": df.avg_lat_ms.values.astype(float),
            "tests": df.tests.values.astype(int),
            "devices": df.devices.values.astype(int),
        }
    )


def aggregate_cells(tiles: pd.DataFrame) -> pd.DataFrame:
    """Per (cell, quarter): test-weighted mean speeds and latency, total tests, devices, tiles."""
    w = tiles.tests
    t = tiles.assign(
        d=tiles.download_mbps * w, u=tiles.upload_mbps * w, l=tiles.latency_ms * w
    )
    g = t.groupby(["cell_id", "quarter"]).agg(
        d=("d", "sum"), u=("u", "sum"), l=("l", "sum"),
        tests=("tests", "sum"), devices=("devices", "sum"), tiles=("quadkey", "size"),
    )
    out = pd.DataFrame(
        {
            "download_mbps": g.d / g.tests,
            "upload_mbps": g.u / g.tests,
            "latency_ms": g.l / g.tests,
            "tests": g.tests,
            "devices": g.devices,
            "tiles": g.tiles,
        }
    )
    return out.reset_index()


def trend(history: pd.DataFrame) -> pd.DataFrame:
    """Per cell over all quarters present: quarters with data, oldest download, % change
    from oldest to latest, and least-squares slope in Mbps per quarter (>= 3 quarters)."""
    order = {q: i for i, q in enumerate(sorted(history.quarter.unique()))}
    h = history.assign(qi=history.quarter.map(order)).sort_values(["cell_id", "qi"])

    def one(g: pd.DataFrame) -> pd.Series:
        first, last = g.download_mbps.iloc[0], g.download_mbps.iloc[-1]
        slope = np.polyfit(g.qi, g.download_mbps, 1)[0] if len(g) >= 3 else np.nan
        return pd.Series(
            {
                "quarters_with_data": len(g),
                "download_mbps_oldest": first,
                "download_change_pct": 100.0 * (last - first) / first if first > 0 else np.nan,
                "download_trend_mbps_per_quarter": slope,
            }
        )

    return h.groupby("cell_id")[["qi", "download_mbps"]].apply(one).reset_index()
