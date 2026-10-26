"""Screenshots of the data explorer (needs the server running: python run.py).

    python scripts/screenshots.py [--base http://localhost:8000]
    python scripts/screenshots.py --agents      # live agent runs: Great Langdale (My signal), a zone (Council view)

Writes docs/screenshots/*.png and prints any browser console errors. --agents clicks the
agent buttons and waits for the runs (a few minutes each: they call Nemotron).
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
    ("explore_lake_district", f"?layer=los_blocked&lat=54.445&lon=-3.105&zoom=10.4&cell={LANGDALE_CELL}", (1440, 900), ".diagnose"),
    ("rhayader_panel", "?layer=microwave_backhaul_sites_within_5km&lat=52.30&lon=-3.51&zoom=11&cell=87195e3aeffffff", (1440, 900), ".diagnose"),
    # Other pages: the query string starts with the page path.
    ("signal_great_langdale", "signal?lat=54.445&lon=-3.105", (1440, 900), ".best"),
    ("signal_rhayader", "signal?lat=52.30&lon=-3.51", (1440, 900), ".best"),
    ("signal_phone", "signal?q=WC2N%205DU", (390, 844), ".best"),
    ("council_uk", "council", (1440, 900), "table.zones tbody tr"),
    ("council_westmorland_great_langdale", "council?scope=la:E06000064&zone=Z00603", (1440, 900), ".fix"),
    ("explore_zone_great_langdale", "?layer=los_blocked&zone=Z00603&lat=54.445&lon=-3.12&zoom=11", (1440, 900), None),
    ("council_phone", "council?scope=la:E06000064", (390, 844), "table.zones tbody tr"),
    ("phone_panel", f"?layer=download_mbps&lat=54.445&lon=-3.105&zoom=10&cell={LANGDALE_CELL}", (390, 844), ".diagnose"),
]


AGENT_TIMEOUT_MS = 8 * 60_000


def _scroll_to(page, panel: str, selector: str) -> None:
    page.eval_on_selector(selector, f"""el => {{ const p = document.querySelector('{panel}');
        p.scrollTop += el.getBoundingClientRect().top - p.getBoundingClientRect().top - 8; }}""")
    page.wait_for_timeout(400)


def agent_shots(browser, base: str) -> None:
    """Run the agents from the pages, as a user would, and capture progress, result, evidence and trace."""
    def shot(page, name):
        page.screenshot(path=str(OUT / f"{name}.png"))
        print(f"{name}.png")

    for page_name, url, button, panel, centre in [
        ("signal_agents_great_langdale", "signal?lat=54.445&lon=-3.105", "#diagnose", "#panel", "place"),
        ("council_agents_zone", "council?scope=la:E06000064&zone=Z00072", "#zone-diagnose", "#panel", "zone"),
    ]:
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/{url}", wait_until="networkidle")
        page.wait_for_selector(button, timeout=60_000)
        page.wait_for_timeout(2500)
        page.click(button)
        page.wait_for_selector(".pchip.running, .pchip.done", timeout=120_000)
        page.wait_for_timeout(15_000)  # a few steps in
        _scroll_to(page, panel, ".agents")
        shot(page, f"{page_name}_progress")
        page.wait_for_selector(".agent-verdict", timeout=AGENT_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        _scroll_to(page, panel, ".agents")
        shot(page, f"{page_name}_result")
        page.hover(".cause .cbar")
        page.wait_for_timeout(300)
        shot(page, f"{page_name}_confidence_history")
        page.mouse.move(5, 5)
        page.click(".cause .ev-tag")
        page.wait_for_selector(".ev-open")
        _scroll_to(page, panel, ".ev-open")
        shot(page, f"{page_name}_evidence_sql")
        if page_name.startswith("signal"):
            _scroll_to(page, panel, ".net-rank")
            shot(page, f"{page_name}_network_actions")
            page.click("#draft-letter")
            page.wait_for_selector("#letter-text", timeout=180_000)
            _scroll_to(page, panel, "#letter")
            shot(page, f"{page_name}_letter")
        else:
            _scroll_to(page, panel, ".fix-card")
            shot(page, f"{page_name}_fix")
        page.click(".trace-wrap > summary")
        _scroll_to(page, panel, ".round-cards")
        shot(page, f"{page_name}_trace")
        _scroll_to(page, panel, "svg.wm")
        shot(page, f"{page_name}_world_model")
        print(f"  run {page.evaluate('new URLSearchParams(location.search).get(\"run\")')}: "
              f"{'errors: ' + '; '.join(errors[:3]) if errors else 'no console errors'}")
        page.close()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto(f"{base}/council?scope=la:E06000064", wait_until="networkidle")
    page.wait_for_selector("table.zones tbody tr", timeout=60_000)
    page.click("#summary-btn")
    page.wait_for_selector(".summary-panel", timeout=180_000)
    page.wait_for_timeout(1500)
    shot(page, "council_agents_priority_summary")
    page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--chrome", default=os.environ.get("CHROME_PATH"),
                        help="browser binary, if Playwright's own build is not installed")
    parser.add_argument("--agents", action="store_true", help="live agent runs instead of the page shots")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        if args.agents:
            agent_shots(browser, args.base)
            browser.close()
            return
        for name, qs, (w, h), wait_for in SHOTS:
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(args.base + "/" + qs, wait_until="networkidle")
            if qs.startswith("?"):  # the explorer
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
