import h3

from coverage_detective.data.grid import connected_groups


def test_connected_groups_splits_islands():
    home = h3.latlng_to_cell(54.445, -3.105, 7)
    mainland = set(h3.grid_disk(home, 2))
    island = {h3.latlng_to_cell(50.0, -6.3, 7)}
    groups = connected_groups(mainland | island)
    assert sorted(len(g) for g in groups) == [1, len(mainland)]
