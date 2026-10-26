import h3
import pytest
from fastapi.testclient import TestClient

from coverage_detective.api.app import _quadkey_bounds, app, cell_sql

client = TestClient(app)


def test_cell_rejects_bad_ids():
    assert client.get("/api/cell/not-a-cell").status_code == 400
    assert client.get("/api/cell/" + h3.latlng_to_cell(54.4, -3.1, 6)).status_code == 400  # wrong resolution


def test_cell_sql_is_one_query_with_neighbours():
    cid = h3.latlng_to_cell(54.445, -3.105, 7)
    sql, tables = cell_sql(cid)
    assert sql.count("SELECT") >= 3 and sql.strip().endswith(f"WHERE c.cell_id = '{cid}'")
    for n in h3.grid_ring(cid, 1):
        assert f"'{n}'" in sql
    assert {"cells_r7", "ookla_mobile_r7", "masts_r7", "ofcom_area_r7"} <= set(tables)


def test_quadkey_bounds():
    w, s, e, n = _quadkey_bounds("0")
    assert (w, e) == (-180.0, 0.0) and s == pytest.approx(0.0, abs=1e-9) and n > 85


def test_bad_bbox():
    assert client.get("/api/masts", params={"bbox": "nope"}).status_code == 400


def test_pages_are_served():
    assert client.get("/signal").status_code == 200 and "signal.js" in client.get("/signal").text
    assert client.get("/council").status_code == 200 and "council.js" in client.get("/council").text
    assert client.get("/").status_code == 200


def test_council_inputs_are_validated():
    assert client.get("/api/council/zones", params={"scope": "nation:Atlantis"}).status_code == 400
    assert client.get("/api/council/zones/Z1' OR 1=1").status_code in (400, 404)
    assert client.get("/api/council/zones/abc/cells").status_code == 400
