"""Phase E: Ofcom Connected Nations area coverage per H3 cell (newest release zip).

    python scripts/download/ons_boundaries.py   # constituency + local authority boundaries
    python scripts/process/build_ofcom.py [--force]

Reads the newest data/raw/ofcom/YYYYMM_mobile_coverage_rNN.zip. Each cell centre is placed in its
Westminster constituency (July 2024) and local authority (December 2024); centres
offshore go to the nearest area. Writes to data/processed/:
  ofcom_area_r7.parquet   per cell: laua/pcon code and name, and the constituency's
                          coverage by number of operators (g4_prem_out_0..4, g4_prem_in_*,
                          g4_geo_out_*, g4_abrd_in_*, g4_mway_in_*, g5hc_prem_out_*,
                          g5hc_geo_out_*, each with *_at_least_one), plus the local
                          authority's g4_geo_out_0/1 for context
  ofcom_nations.parquet   per-operator coverage by nation and urban/rural
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import H3_RES, PROCESSED, RAW, SAMPLE_LOCATIONS  # noqa: E402
from coverage_detective.data.grid import load_cells  # noqa: E402
from coverage_detective.data import manifest  # noqa: E402
from coverage_detective.sources.ofcom import area_table, nations_table, read_csv, release  # noqa: E402

OFCOM_DIR = RAW / "ofcom"
PCON = RAW / "boundary" / "pcon_2024.geojson"
LAD = RAW / "boundary" / "lad_2024.geojson"
AREA_OUT = PROCESSED / "ofcom_area_r7.parquet"
NATIONS_OUT = PROCESSED / "ofcom_nations.parquet"
BNG = "EPSG:27700"


def assign_areas(cells: pd.DataFrame, path: Path, code: str, name: str) -> pd.DataFrame:
    """cell_id -> area code/name: polygon containing the centre, else the nearest one."""
    areas = gpd.read_file(path)[[code, name, "geometry"]].to_crs(BNG)
    pts = gpd.GeoDataFrame(cells[["cell_id"]], geometry=gpd.points_from_xy(cells.lon, cells.lat), crs="EPSG:4326").to_crs(BNG)
    hit = gpd.sjoin(pts, areas, how="left", predicate="within").drop_duplicates("cell_id")
    miss = hit[code].isna()
    if miss.any():
        near = gpd.sjoin_nearest(pts[miss.to_numpy()], areas, how="left").drop_duplicates("cell_id")
        hit = pd.concat([hit[~miss], near])
    print(f"  {path.name}: {len(cells) - int(miss.sum()):,} cell centres inside an area, {int(miss.sum()):,} offshore -> nearest")
    return hit[["cell_id", code, name]]


def latest_zip() -> Path:
    """The newest release zip (names start YYYYMM_mobile_coverage_rNN)."""
    zips = sorted(OFCOM_DIR.glob("*_mobile_coverage_r*.zip"))
    if not zips:
        sys.exit(f"No Ofcom mobile coverage zip in {OFCOM_DIR}")
    return zips[-1]


def build() -> None:
    zip_path = latest_zip()
    stem, data_date = release(zip_path)
    print(f"  release {stem}")
    cells = load_cells()
    pcon = area_table(read_csv(zip_path, "pcon"), "parl_const", "parl_const_name")
    laua = area_table(read_csv(zip_path, "laua"), "laua", "laua_name")

    places = assign_areas(cells, PCON, "PCON24CD", "PCON24NM").merge(
        assign_areas(cells, LAD, "LAD24CD", "LAD24NM"), on="cell_id")
    places = places.rename(columns={"PCON24CD": "pcon_code", "PCON24NM": "pcon_name",
                                    "LAD24CD": "laua_code", "LAD24NM": "laua_name"})

    metrics = pcon.drop(columns=["name"]).rename(columns={"code": "pcon_code", "prem_count": "pcon_prem_count",
                                                         "pixel_count": "pcon_pixel_count"})
    la = laua[["code", "g4_geo_out_0", "g4_geo_out_1"]].rename(
        columns={"code": "laua_code", "g4_geo_out_0": "laua_g4_geo_out_0", "g4_geo_out_1": "laua_g4_geo_out_1"})
    out = places.merge(metrics, on="pcon_code", how="left").merge(la, on="laua_code", how="left")
    missing = out.g4_geo_out_0.isna().sum()
    if missing:  # constituency not in the Ofcom file: fall back to the local authority
        print(f"  {missing} cells without constituency data; using local authority values")
    out.insert(5, "ofcom_area_level", "pcon")
    out["data_date"] = data_date
    out["ofcom_release"] = stem

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out.to_parquet(AREA_OUT, index=False)
    nations_table(read_csv(zip_path, "UK_and_nations")).to_parquet(NATIONS_OUT, index=False)
    manifest.record(
        "ofcom", title="Ofcom Connected Nations mobile coverage (area level)",
        data_period=f"{data_date} (release {stem})",
        downloaded={p.name: manifest.file_date(p) for p in (zip_path, PCON, LAD)},
        outputs=[AREA_OUT, NATIONS_OUT], refresh="per Ofcom release (download the new zip by hand)",
        licence="Ofcom data OGL v3.0; ONS boundaries OGL v3.0",
    )
    print(f"wrote {AREA_OUT.name} ({len(out):,} rows), {NATIONS_OUT.name}")


def finding(area: str, geo0: float, geo1: float, data_date: str) -> str:
    month = datetime.strptime(data_date, "%Y-%m").strftime("%B %Y")
    return (f"In {area}, {geo0:.1f}% of land has no outdoor 4G from any operator and {geo1:.1f}% from only one "
            f"(Ofcom Connected Nations, {month}).")


def check() -> None:
    area = pd.read_parquet(AREA_OUT)
    print(f"cells with constituency data: {area.g4_geo_out_0.notna().sum():,} / {len(area):,}")
    for name, lat, lon in SAMPLE_LOCATIONS:
        r = area[area.cell_id == h3.latlng_to_cell(lat, lon, H3_RES)].iloc[0]
        print(f"\n{name}: constituency {r.pcon_name} ({r.pcon_code}), local authority {r.laua_name} ({r.laua_code})")
        print("  4G by number of operators (%):   0      1      2      3      4")
        for fam, label in [("g4_geo_out", "land, outdoor"), ("g4_prem_out", "premises, outdoor"),
                           ("g4_prem_in", "premises, indoor"), ("g4_abrd_in", "A/B roads, in-car"),
                           ("g4_mway_in", "motorways, in-car")]:
            vals = [r[f"{fam}_{i}"] for i in range(5)]
            shown = "  ".join(f"{v:5.1f}" if pd.notna(v) else "    -" for v in vals)
            print(f"    {label:<20} {shown}")
        print(f"  5G high-confidence outdoor premises, at least one operator: {r.g5hc_prem_out_at_least_one:.1f}%")
        print(f"  local authority land: {r.laua_g4_geo_out_0:.1f}% none, {r.laua_g4_geo_out_1:.1f}% only one")
        print("  finding: " + finding(r.pcon_name, r.g4_geo_out_0, r.g4_geo_out_1, r.data_date))

    nations = pd.read_parquet(NATIONS_OUT)
    q = nations[(nations.technology == "4G") & (nations.coverage_type == "Geographic")
                & (nations.rurality == "Total")].pivot(index="location", columns="operator", values="coverage_pct")
    print("\n4G geographic coverage by operator and nation (%):")
    print(q.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.force or not (AREA_OUT.exists() and NATIONS_OUT.exists()):
        build()
    check()


if __name__ == "__main__":
    main()
