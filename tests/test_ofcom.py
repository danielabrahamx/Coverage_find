import numpy as np
import pandas as pd

from coverage_detective.sources.ofcom import FAMILIES, area_table


def _row(code, values_by_family):
    row = {"code": code, "name": code, "prem_count": 1, "pixel_count": 1}
    for family in FAMILIES:
        vals = values_by_family.get(family, [np.nan] * 5)
        row.update({f"{family}_{i}": v for i, v in enumerate(vals)})
    return row


def test_blanks_are_zero_unless_the_whole_group_is_blank():
    df = pd.DataFrame([_row("A", {"4G_geo_out": [np.nan, 2.0, np.nan, 8.0, 90.0]})])
    out = area_table(df, "code", "name").iloc[0]
    assert [out[f"g4_geo_out_{i}"] for i in range(5)] == [0.0, 2.0, 0.0, 8.0, 90.0]
    assert out.g4_geo_out_at_least_one == 100.0
    assert np.isnan(out.g4_mway_in_0)  # whole group blank: not applicable (no motorways)
