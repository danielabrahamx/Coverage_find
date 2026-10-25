# Data sources

All data is mapped onto an H3 grid at resolution 7 (~5 km² cells) covering the UK.
Raw files live in `data/raw/` and built files in `data/processed/`; both are gitignored.

| Source | Version used | Licence | Raw file(s) | Built file(s) |
|---|---|---|---|---|
| ONS Countries boundaries | December 2023, UK BUC | Open Government Licence v3.0 | `raw/boundary/uk_countries.geojson` | `cells_r7.parquet` |
| WorldPop population | 2020, 1 km, UN-adjusted (GBR) | CC BY 4.0 | `raw/population/population.tif` | `cells_r7.parquet` |
| Ookla open data, mobile | 2025Q4–2026Q3 (latest: 2026Q3) | CC BY-NC-SA 4.0 | `raw/ookla/<quarter>_mobile_tiles_uk.parquet` | `ookla_mobile_r7.parquet`, `ookla_mobile_history_r7.parquet`, `ookla_mobile_tiles.parquet` |
| OpenCelliD cell towers | download date in `masts_meta.json` | CC BY-SA 4.0 | `raw/opencellid/234.csv.gz`, `235.csv.gz` | `masts.parquet`, `masts_r7.parquet` |
| UK network codes (Wikipedia) | revision 1378731553, 5 Oct 2026 | CC BY-SA 4.0 | — | `reference/mcc_mnc_uk.csv` (committed) |

## ONS Countries boundaries

*Countries (December 2023) Boundaries UK BUC*, Office for National Statistics.
Source: Office for National Statistics licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Contains OS data © Crown copyright and database right 2023.

## WorldPop

WorldPop (www.worldpop.org), *Global 2000–2020 1 km UN-adjusted population counts*,
United Kingdom, 2020:
https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/GBR/gbr_ppp_2020_1km_Aggregated_UNadj.tif
Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**Processing** (`scripts/process/build_cells.py`): for each nation, every H3 r7 cell that
overlaps the boundary is kept, so coastal cells are kept too. Raster pixels inside the
boundary are summed into the cell holding each pixel's centre. A cell on a national border
goes to the nation where most of its people live (or, with nobody, the nation containing its centre).
Groups of connected cells with fewer than 500 people (small islands) are dropped.
Result: 56,592 cells, 67.41 million people.

## Ookla open data (mobile)

Speedtest® by Ookla® Global Fixed and Mobile Network Performance Maps, from the public S3
bucket `ookla-open-data` (`parquet/performance/type=mobile/`). Licence:
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Attribution:
"Speedtest® by Ookla® Global Fixed and Mobile Network Performance Maps. Based on analysis
by Ookla of Speedtest Intelligence® data for [quarter]. Provided by Ookla and accessed
[date]. Ookla trademarks used under license and reprinted with permission."
Non-commercial use only.

Each tile is a zoom-16 web-mercator quadkey (~600 m) with average download/upload (kbps),
average latency, number of tests and unique devices for the quarter. There is **no
time-of-day or weekday breakdown**, so congestion can only be inferred indirectly.

**Download** (`scripts/download/ookla.py`): the latest 4 quarters. Only the Parquet row
groups whose quadkey range can hold UK tiles, and only the needed columns, are fetched with
HTTP range requests (~20 MB of each ~185 MB file), then tiles are kept if their centre is in
the UK bounding box.

**Processing** (`scripts/process/build_ookla.py`): each tile's centre is mapped to its H3 r7
cell, and tiles outside the grid (Ireland, France, sea) are dropped. Per cell and quarter:
test-weighted mean download, upload and latency, total tests, devices and tiles.
- `ookla_mobile_r7.parquet`: latest quarter per cell; tests and devices per 1,000 people;
  trend over the 4 quarters (quarters with data, oldest download, % change, least-squares
  slope in Mbps per quarter when there are ≥ 3 quarters).
- `ookla_mobile_history_r7.parquet`: one row per (cell, quarter).
- `ookla_mobile_tiles.parquet`: every UK tile and quarter with its r7 cell, for variation
  within a cell and across neighbours.
- `ookla_meta.json`: quarters used.

Caveat: many cells have only 1–2 tests, so always report `tests` as the sample size.

## OpenCelliD

OpenCelliD (https://opencellid.org), the open database of cell towers by Unwired Labs.
Licence: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Files for MCC 234
and 235 (United Kingdom), downloaded with a free account token (`OPENCELLID_TOKEN`).

Each row is one radio cell (a sector on one technology) with a position **estimated from
crowd-sourced measurements**, not the surveyed mast position. Coverage of the database is
uneven and incomplete, so the absence of masts is weaker evidence than their presence.

**Processing** (`scripts/process/build_masts.py`):
1. Keep GSM/UMTS/LTE/NR rows inside the UK bounding box.
2. Label each row with its operator from the network-code table below (MCC + MNC). Codes
   the table marks as MVNO, GSM-R (Network Rail) or TETRA (Airwave) are dropped: they
   are not public mobile networks with their own masts. Codes not in the table are kept as
   `unknown (234-NN)`.
3. Cluster rows into approximate mast sites: rows are taken in order of most samples first,
   and each joins the nearest site leader within 150 m or starts a new site. This is leader
   clustering, which avoids chaining a dense city into one giant site.
   `masts.parquet`: site_id, lat, lon (mean of members), radio_types, operators,
   operator_count, cell_count, samples, cell_id.
4. Per grid cell centre (`masts_r7.parquet`): masts_within_5km, nearest_mast_km,
   nearest_mast_bearing_deg (from the cell towards the mast), nearest_mast_id / lat / lon /
   operators, distinct_operators_within_5km, operators_within_5km.

List columns are comma-separated strings so any SQL engine (Zetaris) can read them.

## UK network codes (MCC/MNC → operator)

Wikipedia, *Mobile network codes in ITU region 2xx (Europe)*, section "United Kingdom – GB",
revision [1378731553](https://en.wikipedia.org/w/index.php?oldid=1378731553) (5 Oct 2026),
which cites the ITU Operational Bulletins and Ofcom's numbering allocations. Text licence:
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Built by
`scripts/download/mcc_mnc.py` into `data/reference/mcc_mnc_uk.csv` (81 codes): mcc, mnc,
label, brand, operator, status, bands, notes.

Operators are labelled **as the reference labels them** (`label` = Brand, or Operator when
Brand is empty), e.g. `EE`, `O2 (UK)`, `Vodafone UK`, `3`. Networks have merged in recent
years: EE absorbed T-Mobile and Orange (codes 30–34 are all EE), and Vodafone UK and Three
UK merged as VodafoneThree in 2025 but keep separate codes (15 and 20). So one current
company can appear under several labels, and labels are not current company names.
