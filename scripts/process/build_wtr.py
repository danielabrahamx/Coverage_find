"""Ofcom Wireless Telegraphy Register -> operator-labelled points, merged into mast sites.

    python scripts/download/ofcom_wtr.py
    python scripts/process/build_wtr.py

Writes data/processed/wtr_points.parquet (one row per licence and location: lat, lon,
licensee, operators, product, frequency band, antenna height, link id) and then rebuilds
the mast tables (scripts/process/build_masts.py) so register sites are merged in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from coverage_detective.config import PROCESSED, RAW  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.sources.ofcom_wtr import load_licensees, read_points  # noqa: E402

WTR_CSV = RAW / "ofcom_wtr" / "WTR.csv"
LICENSEES = ROOT / "data" / "reference" / "wtr_operator_licensees.csv"
OUT = PROCESSED / "wtr_points.parquet"


def main() -> None:
    if not WTR_CSV.exists():
        sys.exit(f"{WTR_CSV} missing; run scripts/download/ofcom_wtr.py")
    points, counts = read_points(WTR_CSV, load_licensees(LICENSEES))
    print(f"  register rows {counts['register_rows']:,}; live operator rows {counts['operator_rows']:,}; "
          f"dropped (no location / outside UK) {counts['no_location_or_outside_uk']:,}; points {counts['points']:,}")
    print("  points by licensee and product:")
    print(points.groupby(["licensee", "operators", "product"]).size().rename("points").to_string())
    print(f"  location from grid reference: {(points.location_from == 'grid_ref').sum():,}, "
          f"register lat/lon: {(points.location_from == 'register_latlon').sum():,}")
    points.to_parquet(OUT, index=False)
    downloaded = manifest.file_date(WTR_CSV)
    manifest.record(
        "wtr", title="Ofcom Wireless Telegraphy Register: mobile operators' licensed fixed links",
        data_period=f"register downloaded {downloaded}", downloaded={WTR_CSV.name: downloaded},
        outputs=[OUT], refresh="monthly (Ofcom updates the register regularly)",
        licence="Ofcom copyright; free re-use if reproduced accurately and not misleadingly, acknowledged as Ofcom copyright",
        extra={"counts": counts},
    )
    print(f"wrote {OUT.name}; rebuilding mast tables ...")
    subprocess.run([sys.executable, "scripts/process/build_masts.py", "--force"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
