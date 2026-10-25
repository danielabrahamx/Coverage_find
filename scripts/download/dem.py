"""Download the Copernicus DEM GLO-30 tiles covering the UK.

    python scripts/download/dem.py

Source: public AWS bucket `copernicus-dem-30m` (no account), one 1°x1° Cloud-Optimised
GeoTIFF per tile, 1 arc-second (~30 m). Tiles that are all sea do not exist and are
skipped. Files land in data/raw/dem/; existing files are skipped.
Licence: Copernicus DEM licence (free of charge, worldwide, attribution required):
"© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under
COPERNICUS by the European Union and ESA; all rights reserved".
"""

from __future__ import annotations

import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import RAW, UK_BBOX  # noqa: E402

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
OUT_DIR = RAW / "dem"


def tile_name(lat: int, lon: int) -> str:
    ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
    ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def fetch(name: str, client: httpx.Client) -> str:
    dest = OUT_DIR / f"{name}.tif"
    if dest.exists():
        return "exists"
    r = client.get(f"{BUCKET}/{name}/{name}.tif")
    if r.status_code in (403, 404):  # no tile: all sea
        return "none"
    r.raise_for_status()
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.rename(dest)
    return "downloaded"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    b = UK_BBOX
    names = [
        tile_name(lat, lon)
        for lat in range(math.floor(b["min_lat"]), math.floor(b["max_lat"]) + 1)
        for lon in range(math.floor(b["min_lon"]), math.floor(b["max_lon"]) + 1)
    ]
    counts: dict[str, int] = {}
    with httpx.Client(timeout=300) as client, ThreadPoolExecutor(max_workers=4) as pool:
        for name, result in zip(names, pool.map(lambda n: fetch(n, client), names)):
            counts[result] = counts.get(result, 0) + 1
            if result == "downloaded":
                print(f"  {name}", flush=True)
    print(f"done: {counts} of {len(names)} tiles in the UK bounding box")


if __name__ == "__main__":
    main()
