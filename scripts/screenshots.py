"""Screenshots of the data explorer (needs the server running: python run.py).

    python scripts/screenshots.py [--base http://localhost:8000]

Writes docs/screenshots/*.png and prints any browser console errors.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
LANGDALE_CELL = "871955454ffffff"
SHOTS = [
    # name, query string, viewport, what to wait for
    ("uk_speed", "?layer=download_mbps", (1440, 900), None),
    ("lake_district_masts", "?layer=download_mbps&lat=54.46&lon=-3.08&zoom=10.6", (1440, 900), None),
    ("great_langdale_panel", f"?layer=download_mbps&lat=54.445&lon=-3.105&zoom=11.2&cell={LANGDALE_CELL}", (1440, 900), ".diagnose"),
    ("rhayader_panel", "?layer=microwave_backhaul_sites_within_5km&lat=52.30&lon=-3.51&zoom=11&cell=87195e3aeffffff", (1440, 900), ".diagnose"),
    ("great_langdale_right_now", f"?layer=download_mbps&lat=54.445&lon=-3.105&zoom=11.2&cell={LANGDALE_CELL}", (1440, 900), "#right-now .live-row"),
    ("great_langdale_line_of_sight", f"?layer=los_blocked&lat=54.435&lon=-3.085&zoom=12&cell={LANGDALE_CELL}", (1440, 900), "#los .profile"),
    ("phone_panel", f"?layer=download_mbps&lat=54.445&lon=-3.105&zoom=10&cell={LANGDALE_CELL}", (390, 844), ".diagnose"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--chrome", default=os.environ.get("CHROME_PATH"),
                        help="browser binary, if Playwright's own build is not installed")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for name, qs, (w, h), wait_for in SHOTS:
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(args.base + "/" + qs, wait_until="networkidle")
            page.wait_for_selector("#legend h2", timeout=60_000)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=60_000)
            if wait_for and wait_for.startswith("#"):  # scroll the panel to that section
                page.wait_for_selector(".diagnose", timeout=60_000)
                page.eval_on_selector(wait_for.split()[0], "el => el.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(4000)  # basemap tiles, masts and hexagons settle
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path))
            print(f"{path.name}: {'errors: ' + '; '.join(errors[:3]) if errors else 'no console errors'}")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
