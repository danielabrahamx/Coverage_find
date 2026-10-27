# Examples

Recorded agent runs, replayed by sample mode (`python run.py --sample`) and the tests. Recorded on 27 Oct 2026 with
`scripts/record_examples.py`: sample data (DuckDB over `sample_data/zetaris/`, saved live responses) and the live
NVIDIA Nemotron models, so replay reproduces each run exactly. `index.json` lists what each example answers (a
place within 1 km, a zone id, or an area) and the hash of the prompts used; a test fails if a prompt changes
after recording.

| Folder | Kind |
|---|---|
| `great_langdale/` | point: hills block every operator; letters to the operator, council and MP |
| `central_london/` | point: fast measured service, no strong cause |
| `near_rhayader/` | point: two rounds, critic objections |
| `sutton_st_edmund/` | point: flat Fens, distance |
| `remote_powys/` | point: insufficient data (no tests, no site within 10 km) |
| `zone_ousby/` | gap zone with a fix plan |
| `opportunity_windermere/` | improvement opportunity |
| `summary_uk/`, `summary_westmorland/` | priority summaries (gap and opportunity sections) |

Each point / zone folder: `diagnosis.json` (the result), `trace.json` (Meterless audit trail, notes, critiques),
`evidence.json` (items with their SQL), `world.json` (World Model), `progress.json` (per-step progress),
`llm_replies.json` (every agent reply, keyed by example + agent + round + call index; a missing key fails the
run with "no recorded reply for this step", never a live call).

Earlier development runs (`phase4/`, `compare/`) were removed from the tree on 27 Oct 2026; they remain in the
git history (commit 8ad9932).
