"""Build the UK MCC/MNC -> operator reference table from Wikipedia.

    python scripts/download/mcc_mnc.py [--force]

Source: Wikipedia, "Mobile network codes in ITU region 2xx (Europe)", section
"United Kingdom – GB", pinned to one revision so the table is reproducible. Text licence:
CC BY-SA 4.0. Writes data/reference/mcc_mnc_uk.csv (small, committed).

Operators are labelled as the page labels them (the Brand column, or the Operator
column where Brand is empty). Networks have merged in recent years (EE absorbed
T-Mobile and Orange; Vodafone UK and Three UK merged as VodafoneThree in 2025), so one
current operator can appear under several codes or older names.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import ROOT  # noqa: E402

PAGE = "Mobile network codes in ITU region 2xx (Europe)"
REVISION = 1378731553  # 2026-10-05T23:10:17Z
API = "https://en.wikipedia.org/w/api.php"
PARAMS = {"action": "parse", "oldid": REVISION, "prop": "wikitext", "format": "json", "formatversion": "2"}
OUT = ROOT / "data" / "reference" / "mcc_mnc_uk.csv"
FIELDS = ["mcc", "mnc", "label", "brand", "operator", "status", "bands", "notes"]


def clean(text: str) -> str:
    """Wikitext cell -> plain text."""
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)  # [[target|shown]]
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)  # [[target]]
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)  # [url shown]
    return re.sub(r"\s+", " ", text).strip(" ;")


def uk_rows(wikitext: str) -> list[dict]:
    start = wikitext.index("==== [[United Kingdom]] – GB ====")
    end = wikitext.find("\n==", start + 10)
    rows = []
    for line in wikitext[start:end].splitlines():
        if not re.match(r"\|\s*23[45]\s*\|\|", line):
            continue
        cells = [clean(c) for c in line.lstrip("|").split("||")]
        cells += [""] * (7 - len(cells))
        mcc, mnc, brand, operator, status, bands, notes = cells[:7]
        rows.append(
            {
                "mcc": int(mcc), "mnc": int(mnc), "label": brand or operator,
                "brand": brand, "operator": operator, "status": status, "bands": bands, "notes": notes,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if OUT.exists() and not args.force:
        print(f"exists: {OUT}")
        return
    headers = {"User-Agent": "CoverageDetective/0.1 (hackathon)", "Accept": "*/*"}
    r = httpx.get(API, params=PARAMS, headers=headers, timeout=30).raise_for_status()
    wikitext = r.json()["parse"]["wikitext"]
    rows = uk_rows(wikitext)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} codes) from {PAGE!r} revision {REVISION}")


if __name__ == "__main__":
    main()
