# Coverage Detective

**Why is my mobile signal bad here, and where should a council act?** Coverage Detective answers both from
real public data (measured speeds, mast sites, terrain, Ofcom coverage, live weather and warnings). A small
team of AI agents investigates, argues with each other and writes a plain-English explanation in which every
claim points to an evidence item and the SQL behind it. Built for the Open Agent Hackathon ("The Agent That
Can Explain Why").

- **My signal** (`/signal`): pick an exact spot; the agents rank the likely causes with confidence, say what
  was ruled out, which network is likely best, what to do, and draft an evidence letter.
- **Council view** (`/council`): ranked **gap zones** (poorly served people) and **improvement opportunities**
  (not poorly served, but a measurable weakness), a fix view with candidate mast sites and the people each
  would reach, agent diagnoses on demand and a priority summary for any area.
- **Explore** (`/`): the data itself, cell by cell.

## Try it in two minutes (sample mode: no Zetaris, no network, no API key)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd meterless_service && npm install)        # Node 18+, for the Meterless memory service
.venv/bin/python run.py --sample             # http://localhost:8000
```

Sample mode answers every database query with DuckDB over small committed extracts of the Zetaris sources
(`data/samples/zetaris/`, DEM crops in `data/samples/dem/`), uses saved live responses (`data/samples/`) and
replays the recorded agent replies of the examples (`examples/`); Meterless still runs locally. Only the
example places and zones can be diagnosed there; anything else is refused with a clear message, and replayed
results are labelled "recorded". Open `/signal?lat=54.445&lon=-3.105` and press "Diagnose with agents", or
`/council?zone=Z00072`.

## Architecture

```
                 pages (/signal, /council, /)  ──  FastAPI  ──  coordinator (the loop)
                                                                   │
        ┌──────────────── evidence layer ───────┐    ┌──── shared case file ────┐    ┌── model layer ──┐
        │ Zetaris: one Lightning source per     │    │ Meterless H-MEM: evidence, │    │ NVIDIA Nemotron │
        │ dataset (CD_CELLS, CD_OOKLA_*, CD_MASTS│◄──►│ beliefs + revisions, critiques,│◄──►│ 3.5 Super: tools,│
        │ _*, CD_OFCOM_*, CD_TERRAIN, CD_LOS,    │    │ notes, trust-ledger audit │    │ diagnosis, advice│
        │ CD_GAP_ZONES, CD_OPP_ZONES, ... and the│    │ Meterless World Model:    │    │ 3 Ultra (thinking│
        │ live REST source CD_LIVE_EA_FLOODS)    │    │ places, zones, sites,     │    │ on): the critic  │
        │ + DEM line of sight, live APIs         │    │ operators, warnings, events│    └─────────────────┘
        └────────────────────────────────────────┘    └───────────────────────────┘
                       code guard after every agent: citations, weak evidence, numbers, wording
```

- **Zetaris is the evidence layer.** Every dataset is its own Lightning database and every query is logged
  with the evidence item it produced, so the UI can show the exact SQL behind each claim
  ([data report](docs/data_report.md): row counts, freshness and query times through Zetaris).
- **Meterless is the shared case file.** Agents never message each other: each reads the run's evidence,
  beliefs and critiques from Meterless H-MEM and writes its own back. Belief revisions are trust-ledger
  updates (who, old → new confidence, reason), so the audit trail is the trace you see. The World Model holds
  the place or zone, its sites per operator (with the line-of-sight result), warnings and events, and earlier
  diagnoses nearby are looked up as context.
- **Nemotron is the model layer** (`agents/llm.py`, OpenAI-compatible API): 3.5 Super for the investigator
  (tool calling), diagnostician, advisor, letter writer and fix planner (strict JSON schema); 3 Ultra with
  thinking for the critic. 5xx bursts are retried after 2 s and 6 s, then the other model answers; retries and
  switches are in the trace.

## The agent loop

```
investigate ──► diagnose ──► critique ──► critic asked for checks and round < 3? ──yes──► investigate again
                                                │no
                                                ▼
                         act: advisor (point)  /  fix planner ⇄ critic review (zone)
```

1. **Investigator** chooses tools (speeds, trend, sites, line of sight per operator, terrain, Ofcom area,
   live conditions, earlier diagnoses; for zones: zone summary, candidate sites). Each tool writes evidence
   items with stable ids, their Zetaris SQL and a strength (strong / moderate / weak).
2. **Diagnostician** ranks causes from a fixed set (distance_to_mast, terrain_blocking, single_operator,
   capacity_strain, weather, active_incident, insufficient_data) with confidence, citing evidence ids.
   "Insufficient data" is a valid answer.
3. **Critic** approves, asks for specific checks (which send the loop round again), downgrades or rejects,
   with reasons. Checks it applies: citations, evidence strength, unchecked alternatives, contradictions and
   time fit (a storm cannot explain years of poor speeds).
4. **Advisor** explains the reviewed beliefs for a resident, council officer or operator; for zones the
   **fix planner** proposes a fix from the candidate sites and the critic reviews it (one revision at most).

**The code guard** runs after every agent and records every intervention in Meterless: citations to evidence
that does not exist are removed (a belief left with none is dropped); a belief resting only on weak evidence
(under 30 tests, crowd-sourced sites only, unknown operators, a region-wide weather warning) is capped at
0.5; earlier diagnoses are context, never support; a confidence change needs a reason; every number must
match the cited evidence (else one rewrite, then the sentence is removed); improvement opportunities must be
called opportunities, never gaps or "no coverage". If an agent fails twice the run returns a partial result
built from the evidence.

## Pages

| My signal: the agents' result | How the agents decided | Council view: fix with a candidate |
|---|---|---|
| ![](docs/screenshots/ui_cleanup/after_great_langdale_result.png) | ![](docs/screenshots/ui_cleanup/after_ousby_agents_decided_round_open.png) | ![](docs/screenshots/council/06_ousby_fix_with_candidate.png) |

- Result tab: headline, recommended fix or best network, "why we think this" (confidence bars; hover shows
  old → new with the reason), ruled out, actions, an editable evidence letter (Markdown download).
- How the agents decided: one card per round from the Meterless audit trail; technical details (models,
  timings, tools, guard codes) on demand.
- Evidence: every item with its Zetaris SQL, and the run's World Model.
- Council view: "Analyse area" picker, Gaps | Opportunities | Both, zoom-based lists that always match the
  map, a Diagnose button per zone, "Diagnose the top 3 in view", Today / With candidate N.

## Examples

| Example | What it shows | Agents' headline | Rounds | Recorded in |
|---|---|---|---:|---:|
| [`central_london`](examples/central_london/) | fast measured service: "no strong cause" (good data, no cause above 0.3) | No strong cause was found; the service measures well here. | 1 | 49 s |
| [`great_langdale`](examples/great_langdale/) | hills block every operator (terrain 0.70, critic approves citing the margins); 3 evidence letters | Hills between you and the nearest masts are the likely cause. | 1 | 81 s |
| [`near_rhayader`](examples/near_rhayader/) | the loop at work: the critic asks for more checks (round 2) and downgrades a weak single-operator belief | Terrain blocking EE and Three signals is the likely cause. | 2 | 180 s |
| [`opportunity_windermere`](examples/opportunity_windermere/) | improvement opportunity: capacity upgrade, critic downgrades a weak belief, opportunity wording checked | Busy-network capacity strain is the likely cause. | 1 | 92 s |
| [`remote_powys`](examples/remote_powys/) | insufficient data: no tests, no site within 10 km | Not enough data to say why: there are no measured speeds at this point or within 1 km and no mast sites in our data within 10 km, so operators could not be identified. | 1 | 54 s |
| [`summary_uk`](examples/summary_uk/) | priority summary, gap and opportunity sections |  |  |  |
| [`summary_westmorland`](examples/summary_westmorland/) | priority summary for one council |  |  |  |
| [`sutton_st_edmund`](examples/sutton_st_edmund/) | flat Fens: distance, not terrain | Distance to the nearest mast is the likely cause. | 1 | 72 s |
| [`zone_ousby`](examples/zone_ousby/) | gap zone with no measurements: candidate sites, fix plan reviewed by the critic | No strong cause was found because there are no recent measurements. | 1 | 96 s |

Each example folder holds the result (`diagnosis.json`), the Meterless trace, evidence and World Model, the
progress steps and the recorded agent replies (keyed by example + agent + round + call). They were recorded
with `scripts/record_examples.py` (sample data, live model); `examples/index.json` records the prompts' hash,
and a test fails if a prompt changes after recording. `examples/phase4/` and `examples/compare/` keep earlier
runs made during development.

## Run it with the full data


```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in Zetaris, OpenCelliD and (optionally) Ofcom settings
```

Put the two input files in place:

- `data/raw/boundary/uk_countries.geojson`: ONS *Countries Boundaries UK* (all four nations)
- `data/raw/population/population.tif`: WorldPop UK population raster

## Zetaris

All data is queried through [Zetaris](https://www.zetaris.com) running locally in Docker
(the `zetaris-platform` bundle, default `~/zetaris-platform`; start it with its own
README and check with its `./verify.sh`).

1. **Settings** in `.env`: `ZETARIS_URL=http://localhost:3000` (the Zetaris web app; the
   client signs in there and sends SQL through its API proxy), `ZETARIS_USER`,
   `ZETARIS_PASSWORD`.
