"""Data checks, run through Zetaris. Grows phase by phase.

    python scripts/check_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.data.zetaris import QUERY_LOG, query  # noqa: E402

SLOWEST_SQL = """
SELECT c.cell_id, c.nation, round(c.lat, 3) AS lat, round(c.lon, 3) AS lon,
       round(c.population) AS population,
       round(o.download_mbps, 2) AS download_mbps, round(o.upload_mbps, 2) AS upload_mbps,
       round(o.latency_ms) AS latency_ms, o.tests, o.devices, o.quarter
FROM CD_CELLS.cells_r7 c
JOIN CD_OOKLA_MOBILE.ookla_mobile_r7 o ON o.cell_id = c.cell_id
WHERE c.population > 0 AND o.tests >= 10
ORDER BY o.download_mbps
LIMIT 10
"""


def table(rows: list[dict], columns: list[str]) -> str:
    """Rows as text, columns in the given order (Zetaris does not keep SELECT order)."""
    return pd.DataFrame(rows, columns=columns).to_string(index=False)


def check_phase_a() -> None:
    print("Phase A: 10 slowest populated cells with >= 10 tests (CD_CELLS x CD_OOKLA_MOBILE, via Zetaris)")
    rows = query(SLOWEST_SQL)
    print(table(rows, ["cell_id", "nation", "lat", "lon", "population", "download_mbps",
                       "upload_mbps", "latency_ms", "tests", "devices", "quarter"]))
    entry = QUERY_LOG[-1]
    print(f"  {entry['rows']} rows in {entry['duration_ms']} ms")


def main() -> None:
    check_phase_a()


if __name__ == "__main__":
    main()
