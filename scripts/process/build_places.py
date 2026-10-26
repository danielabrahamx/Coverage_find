"""OSM named places -> data/processed/places.parquet (name, place type, rank, lat, lon, cell_id).

    python scripts/process/build_places.py

Needs the Geofabrik extracts from scripts/download/osm.py. Used to name gap zones.
"""

from __future__ import annotations

import sys
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import H3_RES, PROCESSED, RAW  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.sources.osm_places import extract  # noqa: E402

FILES = [RAW / "osm" / "great-britain-latest.osm.pbf", RAW / "osm" / "ireland-and-northern-ireland-latest.osm.pbf"]
OUT = PROCESSED / "places.parquet"


def main() -> None:
    parts = [extract(f) for f in FILES if f.exists()]
    if not parts:
        sys.exit("No OSM extracts in data/raw/osm/; run scripts/download/osm.py")
    df = pd.concat(parts)
    # The extracts overlap a little at the borders: drop the same place twice, not same-named places.
    df = df.assign(_k=df.lat.round(3).astype(str) + df.lon.round(3).astype(str)).drop_duplicates(["name", "place", "_k"])
    df = df.drop(columns="_k").reset_index(drop=True)
    df["cell_id"] = [h3.latlng_to_cell(a, b, H3_RES) for a, b in zip(df.lat, df.lon)]
    df.to_parquet(OUT, index=False)
    print(f"wrote {OUT.name}: {len(df):,} places; " + ", ".join(f"{k} {v:,}" for k, v in df.place.value_counts().items()))
    manifest.record(
        "places", title="OpenStreetMap named places (city, town, village, hamlet)",
        data_period=f"OSM extracts downloaded {manifest.file_date(FILES[0])}",
        downloaded={f.name: manifest.file_date(f) for f in FILES if f.exists()}, outputs=[OUT],
        refresh="with the OSM extracts (monthly)", licence="ODbL 1.0, (c) OpenStreetMap contributors",
    )


if __name__ == "__main__":
    main()
