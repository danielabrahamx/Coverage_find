"""Coordinator loop with a scripted LLM, fake tools and the in-memory Meterless (no network)."""

import json
import re

import httpx
import pytest

from coverage_detective.agents import agents as A
from coverage_detective.agents import coordinator as C
from coverage_detective.agents import schemas as S
from coverage_detective.agents import tools as T
from coverage_detective.agents.llm import LLMError, LLMResult
from coverage_detective.memory.meterless import Meterless

POINT = {"kind": "point", "label": "54.44500, -3.10500", "lat": 54.445, "lon": -3.105, "nearest_postcode": "LA22 9JY",
         "admin_district": "Westmorland and Furness", "country": "England"}


def item(id, finding, strength="strong", value=None):
    return {"id": id, "source": "test", "data_period": "2026Q3", "as_of": "2026-10-26", "query_or_url": "zetaris:Q1",
            "cell_ids": ["c"], "finding": finding, "value": value or {}, "sample_size": None, "strength": strength,
            "bears_on": []}


def fake_tools(monkeypatch):
    ran = []

    def make(name):
        def tool(case, operator=None):
            ran.append((name, operator))
            if name == "line_of_sight":
                return [item(f"los_{operator.lower()}", f"{operator}'s site is 3.8 km away. Terrain rises 288 m above the line.",
                             value={"site_id": "S1", "los_class": "blocked", "max_obstruction_m": 288.0})]
            if name == "speed_trend":
                return [item("speed_trend", "Download speed fell 35% over 4 quarters.", "moderate")]
            return [item(name, f"{name} result.", "moderate")]
        tool.__doc__ = f"fake {name}"
        return tool

    for name in T.TOOLS:
        monkeypatch.setitem(T.TOOLS, name, make(name))
    monkeypatch.setattr(A, "network_comparison", lambda case: [item("network_comparison", "No operator has a clear line.")])
    return ran


