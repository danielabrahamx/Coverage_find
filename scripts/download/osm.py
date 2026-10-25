"""Download the OpenStreetMap extracts for Great Britain and Ireland from Geofabrik.

    python scripts/download/osm.py

Files land in data/raw/osm/ (~2.2 GB + ~0.4 GB); existing files are skipped.
Licence: ODbL 1.0, © OpenStreetMap contributors.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import RAW  # noqa: E402

OUT_DIR = RAW / "osm"
EXTRACTS = {
    "great-britain-latest.osm.pbf": "https://download.geofabrik.de/europe/great-britain-latest.osm.pbf",
    "ireland-and-northern-ireland-latest.osm.pbf": "https://download.geofabrik.de/europe/ireland-and-northern-ireland-latest.osm.pbf",
}


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done, next_report = 0, 0.0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and done / total >= next_report:
                    print(f"  {dest.name}: {done / total:.0%} of {total / 1e6:.0f} MB", flush=True)
                    next_report += 0.25
        print(f"  from {r.url}")
    tmp.rename(dest)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in EXTRACTS.items():
        dest = OUT_DIR / name
        if dest.exists():
            print(f"exists: {dest.name}")
            continue
        print(f"downloading {url}", flush=True)
        download(url, dest)
        (OUT_DIR / f"{name}.downloaded").write_text(date.today().isoformat() + "\n")
    print("done")


if __name__ == "__main__":
    main()