2. **Mount our data into Zetaris.** Zetaris only reads local files under
   `/home/zetaris/customer-data/shared/` inside its query engine; any other path fails
   with `Invalid file path to access`. `zetaris/docker-compose.coverage.yml` mounts
   `data/processed` there read-only, as `coverage_detective/`. Apply it with the wrapper,
   which passes that file after Zetaris's own `docker-compose.yml` (nothing in the
   zetaris-platform folder is changed):

   ```bash
   scripts/zetaris/compose.sh up -d driver
   ```

   Use `scripts/zetaris/compose.sh` instead of a plain `docker compose` from then on: a
   plain `docker compose up -d` in zetaris-platform recreates the driver without the mount.
   Set `ZETARIS_PLATFORM_DIR` if the bundle is elsewhere.
3. **Register the sources** (after building the data; re-runnable):

   ```bash
   .venv/bin/python scripts/zetaris/register_sources.py
   .venv/bin/python scripts/check_data.py      # cross-source checks through Zetaris
   ```

Each dataset is its own Zetaris source (Lightning database), e.g. `CD_CELLS.cells_r7`,
`CD_OOKLA_MOBILE.ookla_mobile_r7`. Code queries them with
`coverage_detective.data.zetaris.query(sql)`; every query is logged to
`logs/zetaris_queries.jsonl` (time, SQL, duration, rows, error) for the evidence trail.

