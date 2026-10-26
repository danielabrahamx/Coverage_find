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

**single_operator** comes from the mast sites (OpenCelliD / OSM / Ofcom register), not Ofcom
coverage: word findings as "only N operators have approximate mast sites within 5 km", never
"only N operators cover this area", and lower confidence when few sites are found.

Evidence strength: OpenCelliD is crowd-sourced and incomplete, so "masts found" is stronger
evidence than "no masts found".

**Confirmed vs inferred operators**: `operators_confirmed` come from Ofcom's Wireless
Telegraphy Register (licensed microwave links at the site): say "confirmed by Ofcom's
licence register". `operators_inferred` come from OpenCelliD network codes / OSM tags: say
"inferred from crowd-sourced data". The register lists fixed links, not base stations, so a
site missing from it is not evidence of anything. operator_data_status per cell:
confirmed / inferred / unknown / no_sites_found.

**Mast wording rules** (evidence findings and agent output):
- Say "approximate mast sites", never a count of "masts": sites are clusters of
  crowd-sourced radio cells and mapped towers, and one real mast can appear as several.
- Use `operator_data_status` (per cell, `CD_MASTS.masts_r7`): `confirmed` (an operator within
  5 km is confirmed by Ofcom's licence register), `inferred` (operators only from crowd-sourced
  data), `unknown` (sites found, no operators known), `no_sites_found`. Whenever
  `masts_unknown_operator_within_5km` > 0, say "operators could not be identified for N nearby
  sites"; never imply fewer operators are present.
- `no_sites_found` is weak evidence: OpenCelliD's free data is incomplete.

