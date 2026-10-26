# Examples

Real agent runs (Nemotron + Meterless + Zetaris), 26 Oct 2026.

- `great_langdale/`: the reference point run (run_20261026213702_fgoz, 2 rounds, after the Phase 4
  review fixes: the critic asked for a speed trend on the weather belief and rejected a weak
  single-operator belief; the guard's interventions are in the trace): `diagnosis.json`
  (result), `trace.json` (Meterless audit trail, notes, critiques), `evidence.json`, `world.json`
  (World Model entities and relationships), `progress.json` (per-step progress). Used for sample
  mode and the demo.
- `compare/`: the model check after Phase 4 (diagnostician on 3.5 Super, critic on Ultra with a
  90 s timeout, the code guard's weak-evidence and context-only rules): Great Langdale (3 runs),
  central London, near Rhayader, with `summary.json` and the printed output.
- `phase4/`: every Phase 4 check run (kept as recorded; the first reference example was its
  Great Langdale run c6qi) in full (`*.full.json`: result, audit, evidence, beliefs,
  critiques, notes, World Model; `*.progress.json`), `summary.json` and the check's printed output
  (`check_output.txt`, from `scripts/check_coordinator.py`).
