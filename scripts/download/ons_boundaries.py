"""Download ONS boundary files used to map cells to areas.

    python scripts/download/ons_boundaries.py

From the ONS Open Geography Portal (ArcGIS feature services), as GeoJSON in WGS84, into
data/raw/boundary/; existing files are skipped. Licence: Open Government Licence v3.0;
contains OS data © Crown copyright and database right.

  pcon_2024.geojson   Westminster Parliamentary Constituencies (July 2024), UK BGC
  lad_2024.geojson    Local Authority Districts (December 2024), UK BGC (the codes match
                      Ofcom's July 2025 release; May 2025 is published only as map tiles)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import RAW  # noqa: E402

BASE = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
OUT_DIR = RAW / "boundary"
FILES = {
    "pcon_2024.geojson": ("Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC", "PCON24CD,PCON24NM"),
    "lad_2024.geojson": ("Local_Authority_Districts_December_2024_Boundaries_UK_BGC", "LAD24CD,LAD24NM"),
}


def fetch(service: str, fields: str, client: httpx.Client) -> dict:
    """All features of a layer, paged."""
    url = f"{BASE}/{service}/FeatureServer/0/query"
    features, offset = [], 0
    while True:
        params = {"where": "1=1", "outFields": fields, "outSR": 4326, "f": "geojson",
                  "resultOffset": offset, "resultRecordCount": 100}
        page = client.get(url, params=params).raise_for_status().json()
        if "error" in page:
            raise RuntimeError(f"{service}: {page['error']}")
        features += page["features"]
        if len(page["features"]) < 100:
            return {"type": "FeatureCollection", "features": features}
        offset += 100


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300) as client:
        for name, (service, fields) in FILES.items():
            dest = OUT_DIR / name
            if dest.exists():
                print(f"exists: {dest.name}")
                continue
            print(f"downloading {service} ...", flush=True)
            geo = fetch(service, fields, client)
            dest.write_text(json.dumps(geo))
            print(f"  wrote {dest.name}: {len(geo['features'])} features, {dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