## Pre-existing components

Not written for this project, used unchanged:

| Component | From | Licence | Used for |
|---|---|---|---|
| Meterless H-MEM reference engine (`vendor/meterless/hmem/`) | [Meterless/Meterless](https://github.com/Meterless/Meterless) `engines/hmem/reference` | Apache 2.0 | agents' shared memory: evidence, beliefs, critiques, trust ledger (audit trail) |
| Meterless World Model reference engine (`vendor/meterless/world-model/`) | same repo, `engines/world-model/reference` | Apache 2.0 | places, zones, sites, operators, warnings, relationships, events |
| Zetaris Lightning (local Docker stack) | Zetaris | sponsor licence | federated SQL over every dataset |
| Map and UI libraries: MapLibre GL, deck.gl, h3-js, OpenFreeMap tiles | npm / CDN | BSD-3 / MIT / Apache 2.0 / ODbL | the web pages |

The vendored engines' own tests: `cd vendor/meterless/hmem && npm install && npm test` (and
`world-model`). The upstream commit is recorded in `vendor/meterless/README.md`.

## Meterless service (agent memory)

`meterless_service/server.ts` (Node 18+, `cd meterless_service && npm install`) is a small
HTTP service on port 8100 over the two vendored engines; `python run.py` starts it next to
the web app and waits for its health check. It persists to `data/meterless/` (gitignored).

