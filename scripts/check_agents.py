"""Phase 3 check: each agent once on Great Langdale (point) and its gap zone, plus timings.

    python scripts/check_agents.py     # needs Zetaris, the Meterless service and LLM_* in .env

Not the loop (that is phase 4): investigate, diagnose and critique one round each (a second
investigate + diagnose if the critic asked for checks), then advise and draft a letter; for the
zone: investigate, diagnose, plan a fix, review it, advise.
"""

from __future__ import annotations

import statistics
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.agents import agents as A  # noqa: E402
from coverage_detective.agents.tools import Case  # noqa: E402
from coverage_detective.memory.meterless import memory  # noqa: E402


def show_beliefs(run_id: str) -> None:
    for b in memory.beliefs(run_id):
        hist = " -> ".join(f"{h['confidence']:.2f}" for h in b["history"])
        print(f"    {b['belief_id']:<18} {hist:<16} ({b.get('status')}) for {b.get('supporting')}")
        for h in b["history"][1:]:
            print(f"        {h['by']}: {h['reason'][:140]}")


def notes(run_id: str, kind: str) -> list[dict]:
    return [n for n in memory.notes(run_id) if n.get("type") == kind]


def point() -> str:
    run_id = memory.create_run("point", query="Great Langdale (agents check)", location={"lat": 54.445, "lon": -3.105})
    case = Case.for_point(run_id, lat=54.445, lon=-3.105)
    print(f"== point run {run_id}")
    ids = A.investigate(case, 1)
    print(f"  investigator round 1 -> {len(ids)} items: {', '.join(ids)}")
    A.diagnose(case, 1)
    print("  diagnostician round 1:")
    show_beliefs(run_id)
    req = A.critique(case, 1, final_round=False)
    print("  critic round 1:")
    for c in memory.critiques(run_id):
        print(f"    {c['belief_id']}: {c['verdict']}: {c['reason'][:170]}")
        for chk in c.get("requested_checks") or []:
            print(f"        requests {chk['tool']}({chk.get('operator') or ''}): {chk['why'][:90]}")
    if req:
        ids = A.investigate(case, 2, req)
        print(f"  investigator round 2 (critic's checks) -> {', '.join(ids) or 'nothing new'}")
        A.diagnose(case, 2)
        print("  diagnostician round 2:")
        show_beliefs(run_id)
    adv = A.advise(case)
    print(f"  advisor headline: {adv.headline}")
    print(textwrap.fill(f"  explanation: {adv.explanation}", 130, subsequent_indent="    "))
    print(f"  best network: {adv.best_network.summary}")
    for n in adv.best_network.ranking:
        print(f"    {n.rank}. {n.operator} ({n.confidence}): {n.why[:120]}")
    print(f"  ruled out: {[(r.cause, r.reason[:60]) for r in adv.ruled_out]}")
    print(f"  actions: {[a.text[:70] for a in adv.actions]}")
    diag = {"location": case.point, "headline": adv.headline, "explanation": adv.explanation,
            "cited_evidence": adv.cited_evidence,
            "hypotheses": [{"cause": b["cause"], "confidence": b["confidence"], "status": b.get("status"),
                            "supporting": b.get("supporting")} for b in memory.beliefs(run_id)]}
    letter = A.write_letter(case, "operator", diag)
    print(f"  letter to operator: {letter.subject}\n" + textwrap.indent(letter.body_markdown[:600], "    | "))
    for g in notes(run_id, "guard"):
        print(f"  GUARD: {g['summary'][:160]}")
    return run_id


def zone() -> str:
    run_id = memory.create_run("zone", query="Z00603", label="Near Raw Head (Great Langdale)")
    case = Case(run_id=run_id, scope="zone", point={"lat": 54.4458, "lon": -3.1121, "label": "Z00603"}, zone_id="Z00603")
    print(f"\n== zone run {run_id}")
    print(f"  investigator -> {', '.join(A.investigate(case, 1))}")
    A.diagnose(case, 1)
    show_beliefs(run_id)
    plan = A.plan_fix(case, 1)
    print(f"  fix plan: {plan['fix_type']} at {plan['candidate']}: {plan['why'][:160]}")
    print(f"    assumptions: {plan['assumptions']}")
    print(f"    values from evidence: {plan.get('candidate_values')}")
    review = A.review_fix(case, 1, plan)
    print(f"  critic on the plan: {review.verdict}: {review.reason[:160]} {review.issues}")
    if review.verdict == "revise":
        plan = A.plan_fix(case, 2, review)
        print(f"  revised plan: {plan['fix_type']} at {plan['candidate']}: {plan['why'][:160]}")
    adv = A.advise_zone(case)
    print(f"  zone advice: {adv.headline}")
    for g in notes(run_id, "guard"):
        print(f"  GUARD: {g['summary'][:160]}")
    return run_id


def timings(run_ids: list[str]) -> None:
    calls = [n for r in run_ids for n in notes(r, "llm_call")]
    errors = [n for r in run_ids for n in notes(r, "llm_error")]
    print("\n== time per agent call")
    by: dict[str, list[dict]] = {}
    for n in calls:
        by.setdefault(n["by"], []).append(n)
    for agent, ns in sorted(by.items()):
        secs = [n["duration_ms"] / 1000 for n in ns]
        tokens = [n["tokens"].get("total_tokens", 0) for n in ns if n.get("tokens")]
        retries = sum(len(n.get("retries") or []) for n in ns)
        switches = sum(1 for n in ns if n.get("fallback"))
        print(f"  {agent:<14} {len(ns)} calls  avg {statistics.mean(secs):5.1f}s  (min {min(secs):.1f}, max {max(secs):.1f})  "
              f"avg tokens {statistics.mean(tokens) if tokens else 0:,.0f}  retries {retries}  model switches {switches}  "
              f"model {ns[0]['model'].split('/')[-1]}")
    if errors:
        print(f"  failed calls: {len(errors)}: {[e['summary'][:80] for e in errors]}")


if __name__ == "__main__":
    runs = [point(), zone()]
    timings(runs)
