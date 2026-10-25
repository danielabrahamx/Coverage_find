import pandas as pd
import pytest

from coverage_detective.sources.opencellid import bearing_deg, cluster_sites, masts_per_cell


def _cells(rows):
    return pd.DataFrame(rows, columns=["radio", "label", "lat", "lon", "samples"])


def test_cells_within_150m_form_one_site():
    # Two sectors ~50 m apart, a third ~1 km away.
    cells = _cells(
        [
            ("LTE", "EE", 54.4450, -3.1050, 10),
            ("NR", "O2 (UK)", 54.4454, -3.1050, 5),
            ("LTE", "EE", 54.4540, -3.1050, 3),
        ]
    )
    sites, site_of = cluster_sites(cells)
    assert len(sites) == 2
    assert site_of[0] == site_of[1] != site_of[2]
    big = sites[sites.cell_count == 2].iloc[0]
    assert big.operators == "EE,O2 (UK)" and big.radio_types == "LTE,NR" and big.operator_count == 2


def test_no_chaining_along_a_line():
    # Cells every 100 m along a line: single-linkage would make one 1 km "site".
    cells = _cells([("LTE", "EE", 54.0 + i * 0.0009, -3.0, 1) for i in range(11)])
    sites, _ = cluster_sites(cells)
    assert len(sites) >= 4


def test_masts_per_cell_distance_bearing_operators():
    sites = pd.DataFrame(
        {
            "site_id": ["S1", "S2"],
            "lat": [54.4450 + 0.0270, 54.4450],  # ~3 km north; ~20 km east below
            "lon": [-3.1050, -3.1050 + 0.31],
            "operators": ["EE,Vodafone UK", "3"],
        }
    )
    cells = pd.DataFrame({"cell_id": ["c"], "lat": [54.4450], "lon": [-3.1050]})
    row = masts_per_cell(cells, sites).iloc[0]
    assert row.nearest_mast_id == "S1"
    assert row.nearest_mast_km == pytest.approx(3.0, abs=0.05)
    assert row.nearest_mast_bearing_deg == pytest.approx(0.0, abs=0.5)
    assert row.masts_within_5km == 1
    assert row.distinct_operators_within_5km == 2
    assert row.operators_within_5km == "EE,Vodafone UK"


def test_bearing_east():
    assert bearing_deg(54.0, -3.0, 54.0, -2.0) == pytest.approx(90.0, abs=0.5)