- H-MEM: runs, evidence items (stable ids per run, idempotent), beliefs (cause + confidence),
  belief revisions as trust-ledger updates (who, old → new confidence, reason), critiques,
  notes (guard interventions, tool calls), the ordered audit trail of a run, and past
  diagnoses near a point (within ~10 km).
- World Model: entities (place, zone, site, operator, warning), relationships (scoped by an
  operator context, e.g. place → nearest_site{EE} → site), events (diagnosis_completed,
  fix_plan_proposed).
- Python client: `coverage_detective/memory/meterless.py` (5 s timeout, one retry). If the
  service is down it logs loudly and uses an in-memory store with the same interface.

Check: `python scripts/check_memory.py`. Tests: `cd meterless_service && npm test`, and
`tests/test_memory.py` for the fallback.

## Data sources

| Source | What it tells us | Type | Licence | Date / version |
|---|---|---|---|---|
| WorldPop + ONS boundaries | People per cell; nation | file | CC BY 4.0; OGL v3.0 | 2020; ONS Dec 2023 |
| Ookla open data (mobile) | Measured mobile download/upload/latency, tests, devices, trend | file | CC BY-NC-SA 4.0 | 2026Q3 + 3 previous quarters |
| OpenCelliD | Crowd-sourced radio cells → approximate mast sites, operators *inferred* from network codes | file | CC BY-SA 4.0 | downloaded 25 Oct 2026 |
| OpenStreetMap (Geofabrik) | Mapped communication masts and towers | file | ODbL 1.0 | downloaded 25 Oct 2026 |
| Ofcom Wireless Telegraphy Register | Operators' licensed microwave links: operators *confirmed* at sites, antenna heights | file | Ofcom copyright, free re-use | downloaded 25 Oct 2026 |
| Ofcom Connected Nations | Predicted coverage by number of operators, per constituency / local authority; per operator by nation | file | OGL | July 2025 |
| ONS constituencies, local authorities | Which area a cell is in | file | OGL v3.0 | July 2024; Dec 2024 |
| OpenStreetMap places | Names for gap zones (city, town, village, hamlet) | file (from the OSM extracts) | ODbL 1.0 | downloaded 25 Oct 2026 |
| Copernicus DEM GLO-30 | Elevation per cell; line of sight to mast sites | file (93 tiles) | Copernicus DEM licence (free, attribution) | 2021 release (data 2011–2015) |
| postcodes.io | Postcode / place → location, district, region; nearest postcode to a point | REST, live (Python client) | OGL v3 data (ONS, OS, Royal Mail) | at question time |
| Open-Meteo forecast | Weather now and next 24 h (rain, snow, wind, gusts) → severity | REST, live (Python client) | CC BY 4.0, non-commercial, attribution | at question time |
| Met Office severe weather warnings (RSS) | Yellow / amber / red warnings for the point's region | RSS, live (Python client) | Crown copyright, OGL v3 | at question time |
| Environment Agency flood monitoring | Flood alerts / warnings within 10 km (England only) | REST, live: Python client + Zetaris REST source `CD_LIVE_EA_FLOODS` | OGL v3 | at question time |

Details, processing steps and exact licences: `data/README.md`.

## Build the data

