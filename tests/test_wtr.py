from pathlib import Path

import pytest

from coverage_detective.sources.ofcom_wtr import grid_ref_to_en, grid_ref_to_latlon, load_licensees, operators_for

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("TQ 30080 80071", (530080.5, 180071.5)),   # 10-figure, central London
        ("TQ30088007", (530085.0, 180075.0)),       # 8-figure: centre of a 10 m square
        ("TQ 300 800", (530050.0, 180050.0)),       # 6-figure: centre of a 100 m square
        ("NY 289 050", (328950.0, 505050.0)),       # Lake District (NY)
        ("HU 450 410", (445050.0, 1141050.0)),      # Shetland (HU)
    ],
)
def test_british_grid_refs(ref, expected):
    grid, e, n = grid_ref_to_en(ref)
    assert grid == "GB" and (e, n) == pytest.approx(expected)


def test_grid_ref_to_latlon():
    # Ordnance Survey's worked example: TG 51409 13177 = 52.6576 N, 1.7179 E on OSGB36; WGS84 is
    # within ~120 m of that. (Against Ofcom's own WGS84 lat/lon the conversion agrees to 0.1 m.)
    lat, lon = grid_ref_to_latlon("TG 51409 13177")
    assert lat == pytest.approx(52.6576, abs=0.002) and lon == pytest.approx(1.7179, abs=0.003)
    lat, lon = grid_ref_to_latlon("J 3374 7428")      # Belfast, Irish Grid
    assert lat == pytest.approx(54.60, abs=0.02) and lon == pytest.approx(-5.93, abs=0.03)


def test_bad_grid_refs():
    for ref in ["-", "", "ZU COORDINATE (NOT CONVERTED)", "TQ 123 45", "TQ"]:
        assert grid_ref_to_latlon(ref) is None


def test_licensee_mapping_is_exact():
    lic = load_licensees(ROOT / "data" / "reference" / "wtr_operator_licensees.csv")
    assert operators_for("Telefonica UK Limited", lic) == ["O2"]
    assert operators_for("VODAFONE LIMITED", lic) == ["Vodafone"]
    assert operators_for("MOBILE BROADBAND NETWORK LIMITED", lic) == ["EE", "Three"]
    assert operators_for("Cornerstone Telecommunications Infrastructure Limited", lic) == ["O2", "Vodafone"]
    # Loose word matches must not count.
    for other in ["East Anglia Three Limited", "Cornerstone Security Systems Limited", "Three Horseshoes Inn Limited",
                  "BRITISH TELECOMMUNICATIONS LIMITED"]:
        assert operators_for(other, lic) == []