Ofcom: the postcode-level API is not available to us (`sources/ofcom_api.py` is a stub that
returns None; None means "no Ofcom data", not "no coverage"). Ofcom Connected Nations area
data (July 2025, constituency / local authority; phase E) is regional context only, never
coverage at the exact location. Wording: "In <area>, X% of land has no outdoor 4G from any
operator and Y% from only one (Ofcom Connected Nations, July 2025)" (X = g4_geo_out_0,
Y = g4_geo_out_1). The Advisor's resident
actions must include "Check your address on Ofcom's mobile coverage checker"
(https://www.ofcom.org.uk/mobile-coverage-checker).

**Freshness**: every evidence item carries `data_period` and `as_of`. Stored tables: from
`data/manifest.json` via `manifest.evidence_meta(<zetaris table>)`; live sources: the fetch
time (`manifest.live_meta()`). Every build script must call `manifest.record(...)`.
`scripts/refresh.py` refreshes stored sources on their cadence (Ookla new quarter,
OpenCelliD weekly, OSM monthly, Ofcom new release; WorldPop/ONS/DEM manual).

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
- Terrain: blocked means weaker, not no signal; antenna heights mostly assumed (25 m); GLO-30 is
  a surface model (includes some trees and buildings), most reliable for hills and valleys.

## Layout

```
coverage_detective/     package
  config.py             paths, .env loading, H3_RES=7, UK_BBOX, SAMPLE_LOCATIONS, sample_mode()
  evidence.py           evidence bundle for a point (Zetaris queries, line of sight, live sources)
  planning/             zones.py (gap zones), scoring.py (priority score), siting.py (fixes, candidates)
  memory/meterless.py   Meterless client (H-MEM + World Model over HTTP; in-memory fallback)
  agents/               llm.py (Nemotron client), schemas.py (pydantic), tools.py (tools -> Meterless),
                        agents.py (the agents), guard.py (code guard), prompts/*.md,
                        coordinator.py (the loop: diagnose_point, diagnose_zone; progress; export)
meterless_service/      Node HTTP service on :8100 over vendor/meterless (H-MEM, World Model); data/meterless/
vendor/meterless/       Meterless reference engines, vendored unchanged (Apache 2.0)
  data/
    grid.py             H3 r7 cells over the UK + WorldPop population
    masts.py            merge OpenCelliD / OSM / Ofcom register sites; per-cell mast stats
    terrain.py          Copernicus DEM reader + line_of_sight()
    queries.py          cell_sql(): the cross-source cell query (explorer + evidence)
    manifest.py         data/manifest.json: data periods, refresh cadence, evidence_meta()
    zetaris.py          Zetaris client (query / execute, token refresh, query log)
  sources/
    ookla.py, opencellid.py, osm_masts.py, ofcom.py, ofcom_wtr.py     stored sources
    live.py             shared live fetching (timeout, retry, cache, sample fallback)
    geocode.py, weather.py, met_office_warnings.py, flood_warnings.py live sources
    ofcom_api.py        stub (Ofcom postcode API not available; returns None)
  api/app.py            FastAPI: explorer API + /api/live + /api/los + POST /api/evidence; pages /, /signal, /council
  api/council.py        /api/council/* (scopes, ranked zones, CSV, zone detail with fixes)
scripts/download/       fetch raw data into data/raw/<source>/ (skip files that exist)
scripts/process/        build data/processed/*.parquet (+ build_web_layers.py for the map)
scripts/zetaris/        compose.sh (data mount), register_sources.py (one function per source)
scripts/check_*.py      check_data (A, B, E), check_live (D), check_terrain (C), check_evidence
scripts/refresh.py      refresh stored sources on their cadence
scripts/screenshots.py  Playwright screenshots -> docs/screenshots/
tests/                  pytest (91 tests; offline: samples, mocked Zetaris / DEM)
web/                    pages, no build step (MapLibre 5.24 + deck.gl 9.4 + h3-js 4.5):
                        index.html + app.js (Explore), signal.html + signal.js (My signal),
                        council.html + council.js (Council view), style.css
run.py                  start the explorer on :8000 (checks Zetaris)
data/raw/               raw inputs and downloads (gitignored)
data/processed/         built Parquet files (gitignored)
data/web/, data/cache/  generated map layers, live-call cache (gitignored)
data/samples/           live responses + evidence bundles for the sample places (committed)
data/reference/         small reference tables (committed): mcc_mnc_uk.csv,
                        operator_groups.csv, wtr_operator_licensees.csv
data/manifest.json      data versions (committed)
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
- REST sources: `CREATE LIGHTNING REST TABLE t FROM DB REQUEST(endpoint "...", method "GET",
  http_encoding "URLENCODED", response_type "JSON", insecure_ssl "false") HEADER() BODY()`; each
  query calls the endpoint and the JSON becomes one row (explode arrays in SQL). `${name}` in
  the endpoint is filled per query by `/*+ apiParam('name', 'value') */`, but CREATE calls the
  endpoint literally to infer the schema, and Open-Meteo / EA gateways 403 a literal `${`. So
  only unparameterised feeds work: `CD_LIVE_EA_FLOODS` (floods + flood_areas).
- After a Docker upgrade, containers on the old network could not reach each other; the
  fix was `sudo aa-remove-unknown`, then `docker compose down` (no `-v`) and `up -d`.

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                  # then fill in (never print or commit it)
scripts/zetaris/compose.sh up -d driver               # Zetaris with our read-only data mount

# Stored data (build order)
.venv/bin/python scripts/process/build_cells.py       # cells_r7 (needs the two hand-placed inputs below)
.venv/bin/python scripts/download/ookla.py            # UK extracts of the last 4 quarters (range reads)
.venv/bin/python scripts/process/build_ookla.py       # ookla_mobile_r7 / _history_r7 / _tiles
.venv/bin/python scripts/download/mcc_mnc.py          # operator reference (already committed)
.venv/bin/python scripts/download/opencellid.py       # needs OPENCELLID_TOKEN
.venv/bin/python scripts/download/osm.py              # Geofabrik GB + Ireland (~2.6 GB)
.venv/bin/python scripts/process/build_masts.py       # masts_sites, masts_r7
.venv/bin/python scripts/download/ofcom_wtr.py        # Ofcom Wireless Telegraphy Register (~54 MB)
.venv/bin/python scripts/process/build_wtr.py         # wtr_points, then rebuilds the mast tables
.venv/bin/python scripts/download/ons_boundaries.py   # constituencies 2024 + local authorities Dec 2024
.venv/bin/python scripts/process/build_ofcom.py       # ofcom_area_r7, ofcom_nations (zip in data/raw/ofcom/)
.venv/bin/python scripts/download/dem.py              # Copernicus GLO-30 tiles (~1.4 GB)
.venv/bin/python scripts/process/build_terrain.py     # terrain_r7, los_r7 (~2 min; --los = los only)
.venv/bin/python scripts/process/build_places.py      # OSM place names (for zone names)
.venv/bin/python scripts/process/build_zones.py       # gap_zones, gap_zone_cells (~30 s)
.venv/bin/python scripts/zetaris/register_sources.py  # all CD_* sources (or name some)
.venv/bin/python scripts/download/live_samples.py     # refresh the live samples in data/samples/

# Checks
.venv/bin/python scripts/check_data.py                # A, B, E through Zetaris
.venv/bin/python scripts/check_live.py                # /api/live live, then SAMPLE_MODE
.venv/bin/python scripts/check_terrain.py             # line of sight at 4 places
.venv/bin/python scripts/check_evidence.py            # evidence bundles for the sample places
.venv/bin/python scripts/check_council.py             # top zones UK / Westmorland and Furness, Great Langdale fixes
.venv/bin/python scripts/refresh.py --check-only      # which stored sources are due
.venv/bin/python -m pytest -q

# Explorer
.venv/bin/python scripts/process/build_web_layers.py  # after any data change
.venv/bin/python run.py                               # http://localhost:8000 (+ Meterless on :8100)
(cd meterless_service && npm install)                 # once: Node deps for the Meterless service
.venv/bin/python scripts/screenshots.py --chrome ~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome
```

Inputs placed by hand: `data/raw/boundary/uk_countries.geojson` (ONS countries, all four
nations) and `data/raw/population/population.tif` (WorldPop UK).

## Status (25 Oct 2026, evening)

Built in phases; after each: run checks, commit, push, stop for review. Order agreed:
A → B → E → freshness → explorer → WTR → D → C → evidence API → F → final check_data.py;
G (power cuts) dropped as future work; H (visitor load) only if time. Then the agents.

### Done (commit)

- **A. Zetaris foundation** (`d4f80c9`): client, data mount, `CD_CELLS` (56,592 r7 cells,
  67.41 m people) and three Ookla sources. Ookla open data, 2026Q3 + 3 previous quarters,
  read by HTTP range requests of the UK row groups: 23,412 cells with tests, 87,725
  cell-quarters, 420,260 tiles (zoom 16, ~350–400 m). Test-weighted averages; sample sizes
  always carried.
- **B. Masts** (`f6f3889`, `c29b4a2`): OpenCelliD cells clustered at 150 m (MVNO / GSM-R /
  TETRA excluded) + OSM communication masts (two-pass pyosmium), merged within 200 m.
  Per-cell stats in `masts_r7`, operator_data_status and the wording rules above.
- **E. Ofcom regional** (`6afb9c6`): Connected Nations July 2025, constituency per cell
  (`CD_OFCOM_AREA`, with the local authority figures) and per operator by nation
  (`CD_OFCOM_NATIONS`). Blanks = 0 unless the whole group is blank.
- **Freshness** (`d07f9c1`): manifest, `refresh.py` (Ookla quarterly, OpenCelliD weekly,
  OSM and WTR monthly, Ofcom new release, cells / DEM manual), evidence_meta().
- **Data explorer** (`cc0cf3d`, `1095848`, `dfd8cb8`): FastAPI + MapLibre/deck.gl; 12
  layers, mast sites from zoom 10, Ookla tiles from zoom 12, cell panel from one Zetaris
  query, search, phone layout. UK map limits were tried and removed at the user's request
  (they broke scrolling). The Zetaris client signs in again before its 15-minute token expires.
- **Ofcom Wireless Telegraphy Register** (`ae28592`): base stations are NOT in it; it holds
  the operators' licensed microwave links. Licensees matched by exact legal name
  (Telefonica → O2, Vodafone, MBNL → EE + Three; BT and Arqiva not mapped). 13,122 points,
  8,504 sites (3,797 matched existing sites, 4,707 new) → 93,638 sites. Populated cells with
  sites but no known operator fell from 20.9% to 3.9%. Antenna heights for line of sight.
- **D. Live sources** (`5261816`): `sources/live.py` (5 s timeout, one retry, disk cache
  `data/cache/live/`, fallback cached → sample, status live / cached / sample / not_covered
  / unavailable) + geocode (postcodes.io, 30 days), weather (Open-Meteo, 30 min; severity
  none / moderate / severe: gusts ≥ 70 km/h, rain ≥ 8 mm/h, snow ≥ 1 cm/h or thunder =
  severe; only severe supports the `weather` cause), Met Office warnings (public RSS by
  region, 15 min; `district_listed`), EA floods (England only, 15 min; "not covered" outside
  England, never an empty list). `/api/live`, `/api/geocode`, `/api/geocode/reverse`;
  explorer "Right now" section; attribution footer. Zetaris REST: `CD_LIVE_EA_FLOODS` works
  (centre-based, so the point answer uses EA's polygon-aware API); Open-Meteo cannot be
  registered (see Zetaris notes).
- **C. Terrain** (`c3caa01`): `data/terrain.py` (bilinear DEM, ≤ 4 tiles in memory,
  `line_of_sight()` with 30 m samples, k = 4/3 curvature, antenna height from the register
  else 25 m). `CD_TERRAIN.terrain_r7` (elevation per cell from 343 r10 samples) and
  `CD_LOS.los_r7` (cell centre → nearest site, map layer only; clear 29,555 / marginal < 10 m
  10,153 / blocked 15,869 populated cells; register height for 40%). Everything a user or
  agent sees for a location uses the EXACT point, never the cell centre: the evidence API
  (to each operator's nearest site) and the explorer panel (`/api/los?lat=&lon=`, nearest
  site to the clicked / searched point; map line + elevation profile). Great Langdale:
  blocked by 288 m, 2.25 km towards the site.
  Mast refreshes rebuild `los_r7`.
- **Evidence API** (`d9cbd90`): `POST /api/evidence` {query} or {lat, lon} →
  `evidence.py`: Q1 `cell_sql`, Q2 sites within 10 km of the exact point, Q3 UK context
  (cached), all logged in the bundle; line of sight to the nearest site of each operator
  within 10 km (+ nearest of any operator); live items. Items: id, source, data_period,
  as_of, query_or_url, cell_ids, finding, value, sample_size, strength (strong / moderate /
  weak), bears_on. Bundles for the sample places saved in `data/samples/evidence/`.

- **Pages, phase 1: My signal** (26 Oct): `/signal`. Evidence bundle gained Q4 (Ookla tiles
  within 1 km), `operators` (per operator: nearest site, confirmed / inferred, line of sight
  from the exact point, mast height measured / assumed) and `likely_best` (rule: clear first,
  nearest, confirmed on ties; else least obstructed; `reviewed_by_agents: false`). Map draws each
  operator's line (own colour; red dashed when blocked; obstruction marked). Agent placeholders:
  "Explanation (agents)", disabled "Diagnose with agents" / "Draft evidence letter".
- **Levels of detail** (26 Oct): Explore = area level (hexagons; cell panel shows cell aggregates
  only, line-of-sight grade from the cell centre, "Data details" SQL, "Check an exact location
  here" → /signal?lat&lon). My signal = point level (no hex colouring: Ookla tiles within 2 km,
  sites within 10 km marked confirmed / inferred / unknown, hexagon outline, per-operator lines,
  "See this area in Explore"). Council view = zones.
- **Council view** (26 Oct): gap zones (build_zones.py; rules in planning/zones.py: (a) < 5 Mbps
  over cell + ring from >= 10 tests, (b) no site within 5 km unless >= 10 tests measure >= 5 Mbps
  = "site data gap", (c) < 10 tests and terrain blocking every site within 5 km; cells >= 10 people,
  zones >= 50 people (user's choice, so sparse valleys like Great Langdale count); 677 zones),
  scoring.py (rank-normalised factors within the scope, weights adjustable, contributions;
  "need" omitted until deprivation is built), siting.py (rule-based fix + DEM high points and
  existing sites by people gaining a clear line), api/council.py, /council page (scope picker,
  sliders, ranked table, map, zone panel, CSV, agent placeholders). Zones link to Explore
  (?zone= outline) and My signal (centroid). CD_GAP_ZONES, CD_GAP_ZONE_CELLS.

- **Agents, phase 1: Meterless service** (26 Oct): vendored H-MEM + World Model reference engines
  (their tests pass); meterless_service/server.ts on :8100 (runs, evidence, beliefs with
  ledger revisions, critiques, notes, audit trail, diagnoses near a point; World Model entities,
  operator-context relationships, events); Python client with fallback; run.py starts it.
  Agent plan (user's brief): investigator / diagnostician / critic / advisor / letter writer /
  fix planner, loop of max 3 rounds via the shared case file in Meterless, code guard, NVIDIA
  Nemotron via an OpenAI-compatible API (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL).
- **Agents, phase 2: tools, schemas, Nemotron client** (26 Oct). Models: LLM_MODEL =
  nemotron-3.5-super-vl (fast: investigator tool calling, advisor / letters / fix planner with
  strict json_schema, thinking off); LLM_MODEL_REASONING = nemotron-3-ultra (diagnostician,
  critic: thinking ON, JSON schema in the prompt, validated by pydantic). Probe results: Ultra under
  strict json_schema degenerates on long prompts; Super with thinking is slow/flaky; guided_json is
  rejected; nemotron-3-super (non-3.5) is 404 for this account. The endpoint has bursts of HTTP 500:
  llm.py retries once, then the other model answers (`fallback` on the result). Raw reasoning is
  never stored. Tools (agents/tools.py): speeds_near, speed_trend, sites_near, line_of_sight(op),
  terrain, ofcom_area, live_conditions, prior_diagnoses_nearby, zone_summary, candidate_sites
  (+ network_comparison, code only); each writes items with stable ids to Meterless (with their
  Zetaris SQL) and logs a tool_call note. Check: scripts/check_agent_tools.py.
- **Agents, phase 3: agents + guard** (26 Oct): agents.py (investigate, diagnose, critique, advise,
  write_letter, plan_fix, review_fix, advise_zone), prompts/*.md (short, 1-2 examples each).
  Guard after every agent: unknown evidence ids removed (belief dropped if nothing supports it),
  weak-only beliefs capped at 0.5, numbers must match a value in the cited evidence within rounding /
  unit changes (else one rewrite by the same agent, then the sentence is removed); all recorded as
  "guard" notes. LLM: 5xx retried after 2 s then 6 s, then the other model; retries and switches are
  in "llm_call" notes. Code also enforces: round-1 checks, max 8 calls a round, no repeated checks,
  round-3 needs_evidence -> downgrade, mandatory resident actions, one ranking entry per operator,
  letter sources listed from evidence. Timings (26 Oct): investigator ~3 s, diagnostician ~19 s,
  critic ~40 s (Ultra), advisor / letter ~5 s, fix planner ~2 s. Check: scripts/check_agents.py.
- **Agents, phase 4: coordinator** (26 Oct): coordinator.py. Point: create run, World Model place
  (+ area), prior_diagnoses_nearby, loop (investigate -> diagnose -> critique; next round only if the
  critic requested new checks; max 3), World Model sites per operator (nearest_site{op} with the
  line-of-sight result), warnings, advisor, record_diagnosis + diagnosis_completed event. Zone: same
  loop on zone tools, then fix planner + critic review (max one revision), fix_plan_proposed event,
  candidate sites in the World Model. An agent failing twice -> status "partial" built from the
  evidence. Progress: one step per LLM call and tool call in data/runs/<run_id>.json (and Meterless
  run progress); full output in data/runs/<run_id>.full.json. Prompts: critic has a time-fit check
  (short-lived causes cannot explain long-standing poor service; downgrade to <= 0.3), diagnostician
  caps weather / active_incident at 0.4 when poor service is long-standing. Guard rewrites use the
  same agent prompt on the fast model. Meterless payloads can no longer overwrite record fields.
  Check: scripts/check_coordinator.py (summary in data/runs/phase4_summary.json).
- **Phase 4 review fixes** (26 Oct, user's go-ahead): diagnostician moved to 3.5 Super (strict json_schema;
  DIAGNOSTICIAN_ULTRA_ROUNDS in agents.py can put rounds back on Ultra), critic stays on Ultra; calls with
  thinking on time out at 90 s (45 s otherwise). Guard rules now in code, not only prompts: weakness is decided
  by code (`guard.weak_reason`: labelled weak, Ookla < 30 tests, sites crowd-sourced only, sites with unknown
  operators) for the 0.5 cap; [prior_diagnoses] is context only (stripped from belief evidence, and not shown
  to the critic, which kept using it as support); a confidence change without a revision reason is discarded
  ("unexplained_change"). Prompts: critic (b) must downgrade weak beliefs above 0.5, (e) only calls service
  long-standing when the trend shows it; diagnostician: 30+ tests above the UK median -> no problem cause
  above 0.3; advisor: "service measures well here" headline. Check (examples/compare/): wall clock 63-171 s
  (Phase 4: 130-272 s; one run 284 s from fast-model timeouts), diagnostician 3-19 s (was 49-100 s); London now
  "No strong cause was found; the service measures well here". examples/great_langdale/ re-recorded from
  run_20261026213702_fgoz.

### Zetaris sources

`CD_CELLS`, `CD_OOKLA_MOBILE`, `CD_OOKLA_MOBILE_HISTORY`, `CD_OOKLA_MOBILE_TILES`,
`CD_MASTS_SITES`, `CD_MASTS`, `CD_WTR_POINTS`, `CD_OFCOM_AREA`, `CD_OFCOM_NATIONS`,
`CD_TERRAIN`, `CD_LOS`, `CD_GAP_ZONES`, `CD_GAP_ZONE_CELLS` (Parquet) and `CD_LIVE_EA_FLOODS` (live REST). Row counts are in
data/README.md.

### Sample places (what the data says, 25 Oct)

- Great Langdale (54.445, -3.105): no Ookla tests in its cell; nearest site 3.8 km SE; EE,
  Three, Vodafone inferred, none confirmed; every operator's nearest site blocked by
  terrain (129–288 m). Storm Bolelo: severe gusts, flood alerts nearby.
- Central London (WC2N 5DU): 133.6 Mbps from 1,425 tests; all four operators confirmed;
  devices per head far above the UK median (visitors).
- Near Rhayader (52.30, -3.51): 14.4 Mbps from 25 tests, down 35% over 4 quarters; only
  Vodafone within 5 km (confirmed), 2 sites with unknown operators; EE / Three site 6.5 km,
  blocked by 137 m; no O2 site within 10 km (weak); floods not covered (Wales).
- Flat check village: Sutton St Edmund (Lincolnshire Fens), line of sight clear.

### Known limits and open questions

- OpenCelliD's free file is incomplete; postcodes.io's place list lacks "Great Langdale"
  (by name it resolves approximately to Little Langdale: use coordinates).
- Our data is far coarser than Ofcom's own checker (address level); suggested retrying for
  an Ofcom API key.
- 26 Oct: the Zetaris stack was found removed (containers gone); restarted with
  `scripts/zetaris/compose.sh up -d` (volumes kept, sources intact). Earlier the driver was
  restarted without the mount: always use compose.sh.
- Top-ranked zones mostly have low data confidence (0-5 tests): the score is about need, the
  confidence column shows how sure we are. Northern Ireland has many zones (thin crowd-sourced
  site data there may contribute).
- Met Office warnings cover whole regions: should "elsewhere in the region" warnings count
  as weaker evidence for `weather`? (asked the user, no answer yet)
- 47% of populated cells look blocked from their centre; many margins are small (surface
  model), hence the marginal class.

### Next

1. F. Rural–urban classification + deprivation (deciles within each nation) →
   `deprivation_r7`, `CD_DEPRIVATION` (`queries.py` already joins it when the manifest has
   "deprivation"; layer `deprivation_decile` ready in build_web_layers).
2. Final `scripts/check_data.py`: every Zetaris source with row counts and freshness, a
   cross-source row per sample place, live results.
3. H. Visitor load, if time.
4. The agents (Coordinator, Investigator on `POST /api/evidence`, Diagnostician, Critic,
   Advisor, Gap analyst) with Meterless memory.

## Rules

- Never commit secrets: `.env` is gitignored, `.env.example` has placeholders only.
- Raw downloads go in `data/raw/` (gitignored). Committed sample data stays small (`data/samples/`).
- Record every source's licence and processing steps in data/README.md.
- Always carry sample sizes (tests, devices) with Ookla figures; many cells have 1–2 tests.
- Scripts are re-runnable: skip downloads that already exist; `--force` rebuilds.
- Simple, readable code. If an external source or Zetaris is blocked or slow, say so
  with options rather than working around it silently.
