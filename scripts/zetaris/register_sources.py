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


def _register(database: str, table: str, filename: str, description: str) -> None:
    """(Re)create one Lightning database holding one Parquet table, then count its rows."""
    if not (PROCESSED / filename).exists():
        print(f"  {database}: skipped, {filename} not built yet")
        return
    try:
        execute(f"DROP LIGHTNING DATABASE {database}")
    except ZetarisError as e:
        if "doesn't exist" not in str(e):
            raise
    # Zetaris accepts only letters, digits, spaces and _ . - , in descriptions.
    description = " ".join(re.sub(r"[^A-Za-z0-9_.,\- ]", " ", description).split())
    execute(f'CREATE LIGHTNING DATABASE {database} DESCRIBE BY "{description}" OPTIONS ()')
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
        "Ookla mobile tiles (~600 m) in the UK for the last 4 quarters, with their H3 r7 cell. "
        "Speedtest by Ookla open data (CC BY-NC-SA 4.0).",
    )


def register_masts_sites() -> None:
    _register(
        "CD_MASTS_SITES", "masts_sites", "masts_sites.parquet",
        "Approximate mobile mast sites: OpenCelliD radio cells clustered within 150 m (CC BY-SA 4.0) "
        "merged with OpenStreetMap communication masts (ODbL), operators grouped as EE, O2, Vodafone, Three.",
    )


def register_masts_cells() -> None:
    _register(
        "CD_MASTS", "masts_r7", "masts_r7.parquet",
        "Per H3 r7 cell: nearest mast distance and bearing, masts and operators within 5 km, "
        "OSM-only masts within 5 km. From OpenCelliD (CC BY-SA 4.0) and OpenStreetMap (ODbL).",
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


SOURCES = {
    "cells": register_cells,
    "ookla_mobile": register_ookla_mobile,
    "ookla_mobile_history": register_ookla_mobile_history,
    "ookla_mobile_tiles": register_ookla_mobile_tiles,
    "masts_sites": register_masts_sites,
    "masts_cells": register_masts_cells,
    "ofcom_area": register_ofcom_area,
    "ofcom_nations": register_ofcom_nations,
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
