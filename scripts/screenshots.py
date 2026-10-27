"""The README screenshots, at 1440x1000, from the running app (python run.py). No new agent runs: the recorded
example runs are reopened with ?run= (their files are in data/runs/ after scripts/record_examples.py).

    python scripts/screenshots.py [--base http://localhost:8000] [--chrome PATH]

Writes docs/screenshots/*.png. The Council view's fix and zoom shots come from scripts/council_screenshots.py.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
SCROLL = ("el => { const p = document.querySelector('#panel'); "
          "p.scrollTop += el.getBoundingClientRect().top - p.getBoundingClientRect().top - 8; }")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH"))
    a = ap.parse_args()
    runs = {e["example_id"]: e.get("run_id") for e in json.loads((ROOT / "examples" / "index.json").read_text())["examples"]}
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chrome, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def shot(name):
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(f"{name}.png")

        # My signal: Great Langdale, the agents' result (hero) and the evidence with its Zetaris SQL
        page.goto(f"{a.base}/signal?lat=54.445&lon=-3.105&run={runs['great_langdale']}", wait_until="networkidle")
        page.wait_for_selector(".rp-headline", timeout=90_000)
        page.wait_for_timeout(3000)
        page.eval_on_selector(".agents", SCROLL)
        page.wait_for_timeout(500)
        shot("hero_my_signal")
        page.click("[data-tab=evidence]")
        page.click(".ev-sql summary")
        page.wait_for_timeout(500)
        shot("my_signal_evidence")
        # Near Rhayader: how the agents decided (the critic sends the loop round again)
        page.goto(f"{a.base}/signal?lat=52.30&lon=-3.51&run={runs['near_rhayader']}", wait_until="networkidle")
        page.wait_for_selector(".rp-headline", timeout=90_000)
        page.wait_for_timeout(2500)
        page.click("[data-tab=trace]")
        page.click(".tl-card summary")
        page.wait_for_timeout(400)
        page.eval_on_selector(".agents", SCROLL)
        page.wait_for_timeout(400)
        shot("my_signal_how_agents_decided")
        # Council view: Ousby, the agents' result with the fix
        page.goto(f"{a.base}/council?zone=Z00072&run={runs['zone_ousby']}", wait_until="networkidle")
        page.wait_for_selector(".rp-headline", timeout=120_000)
        page.wait_for_timeout(3500)
        shot("council_zone_result")
        # Explore: the data, cell by cell
        page.goto(f"{a.base}/?layer=los_blocked&lat=54.445&lon=-3.105&zoom=10.4&cell=871955454ffffff", wait_until="networkidle")
        page.wait_for_selector("#legend h2", timeout=60_000)
        page.wait_for_selector(".diagnose", timeout=60_000)
        page.wait_for_timeout(4000)
        shot("explore")
        print("console errors:", errors or "none")
        b.close()


if __name__ == "__main__":
    main()
