# Data report

Generated 2026-10-27 00:10 by `scripts/check_data.py`: every query below ran through Zetaris (one Lightning database per source). Freshness from `data/manifest.json`.

## Sources

| Zetaris source | Rows | Query | Data period | As of | Age | Refresh | Licence |
|---|---:|---:|---|---|---:|---|---|
| `CD_CELLS.cells_r7` (H3 r7 grid, WorldPop population, nation) | 56,592 | 576 ms | WorldPop 2020 (1 km, UN-adjusted); ONS countries December 2023 | 2026-10-23 | 4 d | manual (WorldPop, ONS boundaries) | WorldPop CC BY 4.0; ONS boundaries OGL v3.0 |
| `CD_OOKLA_MOBILE.ookla_mobile_r7` (Ookla mobile speeds per cell, latest quarter) | 23,412 | 77 ms | 2026Q3 | 2026-10-23 | 4 d | quarterly (new quarter in ookla-open-data) | CC BY-NC-SA 4.0 |
| `CD_OOKLA_MOBILE_HISTORY.ookla_mobile_history_r7` (Ookla speeds per cell and quarter) | 87,725 | 88 ms | 2026Q3 | 2026-10-23 | 4 d | quarterly (new quarter in ookla-open-data) | CC BY-NC-SA 4.0 |
| `CD_OOKLA_MOBILE_TILES.ookla_mobile_tiles` (Ookla tiles (~400 m)) | 420,260 | 90 ms | 2026Q3 | 2026-10-23 | 4 d | quarterly (new quarter in ookla-open-data) | CC BY-NC-SA 4.0 |
| `CD_MASTS_SITES.masts_sites` (Approximate mast sites (OpenCelliD, OSM, Ofcom register)) | 93,638 | 78 ms | OpenCelliD downloaded 2026-10-25; OpenStreetMap extract downloaded 2026-10-25; Ofcom WTR downloaded 2026-10-25 | 2026-10-25 | 2 d | OpenCelliD weekly; OpenStreetMap monthly; Ofcom WTR monthly | OpenCelliD CC BY-SA 4.0; OpenStreetMap ODbL 1.0; Ofcom WTR: Ofcom copyright, free re-use |
| `CD_MASTS.masts_r7` (Mast statistics per cell) | 56,592 | 91 ms | OpenCelliD downloaded 2026-10-25; OpenStreetMap extract downloaded 2026-10-25; Ofcom WTR downloaded 2026-10-25 | 2026-10-25 | 2 d | OpenCelliD weekly; OpenStreetMap monthly; Ofcom WTR monthly | OpenCelliD CC BY-SA 4.0; OpenStreetMap ODbL 1.0; Ofcom WTR: Ofcom copyright, free re-use |
| `CD_WTR_POINTS.wtr_points` (Ofcom Wireless Telegraphy Register points) | 13,122 | 104 ms | register downloaded 2026-10-25 | 2026-10-25 | 2 d | monthly (Ofcom updates the register regularly) | Ofcom copyright; free re-use if reproduced accurately and not misleadingly, acknowledged as Ofcom copyright |
| `CD_OFCOM_AREA.ofcom_area_r7` (Ofcom Connected Nations per cell (constituency, council)) | 56,592 | 121 ms | 2025-07 (release 202507_mobile_coverage_r01) | 2026-10-25 | 2 d | per Ofcom release (download the new zip by hand) | Ofcom data OGL v3.0; ONS boundaries OGL v3.0 |
| `CD_OFCOM_NATIONS.ofcom_nations` (Ofcom Connected Nations per operator and nation) | 1,035 | 82 ms | 2025-07 (release 202507_mobile_coverage_r01) | 2026-10-25 | 2 d | per Ofcom release (download the new zip by hand) | Ofcom data OGL v3.0; ONS boundaries OGL v3.0 |
| `CD_TERRAIN.terrain_r7` (Elevation per cell (Copernicus DEM)) | 56,592 | 73 ms | Copernicus DEM GLO-30 (2021 release; source data 2011-2015) | 2026-10-25 | 2 d | manual (static); los_r7 after mast tables change | Copernicus DEM licence: free, attribution required. (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA |
| `CD_LOS.los_r7` (Line of sight from cell centres) | 55,577 | 71 ms | Copernicus DEM GLO-30 (2021 release; source data 2011-2015) | 2026-10-25 | 2 d | manual (static); los_r7 after mast tables change | Copernicus DEM licence: free, attribution required. (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA |
| `CD_GAP_ZONES.gap_zones` (Gap zones) | 677 | 77 ms | built from Ookla 2026Q3 and mast sites 2026-10-25 | 2026-10-26 | 1 d | after Ookla or mast refreshes | derived from the sources above (see their licences) |
| `CD_GAP_ZONE_CELLS.gap_zone_cells` (Gap zone cells) | 2,921 | 75 ms | built from Ookla 2026Q3 and mast sites 2026-10-25 | 2026-10-26 | 1 d | after Ookla or mast refreshes | derived from the sources above (see their licences) |
| `CD_OPP_ZONES.opportunity_zones` (Improvement opportunities) | 1,816 | 88 ms | built from Ookla 2026Q3 and mast sites 2026-10-25 | 2026-10-26 | 1 d | after Ookla or mast refreshes | derived from the sources above (see their licences) |
| `CD_OPP_ZONE_CELLS.opportunity_zone_cells` (Improvement opportunity cells) | 8,832 | 93 ms | built from Ookla 2026Q3 and mast sites 2026-10-25 | 2026-10-26 | 1 d | after Ookla or mast refreshes | derived from the sources above (see their licences) |
| `CD_LIVE_EA_FLOODS.floods` (Environment Agency flood warnings (live REST)) | 111 now | 237 ms | live | | | each query | OGL v3 |

## Sample places: one cross-source row each

One Zetaris query per place joins cells, Ookla (latest + history + neighbours), masts, Ofcom area, terrain and line of sight.

| Place | People | Mbps | Tests | Quarters | Nearest site | Sites in 5 km | Operators | Operator data | Council | 4G not-spot land | Elevation | Line of sight (cell centre) | Query |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|---|---:|
| Great Langdale, Cumbria | 48 |  |  |  | 3.67 km | 4 | EE,Three,Vodafone | inferred | Westmorland and Furness | 5.6% | 247 m | blocked | 366 ms |
| Central London (WC2N 5DU) | 22,801 | 133.6 | 1,425 | 4 | 0.10 km | 1,153 | EE,O2,Three,Vodafone | confirmed | Westminster | 0.0% | 28 m | clear | 446 ms |
| Near Rhayader, Powys | 1,759 | 14.4 | 25 | 4 | 1.13 km | 4 | Vodafone | confirmed | Powys | 5.8% | 250 m | clear | 467 ms |
| Sutton St Edmund, Lincolnshire | 163 |  |  |  | 4.60 km | 1 | O2 | confirmed | South Holland | 0.0% | 0 m | clear | 444 ms |
| Remote cell near Bettws, Powys (no tests, no site within 10 km) | 66 |  |  |  | 10.73 km | 0 |  | no_sites_found | Powys | 5.8% | 324 m | blocked | 369 ms |

## Live sources for the sample places

| Place | Geocode | Weather | Met Office | EA floods |
|---|---|---|---|---|
| Great Langdale, Cumbria | live | live: severe | live: 1 warnings (North West England) | live: 2 |
| Central London (WC2N 5DU) | live | live: moderate | live: 0 warnings (London & South East England) | live: 0 |
| Near Rhayader, Powys | live | live: moderate | live: 1 warnings (Wales) | not_covered: None |
| Sutton St Edmund, Lincolnshire | live | live: moderate | live: 0 warnings (East Midlands) | live: 0 |
| Remote cell near Bettws, Powys (no tests, no site within 10 km) | live | live: moderate | live: 1 warnings (Wales) | not_covered: None |
