"""Evidence bundle shape and wording, with Zetaris and the DEM mocked and live sources from samples."""

import pytest
from fastapi.testclient import TestClient

from coverage_detective import evidence
from coverage_detective.sources import live

ITEM_KEYS = {"id", "source", "data_period", "as_of", "query_or_url", "cell_ids", "finding", "value", "sample_size",
             "strength", "bears_on"}

CELL = {
    "cell_id": "x", "lat": 52.3, "lon": -3.51, "population": 1800, "nation": "Wales", "quarter": "2026Q3",
    "download_mbps": 14.4, "upload_mbps": 8.5, "latency_ms": 43.0, "tests": 25, "devices": 13,
    "tests_per_1k_pop": 13.9, "devices_per_1k_pop": 7.4, "quarters_with_data": 4, "download_mbps_oldest": 22.2,
    "download_change_pct": -35.1, "history_json": '[{"quarter": "2026Q3", "download_mbps": 14.4, "tests": 25}]',
    "neighbour_download_mbps": 9.1, "neighbour_tests": 2, "neighbour_cells_with_data": 1,
    "pcon_name": "Brecon, Radnor and Cwm Tawe", "g4_geo_out_0": 5.8, "g4_geo_out_1": 7.9, "ofcom_data_date": "2025-07",
    "laua_name": "Powys", "elevation_mean_m": 250.0, "elevation_range_m": 197.0,
}


def site(i, km, operators="", confirmed="", sources="opencellid", height=None):
    return {"site_id": f"S{i}", "lat": 52.3 + km / 111, "lon": -3.51, "sources": sources, "operators": operators,
            "operators_inferred": operators, "operators_confirmed": confirmed, "antenna_height_m": height,
            "has_microwave_backhaul": "true" if confirmed else "false", "cell_count": 1, "distance_km": km}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path / "cache")
    evidence._CACHE.clear()
    state = {"sites": [site(1, 0.5), site(2, 1.4, "Vodafone", "Vodafone", "ofcom_wtr", 15.0),
                       site(3, 6.5, "EE,Three", "EE,Three", "ofcom_wtr", 20.0)],
             "cell": dict(CELL)}

    def query(sql, timeout=None):
        rows = ([state["cell"]] if "FROM CD_CELLS" in sql else state["sites"] if "CD_MASTS_SITES" in sql
                else [{"devices_per_1k_p50": 3.6, "devices_per_1k_p90": 27.3, "download_mbps_p50": 103.0, "cells": 7640}])
        evidence.QUERY_LOG.append({"at": "t", "sql": sql, "duration_ms": 1, "rows": len(rows), "error": None})
        return [dict(r) for r in rows]

    def los(lat, lon, slat, slon, mast_height=None, **kw):
        blocked = abs(slat - 52.3) > 0.05  # only the 6.5 km site is behind a hill
        return {"blocked": blocked, "max_obstruction_m": 137.0 if blocked else -5.0, "obstruction_distance_m": 2000.0,
                "obstruction_lat": 52.31, "obstruction_lon": -3.51, "obstruction_ground_m": 400.0,
                "path_length_m": abs(slat - 52.3) * 111_000, "rx_ground_m": 215.0, "site_ground_m": 300.0,
                "rx_height_m": 1.5, "mast_height_m": mast_height or 25.0,
                "mast_height_source": "ofcom_register" if mast_height else "assumed_default", "samples": 50,
                "profile": {}}

    monkeypatch.setattr(evidence, "query", query)
    monkeypatch.setattr(evidence.terrain, "line_of_sight", los)
    return state


def items(bundle):
    return {i["id"]: i for i in bundle["items"]}


def test_bundle_shape_and_query_log(fake):
    b = evidence.build_bundle(lat=52.30, lon=-3.51)
    assert b["cell_id"] and len(b["neighbour_cell_ids"]) == 6 and b["sample_mode"]
    for i in b["items"]:
        assert set(i) == ITEM_KEYS, i["id"]
        assert i["strength"] in ("strong", "moderate", "weak") and i["finding"].endswith((".", ")"))
    assert [q["id"] for q in b["zetaris_queries"]] == ["Q1", "Q2", "Q3"]
    assert all(q["sql"] for q in b["zetaris_queries"])
    assert "ofcom.org.uk/mobile-coverage-checker" in b["resident_check"]


def test_wording_rules(fake):
    it = items(evidence.build_bundle(lat=52.30, lon=-3.51))
    ops = it["operators_5km"]["finding"]
    assert ops.startswith("Only 1 operator (Vodafone) has approximate mast sites within 5 km.")
    assert "confirmed by Ofcom's licence register" in ops
    assert "Operators could not be identified for 1 nearby site." in ops
    assert it["operators_5km"]["strength"] == "weak"
    text = " ".join(i["finding"] for i in it.values())
    assert "cover this area" not in text and " masts " not in text
    # O2 has no site within 10 km: weak, never "no O2 coverage".
    assert it["no_site_o2"]["strength"] == "weak" and "weak evidence" in it["no_site_o2"]["finding"]
    assert "Ofcom Connected Nations, July 2025" in it["ofcom_area"]["finding"]
    assert "not this exact location" in it["ofcom_area"]["finding"]


def test_line_of_sight_per_operator(fake):
    it = items(evidence.build_bundle(lat=52.30, lon=-3.51))
    ee = it["los_ee_three"]
    assert ee["strength"] == "strong" and "Terrain rises 137 m" in ee["finding"]
    assert "not necessarily lost" in ee["finding"] and "EE and Three confirmed" in ee["finding"]
    assert ee["value"]["mast_height_source"] == "ofcom_register"
    vf = it["los_vodafone"]
    assert "clears the ground" in vf["finding"] and vf["strength"] == "moderate"
    assert "los_nearest" in it and "operator unknown" in it["los_nearest"]["finding"]


def test_no_tests_and_no_sites_are_weak(fake):
    fake["cell"].update(tests=None, devices=None, quarters_with_data=None, download_change_pct=None, neighbour_tests=None)
    fake["sites"] = []
    it = items(evidence.build_bundle(lat=52.30, lon=-3.51))
    assert it["speed_cell"]["strength"] == "weak" and it["speed_cell"]["bears_on"] == ["insufficient_data"]
    assert "speed_trend" not in it and "usage_per_head" not in it
    assert it["nearest_site"]["strength"] == "weak" and "weak evidence" in it["nearest_site"]["finding"]
    assert not any(k.startswith("los_") for k in it)


def test_floods_not_covered_in_wales(fake):
    f = items(evidence.build_bundle(lat=52.30, lon=-3.51))["flood_warnings"]
    assert f["strength"] == "weak" and "unknown, not absent" in f["finding"] and f["data_period"] == "not_covered"


def test_api_validation_and_not_found(fake):
    from coverage_detective.api.app import app

    client = TestClient(app)
    assert client.post("/api/evidence", json={}).status_code == 422
    assert client.post("/api/evidence", json={"lat": 52.3}).status_code == 422
    assert client.post("/api/evidence", json={"lat": 40.0, "lon": -3.0}).status_code == 422  # outside the UK
    assert client.post("/api/evidence", json={"query": "ZZ1 1ZZ"}).status_code == 404
    r = client.post("/api/evidence", json={"query": "WC2N 5DU"})
    assert r.status_code == 200 and r.json()["point"]["postcode"] == "WC2N 5DU"
