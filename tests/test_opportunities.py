"""Improvement opportunities (reasons computed in code), zoom caps, the viewport list and the area picker counts."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from coverage_detective import config
from coverage_detective.api import council as C
from coverage_detective.planning import opportunities as O


def cell(cid, **kw):
    base = {"cell_id": cid, "population": 200.0, "poor": False, "ring_tests": 40, "ring_mbps": 90.0, "tests": 40,
            "download_mbps": 90.0, "quarters_with_data": 4, "download_change_pct": 0.0, "devices_per_1k_pop": 5.0,
            "distinct_operators_within_5km": 4, "masts_unknown_operator_within_5km": 0, "laua_code": "E1"}
    return {**base, **kw}


def classify(rows):
    df = pd.DataFrame(rows)
    return O.classify(df, uk_median=100.0, la_median=pd.Series({"E1": 80.0}), devices_p90=20.0).set_index("cell_id")


def test_opportunity_reasons_are_computed_in_code():
    df = classify([
        cell("ok"),
        cell("slow", ring_mbps=30.0),                                          # < 0.5 x min(80, 100) = 40
        cell("not_slow", ring_mbps=45.0),
        cell("falling", download_change_pct=-35.0),
        cell("few", distinct_operators_within_5km=2),
        cell("few_but_unknown", distinct_operators_within_5km=1, masts_unknown_operator_within_5km=3),
        cell("busy", population=1500.0, ring_mbps=60.0, devices_per_1k_pop=25.0),  # < 0.75 x 100 and busy
        cell("several", ring_mbps=20.0, download_change_pct=-50.0, distinct_operators_within_5km=1),
        cell("gap_cell", ring_mbps=2.0, poor=True),                             # gap cells are never opportunities
        cell("thin", ring_tests=3, ring_mbps=5.0),                              # too few tests to call it slow
    ])
    flags = {c: [r for r in O.REASONS if df.loc[c, f"opp_{r}"]] for c in df.index}
    assert flags == {"ok": [], "slow": ["slow"], "not_slow": [], "falling": ["falling"], "few": ["few_operators"],
                     "few_but_unknown": [], "busy": ["capacity"], "several": ["slow", "falling", "few_operators"],
                     "gap_cell": [], "thin": []}
    assert df.loc["slow", "ref_mbps"] == 80.0 and df.loc["slow", "shortfall"] == pytest.approx((80 - 30) / 80)


def test_opportunity_zones_list_every_reason_and_flag_limited_data(monkeypatch):
    import h3
    a = h3.latlng_to_cell(54.5, -3.0, 7)
    b = h3.grid_ring(a, 1)[0]
    far = h3.latlng_to_cell(52.0, -1.0, 7)
    rows = []
    for cid, extra in [(a, {"ring_mbps": 20.0}), (b, {"distinct_operators_within_5km": 2, "tests": 2}), (far, {"ring_mbps": 20.0, "population": 20.0})]:
        lat, lon = h3.cell_to_latlng(cid)
        rows.append(cell(cid, lat=lat, lon=lon, nation="England", laua_name="Somewhere", operators_within_5km="EE,O2", **extra))
    df = O.classify(pd.DataFrame(rows), 100.0, pd.Series({"E1": 80.0}), 20.0)
    history = pd.DataFrame(columns=["cell_id", "quarter", "download_mbps", "tests"])
    zones, cells = O.build(df, history, None, 100.0)
    assert len(zones) == 1  # the far cell alone has 20 people (< 50)
    z = zones.iloc[0]
    assert z.zone_id == "O00001" and set(z.reasons.split(",")) == {"slow", "few_operators"}
    assert z.pop_slow == 200 and z.pop_few_operators == 200 and not z.limited_data  # 42 tests
    assert set(cells.zone_id) == {"O00001"} and len(cells) == 2


@pytest.mark.parametrize("zoom,caps", [(4.0, (40, 0)), (7.99, (40, 0)), (8.0, (40, 0)), (9.9, (40, 0)), (10.0, (100, 60)), (14, (100, 60))])
def test_zoom_caps(zoom, caps):
    assert C.view_caps(zoom) == caps
    assert config.COUNCIL_VIEW[0][1] == 40  # the constants live in one place


def scored(n, lon0=-3.0, prefix="Z"):
    return pd.DataFrame({"zone_id": [f"{prefix}{i:05d}" for i in range(1, n + 1)], "score": np.linspace(90, 10, n),
                         "centroid_lon": [lon0 + i * 0.01 for i in range(n)], "centroid_lat": [54.5] * n,
                         "population": [100.0] * n})


def test_viewport_selection_matches_the_map_bbox_and_keeps_the_selection():
    df = scored(50)
    bbox = (-3.0, 54.0, -2.705, 55.0)  # the first 30 centroids
    shown, n_view = C.select_view(df, bbox, cap=20)
    assert n_view == 30 and list(shown.zone_id) == list(df.zone_id[:20])
    assert all(bbox[0] <= x <= bbox[2] for x in shown.centroid_lon)
    shown, _ = C.select_view(df, bbox, cap=20, selected="Z00045")  # outside the view, selected: kept
    assert "Z00045" in set(shown.zone_id) and len(shown) == 21
    assert C.view_note("gap zones", 20, 30, 20) == "Showing the top 20 of 30 gap zones in view. Zoom in to see more."
    assert C.view_note("gap zones", 8, 8, 40) is None


@pytest.fixture
def api(monkeypatch):
    gaps, opps = scored(60), scored(80, prefix="O")
    monkeypatch.setattr(C, "ranked", lambda scope, w, log, kind="gap": ((opps if kind == "opportunity" else gaps), {"factors_used": []}))
    monkeypatch.setattr(C, "zone_cell_ids", lambda kind, log: {})
    monkeypatch.setattr(C, "_zone_row", lambda r, cells=None, kind="gap": {"zone_id": r["zone_id"], "lon": r["centroid_lon"], "zone_type": kind})
    from coverage_detective.api.app import app
    return TestClient(app)


def test_view_endpoint_lists_exactly_what_the_map_shows(api):
    zoomed_out = api.get("/api/council/view?zoom=6&bbox=-11,49,3,61").json()
    assert zoomed_out["gaps"]["shown"] == 40 and zoomed_out["gaps"]["in_view"] == 60
    assert zoomed_out["opportunities"]["shown"] == 0 and zoomed_out["opportunities"]["hidden"] == "zoom"
    assert "Showing the top 40 of 60 gap zones in view. Zoom in to see more." in zoomed_out["notes"]
    close = api.get("/api/council/view?zoom=11&bbox=-3.0,54,-2.755,55").json()  # 25 of each in the box
    assert close["gaps"]["in_view"] == 25 and close["gaps"]["shown"] == 25
    assert close["opportunities"]["shown"] == 25 and all(-3.0 <= z["lon"] <= -2.755 for z in close["opportunities"]["zones"])
    gaps_only = api.get("/api/council/view?zoom=11&bbox=-3.0,54,-2.755,55&show=gaps").json()
    assert gaps_only["opportunities"]["zones"] == [] and gaps_only["gaps"]["shown"] == 25


def test_picker_counts_per_council_and_nation():
    las = [{"laua_code": "E1", "laua_name": "Alpha", "nation": "England", "population": 1000, "min_lat": 54, "max_lat": 55, "min_lon": -3, "max_lon": -2},
           {"laua_code": "E1", "laua_name": "Alpha", "nation": "Wales", "population": 10, "min_lat": 53, "max_lat": 54, "min_lon": -4, "max_lon": -3},
           {"laua_code": "E2", "laua_name": "Beta", "nation": "England", "population": 500, "min_lat": 51, "max_lat": 52, "min_lon": 0, "max_lon": 1}]
    gaps = [{"zone_id": "Z1", "nation": "England", "la_codes": "E1", "population": 100},
            {"zone_id": "Z2", "nation": "England", "la_codes": "E1,E2", "population": 50}]
    opps = [{"zone_id": "O1", "nation": "England", "la_codes": "E2", "population": 900}]
    p = C.picker_counts(las, gaps, opps)
    alpha, beta = (next(c for c in p["councils"] if c["code"] == k) for k in ("E1", "E2"))
    assert (alpha["zones"], alpha["people"], alpha["opportunities"], alpha["nation"]) == (2, 150, 0, "England")
    assert (beta["zones"], beta["people"], beta["opportunities"], beta["opportunity_people"]) == (1, 50, 1, 900)
    assert alpha["bbox"] == [-4, 53, -2, 55]  # bounds over both parts of the council
    assert p["uk"] == {"scope": "uk", "name": "United Kingdom", "zones": 2, "people": 150, "opportunities": 1}
    assert next(n for n in p["nations"] if n["name"] == "England")["zones"] == 2


def test_empty_scope_and_all_null_factors_do_not_crash():
    from coverage_detective.planning import scoring
    shown, n = C.select_view(pd.DataFrame(), (-1, 50, 0, 51), cap=40, selected="O00552")
    assert n == 0 and shown.empty
    zones = pd.DataFrame({"zone_id": ["O1", "O2"], "population": [100.0, 200.0], "shortfall_pct": [None, None],
                          "trend_pct": [None, None], "operators_mean": [2.0, 1.0]})
    out, summary = scoring.score(zones, scoring.parse_weights(None, "opportunity"), "opportunity")
    assert len(out) == 2 and "trend" not in summary["factors_used"]  # no data: left out, not a crash
