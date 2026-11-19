"""H3 supports: the grid build, index lookups, and points → H3 → zones by polygon, point and line."""

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

import urbanweave as uw
from urbanweave.inputs import SUPPORT_ATTR

BOUNDS = (-74.00, 40.70, -73.96, 40.74)  # lower Manhattan / Brooklyn


@pytest.fixture(scope="module")
def cells():
    return uw.targets.h3_cells(BOUNDS, 9)


def _points(n=200, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.uniform(BOUNDS[0], BOUNDS[2], n)
    y = rng.uniform(BOUNDS[1], BOUNDS[3], n)
    return gpd.GeoDataFrame({"crashes": rng.integers(0, 4, n)}, geometry=gpd.points_from_xy(x, y), crs=4326)


def test_grid_build_matches_h3_center_fill(cells):
    expected = set(h3.h3shape_to_cells(h3.LatLngPoly([(40.70, -74.00), (40.70, -73.96), (40.74, -73.96),
                                                     (40.74, -74.00)]), 9))
    assert set(cells["target_id"]) == expected
    assert cells.attrs[SUPPORT_ATTR]["kind"] == "h3" and cells.attrs[SUPPORT_ATTR]["resolution"] == 9


def test_points_use_the_h3_index_and_cells_outside_the_support_are_unmatched(cells):
    pts = _points()
    pts = pd.concat([pts, gpd.GeoDataFrame({"crashes": [1]}, geometry=[Point(-73.90, 40.72)], crs=4326)],
                    ignore_index=True)  # one point east of the support
    m = uw.match(pts, cells, "contain")
    assert m.report["notes"]["lookup"] == "h3_index"
    expected = [h3.latlng_to_cell(p.y, p.x, 9) for p in pts.geometry]
    got = m.pairs.set_index("source_id")["target_id"]
    inside = [i for i, c in enumerate(expected) if c in set(cells["target_id"])]
    assert all(got[i] == expected[i] for i in inside)
    assert m.report["sources"]["unmatched"]["outside_support"]["count"] == len(pts) - len(inside)


def test_points_to_h3_to_polygon_zones(cells):
    pts = _points()
    on_grid = uw.aggregate(uw.match(pts, cells, "contain"), None, [uw.sum("crashes", as_="crashes", fill_empty=0)])
    zones = gpd.GeoDataFrame({"zone_id": ["w", "e"]}, geometry=[box(-74.0, 40.70, -73.98, 40.74), box(-73.98, 40.70, -73.96, 40.74)], crs=4326)
    by_centroid = uw.aggregate(uw.match(on_grid, zones, "centroid", target_id="zone_id"), None, [uw.sum("crashes")])
    by_area = uw.aggregate(uw.match(on_grid, zones, "area_overlap", target_id="zone_id"), None, [uw.sum("crashes")])
    total = on_grid["crashes"].sum()
    assert by_centroid["sum_crashes"].sum() == pytest.approx(total)  # every cell centroid is in a zone
    # Area overlap keeps the share of each cell inside the zones; cells partly outside lose that share.
    rep = uw.report_of(by_area)["aggregate"][0]["extensive"]
    assert rep["allocated"] + rep["unallocated"] == pytest.approx(total)
    assert by_area["sum_crashes"].sum() <= total + 1e-9


def test_h3_to_point_zones_is_a_cell_lookup(cells):
    values = cells.assign(heat=np.arange(len(cells), dtype=float))
    stations = gpd.GeoDataFrame({"target_id": ["s1", "s2", "s3"]},
                                geometry=[Point(-73.99, 40.71), Point(-73.99, 40.7101), Point(-73.80, 40.71)], crs=4326)
    m = uw.match(values, stations, "sample")
    assert m.report["notes"]["lookup"] == "h3_index"
    out = uw.aggregate(m, None, [uw.first("heat")]).set_index("target_id")
    cell_of = {c: v for c, v in zip(values["target_id"], values["heat"])}
    assert out.loc["s1", "first_heat"] == cell_of[h3.latlng_to_cell(40.71, -73.99, 9)]
    assert out.loc["s3", "first_heat"] is None  # outside the support


def test_h3_to_line_zones_by_length_inside_each_cell(cells):
    values = cells.assign(heat=np.linspace(20, 30, len(cells)))
    streets = gpd.GeoDataFrame({"target_id": ["broadway"]}, geometry=[LineString([(-73.995, 40.705), (-73.965, 40.735)])], crs=4326)
    m = uw.match(values, streets, "polygon_to_lines")
    out = uw.aggregate(m, None, [uw.weighted_mean("heat", valid_measure_as="metres")])
    street_m = streets.to_crs(32618).length.iloc[0]
    # Cells fill the box by center, so a sliver of street near the box's edge may lie outside every cell.
    assert out["metres"].iloc[0] == pytest.approx(street_m, rel=0.02)
    pairs = m.pairs
    expected = (pairs["overlap_measure"] * pairs["source_id"].map(dict(zip(values["target_id"], values["heat"])))).sum() / pairs["overlap_measure"].sum()
    assert out["weighted_mean_heat"].iloc[0] == pytest.approx(expected, rel=1e-12)


def test_h3_output_keeps_cell_ids_as_the_next_steps_source_ids(cells):
    pts = _points(50)
    on_grid = uw.aggregate(uw.match(pts, cells, "contain"), None, [uw.count(as_="n", fill_empty=0)])
    zones = gpd.GeoDataFrame({"zone_id": ["all"]}, geometry=[box(*BOUNDS)], crs=4326)
    m = uw.match(on_grid, zones, "centroid", target_id="zone_id")
    assert set(m.pairs["source_id"]) <= set(cells["target_id"])


def test_h3_from_cells_and_as_h3_checks():
    with pytest.raises(uw.InputError):
        uw.targets.h3_from_cells(["not-a-cell"])
    a = h3.latlng_to_cell(40.7, -74.0, 9)
    b = h3.latlng_to_cell(40.7, -74.0, 8)
    with pytest.raises(uw.InputError, match="resolution"):
        uw.targets.h3_from_cells([a, b])
    frame = gpd.GeoDataFrame({"cell": [a]}, geometry=[uw.targets.cell_polygon(a)], crs=4326)
    marked = uw.targets.as_h3(frame, "cell")
    assert marked.attrs[SUPPORT_ATTR]["resolution"] == 9 and SUPPORT_ATTR not in frame.attrs
