"""Register every processed dataset in Zetaris as its own source (Lightning database).

    python scripts/zetaris/register_sources.py            # all sources
    python scripts/zetaris/register_sources.py cells      # just one (see SOURCES)

Needs the data mount (scripts/zetaris/compose.sh up -d driver): Zetaris reads local files
only under /home/zetaris/customer-data/shared/, where data/processed appears as
coverage_detective/. Re-runnable: each source is dropped and recreated, which also picks
up a rebuilt file's schema. Each source is then checked with a row count.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import PROCESSED  # noqa: E402
from coverage_detective.data.zetaris import ZetarisError, execute, query  # noqa: E402

ZETARIS_DATA_DIR = "/home/zetaris/customer-data/shared/coverage_detective"


def _recreate_database(database: str, description: str) -> None:
    try:
        execute(f"DROP LIGHTNING DATABASE {database}")
    except ZetarisError as e:
        if "doesn't exist" not in str(e):
            raise
    # Zetaris accepts only letters, digits, spaces and _ . - , in descriptions.
    description = " ".join(re.sub(r"[^A-Za-z0-9_.,\- ]", " ", description).split())
    execute(f'CREATE LIGHTNING DATABASE {database} DESCRIBE BY "{description}" OPTIONS ()')


def _register(database: str, table: str, filename: str, description: str) -> None:
    """(Re)create one Lightning database holding one Parquet table, then count its rows."""
    if not (PROCESSED / filename).exists():
        print(f"  {database}: skipped, {filename} not built yet")
        return
    _recreate_database(database, description)
    execute(
        f"CREATE LIGHTNING FILESTORE TABLE {table} FROM {database} FORMAT parquet "
        f'OPTIONS (path "file://{ZETARIS_DATA_DIR}/{filename}")'
    )
    n = query(f"SELECT count(*) AS n FROM {database}.{table}")[0]["n"]
    print(f"  {database}.{table}: {n:,} rows")


def register_cells() -> None:
    _register(
        "CD_CELLS", "cells_r7", "cells_r7.parquet",
        "H3 r7 grid over the UK with WorldPop 2020 population and nation. "
        "ONS boundaries (OGL v3), WorldPop (CC BY 4.0).",
    )


def register_ookla_mobile() -> None:
    _register(
        "CD_OOKLA_MOBILE", "ookla_mobile_r7", "ookla_mobile_r7.parquet",
        "Ookla mobile speeds per H3 r7 cell, latest quarter, with tests/devices per head "
        "and 4-quarter trend. Speedtest by Ookla open data (CC BY-NC-SA 4.0).",
    )


def register_ookla_mobile_history() -> None:
    _register(
        "CD_OOKLA_MOBILE_HISTORY", "ookla_mobile_history_r7", "ookla_mobile_history_r7.parquet",
        "Ookla mobile speeds per H3 r7 cell and quarter (last 4 quarters). "
        "Speedtest by Ookla open data (CC BY-NC-SA 4.0).",
    )


def register_ookla_mobile_tiles() -> None:
    _register(
        "CD_OOKLA_MOBILE_TILES", "ookla_mobile_tiles", "ookla_mobile_tiles.parquet",
        "Ookla mobile tiles (zoom 16, about 350-400 m in the UK) in the UK for the last 4 quarters, with their H3 r7 cell. "
        "Speedtest by Ookla open data (CC BY-NC-SA 4.0).",
    )


def register_masts_sites() -> None:
    _register(
        "CD_MASTS_SITES", "masts_sites", "masts_sites.parquet",
        "Approximate mobile mast sites: OpenCelliD radio cells clustered within 150 m (CC BY-SA 4.0), "
        "OpenStreetMap communication masts (ODbL) and Ofcom licence register fixed-link sites, merged within "
        "200 m. operators_inferred from OpenCelliD and OSM, operators_confirmed from the Ofcom register.",
    )


def register_masts_cells() -> None:
    _register(
        "CD_MASTS", "masts_r7", "masts_r7.parquet",
        "Per H3 r7 cell: nearest approximate mast site, sites and operators within 5 km (confirmed by "
        "Ofcom licence register or inferred), register and microwave backhaul sites within 5 km, operator data status.",
    )


def register_wtr_points() -> None:
    _register(
        "CD_WTR_POINTS", "wtr_points", "wtr_points.parquet",
        "Ofcom Wireless Telegraphy Register: mobile operators' licensed fixed links, one row per licence and "
        "location, with licensee, operators, frequency band and antenna height. Ofcom copyright, free re-use.",
    )


def register_ofcom_area() -> None:
    _register(
        "CD_OFCOM_AREA", "ofcom_area_r7", "ofcom_area_r7.parquet",
        "Per H3 r7 cell: Westminster constituency and local authority, and the constituency's predicted "
        "4G and 5G coverage by number of operators. Ofcom Connected Nations, July 2025, Open Government Licence. "
        "Area-level context, not coverage at the exact location.",
    )


def register_ofcom_nations() -> None:
    _register(
        "CD_OFCOM_NATIONS", "ofcom_nations", "ofcom_nations.parquet",
        "Predicted 4G and 5G coverage per operator, by UK nation and urban or rural. "
        "Ofcom Connected Nations, July 2025, Open Government Licence.",
    )


def register_terrain() -> None:
    _register(
        "CD_TERRAIN", "terrain_r7", "terrain_r7.parquet",
        "Per H3 r7 cell: elevation mean, min, max, range and std in metres, sampled at H3 r10 centres. "
        "Copernicus DEM GLO-30, a surface model including some trees and buildings. DLR, Airbus, Copernicus EU and ESA.",
    )


def register_los() -> None:
    _register(
        "CD_LOS", "los_r7", "los_r7.parquet",
        "Per populated H3 r7 cell: line of sight from the cell centre at 1.5 m to the nearest approximate mast site, "
        "antenna height from Ofcom register or assumed 25 m, earth curvature with k four thirds. blocked, obstruction_m and where. "
        "Map context only, blocked means weaker signal, not none. Copernicus DEM GLO-30.",
    )


def register_gap_zones() -> None:
    _register(
        "CD_GAP_ZONES", "gap_zones", "gap_zones.parquet",
        "Gap zones, connected clusters of poorly served H3 r7 cells with at least 50 people. Per zone, name from the "
        "largest OSM place, nation, local authorities, people, severity, persistence, trend, operators nearby and test "
        "counts. Scored per request. Derived from Ookla, mast sites, Copernicus DEM and Ofcom areas.",
    )


def register_gap_zone_cells() -> None:
    _register(
        "CD_GAP_ZONE_CELLS", "gap_zone_cells", "gap_zone_cells.parquet",
        "Poorly served H3 r7 cells in gap zones, with zone_id, population, why each is poor (slow, no_site, blocked), "
        "severity, neighbour-ring speed and tests, local authority.",
    )


def _rest_table(database: str, table: str, endpoint: str) -> None:
    """A Lightning REST table: each query calls the endpoint live (Zetaris infers the JSON schema
    from one call at creation). Endpoints must work as written: a ${param} placeholder for the
    apiParam hint is sent literally at creation, and the EA / Open-Meteo gateways reject it (403)."""
    execute(
        f"CREATE LIGHTNING REST TABLE {table} FROM {database} "
        f'REQUEST(endpoint "{endpoint}", method "GET", http_encoding "URLENCODED", response_type "JSON", '
        f'insecure_ssl "false") HEADER() BODY()'
    )


def register_ea_floods() -> None:
    """Live source: Environment Agency flood monitoring API (England), two REST tables."""
    from coverage_detective.sources.flood_warnings import API, AREAS_API, ZETARIS_DB

    _recreate_database(
        ZETARIS_DB,
        "LIVE REST source. Environment Agency flood monitoring API, England. floods = every flood alert and "
        "warning in force now, flood_areas = flood area centres. Open Government Licence v3.",
    )
    _rest_table(ZETARIS_DB, "floods", API)
    _rest_table(ZETARIS_DB, "flood_areas", AREAS_API)
    n = query(f"SELECT size(items) AS n FROM {ZETARIS_DB}.floods")[0]["n"]
    m = query(f"SELECT size(items) AS n FROM {ZETARIS_DB}.flood_areas")[0]["n"]
    print(f"  {ZETARIS_DB}.floods: {n:,} alerts/warnings now (live); flood_areas: {m:,} areas")


SOURCES = {
    "cells": register_cells,
    "ookla_mobile": register_ookla_mobile,
    "ookla_mobile_history": register_ookla_mobile_history,
    "ookla_mobile_tiles": register_ookla_mobile_tiles,
    "masts_sites": register_masts_sites,
    "masts_cells": register_masts_cells,
    "wtr_points": register_wtr_points,
    "ofcom_area": register_ofcom_area,
    "ofcom_nations": register_ofcom_nations,
    "terrain": register_terrain,
    "los": register_los,
    "gap_zones": register_gap_zones,
    "gap_zone_cells": register_gap_zone_cells,
    "ea_floods": register_ea_floods,
}


def main() -> None:
    names = sys.argv[1:] or list(SOURCES)
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        sys.exit(f"Unknown source(s) {unknown}; choose from {list(SOURCES)}")
    for name in names:
        SOURCES[name]()


if __name__ == "__main__":
    main()
