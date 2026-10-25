"""Evidence API check: readable bundles for the three sample places.

    python scripts/check_evidence.py            # also saves them to data/samples/evidence/
    python scripts/check_evidence.py --json     # print the raw JSON instead

Calls POST /api/evidence in-process. Great Langdale and Rhayader by coordinates (the
sample points), London by postcode.
"""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from coverage_detective.api.app import app  # noqa: E402
from coverage_detective.config import SAMPLES  # noqa: E402

REQUESTS = [
    ("great_langdale", {"lat": 54.445, "lon": -3.105}),
    ("london_wc2n_5du", {"query": "WC2N 5DU"}),
    ("rhayader", {"lat": 52.30, "lon": -3.51}),
]
OUT = SAMPLES / "evidence"


def show(bundle: dict, seconds: float) -> None:
    p = bundle["point"]
    print("=" * 100)
    print(f"{p.get('label')}  [{p.get('postcode') or p.get('nearest_postcode')}, {p.get('admin_district')}, "
          f"{p.get('country')}]  cell {bundle['cell_id']}  ({seconds:.1f}s, sample_mode={bundle['sample_mode']})")
    for i in bundle["items"]:
        head = f"  [{i['strength']:<8}] {i['id']:<20}"
        body = textwrap.fill(i["finding"], 100, initial_indent=head + " ", subsequent_indent=" " * (len(head) + 1))
        print(body)
        print(" " * (len(head) + 1) + f"source: {i['source']} | {i['data_period']} | as of {i['as_of']} | "
              f"bears on: {', '.join(i['bears_on']) or '-'}")
    print("  Zetaris queries: " + "; ".join(f"{q['id']} {q['rows']} rows {q['duration_ms']} ms"
                                            + (" (cached)" if q["cached"] else "") for q in bundle["zetaris_queries"]))
    if bundle["errors"]:
        print(f"  errors: {bundle['errors']}")


def main() -> None:
    client = TestClient(app)
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, body in REQUESTS:
        t = time.time()
        r = client.post("/api/evidence", json=body)
        r.raise_for_status()
        bundle = r.json()
        if "--json" in sys.argv:
            print(json.dumps(bundle, indent=1))
        else:
            show(bundle, time.time() - t)
        (OUT / f"{slug}.json").write_text(json.dumps(bundle, indent=1, ensure_ascii=False))
    print(f"\nsaved {len(REQUESTS)} bundles to {OUT}")


if __name__ == "__main__":
    main()
