# Examples

Real agent runs (Nemotron + Meterless + Zetaris), 26 Oct 2026.

- `great_langdale/`: the reference point run (run_20261026205600_c6qi, 2 rounds): `diagnosis.json`
  (result), `trace.json` (Meterless audit trail, notes, critiques), `evidence.json`, `world.json`
  (World Model entities and relationships), `progress.json` (per-step progress). Used for sample
  mode and the demo.
- `phase4/`: every Phase 4 check run in full (`*.full.json`: result, audit, evidence, beliefs,
  critiques, notes, World Model; `*.progress.json`), `summary.json` and the check's printed output
  (`check_output.txt`, from `scripts/check_coordinator.py`).
