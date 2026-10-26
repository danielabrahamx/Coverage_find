"""Council view screenshots at 1440x1000 (server running: python run.py). No new agent runs: saved runs are reopened.

    python scripts/council_screenshots.py [--chrome PATH] [--one-candidate Z00123]

Writes docs/screenshots/council/*.png: Whole UK zoomed out, Westmorland and Furness at county zoom, the Lake District
zoomed in (gap zones and improvement opportunities), an opportunity zone after a run, and the fix view (Today /
With candidate) for Ousby, Mid Devon (Kennerleigh, 3,634 people) and a zone with one candidate if one is given.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "council"
BASE = "http://localhost:8000/council"
OUSBY_RUN = "run_20261026215212_94hi"
OPP_RUN = "run_20261026232653_82an"   # Windermere (O00332), improvement opportunity


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH"))
    ap.add_argument("--one-candidate", default=None, help="a zone id with a single candidate site")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chrome, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def go(qs, ready="table.zones tbody tr", wait=3500):
            page.goto(f"{BASE}{qs}", wait_until="networkidle")
            page.wait_for_selector(ready, timeout=180_000)
            page.wait_for_timeout(wait)

        def shot(name):
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(f"{name}.png")

        go("?area=uk")
        shot("01_whole_uk_zoomed_out")
        go("?area=la:E06000064")
        shot("02_westmorland_county_zoom")
        go("?lat=54.42&lon=-3.02&zoom=10.6")
        shot("03_lake_district_gaps_and_opportunities")
        go(f"?lat=54.42&lon=-3.02&zoom=10.6&zone=O00332&run={OPP_RUN}", ".rp-headline", 4500)
        shot("04_opportunity_selected_after_run")
        for name, qs in [("ousby", f"?zone=Z00072&run={OUSBY_RUN}"), ("mid_devon_kennerleigh", "?zone=Z00004")] + (
                [("one_candidate", f"?zone={a.one_candidate}")] if a.one_candidate else []):
            go(qs, ".cand-card", 4500)
            shot(f"05_{name}_fix_today")
            page.click("#fix-switch [data-mode=with]")
            page.wait_for_timeout(1500)
            shot(f"06_{name}_fix_with_candidate")
            page.hover(".maplibregl-canvas", position={"x": 300, "y": 400})
            page.click("#show-all")
            page.wait_for_timeout(1200)
            shot(f"07_{name}_all_candidates_pins_only")
        print("console errors:", errors or "none")
        b.close()


if __name__ == "__main__":
    main()
