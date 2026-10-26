"""Meterless client: the in-memory fallback must behave like the service (same shapes, order)."""

import httpx

from coverage_detective.memory.meterless import Meterless


def offline_client(monkeypatch) -> Meterless:
    def down(*a, **k):
        raise httpx.ConnectError("service down")
    monkeypatch.setattr(httpx, "request", down)
    monkeypatch.setattr("coverage_detective.memory.meterless.time.sleep", lambda s: None)
    return Meterless("http://127.0.0.1:1")


def test_fallback_beliefs_revisions_and_audit_order(monkeypatch):
    m = offline_client(monkeypatch)
    run = m.create_run("point", query="Great Langdale")
    assert m.mode == "fallback"
    assert m.add_evidence(run, {"id": "los_ee", "finding": "blocked", "strength": "strong"})["created"]
    assert not m.add_evidence(run, {"id": "los_ee", "finding": "again"})["created"]  # stable ids, idempotent
    m.add_belief(run, "terrain_blocking", 0.8, "hills", ["los_ee"], [], round=1)
    b = m.update_belief(run, "terrain_blocking", 0.6, "assumed mast height", by="critic", round=1)
    assert [h["confidence"] for h in b["history"]] == [0.8, 0.6]
    assert b["history"][1] | {"at": None} == {"at": None, "by": "critic", "confidence": 0.6, "previous": 0.8,
                                                "reason": "assumed mast height", "round": 1}
    m.add_critique(run, {"belief_id": "terrain_blocking", "verdict": "downgrade", "reason": "assumed"}, round=1)
    trail = m.audit(run)
    assert [(t["kind"], t["action"]) for t in trail] == [("run", "create"), ("evidence", "create"), ("belief", "create"),
                                                         ("belief", "update"), ("critique", "create")]
    assert [t["seq"] for t in trail] == sorted(t["seq"] for t in trail)


def test_fallback_prior_diagnoses_and_world(monkeypatch):
    m = offline_client(monkeypatch)
    run = m.create_run("point")
    m.record_diagnosis(run, 54.445, -3.105, headline="terrain")
    assert len(m.diagnoses_near(54.45, -3.10)) == 1 and m.diagnoses_near(51.5, -0.12) == []
    assert m.diagnoses_near(54.45, -3.10, exclude_run=run) == []
    place = m.upsert_entity("place", "p1", name="Great Langdale", run_id=run)
    site = m.upsert_entity("site", "S1", run_id=run)
    m.relate(place["id"], "nearest_site", site["id"], context={"type": "operator", "key": "EE"}, run_id=run)
    m.add_event("diagnosis_completed", place["id"], run_id=run)
    assert len(m.world_entity(place["id"])["relationships"]) == 2
    assert len(m.world_for_run(run)["entities"]) == 3
