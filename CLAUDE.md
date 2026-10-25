# Coverage Detective

Open Agent Hackathon project (deadline Tue 27 Oct 2026, 23:45 UK). A multi-agent tool that
explains **why mobile signal is poor** at a UK location from real public data, and ranks
coverage gaps for operators and councils. Scope: mobile networks only (4G/5G, phones,
mobile data), not home broadband.

Sponsor tech: **Zetaris** (federated SQL, local Docker) — every dataset the agents use is
registered there as a separate source and queried through it. **Meterless** (memory /
world model) comes later; agents are not built yet.

## Product context

Hackathon track: "The Agent That Can Explain Why". Judging: Impact 30, Technical 20,
Innovation 15, Demo 15, Product & UX 10, Sponsor Tech 10. Judges reward agents that
critique each other, planner/executor/evaluator loops, shared memory, retries and visible
traces; they penalise linear pipelines, prompt wrappers, hardcoded demo paths and
unsupported claims.

Two modes:
1. **Why is my signal bad?** postcode/place → ranked likely causes with confidence,
   evidence for each, causes ruled out, actions.
2. **Where are the gaps?** region → ranked under-served areas with main cause, people
   affected and suggested fix.

Agents (built later): Coordinator (routing, max 3 rounds, fallbacks), Investigator
(Zetaris + live APIs → evidence items), Diagnostician (hypotheses from a fixed cause set:
distance_to_mast, terrain_blocking, single_operator, capacity_strain, weather,
active_incident, insufficient_data), Critic (approves / asks for more
evidence / downgrades), Advisor (audience-specific explanation), Gap analyst (screening
query → parallel diagnoses → group by cause). Meterless holds the world model and each
agent's beliefs with an audit trail; Zetaris is the evidence layer.

**capacity_strain** (not "peak congestion": Ookla open data has no time-of-day or weekday
breakdown, so congestion can only be inferred): speeds are low although coverage and
nearby masts look adequate. Evidence: speeds declining over the last 3–4 quarters, high
tests/devices per head (e.g. visitor areas), masts nearby with no terrain block.

**single_operator** comes from OpenCelliD (not Ofcom): word findings as "only N operators
have masts within 5 km", never "only N operators cover this area", and lower confidence
when masts_within_5km is small.

Evidence strength: OpenCelliD is crowd-sourced and incomplete, so "masts found" is stronger
evidence than "no masts found".

Ofcom: the postcode-level API is not available to us (`sources/ofcom_api.py` is a stub that
returns None; None means "no Ofcom data", not "no coverage"). Ofcom local-authority
downloads are regional context only, deferred to Mon 26 Oct. The Advisor's resident
actions must include "Check your address on Ofcom's mobile coverage checker"
(https://www.ofcom.org.uk/mobile-coverage-checker).

Principles: code and SQL compute every number, the LLM only interprets; every claim links
to an evidence item; causes are "likely" with confidence; sample/offline mode for
reproducible runs.

Limitations (state them in outputs):
- Causes are inferred, not confirmed (operators' internal data isn't public).
- Ookla data is aggregated by quarter with no time-of-day detail, so congestion can only
  be inferred indirectly.
- No address-level Ofcom coverage: the Ofcom API is not available to us, and Ofcom's
  local-authority figures (regional context only) are predicted, not measured.
- OpenCelliD mast data is crowd-sourced and incomplete, and positions are estimated from
  measurements, so sites are approximate. Operators come from network codes, and networks
  have merged (EE = T-Mobile + Orange; Vodafone UK + Three UK = VodafoneThree, 2025), so
  labels follow the reference table, not current company names.
- Mobile networks only; home broadband is out of scope.

## Layout

```
coverage_detective/   package
  config.py           paths (data/raw, data/processed, data/samples), .env loading, H3_RES=7
  data/               processed-data helpers (grid.py: H3 cells + population), Zetaris client
  sources/            external sources (Ookla, OpenCelliD, DEM, Ofcom, geocode, weather, floods)
  api/                FastAPI evidence API
scripts/download/     fetch raw data into data/raw/<source>/ (skip files that exist)
scripts/process/      build data/processed/*.parquet from raw data
scripts/zetaris/      register processed files as Zetaris sources
tests/                pytest
web/                  frontend (later)
data/raw/             raw inputs and downloads (gitignored)
data/processed/       built Parquet files (gitignored)
data/samples/         small cached API responses for SAMPLE_MODE (committed)
data/reference/       small reference tables (committed), e.g. mcc_mnc_uk.csv
```

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # then fill in
.venv/bin/python scripts/process/build_cells.py    # Phase 1 -> data/processed/cells_r7.parquet
.venv/bin/python scripts/download/ookla.py         # Phase 2: UK extracts of the last 4 quarters
.venv/bin/python scripts/process/build_ookla.py    # -> ookla_mobile_r7 / _history_r7 / _tiles
.venv/bin/python scripts/download/mcc_mnc.py       # Phase 3: operator reference (already committed)
.venv/bin/python scripts/download/opencellid.py    # needs OPENCELLID_TOKEN; skips without it
.venv/bin/python scripts/process/build_masts.py    # -> masts.parquet, masts_r7.parquet
.venv/bin/python -m pytest -q
```

Inputs placed by hand: `data/raw/boundary/uk_countries.geojson` (ONS countries, all four
nations) and `data/raw/population/population.tif` (WorldPop UK).

## Status

Built in phases; stop after each for review.
1. Grid, H3 r7: done (`cells_r7.parquet`: cell_id, lat, lon, population, nation)
2. Ookla mobile speeds: done (latest 2026Q3 + 3 previous quarters; per-cell, history and tile tables)
3. OpenCelliD masts: code done and tested; waiting for OPENCELLID_TOKEN to build real data
4. Terrain/DEM + line of sight: not started
5. Ofcom LA coverage: deferred to Mon 26 Oct (regional context only); API stub done
6. Zetaris registration · 7. Live sources · 8. Evidence API (neighbour aggregation,
   weak-evidence flags) · 9. Docs

## Rules

- Never commit secrets: `.env` is gitignored, `.env.example` has placeholders only.
- Raw downloads go in `data/raw/` (gitignored). Committed sample data stays small (`data/samples/`).
- Record every source's licence and processing steps in data/README.md.
- Always carry sample sizes (tests, devices) with Ookla figures; many cells have 1–2 tests.
- Scripts are re-runnable: skip downloads that already exist; `--force` rebuilds.
- Simple, readable code. If an external source or Zetaris is blocked or slow, say so
  with options rather than working around it silently.
