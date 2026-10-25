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

**Mast wording rules** (evidence findings and agent output):
- Say "approximate mast sites", never a count of "masts": sites are clusters of
  crowd-sourced radio cells and mapped towers, and one real mast can appear as several.
- Use `operator_data_status` (per cell, `CD_MASTS.masts_r7`): `complete` (every nearby site
  has a known operator), `partial` (some unknown), `unknown` (sites found, no operators
  known), `no_sites_found`. When `partial` or `unknown`, say "operators could not be
  identified for N nearby sites" (N = `masts_unknown_operator_within_5km`); never imply
  fewer operators are present.
- `no_sites_found` is weak evidence: OpenCelliD's free data is incomplete.

Ofcom: the postcode-level API is not available to us (`sources/ofcom_api.py` is a stub that
returns None; None means "no Ofcom data", not "no coverage"). Ofcom Connected Nations area
data (July 2025, constituency / local authority; phase E) is regional context only, never
coverage at the exact location. Wording: "In <area>, X% of land has no outdoor 4G from any
operator and Y% from only one (Ofcom Connected Nations, July 2025)" (X = g4_geo_out_0,
Y = g4_geo_out_1). The Advisor's resident
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

## Zetaris (how it works here)

- Stack: `~/zetaris-platform` (Docker). Health: its `./verify.sh`. Run compose through
  `scripts/zetaris/compose.sh` (adds our read-only data mount; a plain `docker compose up`
  there drops it).
- Local files are readable only under `/home/zetaris/customer-data/shared/`
  (`zetaris_local_file_sytem_root_path`); data/processed is mounted there as
  `coverage_detective/`. Other paths: "Invalid file path to access".
- Client: `coverage_detective/data/zetaris.py`. `query(sql)` = SELECT only
  (`/query/sql/start` + `/query/sql/page`); `execute(sql)` = DDL such as
  `CREATE LIGHTNING ...` (`/sql-editor/sqls/run`). Sign-in at `ZETARIS_URL`
  (`http://localhost:3000`) `/api/auth/login` → `idToken` + `orgId`. All values come back
  as strings (the client converts numbers) and rows do not keep SELECT column order.
  Every query is logged to `logs/zetaris_queries.jsonl`.
- One Lightning database per dataset (`CD_*`), registered by
  `scripts/zetaris/register_sources.py` (one function per source; drop + recreate).
  No `IF EXISTS`; descriptions allow only letters, digits, spaces and `_ . - ,`;
  `SHOW DATABASES` is disabled (use `SHOW TABLES IN <db>`).
- After a Docker upgrade, containers on the old network could not reach each other; the
  fix was `sudo aa-remove-unknown`, then `docker compose down` (no `-v`) and `up -d`.

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # then fill in
.venv/bin/python scripts/process/build_cells.py    # Phase 1 -> data/processed/cells_r7.parquet
.venv/bin/python scripts/download/ookla.py         # Phase 2: UK extracts of the last 4 quarters
.venv/bin/python scripts/process/build_ookla.py    # -> ookla_mobile_r7 / _history_r7 / _tiles
.venv/bin/python scripts/download/mcc_mnc.py       # Phase 3: operator reference (already committed)
.venv/bin/python scripts/download/opencellid.py    # needs OPENCELLID_TOKEN; skips without it
.venv/bin/python scripts/download/osm.py           # Geofabrik GB + Ireland (~2.6 GB)
.venv/bin/python scripts/process/build_masts.py    # -> masts_sites.parquet, masts_r7.parquet
.venv/bin/python scripts/download/dem.py           # Copernicus GLO-30 tiles (~1.4 GB), for phase C
.venv/bin/python scripts/download/ons_boundaries.py # constituencies 2024 + local authorities Dec 2024
.venv/bin/python scripts/process/build_ofcom.py    # -> ofcom_area_r7.parquet, ofcom_nations.parquet
scripts/zetaris/compose.sh up -d driver           # Zetaris with our data mount
.venv/bin/python scripts/zetaris/register_sources.py
.venv/bin/python scripts/check_data.py             # checks through Zetaris
.venv/bin/python -m pytest -q
```

Inputs placed by hand: `data/raw/boundary/uk_countries.geojson` (ONS countries, all four
nations) and `data/raw/population/population.tif` (WorldPop UK).

## Status

Built in phases; after each: run checks, commit, stop for review. Current plan (25 Oct):
A Zetaris foundation · B masts (OpenCelliD + OSM) · C terrain + line of sight ·
D live sources (postcodes.io, Open-Meteo, Met Office warnings, EA floods) ·
E Ofcom regional (file in data/raw/ofcom/) · F rural-urban + deprivation ·
G power cuts (if time) · H visitor load (if time) · final check_data.py.

- A. Zetaris foundation: done (client, mount, CD_CELLS + 3 Ookla sources, join check)
- B. Masts: done (OpenCelliD + OSM merged; CD_MASTS_SITES, CD_MASTS). OpenCelliD's free file
  is incomplete in places (e.g. none within 5 km of Rhayader), so treat "no masts" as weak.
  DEM for phase C already downloaded (data/raw/dem/, Copernicus GLO-30, 93 tiles).
- E. Ofcom regional: done (CD_OFCOM_AREA per cell = constituency figures; CD_OFCOM_NATIONS per
  operator). Columns g4_geo_out_0..4 etc. = % with coverage from exactly N operators.

- Earlier: grid (`cells_r7`) and Ookla (2026Q3 + 3 previous quarters) built; Ofcom API stub.
- Order agreed 25 Oct: B → E → D → C → F → final check; G/H only if time.
- After the data session: evidence API (neighbour aggregation, weak-evidence flags), agents.

## Rules

- Never commit secrets: `.env` is gitignored, `.env.example` has placeholders only.
- Raw downloads go in `data/raw/` (gitignored). Committed sample data stays small (`data/samples/`).
- Record every source's licence and processing steps in data/README.md.
- Always carry sample sizes (tests, devices) with Ookla figures; many cells have 1–2 tests.
- Scripts are re-runnable: skip downloads that already exist; `--force` rebuilds.
- Simple, readable code. If an external source or Zetaris is blocked or slow, say so
  with options rather than working around it silently.
