"""Download Ofcom's Wireless Telegraphy Act Register (WTR) as CSV.

    python scripts/download/ofcom_wtr.py [--force]

Source: the "Wireless Telegraphy Act Register" page, https://www.ofcom.org.uk/spectrum/frequencies/wtr
(link: https://static.ofcom.org.uk/static/radiolicensing/html/register/WTR.csv, ~54 MB,
updated by Ofcom regularly). Saved as data/raw/ofcom_wtr/WTR.csv; skipped if it exists
unless --force. The download date, SHA-256 and the server's Last-Modified are recorded in
data/manifest.json under "wtr". Re-use: Ofcom copyright, reproducible free of charge if
reproduced accurately and not misleadingly, acknowledged as Ofcom copyright.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import RAW  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402

URL = "https://static.ofcom.org.uk/static/radiolicensing/html/register/WTR.csv"
OUT = RAW / "ofcom_wtr" / "WTR.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="download again even if the file exists")
    args = parser.parse_args()
    if OUT.exists() and not args.force:
        print(f"exists: {OUT}")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".part")
    with httpx.stream("GET", URL, timeout=300, follow_redirects=True, headers={"User-Agent": "CoverageDetective/0.1"}) as r:
        r.raise_for_status()
        last_modified = r.headers.get("last-modified")
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(OUT)
    OUT.with_name(OUT.name + ".downloaded").write_text(date.today().isoformat() + "\n")
    manifest.record_raw("wtr", OUT, URL, last_modified=last_modified)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, Last-Modified {last_modified})")


if __name__ == "__main__":
    main()
