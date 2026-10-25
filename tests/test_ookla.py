import pandas as pd
import pytest

from coverage_detective.sources.ookla import aggregate_cells, quadkey_centre


def test_quadkey_centre():
    # Zoom-1 tile "0" is the north-west quarter of the world.
    lat, lon = quadkey_centre("0")
    assert lon == pytest.approx(-90.0)
    assert lat > 0
    # A zoom-16 tile round-trips to within half a tile (~300 m) of central London.
    lat, lon = quadkey_centre("0313131311301000")
    assert abs(lat - 51.5) < 0.1 and abs(lon - (-0.12)) < 0.1


def test_aggregate_is_test_weighted():
    tiles = pd.DataFrame(
        {
            "quarter": "2026Q3", "quadkey": ["a", "b"], "cell_id": "c",
            "download_mbps": [10.0, 40.0], "upload_mbps": [1.0, 4.0], "latency_ms": [50.0, 20.0],
            "tests": [3, 1], "devices": [2, 1],
        }
    )
    row = aggregate_cells(tiles).iloc[0]
    assert row.download_mbps == pytest.approx(17.5)
    assert row.tests == 4 and row.devices == 3 and row.tiles == 2
