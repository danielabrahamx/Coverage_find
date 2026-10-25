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


SOURCES = {
    "cells": register_cells,
    "ookla_mobile": register_ookla_mobile,
    "ookla_mobile_history": register_ookla_mobile_history,
    "ookla_mobile_tiles": register_ookla_mobile_tiles,
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
