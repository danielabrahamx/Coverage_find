"""OpenStreetMap: communication masts and towers from Geofabrik extracts.

Kept: nodes and closed ways tagged as
  man_made=mast|tower with tower:type=communication, man_made=communications_tower,
  or communication:mobile_phone=yes (on anything).
OSM positions are mapped by people, so usually closer to the real structure than
OpenCelliD's estimates, but many towers carry only broadcast (TV/radio) or private radio,
and operator tags are sparse. `mobile_tagged` marks objects with a mobile-phone tag or a
recognised mobile operator.
"""

from __future__ import annotations

import re
from pathlib import Path

import osmium
import pandas as pd

from coverage_detective.config import UK_BBOX

# Operator tag text -> operator groups. Shared-infrastructure companies host two networks:
# MBNL = EE + Three; Cornerstone / CTIL / Beacon = O2 + Vodafone.
OPERATOR_PATTERNS = [
    (r"\bMBNL\b|Mobile Broadband Network", ("EE", "Three")),
    (r"Cornerstone|\bCTIL\b|\bBeacon\b", ("O2", "Vodafone")),
    (r"VodafoneThree|Vodafone ?Three", ("Vodafone", "Three")),
    (r"\bEE\b|Everything Everywhere|T-Mobile|\bOrange\b", ("EE",)),
    (r"\bO2\b|Telef[oó]nica|Virgin Media O2", ("O2",)),
    (r"Vodafone", ("Vodafone",)),
    (r"\bThree\b|\b3 UK\b|Hutchison", ("Three",)),
]


def operator_groups(text: str | None) -> list[str]:
    """Mobile operator groups named in an OSM operator tag (empty if none recognised)."""
    if not text:
        return []
    found: set[str] = set()
    for pattern, groups in OPERATOR_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE if pattern.startswith("Voda") else 0):
            found.update(groups)
    return sorted(found)


def is_comms_mast(tags) -> bool:
    man_made = tags.get("man_made")
    return (
        (man_made in ("mast", "tower") and tags.get("tower:type") == "communication")
        or man_made == "communications_tower"
        or tags.get("communication:mobile_phone") == "yes"
    )


def _record(kind: str, osm_id: int, tags, lat: float, lon: float) -> dict:
    operator = tags.get("operator")
    groups = operator_groups(operator)
    return {
        "osm_id": f"{kind}/{osm_id}",
        "lat": lat,
        "lon": lon,
        "man_made": tags.get("man_made"),
        "osm_operator": operator,
        "operators": ",".join(groups),
        "mobile_tagged": tags.get("communication:mobile_phone") == "yes" or bool(groups),
        "height_m": tags.get("height"),
    }


def extract(path: Path) -> pd.DataFrame:
    """Communication masts in one .osm.pbf file, as points (ways -> mean of their nodes).

    Two light passes instead of a full node-location index: first the tagged nodes and
    ways, then the coordinates of just the nodes those ways use.
    """
    rows, ways = [], {}
    keys = osmium.filter.KeyFilter("man_made", "communication:mobile_phone")
    for obj in osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY).with_filter(keys):
        if not is_comms_mast(obj.tags):
            continue
        if obj.is_node():
            rows.append(_record("node", obj.id, obj.tags, obj.location.lat, obj.location.lon))
        else:
            ways[obj.id] = ([n.ref for n in obj.nodes], dict(obj.tags))

    needed = {ref for refs, _ in ways.values() for ref in refs}
    coords = {}
    if needed:
        ids = osmium.filter.IdFilter(needed)
        for node in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(ids):
            coords[node.id] = (node.location.lat, node.location.lon)
    for way_id, (refs, tags) in ways.items():
        pts = [coords[r] for r in refs if r in coords]
        if pts:
            lat = sum(p[0] for p in pts) / len(pts)
            lon = sum(p[1] for p in pts) / len(pts)
            rows.append(_record("way", way_id, tags, lat, lon))

    df = pd.DataFrame(rows)
    b = UK_BBOX
    return df[df.lon.between(b["min_lon"], b["max_lon"]) & df.lat.between(b["min_lat"], b["max_lat"])]
