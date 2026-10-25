"""Save real responses from every live source for the sample places, for SAMPLE_MODE and tests.

    python scripts/download/live_samples.py

Writes data/samples/<source>/<slug>.json (url, fetched_at, http_status, body). Re-run to
refresh them; each file is a few KB. The Met Office samples are whole regional feeds, so
they hold whatever warnings were active when saved.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import SAMPLE_LOCATIONS, SAMPLES  # noqa: E402
from coverage_detective.sources import flood_warnings, geocode, live, met_office_warnings, weather  # noqa: E402

# Search texts saved for the geocoder: the postcode, a place in the list, and one that is
# not (postcodes.io has no "Great Langdale", so the approximate retry is saved too).
LOOKUPS = ["WC2N 5DU", "Great Langdale", "Rhayader", "ZZ1 1ZZ"]


def main() -> None:
    live.RECORD_SAMPLES = True
    for q in LOOKUPS:
        res = geocode.lookup(q)
        print(f"  lookup {q!r}: {res.status}, {[r['label'] for r in res.data['results']]}")
    for (name, lat, lon), slug in zip(SAMPLE_LOCATIONS, live.SAMPLE_SLUGS):
        g = geocode.reverse(lat, lon)
        place = g.data["nearest"]
        w = weather.forecast(lat, lon)
        m = met_office_warnings.for_place(place, lat, lon)
        # Save the EA response even outside England (the client answers "not covered" there).
        f = flood_warnings.via_api(lat, lon)
        print(f"  {name} [{slug}]: postcode {place and place['postcode']} ({g.status}); weather {w.data.get('severity')} "
              f"({w.status}); Met Office {m.data.get('region')}: {m.data.get('count')} warnings ({m.status}); "
              f"EA floods within 10 km: {f.data.get('count')} ({f.status})")
    files = sorted(SAMPLES.rglob("*.json"))
    print(f"{len(files)} sample files, {sum(p.stat().st_size for p in files) / 1e3:.0f} KB in {SAMPLES}")


if __name__ == "__main__":
    main()
