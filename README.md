# Coverage Detective

Explains why mobile signal is poor at a UK location using public data (measured speeds,
mast locations, terrain, Ofcom coverage, weather), and ranks coverage gaps for operators
and councils. Data is queried through Zetaris.

## Setup

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

## Build the data

```bash
.venv/bin/python scripts/process/build_cells.py   # H3 r7 grid with population and nation
.venv/bin/python scripts/download/ookla.py        # Ookla mobile tiles, UK only, last 4 quarters
.venv/bin/python scripts/process/build_ookla.py   # Ookla speeds per cell + trend
.venv/bin/python scripts/download/opencellid.py   # OpenCelliD UK cells (needs OPENCELLID_TOKEN)
.venv/bin/python scripts/process/build_masts.py   # mast sites + nearest mast / operators per cell
```

Every script can be re-run safely; pass `--force` to rebuild an existing output.

## Tests

```bash
.venv/bin/python -m pytest -q
```

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
- Mobile networks only; home broadband is out of scope.
