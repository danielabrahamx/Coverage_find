"""Phase 4 check: full agent runs through the coordinator.

    python scripts/check_coordinator.py            # all runs below, in order
    python scripts/check_coordinator.py langdale   # just some (names below)
    python scripts/check_coordinator.py --tag compare langdale london rhayader   # -> data/runs/compare_summary.json

Runs: Great Langdale, central London (WC2N 5DU), near Rhayader, Sutton St Edmund, the top zone in
Westmorland and Furness, then Great Langdale again (should find the first run as a prior
diagnosis). Each run's full output is in data/runs/<run_id>.full.json; a summary of all of
them is written to data/runs/phase4_summary.json.
"""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coverage_detective.agents.coordinator import RUNS_DIR, diagnose_point, diagnose_zone  # noqa: E402
from coverage_detective.api.council import zones as ranked_zones  # noqa: E402
from coverage_detective.memory.meterless import memory  # noqa: E402

RUNS = {
    "langdale": lambda: diagnose_point(lat=54.445, lon=-3.105),
    "london": lambda: diagnose_point(query="WC2N 5DU"),
    "rhayader": lambda: diagnose_point(lat=52.30, lon=-3.51),
    "sutton": lambda: diagnose_point(query="Sutton St Edmund"),
    "zone": lambda: diagnose_zone(ranked_zones(scope="la:E06000064", limit=1)["zones"][0]["zone_id"]),
    "langdale_again": lambda: diagnose_point(lat=54.445, lon=-3.105),
}


def wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text or "", 140, initial_indent=indent, subsequent_indent=indent + "  ")


def show(name: str, r: dict) -> dict:
    run_id = r["run_id"]
    notes = memory.notes(run_id)
    calls = [n for n in notes if n.get("type") == "llm_call"]
    print("=" * 140)
    print(f"{name}: {r['location'].get('label')}  run {run_id}  status {r['status']}  rounds {r['rounds']}  "
          f"wall clock {r['elapsed_s']:.0f}s  ({len(calls)} LLM calls, "
          f"{sum(1 for n in notes if n.get('type') == 'tool_call')} tool calls)")
    print(wrap(f"HEADLINE: {r['headline']}", "  "))
    if r.get("explanation"):
        print(wrap(r["explanation"]))
    print("  BELIEFS (confidence history, reasons):")
    for h in r["hypotheses"]:
        hist = " -> ".join(f"{x['confidence']:.2f}" for x in h.get("history") or [])
        print(f"    {h['cause']:<18} {hist:<22} {h['status']:<8} for {h.get('supporting')}")
        for x in (h.get("history") or [])[1:]:
            print(wrap(f"round {x.get('round')} {x['by']}: {x['reason']}", "        "))
    objections = [c for c in r.get("critiques", []) if c["verdict"] != "approve"]
    print(f"  CRITIC: {len(r.get('critiques', []))} reviews, {len(objections)} objections")
    for c in r.get("critiques", []):
        checks = ", ".join(f"{k['tool']}({k.get('operator') or ''})" for k in c.get("requested_checks") or [])
        print(wrap(f"round {c['round']} {c['target']}: {c['verdict'].upper()}"
                   + (f" -> {c['suggested_confidence']}" if c.get("suggested_confidence") is not None and c["verdict"] != "approve" else "")
                   + f": {c['reason']}" + (f" | requested: {checks}" if checks else ""), "    "))
    prior = next((e for e in memory.evidence(run_id) if e["evidence_id"] == "prior_diagnoses"), None)
    if prior:
        print(wrap(f"PRIOR: {prior['finding']}", "  "))
    if r.get("best_network"):
        bn = r["best_network"]
        print(wrap(f"BEST NETWORK: {bn['summary']}", "  "))
        for n in bn["ranking"]:
            print(wrap(f"{n['rank']}. {n['operator']} ({n['confidence']}): {n['why']}", "    "))
    if r.get("ruled_out"):
        print("  RULED OUT: " + "; ".join(f"{x['cause']} ({x['reason'][:80]})" for x in r["ruled_out"]))
    if r.get("actions"):
        print("  ACTIONS: " + " | ".join(a["text"][:80] for a in r["actions"]))
    if r.get("fix_plan"):
        f = r["fix_plan"]
        print(wrap(f"FIX PLAN: {f['fix_type']} at {f.get('candidate')}: {f['why']}", "  "))
        print(f"    people (from evidence): {f.get('candidate_values')}")
        print(f"    assumptions: {f['assumptions']}; revisions {f.get('revisions')}; critic: "
              f"{(f.get('review') or {}).get('verdict')}: {(f.get('review') or {}).get('reason', '')[:160]}")
    guards = [n for n in notes if n.get("type") == "guard"]
    for g in guards:
        print(wrap(f"GUARD: {g['summary']}", "  "))
    for n in notes:
        if n.get("type") in ("agent_error", "fallback", "coordinator", "llm_error"):
            print(wrap(f"{n['type'].upper()}: {n['summary']}", "  "))
    switches = [n for n in calls if n.get("fallback")]
    retries = sum(len(n.get("retries") or []) for n in calls)
    by_agent: dict[str, list[float]] = {}
    for n in calls:
        by_agent.setdefault(n["by"], []).append(n["duration_ms"] / 1000)
    print("  TIME: " + ", ".join(f"{a} {sum(v):.0f}s/{len(v)}" for a, v in by_agent.items())
          + f"; retries {retries}; model switches {len(switches)}")
    return {"name": name, "run_id": run_id, "status": r["status"], "rounds": r["rounds"], "elapsed_s": r["elapsed_s"],
            "headline": r["headline"], "objections": len(objections),
            "confidence_changes": sum(len(h.get("history") or []) - 1 for h in r["hypotheses"]),
            "llm_calls": len(calls), "retries": retries, "model_switches": len(switches),
            "time_by_agent": {a: round(sum(v), 1) for a, v in by_agent.items()}, "guard_interventions": len(guards),
            "guard_kinds": [g.get("guard_kind") for g in guards]}


def main() -> None:
    args = sys.argv[1:]
    tag = "phase4"
    if "--tag" in args:
        i = args.index("--tag")
        tag = args[i + 1]
        del args[i:i + 2]
    names = args or list(RUNS)
    summary = []
    for name in names:
        t = time.time()
        r = RUNS[name]()
        summary.append(show(name, r))
        print(f"  ({time.time() - t:.0f}s)")
    out = RUNS_DIR / f"{tag}_summary.json"
    old = json.loads(out.read_text()) if out.exists() else []
    out.write_text(json.dumps(old + summary, indent=1))
    print("\nSUMMARY")
    for s in summary:
        print(f"  {s['name']:<15} {s['status']:<8} rounds {s['rounds']}  {s['elapsed_s']:>5.0f}s  objections {s['objections']}  "
              f"confidence changes {s['confidence_changes']}  LLM calls {s['llm_calls']}  retries {s['retries']}  "
              f"switches {s['model_switches']}  guard {s['guard_interventions']}")


if __name__ == "__main__":
    main()
