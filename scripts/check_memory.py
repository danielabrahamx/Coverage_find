"""Phase 1 check: the Meterless service through the Python client.

    python scripts/check_memory.py      # needs the service (python run.py starts it, or
                                        # cd meterless_service && npx tsx server.ts)

Creates a run, adds evidence and a belief, revises it with a reason, prints the audit
trail; adds World Model entities and operator-scoped relationships; records a diagnosis and
queries prior diagnoses near Great Langdale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.memory.meterless import Meterless  # noqa: E402

LAT, LON = 54.445, -3.105


def main() -> None:
    m = Meterless()
    h = m.health()
    print(f"health: {h}")
    if h.get("status") != "ok":
        sys.exit("Meterless service is not running (python run.py starts it)")

    run_id = m.create_run("point", query="Great Langdale (check)", location={"lat": LAT, "lon": LON})
    print(f"\nrun {run_id}: {m.get_run(run_id)['status']}")
    m.add_evidence(run_id, {"id": "los_vodafone", "source": "Line of sight over Copernicus DEM GLO-30 (computed)",
                            "finding": "Vodafone's nearest approximate site is 3.8 km south-east. Terrain rises 288 m "
                                       "above the direct line 2.2 km from here.", "strength": "strong",
                            "value": {"obstruction_m": 288.4}, "cell_ids": ["871955454ffffff"]})
    m.add_evidence(run_id, {"id": "speed_cell", "source": "Ookla open data (Zetaris CD_OOKLA_MOBILE)",
                            "finding": "No Ookla speed tests in this cell in 2026Q3.", "strength": "weak"})
    m.add_belief(run_id, "terrain_blocking", 0.8, "Terrain blocks the line to the nearest sites.",
                 ["los_vodafone"], [], round=1)
    m.update_belief(run_id, "terrain_blocking", 0.65, "Antenna height is assumed (25 m), not from Ofcom's register.",
                    by="critic", round=1)
    m.add_critique(run_id, {"belief_id": "terrain_blocking", "verdict": "downgrade",
                            "reason": "Assumed antenna height", "requested_checks": []}, round=1)
    m.add_note(run_id, "guard", "Dropped a claim citing unknown evidence id 'speed_1km'", by="guard")

    print("\nbelief history:")
    for b in m.beliefs(run_id):
        for h in b["history"]:
            print(f"  {b['belief_id']}: {h['previous']} -> {h['confidence']} by {h['by']} (round {h['round']}): {h['reason']}")

    print("\naudit trail (ordered):")
    for e in m.audit(run_id):
        conf = f" {e['old_confidence']} -> {e['new_confidence']}" if e["action"] == "update" and e["new_confidence"] is not None else ""
        print(f"  #{e['seq']:<4} {e['action']:<7} {e['kind']:<9} {e['ref'] or '':<18} by {e['actor']:<14}{conf}  {str(e['summary'])[:70]}")

    place = m.upsert_entity("place", f"{LAT:.5f},{LON:.5f}", name="Great Langdale", attrs={"lat": LAT, "lon": LON}, run_id=run_id)
    for op, site, result in [("Vodafone", "S075142", "blocked"), ("EE", "S065491", "blocked")]:
        s = m.upsert_entity("site", site, attrs={"operators": [op]}, run_id=run_id)
        m.relate(place["id"], "nearest_site", s["id"], context={"type": "operator", "key": op},
                 attrs={"operator": op, "line_of_sight": result}, run_id=run_id)
    m.add_event("diagnosis_completed", place["id"], {"headline": "Terrain likely blocks the nearest sites"}, run_id=run_id)
    w = m.world_entity(place["id"])
    print(f"\nWorld Model: {place['id']}")
    for r in w["relationships"]:
        print(f"  {r['from']} -[{r['type']}{(' ' + json.dumps(r.get('attrs'))) if r.get('attrs') else ''}]-> {r['to']}")

    m.record_diagnosis(run_id, LAT, LON, cell_id="871955454ffffff", scope="point",
                       headline="Terrain likely blocks the nearest sites (check run)", causes=[{"cause": "terrain_blocking", "confidence": 0.65}])
    near = m.diagnoses_near(54.44, -3.09, km=10)
    print(f"\nprior diagnoses within 10 km of Great Langdale: {len(near)}")
    for d in near[:3]:
        print(f"  {d['run_id']} {d['distance_km']} km: {d['headline']}")
    print(f"\nclient mode: {m.mode}")


if __name__ == "__main__":
    main()