def offline_memory(monkeypatch) -> Meterless:
    monkeypatch.setattr(httpx, "request", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    monkeypatch.setattr("coverage_detective.memory.meterless.time.sleep", lambda s: None)
    return Meterless("http://127.0.0.1:1")


def scripted_llm(critic_rounds_needing_evidence=1, fail_agent=None):
    calls = []

    def chat(messages, reasoning=False, schema=None, tools=None, **kw):
        system = messages[0]["content"]
        agent = next(a for a in ["Investigator", "Diagnostician", "Critic", "Advisor"] if f"You are the {a}" in system)
        calls.append(agent)
        if agent.lower() == fail_agent:
            raise LLMError("scripted failure")
        m = re.search(r"Round:? (\d+)", messages[-1]["content"])
        rnd = int(m.group(1)) if m else 0
        if tools:
            return LLMResult(model="m", tool_calls=[{"id": "1", "name": "speeds_near", "arguments": {}}])
        if schema is S.HypothesisSet:
            conf = 0.8 if rnd == 1 else 0.6
            return LLMResult(model="m", parsed=S.HypothesisSet(hypotheses=[S.Hypothesis(
                id="terrain_blocking", cause="terrain_blocking", confidence=conf, supporting_evidence=["los_ee", "los_o2"],
                contradicting_evidence=[], explanation="Terrain rises 288 m above the line [los_ee].")],
                revision_reasons=[] if rnd == 1 else [S.RevisionReason(id="terrain_blocking", reason="speeds also fall")]))
        if schema is S.CritiqueSet:
            needs = rnd <= critic_rounds_needing_evidence
            return LLMResult(model="m", parsed=S.CritiqueSet(critiques=[S.Critique(
                hypothesis_id="terrain_blocking", verdict="needs_evidence" if needs else "approve",
                reason="Check the speed history [los_ee]." if needs else "Solid [los_ee].",
                requested_checks=[S.RequestedCheck(tool="speed_trend", operator=None, why="time pattern")] if needs else [],
                suggested_confidence=None)]))
        if schema is S.AdvisorOutput:
            return LLMResult(model="m", parsed=S.AdvisorOutput(
                headline="Hills likely block your signal [los_ee].", explanation="Terrain rises 288 m [los_ee].",
                cited_evidence=["los_ee"], ruled_out=[], limitations="Sites are approximate.",
                best_network=S.BestNetwork(summary="O2 first [network_comparison].", ranking=[
                    S.NetworkRank(operator="O2", rank=1, confidence="low", why="least obstructed", evidence=["los_o2"])]),
                actions=[S.Action(text="Try O2.", audience="resident")]))
        raise AssertionError(schema)

    return chat, calls


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(C.ev, "resolve", lambda q, lat, lon: (dict(POINT), None))
    monkeypatch.setattr(T.ev, "resolve", lambda q, lat, lon: (dict(POINT), type("G", (), {"data": {}})()))
    return offline_memory(monkeypatch), fake_tools(monkeypatch), tmp_path


def test_critic_request_triggers_a_second_round(setup, monkeypatch):
    memory, ran, runs_dir = setup
    chat, calls = scripted_llm(critic_rounds_needing_evidence=1)
    monkeypatch.setattr(A.llm, "chat", chat)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    assert r["status"] == "complete" and r["rounds"] == 2
    assert ("speed_trend", None) in ran and ran.count(("speed_trend", None)) == 1
    belief = r["hypotheses"][0]
    assert [h["confidence"] for h in belief["history"]] == [0.8, 0.6] and belief["history"][1]["reason"] == "speeds also fall"
    assert [c["verdict"] for c in r["critiques"]] == ["needs_evidence", "approve"]
    assert any("emergency" in a["text"].lower() for a in r["actions"])  # mandatory action added by code
    prog = json.loads((runs_dir / f"{r['run_id']}.json").read_text())
    agents = [s["agent"] for s in prog["steps"] if s["kind"] == "llm"]
    assert agents == ["investigator", "diagnostician", "critic", "investigator", "diagnostician", "critic", "advisor"]
    assert prog["status"] == "complete" and (runs_dir / f"{r['run_id']}.full.json").exists()


def test_loop_stops_after_three_rounds(setup, monkeypatch):
    memory, ran, _ = setup
    chat, calls = scripted_llm(critic_rounds_needing_evidence=5)
    monkeypatch.setattr(A.llm, "chat", chat)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    assert r["rounds"] <= 3 and calls.count("Critic") <= 3


def test_agent_failing_twice_gives_a_partial_result(setup, monkeypatch):
    memory, _, _ = setup
    chat, calls = scripted_llm(fail_agent="diagnostician")
    monkeypatch.setattr(A.llm, "chat", chat)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    assert r["status"] == "partial" and calls.count("Diagnostician") == 2
    assert r["headline"].startswith("Partial result") and "No operator has a clear line" in (r["explanation"] or "")


def test_guard_drops_beliefs_citing_unknown_evidence(setup, monkeypatch):
    memory, _, _ = setup
    chat, _ = scripted_llm(critic_rounds_needing_evidence=0)

    def bad_diag(messages, **kw):
        if kw.get("schema") is S.HypothesisSet:
            return LLMResult(model="m", parsed=S.HypothesisSet(hypotheses=[S.Hypothesis(
                id="weather", cause="weather", confidence=0.9, supporting_evidence=["invented_id"], contradicting_evidence=[],
                explanation="Storms [invented_id].")], revision_reasons=[]))
        return chat(messages, **kw)

    monkeypatch.setattr(A.llm, "chat", bad_diag)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    assert r["hypotheses"] == []
    guards = [n for n in memory.notes(r["run_id"]) if n.get("type") == "guard"]
    assert any(n.get("guard_kind") == "dropped_belief" for n in guards)


def test_guard_caps_weak_beliefs_and_strips_prior_diagnoses(setup, monkeypatch):
    memory, _, _ = setup
    chat, _ = scripted_llm(critic_rounds_needing_evidence=0)
    weak = {"speeds_near": item("speed_cell", "Speed 14.4 Mbps (25 tests).", "moderate"),
            "sites_near": item("operators_5km", "Only Vodafone has sites.", "moderate"),
            "prior_diagnoses_nearby": item("prior_diagnoses", "1 earlier diagnosis within 10 km.", "moderate")}
    weak["speeds_near"]["sample_size"] = {"tests": 25}
    weak["sites_near"].update(source="Approximate mast sites (Zetaris CD_MASTS_SITES)",
                              value={"operators_confirmed": ["Vodafone"]}, sample_size={"sites_unknown_operator": 2})
    for name, it in weak.items():
        monkeypatch.setitem(T.TOOLS, name, (lambda it: lambda case, operator=None: [it])(it))

    def diag(messages, **kw):
        if kw.get("schema") is S.HypothesisSet:
            return LLMResult(model="m", parsed=S.HypothesisSet(hypotheses=[S.Hypothesis(
                id="single_operator", cause="single_operator", confidence=0.8,
                supporting_evidence=["speed_cell", "operators_5km", "prior_diagnoses"], contradicting_evidence=[],
                explanation="Only Vodafone has sites nearby [operators_5km].")], revision_reasons=[]))
        return chat(messages, **kw)

    monkeypatch.setattr(A.llm, "chat", diag)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    b = r["hypotheses"][0]
    assert b["confidence"] == 0.5 and "prior_diagnoses" not in b["supporting"]
    kinds = {n.get("guard_kind") for n in memory.notes(r["run_id"]) if n.get("type") == "guard"}
    assert {"weak_cap", "context_only"} <= kinds


def test_confidence_change_without_a_reason_is_discarded(setup, monkeypatch):
    memory, _, _ = setup
    chat, _ = scripted_llm(critic_rounds_needing_evidence=1)

    def no_reasons(messages, **kw):
        r = chat(messages, **kw)
        if kw.get("schema") is S.HypothesisSet:
            r.parsed.revision_reasons = []
        return r

    monkeypatch.setattr(A.llm, "chat", no_reasons)
    r = C.diagnose_point(lat=54.445, lon=-3.105, memory=memory)
    assert r["rounds"] == 2 and r["hypotheses"][0]["confidence"] == 0.8
    assert any(n.get("guard_kind") == "unexplained_change" for n in memory.notes(r["run_id"]) if n.get("type") == "guard")


def test_zone_advice_keeps_belief_citations_given_as_cause_names(monkeypatch):
    memory = offline_memory(monkeypatch)
    run_id = memory.create_run("zone", query="Z1")
    case = T.Case(run_id=run_id, scope="zone", point={"lat": 54.7, "lon": -2.6, "label": "Ousby"}, zone_id="Z1", memory=memory)
    memory.add_evidence(run_id, {**item("zone_overview", "836 of 873 people have no identified site within 5 km."),
                                 "evidence_id": "zone_overview"})
    memory.add_belief(run_id, "distance_to_mast", 0.65, "No site within 5 km [zone_overview].", ["zone_overview"], [], round=1)
    seen = {}

    def chat(messages, **kw):
        seen["user"] = messages[-1]["content"]
        return LLMResult(model="m", parsed=S.ZoneAdvice(
            headline="Distance is the likely cause [Distance_To_Mast].",
            explanation="836 of 873 people have no site nearby [distance_to_mast][zone_overview] [made_up].",
            cited_evidence=["distance_to_mast", "zone_overview", "made_up"], limitations="Sites are approximate."))

    monkeypatch.setattr(A.llm, "chat", chat)
    out = A.advise_zone(case)
    assert "[distance_to_mast] cause distance_to_mast" in seen["user"]  # beliefs listed with id and cause name
    assert out.cited_evidence == ["distance_to_mast", "zone_overview"]
    assert out.headline.endswith("[distance_to_mast].") and "[distance_to_mast][zone_overview]" in out.explanation
    assert "made_up" not in out.explanation and "836 of 873" in out.explanation  # numbers checked via the belief's evidence