```bash
.venv/bin/python scripts/process/build_cells.py   # H3 r7 grid with population and nation
.venv/bin/python scripts/download/ookla.py        # Ookla mobile tiles, UK only, last 4 quarters
.venv/bin/python scripts/process/build_ookla.py   # Ookla speeds per cell + trend
.venv/bin/python scripts/download/opencellid.py   # OpenCelliD UK cells (needs OPENCELLID_TOKEN)
.venv/bin/python scripts/download/osm.py           # OpenStreetMap GB + Ireland extracts (~2.6 GB)
.venv/bin/python scripts/process/build_masts.py   # mast sites + nearest mast / operators per cell
.venv/bin/python scripts/download/ofcom_wtr.py     # Ofcom Wireless Telegraphy Register (~54 MB)
.venv/bin/python scripts/process/build_wtr.py      # register points, merged into the mast sites
.venv/bin/python scripts/download/dem.py           # Copernicus DEM GLO-30 tiles (~1.4 GB)
.venv/bin/python scripts/download/ons_boundaries.py # ONS constituency + local authority boundaries
.venv/bin/python scripts/process/build_ofcom.py    # Ofcom July 2025 area coverage per cell (zip in data/raw/ofcom/)
.venv/bin/python scripts/process/build_terrain.py  # elevation and line of sight per cell
.venv/bin/python scripts/process/build_places.py   # OSM place names (zone names)
.venv/bin/python scripts/process/build_zones.py    # gap zones and improvement opportunities
.venv/bin/python scripts/zetaris/register_sources.py  # every source into Zetaris
.venv/bin/python scripts/check_data.py             # the data report (docs/data_report.md)
.venv/bin/python scripts/build_samples.py          # extracts for sample mode (data/samples/zetaris, dem)
.venv/bin/python scripts/record_examples.py        # re-record the examples (needs LLM_API_KEY)
```

Every script can be re-run safely; pass `--force` to rebuild an existing output.

## Data explorer

A map of every layer.

```bash
.venv/bin/python scripts/process/build_web_layers.py   # precompute map layers -> data/web/layers/
scripts/zetaris/compose.sh up -d                        # Zetaris with our data mount (cell details use it)
.venv/bin/python run.py                                 # http://localhost:8000
```

- Hexagons (H3 r7) coloured by the chosen layer: download speed (< 2, 2–5, 5–10, > 10
  Mbps), tests, speed trend, population, nearest mast site, operators within 5 km,
  operator data status, Ofcom land with no / one 4G operator, elevation range, line of
  sight to the nearest site (clear / marginal / blocked). Cells with fewer than 10
  tests are faded (weak evidence); grey means no data.
- Approximate mast sites appear from zoom 10 (coloured by source), Ookla tiles from zoom 12.
- Click a cell: its details come from **one cross-source Zetaris query** (cells, Ookla and
  history, neighbours, masts, Ofcom area), shown under "Zetaris query used", with data dates.
- **Explore is area level**: the cell panel shows cell aggregates only (speeds and tests,
  neighbours, trend, nearest site and operators within 5 km of the cell, the line-of-sight
  grade from the cell centre, elevation range, Ofcom area figures) and "Data details" with
  the Zetaris SQL. "Check an exact location here" opens My signal at the clicked point.
- Search a postcode or place (postcodes.io). Works on phones (the panel slides up).

API: `GET /api/layers`, `/api/layer/{name}`, `/api/masts?bbox=`, `/api/tiles?bbox=`,
`/api/cell/{cell_id}`, `/api/geocode?q=`, `/api/geocode/reverse?lat=&lon=`,
`/api/live?lat=&lon=` (add `&flood_via=zetaris` for the Zetaris path),
`/api/los?lat=&lon=` (line of sight from the exact point to the nearest site, or
`&site_id=`), `/health`
(OpenAPI docs at `/docs`).

