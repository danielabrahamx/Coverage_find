"""Line of sight on synthetic terrain (no DEM files needed)."""

import numpy as np
import pytest

from coverage_detective.data import terrain


class FakeDEM:
    """Flat ground at `base` m, with an optional ridge across latitude `ridge_lat`."""

    def __init__(self, base=100.0, ridge_lat=None, ridge_height=0.0, ridge_half_width_deg=0.0005):
        self.base, self.ridge_lat, self.h, self.w = base, ridge_lat, ridge_height, ridge_half_width_deg

    def elevation(self, lats, lons):
        z = np.full(np.shape(lats), self.base, dtype=np.float32)
        if self.ridge_lat is not None:
            z[np.abs(np.asarray(lats) - self.ridge_lat) <= self.w] += self.h
        return z


def test_flat_short_path_is_clear():
    los = terrain.line_of_sight(54.0, -3.0, 54.02, -3.0, source=FakeDEM())
    assert not los["blocked"] and los["max_obstruction_m"] < 0
    assert los["path_length_m"] == pytest.approx(2224, abs=5)
    assert los["mast_height_m"] == 25.0 and los["mast_height_source"] == "assumed_default"
    assert los["samples"] >= 2224 / 30
    p = los["profile"]
    assert len(p["distance_m"]) == len(p["ground_m"]) == len(p["line_m"]) == los["samples"]


def test_ridge_blocks_and_is_located():
    # A 200 m ridge 1.1 km along a 2.2 km path.
    los = terrain.line_of_sight(54.0, -3.0, 54.02, -3.0, source=FakeDEM(ridge_lat=54.01, ridge_height=200))
    assert los["blocked"]
    # Line height mid-path is about 100 + (1.5 + 25) / 2 = 113 m; ridge top 300 m.
    assert los["max_obstruction_m"] == pytest.approx(300 - 113.25, abs=2)
    assert los["obstruction_distance_m"] == pytest.approx(1112, abs=70)
    assert los["obstruction_lat"] == pytest.approx(54.01, abs=0.0006)


def test_register_height_used_and_low_ridge_cleared_by_tall_mast():
    dem = FakeDEM(ridge_lat=54.01, ridge_height=20)
    short = terrain.line_of_sight(54.0, -3.0, 54.02, -3.0, mast_height=15.0, source=dem)
    tall = terrain.line_of_sight(54.0, -3.0, 54.02, -3.0, mast_height=60.0, source=dem)
    assert short["blocked"] and not tall["blocked"]
    assert tall["mast_height_source"] == "ofcom_register" and tall["mast_height_m"] == 60.0
    nan = terrain.line_of_sight(54.0, -3.0, 54.02, -3.0, mast_height=float("nan"), source=dem)
    assert nan["mast_height_source"] == "assumed_default"


def test_earth_curvature_blocks_long_flat_path():
    # 60 km over flat ground: the 4/3-earth bulge at mid-path is 60000^2 / 4 / (2 * 4/3 * R) ~ 53 m,
    # well above a line from 1.5 m to 25 m.
    los = terrain.line_of_sight(54.0, -3.0, 54.54, -3.0, source=FakeDEM(base=0))
    assert los["blocked"] and los["max_obstruction_m"] == pytest.approx(53 - 13.25, abs=3)
    # The line rises towards the mast, so the worst point is short of mid-path:
    # d = L/2 - (25 - 1.5) * k * R / L.
    L = los["path_length_m"]
    assert los["obstruction_distance_m"] == pytest.approx(L / 2 - 23.5 * (4 / 3) * 6_371_000 / L, abs=60)


def test_tile_names():
    assert terrain.tile_name(54, -4) == "Copernicus_DSM_COG_10_N54_00_W004_00_DEM"
    assert terrain.tile_name(51, 0) == "Copernicus_DSM_COG_10_N51_00_E000_00_DEM"
