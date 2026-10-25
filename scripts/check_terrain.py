"""Phase C check: terrain and line of sight at the sample places and a flat Fens village.

    python scripts/check_terrain.py

For each place: line of sight from the exact point (1.5 m) to its nearest approximate mast
site, with the obstruction height and where it is; then the cell's rows in CD_TERRAIN and
CD_LOS through Zetaris (the precomputed, cell-centre version used by the map).
"""

from __future__ import annotations

import sys
from pathlib import Path

import h3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.config import PROCESSED, SAMPLE_LOCATIONS  # noqa: E402
from coverage_detective.data import terrain  # noqa: E402
from coverage_detective.data.masts import bearing_deg  # noqa: E402
from coverage_detective.data.zetaris import ZetarisError, query  # noqa: E402
from coverage_detective.sources import geocode  # noqa: E402

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
FLAT_VILLAGE = "Sutton St Edmund"  # Lincolnshire Fens, a few metres above sea level


def places() -> list[tuple[str, float, float]]:
    out = list(SAMPLE_LOCATIONS)
    hit = geocode.lookup(FLAT_VILLAGE).data["results"]
    out.append((f"{FLAT_VILLAGE}, Lincolnshire", hit[0]["lat"], hit[0]["lon"]) if hit
               else (f"{FLAT_VILLAGE}, Lincolnshire (fallback coords)", 52.7311, 0.0306))
    return out


def nearest_site(sites: pd.DataFrame, lat: float, lon: float) -> pd.Series:
    d = terrain.distance_m(lat, lon, sites.lat.to_numpy(), sites.lon.to_numpy())
    return sites.iloc[int(np.argmin(d))]


def main() -> None:
    sites = pd.read_parquet(PROCESSED / "masts_sites.parquet",
                            columns=["site_id", "lat", "lon", "sources", "operators", "antenna_height_m"])
    for name, lat, lon in places():
        s = nearest_site(sites, lat, lon)
        height = s.antenna_height_m if pd.notna(s.antenna_height_m) else None
        los = terrain.line_of_sight(lat, lon, s.lat, s.lon, mast_height=height)
        b = bearing_deg(lat, lon, s.lat, s.lon)
        print(f"\n{name}  ({lat:.5f}, {lon:.5f})")
        print(f"  ground here {los['rx_ground_m']:.0f} m; nearest site {s.site_id} {los['path_length_m'] / 1000:.2f} km "
              f"{COMPASS[int(b / 45 + 0.5) % 8]} ({s.sources}; operators {s.operators or 'unknown'}), ground "
              f"{los['site_ground_m']:.0f} m, antenna {los['mast_height_m']:.0f} m ({los['mast_height_source']})")
        if los["blocked"]:
            print(f"  BLOCKED: ground rises {los['max_obstruction_m']:.1f} m above the line, "
                  f"{los['obstruction_distance_m'] / 1000:.2f} km from here towards the site "
                  f"(ground {los['obstruction_ground_m']:.0f} m at {los['obstruction_lat']:.5f}, {los['obstruction_lon']:.5f})")
        else:
            print(f"  CLEAR: the line passes {-los['max_obstruction_m']:.1f} m above the highest point "
                  f"({los['obstruction_distance_m'] / 1000:.2f} km along)")
        cell = h3.latlng_to_cell(lat, lon, 7)
        try:
            row = query(f"""SELECT t.elevation_mean_m, t.elevation_range_m, l.blocked, l.obstruction_m,
  l.obstruction_distance_m, l.path_length_m, l.mast_height_source
FROM CD_TERRAIN.terrain_r7 t LEFT JOIN CD_LOS.los_r7 l ON l.cell_id = t.cell_id
WHERE t.cell_id = '{cell}'""")
            r = row[0] if row else {}
            print(f"  Zetaris {cell}: elevation mean {r.get('elevation_mean_m')} m, range {r.get('elevation_range_m')} m; "
                  f"cell centre -> nearest site: blocked={r.get('blocked')}, obstruction {r.get('obstruction_m')} m "
                  f"at {r.get('obstruction_distance_m')} m of {r.get('path_length_m')} m ({r.get('mast_height_source')})")
        except ZetarisError as e:
            print(f"  Zetaris query failed: {e}")


if __name__ == "__main__":
    main()
