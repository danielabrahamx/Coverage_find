"""Named places from OpenStreetMap (place=city/town/village/hamlet nodes), for naming gap zones.

A zone is named after its largest place: city > town > village > hamlet, then by the OSM
`population` tag where present. © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

from pathlib import Path

import osmium
import pandas as pd

from coverage_detective.config import UK_BBOX

PLACE_RANK = {"city": 4, "town": 3, "village": 2, "hamlet": 1}


def _population(tags) -> float | None:
    raw = (tags.get("population") or "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def extract(path: Path) -> pd.DataFrame:
    rows = []
    for node in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("place")):
        kind = node.tags.get("place")
        name = node.tags.get("name:en") or node.tags.get("name")
        if kind in PLACE_RANK and name:
            rows.append((name, kind, PLACE_RANK[kind], _population(node.tags), node.location.lat, node.location.lon))
    df = pd.DataFrame(rows, columns=["name", "place", "rank", "population_tag", "lat", "lon"])
    b = UK_BBOX
    return df[df.lat.between(b["min_lat"], b["max_lat"]) & df.lon.between(b["min_lon"], b["max_lon"])]
