"""Before / after screenshots of the agent panels from saved runs (no new agent runs except the summary).

    python scripts/ui_screenshots.py before|after [--summary] [--chrome PATH]

Writes docs/screenshots/ui_cleanup/<stage>_*.png at 1440x1000.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "ui_cleanup"
BASE = "http://localhost:8000"
OUSBY = "council?scope=la:E06000064&zone=Z00072&run=run_20261026215212_94hi"
LANGDALE = "signal?lat=54.445&lon=-3.105&run=run_20261026214958_kzyq"


def scroll(page, panel, sel):
    page.eval_on_selector(sel, f"""el => {{ const p = document.querySelector('{panel}');
        p.scrollTop += el.getBoundingClientRect().top - p.getBoundingClientRect().top - 8; }}""")
    page.wait_for_timeout(400)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["before", "after"])
    ap.add_argument("--summary", action="store_true", help="also write a priority summary (one LLM call)")
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH"))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    after = a.stage == "after"
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chrome, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def shot(name):
            page.screenshot(path=str(OUT / f"{a.stage}_{name}.png"))
            print(f"{a.stage}_{name}.png")

        for name, url, panel, ready in [("ousby", OUSBY, "#panel", ".agent-verdict"),
                                        ("great_langdale", LANGDALE, "#panel", ".agent-verdict")]:
            page.goto(f"{BASE}/{url}", wait_until="networkidle")
            page.wait_for_selector(".rp-headline" if after else ready, timeout=90_000)
            page.wait_for_timeout(3000)
            if after:
                scroller = ".rp-body" if name == "ousby" else "#panel"
                if name == "great_langdale":
                    scroll(page, "#panel", ".agents")
                shot(f"{name}_result")
                page.click("[data-tab=trace]")
                page.wait_for_timeout(300)
                shot(f"{name}_agents_decided")
                page.click(".tl-card summary")
                page.wait_for_timeout(300)
                shot(f"{name}_agents_decided_round_open")
                page.click("[data-tab=evidence]")
                page.wait_for_timeout(300)
                shot(f"{name}_evidence")
                scroll(page, scroller, "svg.wm")
                shot(f"{name}_world_model")
                if name == "ousby":
                    page.click("#panel-collapse")
                    page.wait_for_timeout(600)
                    shot("ousby_panel_collapsed")
                    page.click("#panel-collapse")
                    page.wait_for_timeout(400)
            else:
                scroll(page, panel, ".agents")
                shot(f"{name}_result")
                page.click(".trace-wrap > summary")
                scroll(page, panel, ".round-cards")
                shot(f"{name}_trace")
        if a.summary:
            page.goto(f"{BASE}/council?scope=la:E06000064", wait_until="networkidle")
            page.wait_for_selector("table.zones tbody tr", timeout=60_000)
            page.wait_for_timeout(1500)
            shot("council_table")
            page.click("#summary-btn")
            page.wait_for_selector(".summary-panel, #panel-body .error", timeout=240_000)
            page.wait_for_timeout(1500)
            shot("priority_summary")
        print("console errors:", errors or "none")
        b.close()


if __name__ == "__main__":
    main()