![Explore, Lake District, line-of-sight layer with a cell open](docs/screenshots/explore_lake_district.png)
Screenshots: `pip install playwright`, then `python scripts/screenshots.py` (pass
`--chrome <path>` to use an installed Chromium) → `docs/screenshots/`.

![UK download speeds](docs/screenshots/uk_speed.png)

## My signal page

`http://localhost:8000/signal` (deep links `?q=LD6 5AD` or `?lat=52.30&lon=-3.51`): point
level, for one exact location. Search a postcode or place, or click the map at the exact
spot. It calls `POST /api/evidence` and shows, with no LLM involved, a map without hexagon
colouring (Ookla tiles within 2 km by speed, identified sites within 10 km by operator and
marked confirmed / inferred / unknown, the point, a faint outline of its hexagon, each
operator's line of sight) and a panel with:

- **Networks compared**: for EE, O2, Three and Vodafone, the nearest identified site
  (distance, direction, source: OpenCelliD / OpenStreetMap / Ofcom register), whether the
  operator is confirmed by Ofcom's licence register or inferred from crowd-sourced data,
  and the line of sight from the exact point (clear / marginal / blocked, obstruction
  height, mast height measured or assumed). Each operator's line is drawn on the map in its
  own colour, red and dashed where blocked, with the highest obstruction marked. "No site
  identified in our data" is never presented as "no coverage".
- **Likely best network here**: a rule (clear lines first, nearest first, confirmed
  operators first on ties; otherwise the least obstructed line), labelled "Based on data,
  not yet reviewed by agents".
- Measured speeds within 1 km (Ookla tiles), in the cell and the neighbouring cells, with
  test counts and strength; the 4-quarter trend; Ofcom area figures (area-level wording);
  current weather, Met Office warnings and flood warnings.
- **Why: the agents' diagnosis** (`POST /api/diagnose`, polled at `GET /api/runs/{id}`): the tabbed run view
  (Result / How the agents decided / Evidence), the evidence letter (`POST /api/runs/{id}/letter`), and a
  `?run=` deep link to reopen a run. "See this area in Explore" goes back to the area view.

![My signal, near Rhayader](docs/screenshots/signal_rhayader.png)

## Council view

`http://localhost:8000/council` (deep links `?scope=la:E06000064&zone=Z00603`): where are
the gaps? Pick an area (UK, a nation or a council), adjust the priority weights, and read a
ranked table of **gap zones** with a map coloured by score. Opening a zone shows its cells,
an evidence summary, a rule-based fix and the top candidate sites with lines to the cells
they would reach. Each zone links to Explore (its cells outlined) and My signal (its
centre). CSV export of the ranking. Two zone types: gap zones (below) and **improvement opportunities**
(cells that are not poorly served but have a measurable weakness: speed well below the area or UK median,
falling speeds, only 1-2 operators identified, or a busy-network signal; reasons computed in code,
`planning/opportunities.py`; 1,816 zones, teal on the map, "limited data" under 10 tests). The list always
matches the map (`GET /api/council/view`; zoom caps in `config.COUNCIL_VIEW`: below zoom 10 the top 40 gap
zones in view, from zoom 10 up to 100 gap zones and 60 opportunities). Any zone can be diagnosed by the
agents (`POST /api/council/zones/{id}/diagnose`); "Priority summary (agents)" summarises what is listed
(`POST /api/council/summary`).

How zones are built (`scripts/process/build_zones.py`, rules in `planning/zones.py`,
thresholds in `config.py`):

- A cell with at least 10 people is **poorly served** if (a) its test-weighted download over
  the cell and neighbour ring is below 5 Mbps from at least 10 tests, or (b) no approximate
  site lies within 5 km, unless at least 10 tests measure at least 5 Mbps (then it is a gap
  in our site data, not in coverage: 227 cells, e.g. Penzance), or (c) it has fewer than 10
  tests and terrain blocks the line (by 10 m or more) to every site within 5 km (the 8
  nearest are checked).
- **Zones** are H3-connected clusters of poorly served cells holding at least 50 people in
  total (a per-cell threshold missed sparse valleys such as Great Langdale). 677 zones,
  264,561 people (25 Oct data). Named after their largest OSM place.
- **Priority score** (`planning/scoring.py`), computed per request: people, severity,
  persistence (share of the last 4 quarters below 5 Mbps), worsening trend and few
  operators, each normalised 0–1 by rank within the chosen area and weighted (defaults
  35 / 25 / 15 / 10 / 15). The API returns each factor's contribution. Data confidence
  (tests) is shown separately. "Need" (deprivation, rural–urban) is left out until built.
- **Fixes** (`planning/siting.py`): a rule picks new site / add operators / capacity
  upgrade / gather measurements; up to 30 DEM high points within 5 km of the zone and the
  existing sites within 10 km are checked by line of sight (25 m mast, 1.5 m receiver) to
  every populated cell within 8 km, ranked by the zone's people gaining a clear line.
  Limits: simplified line of sight, no planning, land, power or backhaul checks.

API: `GET /api/council/scopes`, `/api/council/zones?scope=&weights=people:0.4,...`,
`/api/council/zones.csv`, `/api/council/zones/{zone_id}`, `/api/council/zones/{zone_id}/cells`.
Check: `python scripts/check_council.py`.

![Council view, Westmorland and Furness, Great Langdale zone open](docs/screenshots/council_westmorland_great_langdale.png)

## Evidence API

`POST /api/evidence` with `{"query": "WC2N 5DU"}` (postcode or place) or `{"lat": 54.445,
"lon": -3.105}` returns the evidence bundle the agents will work from
(`coverage_detective/evidence.py`):

- the point, its H3 r7 cell and the six neighbours;
- three Zetaris queries, each logged in the bundle (`zetaris_queries`: SQL, time, rows):
  Q1 the cross-source cell query (cells, Ookla with history and neighbours, masts, Ofcom
  area, terrain, line of sight), Q2 approximate mast sites within 10 km of the exact point,
  Q3 UK context (median devices per head and speed; cached per process), Q4 Ookla tiles
  within 1 km of the point (latest quarter);
- line of sight from the exact point to the nearest site of each operator within 10 km,
  and to the nearest site of any operator;
- live weather, Met Office warnings and EA flood warnings.

The bundle also has `operators` (the per-operator comparison used by the My signal page)
and `likely_best` (the rule-based summary, `reviewed_by_agents: false`). Each item has `id`, `source`, `data_period`, `as_of`, `query_or_url`, `cell_ids`,
`finding` (one plain-English sentence built in code, following the wording rules in
CLAUDE.md), `value`, `sample_size`, `strength` (strong / moderate / weak) and `bears_on`
(the causes it is relevant to). The bundle also carries `errors`, `limitations` and the
Ofcom coverage checker link for residents.

Strength, in short: Ookla speed is strong from 50 tests, weak under 10; line of sight is
strong when blocked by 30 m or more, weak when the margin is under 10 m (trees or buildings
in the surface model) or under 1 m of clearance; "no sites found" and operator gaps are weak
(crowd-sourced data is incomplete); unknown-operator sites weaken the operator item unless
all four operators are present; live items are weak when served from a sample.

```bash
.venv/bin/python scripts/check_evidence.py     # readable bundles for the 3 sample places
curl -s -X POST localhost:8000/api/evidence -H 'content-type: application/json' -d '{"query": "LD6 5AD"}'
```

Saved bundles for the sample places are in `data/samples/evidence/` (for agent tests).

## Data freshness

Two kinds of data:

- **Live, fetched when a question is asked:** postcode lookup (postcodes.io), weather
  (Open-Meteo), Met Office weather warnings and Environment Agency flood warnings. Their
  evidence is stamped with the fetch time. Clients (`coverage_detective/sources/`) use a
  5 s timeout, one retry and a disk cache (`data/cache/live/`, gitignored; postcodes 30
  days, weather 30 min, warnings and floods 15 min). If a call fails they use the cached
  copy, else a saved sample (`data/samples/`), and say which. `SAMPLE_MODE=true` answers
  from the samples only (offline, reproducible); refresh them with
  `python scripts/download/live_samples.py`. Check: `python scripts/check_live.py`.
- **Stored, refreshed periodically** and queried through Zetaris:

  | Source | Refreshed | How |
  |---|---|---|
  | Ookla mobile speeds | quarterly | when a newer quarter appears in the public bucket |
  | OpenCelliD radio cells | weekly | re-download |
  | OpenStreetMap masts | monthly | re-download the Geofabrik extracts |
  | Ofcom Wireless Telegraphy Register | monthly | re-download the CSV |
  | Ofcom Connected Nations | each release (about twice a year) | download the new zip by hand into `data/raw/ofcom/` (no API) |
  | WorldPop population, ONS boundaries, Copernicus DEM | manual | rarely change |

`data/manifest.json` (committed) records for every stored source its data period (e.g.
Ookla `2026Q3`), download dates, build time, refresh cadence and each output's row count
and SHA-256; every build script updates it. Evidence items carry `data_period` and
`as_of` from the manifest (`coverage_detective.data.manifest.evidence_meta`), or the fetch
time for live sources.

```bash
.venv/bin/python scripts/refresh.py --check-only          # what is due
.venv/bin/python scripts/refresh.py                       # refresh what is due
.venv/bin/python scripts/refresh.py --source ookla --force
```

A refresh downloads the new data (keeping the old file until the new one is in), rebuilds
the affected tables, re-registers them in Zetaris and updates the manifest.

## Tests

```bash
.venv/bin/python -m pytest -q        # offline: no Zetaris, network or LLM key needed
```

They cover the Meterless client and fallback, the guard (unknown ids dropped, weak caps, numbers, belief
citations, context-only evidence), the loop (a critic request triggers a second round; three rounds at
most; an agent failing twice gives a partial result), the Nemotron client (schemas, retries, model switch,
no secrets or reasoning kept), the Council view (opportunity reasons, zoom caps, the viewport list,
picker counts), the API, and sample mode end to end (every example replayed through the API with any LLM
call failing the test, a missing recorded reply failing clearly, and the prompts frozen with the examples).

Data sources and licences: see `data/README.md`.

## Limitations

- Causes are inferred from public data, not confirmed: operators' network data isn't public.
- Ookla speeds are quarterly aggregates with no time-of-day detail, so congestion can only
  be inferred indirectly (as "capacity strain").
- No address-level Ofcom coverage: the Ofcom API isn't available to us. Residents are
  pointed to Ofcom's [mobile coverage checker](https://www.ofcom.org.uk/mobile-coverage-checker).
- OpenCelliD mast data is crowd-sourced and incomplete, with approximate positions, so
  "no masts found" is weak evidence. Operator labels come from network codes and follow
  the reference table; networks have merged in recent years.
- Line of sight (terrain): "blocked" means the ground rises above the straight line to the
  site, so the signal is likely weaker (it bends over the ridge), not absent. Most antenna
  heights are assumed (25 m): Ofcom's register gives heights only for sites with licensed
  microwave links (40% of cells' nearest sites). Copernicus GLO-30 is a surface model: it
  includes some trees and buildings, so it is most reliable for hills and valleys; small
  obstructions (< 10 m, "marginal") may be woodland or buildings. Fresnel-zone clearance
  and indoor loss are not modelled.
- Mobile networks only; home broadband is out of scope.

## Future work

- Power cuts as a cause (`active_incident`): the distribution network operators publish
  outages in different formats; dropped for the hackathon.
- Flood warnings for Scotland (SEPA), Wales (NRW) and Northern Ireland (DfI Rivers).
