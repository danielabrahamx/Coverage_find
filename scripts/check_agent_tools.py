"""Phase 2 check: agent tools into Meterless, and Nemotron structured output with the real schemas.

    python scripts/check_agent_tools.py     # needs Zetaris, the Meterless service and LLM_* in .env
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.agents import schemas as S  # noqa: E402
from coverage_detective.agents.llm import llm  # noqa: E402
from coverage_detective.agents.tools import POINT_TOOLS, ZONE_TOOLS, Case, run_tool, tool_specs  # noqa: E402
from coverage_detective.memory.meterless import memory  # noqa: E402


def tools_check() -> tuple[str, list[dict]]:
    run_id = memory.create_run("point", query="Great Langdale (tools check)", location={"lat": 54.445, "lon": -3.105})
    case = Case.for_point(run_id, lat=54.445, lon=-3.105)
    print(f"run {run_id} (Meterless mode: {memory.mode})")
    plan = [("speeds_near", {}), ("speed_trend", {}), ("sites_near", {}), *[("line_of_sight", {"operator": o}) for o in
            ["EE", "O2", "Three", "Vodafone"]], ("terrain", {}), ("ofcom_area", {}), ("live_conditions", {}),
            ("prior_diagnoses_nearby", {}), ("line_of_sight", {"operator": "EE"})]  # the last one: idempotent
    for name, args in plan:
        t = time.time()
        items = run_tool(case, name, args, round=1)
        print(f"  {name}({args or ''}) {time.time() - t:4.1f}s -> " + ", ".join(
            f"{i['id']}[{i['strength']}]{'' if i['created'] else ' (existing)'}" for i in items))
    ev = memory.evidence(run_id)
    print(f"  Meterless now holds {len(ev)} evidence items for the run; "
          f"{sum(1 for e in ev if e.get('zetaris'))} carry their Zetaris SQL; "
          f"{len(memory.notes(run_id))} tool-call notes")
    print(f"  e.g. {ev[0]['evidence_id']}: {ev[0]['finding'][:110]}")

    zrun = memory.create_run("zone", query="Z00603")
    zcase = Case(run_id=zrun, scope="zone", point={"lat": 54.45, "lon": -3.12}, zone_id="Z00603")
    for name in ["zone_summary", "candidate_sites"]:
        items = run_tool(zcase, name, {}, round=1)
        print(f"  zone {name} -> " + ", ".join(i["id"] for i in items))
    return run_id, ev


def llm_check(ev: list[dict]) -> None:
    print(f"\nmodels: fast {llm.model}; reasoning {llm.reasoning_model}")
    evidence_text = "\n".join(f"[{e['evidence_id']}] ({e['strength']}) {e['finding']}" for e in ev)
    cases = [
        ("investigator tool calling", dict(messages=[
            {"role": "system", "content": "You are the investigator. Call the tools needed to explain poor signal at the point. "
                                          "Round 1: speeds_near, sites_near, line_of_sight for each operator, ofcom_area, live_conditions."},
            {"role": "user", "content": "Why is my signal bad here? (point already set)"}], tools=tool_specs(POINT_TOOLS))),
        ("diagnostician HypothesisSet (reasoning)", dict(messages=[
            {"role": "system", "content": "You are the diagnostician. Propose up to 4 ranked hypotheses from the cause list, citing "
                                          "evidence ids only. revision_reasons: empty on the first round."},
            {"role": "user", "content": evidence_text}], schema=S.HypothesisSet, reasoning=True)),
        ("critic CritiqueSet (reasoning)", dict(messages=[
            {"role": "system", "content": "You are the critic. Review each hypothesis: approve, needs_evidence (with requested_checks), "
                                          "downgrade (with suggested_confidence) or reject."},
            {"role": "user", "content": evidence_text + "\n\nHypotheses:\n- terrain_blocking 0.85 cites [los_vodafone, los_ee]\n"
                                        "- single_operator 0.5 cites [operators_5km]"}], schema=S.CritiqueSet, reasoning=True)),
        ("advisor AdvisorOutput", dict(messages=[
            {"role": "system", "content": "You are the advisor for a resident. Use only the evidence; cite ids; no new numbers."},
            {"role": "user", "content": evidence_text + "\n\nApproved: terrain_blocking 0.8."}], schema=S.AdvisorOutput)),
        ("fix planner FixPlan", dict(messages=[
            {"role": "system", "content": "You are the fix planner. Choose a fix type and candidate id from the evidence."},
            {"role": "user", "content": "[fix_rule] Rule-based fix: New site, then gather measurements first.\n"
                                        "[cand_1] Candidate 1: new 25 m mast on high ground; 48 of the zone's people gain a clear line."}],
             schema=S.FixPlan)),
    ]
    for name, kw in cases:
        ok = 0
        for _ in range(2):
            try:
                r = llm.chat(**kw)
                good = bool(r.tool_calls) if "tools" in kw else r.parsed is not None
                ok += good
                last = (", ".join(f"{c['name']}({json.dumps(c['arguments'])})" for c in r.tool_calls) if "tools" in kw
                        else r.parsed.model_dump_json()[:150])
                info = f"{r.duration_ms / 1000:.1f}s, {r.usage.get('total_tokens')} tokens, attempts {r.attempts}"
            except Exception as e:  # noqa: BLE001
                last, info = f"{type(e).__name__}: {str(e)[:150]}", "failed"
        print(f"  {name:<42} {ok}/2 ok ({info})\n      {last}")


if __name__ == "__main__":
    _, evidence = tools_check()
    llm_check(evidence)
