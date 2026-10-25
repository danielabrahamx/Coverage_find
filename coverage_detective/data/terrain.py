"""Terrain from the Copernicus DEM GLO-30, and line of sight from a point to a mast site.

The DEM is a surface model (DSM): it includes some trees and buildings, so it is most
reliable for hills and valleys, and least in towns and woods. Tiles are 1°x1° GeoTIFFs in
data/raw/dem/ (1 arc-second; above 50°N the longitude spacing is wider, read from each
tile). Missing tiles are all sea and read as 0 m.

line_of_sight() answers "does the ground rise above the straight radio path?":
  - the path runs from the receiver (rx_height above ground, 1.5 m = a phone in a hand) to
    the antenna (mast_height above the ground at the site), sampled every ~30 m;
  - earth curvature: the ground at distance d1 from one end and d2 from the other is raised
    by d1*d2 / (2*k*R), with k = 4/3 (the standard allowance for radio bending in air);
  - obstruction at a sample = ground + curvature bulge - line height; the largest one is
    reported (negative = the line clears all ground by that much). blocked = it is > 0.
Blocked means a weaker signal (diffraction over the ridge), not no signal. Fresnel-zone
clearance, clutter and the real antenna heights of most sites are not modelled: when Ofcom's
register gives no antenna height, DEFAULT_MAST_HEIGHT_M is assumed.
"""

from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np
import rasterio

from coverage_detective.config import RAW

DEM_DIR = RAW / "dem"
SAMPLE_SPACING_M = 30.0
EARTH_RADIUS_M = 6_371_000.0
K_FACTOR = 4 / 3
DEFAULT_MAST_HEIGHT_M = 25.0
RX_HEIGHT_M = 1.5
MAX_TILES_IN_MEMORY = 4   # each tile is 13-52 MB


def tile_name(lat: int, lon: int) -> str:
    ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
    ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


class DEM:
    """Bilinear elevation sampling over the tile set, keeping a few tiles in memory."""

    def __init__(self, directory=DEM_DIR, max_tiles: int = MAX_TILES_IN_MEMORY):
        self.directory = directory
        self.max_tiles = max_tiles
        self._tiles: OrderedDict[tuple[int, int], tuple | None] = OrderedDict()

    def _tile(self, key: tuple[int, int]):
        if key in self._tiles:
            self._tiles.move_to_end(key)
            return self._tiles[key]
        path = self.directory / f"{tile_name(*key)}.tif"
        tile = None
        if path.exists():
            with rasterio.open(path) as src:
                # Pixel-centre geometry: column c is centred at west + (c + 0.5) * dx.
                t = src.transform
                tile = (src.read(1).astype(np.float32), t.c, t.f, t.a, -t.e)
        self._tiles[key] = tile
        while len(self._tiles) > self.max_tiles:
            self._tiles.popitem(last=False)
        return tile

    def elevation(self, lats, lons) -> np.ndarray:
        lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
        out = np.zeros(lats.shape, dtype=np.float32)
        tlat, tlon = np.floor(lats).astype(int), np.floor(lons).astype(int)
        for key in set(zip(tlat.tolist(), tlon.tolist())):
            idx = (tlat == key[0]) & (tlon == key[1])
            tile = self._tile(key)
            if tile is None:
                continue  # sea
            z, west, north, dx, dy = tile
            col = (lons[idx] - west) / dx - 0.5
            row = (north - lats[idx]) / dy - 0.5
            c0 = np.clip(np.floor(col).astype(int), 0, z.shape[1] - 2)
            r0 = np.clip(np.floor(row).astype(int), 0, z.shape[0] - 2)
            fc, fr = np.clip(col - c0, 0, 1), np.clip(row - r0, 0, 1)
            out[idx] = ((z[r0, c0] * (1 - fc) + z[r0, c0 + 1] * fc) * (1 - fr)
                        + (z[r0 + 1, c0] * (1 - fc) + z[r0 + 1, c0 + 1] * fc) * fr)
        return out


_dem: DEM | None = None


def dem() -> DEM:
    global _dem
    if _dem is None:
        _dem = DEM()
    return _dem


def distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def line_of_sight(lat: float, lon: float, site_lat: float, site_lon: float, rx_height: float = RX_HEIGHT_M,
                  mast_height: float | None = None, spacing_m: float = SAMPLE_SPACING_M,
                  source: DEM | None = None) -> dict:
    """Line of sight from a receiver at (lat, lon) to an antenna at the site.

    mast_height: the antenna height above ground (Ofcom register) or None for the default.
    """
    source = source or dem()
    height_source = "ofcom_register" if mast_height is not None and not np.isnan(mast_height) else "assumed_default"
    mast_height = float(mast_height) if height_source == "ofcom_register" else DEFAULT_MAST_HEIGHT_M
    length = float(distance_m(lat, lon, site_lat, site_lon))
    n = max(2, int(math.ceil(length / spacing_m)) + 1)
    f = np.linspace(0.0, 1.0, n)
    lats, lons = lat + (site_lat - lat) * f, lon + (site_lon - lon) * f  # straight enough under ~50 km
    ground = source.elevation(lats, lons).astype(float)
    d = f * length
    bulge = d * (length - d) / (2 * K_FACTOR * EARTH_RADIUS_M)
    start, end = ground[0] + rx_height, ground[-1] + mast_height
    line = start + (end - start) * f
    obstruction = ground + bulge - line
    inner = slice(1, n - 1)  # the two ends stand on their own ground
    if n > 2:
        i = 1 + int(np.argmax(obstruction[inner]))
        worst = float(obstruction[i])
    else:
        i, worst = 0, float("-inf")
    return {
        "blocked": bool(worst > 0),
        "max_obstruction_m": round(worst, 1) if np.isfinite(worst) else None,
        "obstruction_distance_m": round(float(d[i]), 0) if n > 2 else None,
        "obstruction_lat": round(float(lats[i]), 6) if n > 2 else None,
        "obstruction_lon": round(float(lons[i]), 6) if n > 2 else None,
        "obstruction_ground_m": round(float(ground[i]), 1) if n > 2 else None,
        "path_length_m": round(length, 0),
        "rx_ground_m": round(float(ground[0]), 1),
        "site_ground_m": round(float(ground[-1]), 1),
        "rx_height_m": rx_height,
        "mast_height_m": mast_height,
        "mast_height_source": height_source,
        "samples": n,
        "profile": {"distance_m": [round(float(x), 0) for x in d], "ground_m": [round(float(x), 1) for x in ground],
                    "line_m": [round(float(x - b), 1) for x, b in zip(line, bulge)]},
    }

