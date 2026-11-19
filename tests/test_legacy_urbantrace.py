"""UrbanTrace's operators (copied at the revision in tests/legacy/urbantrace/REVISION) against
urbanweave through its compatibility layer, on the same inputs. Every difference is attributed to a
named change (urbanweave.compat.urbantrace.CHANGES)."""

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from urbanweave.compat import urbantrace as compat

from .legacy.urbantrace.grids.h3_grid import H3GridSystem
from .legacy.urbantrace.operators.aggregation import aggregators as A
from .legacy.urbantrace.operators.allocation.binary import BinaryCentroidContainment, BinaryContainment, NearestAssignment
from .legacy.urbantrace.operators.allocation.kernel import GaussianKernel
from .legacy.urbantrace.operators.allocation.proportional import ProportionalAreaWeighted, ProportionalLengthWeighted
from .legacy.urbantrace.operators.zoning import aggregators as ZA
from .legacy.urbantrace.operators.zoning import mapping as ZM

pytestmark = pytest.mark.legacy
RES = 9
BOUNDS = (-73.99, 40.70, -73.96, 40.73)
LAT = 40.715


def _legacy_grid(src, alloc, agg):
    src = src.copy()
    src["source_id"] = src.index.astype(str)
    grid = H3GridSystem().generate_grid(tuple(src.total_bounds), RES)
    w = alloc.calculate_weights(src, grid)
    w = w.merge(src[["source_id", "v"]], on="source_id").rename(columns={"v": "source_value"})
    vals = agg.aggregate(w, grid)
    return grid, w, vals


def _points(n=400, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.uniform(BOUNDS[0], BOUNDS[2], n)
    y = rng.uniform(BOUNDS[1], BOUNDS[3], n)
    return gpd.GeoDataFrame({"v": rng.integers(1, 10, n).astype(float)}, geometry=gpd.points_from_xy(x, y), crs=4326)


def _polygons(n=60, seed=2):
    rng = np.random.default_rng(seed)
    x = rng.uniform(BOUNDS[0], BOUNDS[2] - 0.004, n)
    y = rng.uniform(BOUNDS[1], BOUNDS[3] - 0.004, n)
    return gpd.GeoDataFrame({"v": rng.uniform(1, 100, n)}, geometry=[box(a, b, a + 0.003, b + 0.002) for a, b in zip(x, y)], crs=4326)


def _lines(n=40, seed=3):
    rng = np.random.default_rng(seed)
    x = rng.uniform(BOUNDS[0], BOUNDS[2], (n, 2))
    y = rng.uniform(BOUNDS[1], BOUNDS[3], (n, 2))
    return gpd.GeoDataFrame({"v": rng.uniform(1, 10, n)}, geometry=[LineString([(a[0], b[0]), (a[1], b[1])]) for a, b in zip(x, y)], crs=4326)


def _by_cell(frame, column):
    return frame.set_index("cell_id")[column].astype(float)


def test_grid_build_is_the_same_set_of_cells():
    src = _points()
    legacy = H3GridSystem().generate_grid(tuple(src.total_bounds), RES)
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation", legacy_units=False)["grid"]
    assert set(legacy["cell_id"]) == set(new["cell_id"])


def test_containment_sum_matches_except_points_by_a_cell_edge():
    src = _points()
    _, w, legacy = _legacy_grid(src, BinaryContainment(), A.SumAggregation())
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation")["grid"]
    a, b = _by_cell(legacy, "allocated_val"), _by_cell(new, "allocated_val")
    cells = a.index.union(b.index)
    diff = (a.reindex(cells).fillna(0) - b.reindex(cells).fillna(0)).abs()
    # h3_index_lookup: legacy tests the cell polygon drawn with straight edges in degrees; the H3 index
    # uses the true cell. Points within centimetres of an edge can differ; none do in this sample.
    assert (diff > 1e-9).sum() == 0
    # Both lose the points whose cell's center lies outside the box (center-based extent selection).
    report = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation")["reports"]["allocation"]
    lost = report["aggregate"][0]["extensive"]["unmatched_input"]
    assert b.sum() == pytest.approx(src["v"].sum() - lost) and lost == pytest.approx(src["v"].sum() - a.sum())


def test_a_point_on_a_shared_vertex_counts_once():
    src = _points(30)
    cell = h3.latlng_to_cell(40.715, -73.975, RES)
    lat, lng = h3.cell_to_boundary(cell)[0]
    src.loc[len(src)] = [5.0, Point(lng, lat)]
    _, w, legacy = _legacy_grid(src, BinaryContainment(), A.SumAggregation())
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation")["grid"]
    vertex_id = str(len(src) - 1)
    assert (w["source_id"] == vertex_id).sum() >= 2  # boundary_once: legacy counts it in each cell touching it
    extra = 5.0 * ((w["source_id"] == vertex_id).sum() - 1)
    assert legacy["allocated_val"].sum() - new["allocated_val"].sum() == pytest.approx(extra)


def test_centroid_containment_matches():
    src = _polygons()
    _, _, legacy = _legacy_grid(src, BinaryCentroidContainment(), A.SumAggregation())
    new = compat.run(src, "v", RES, "BinaryCentroidContainment", "SumAggregation")["grid"]
    pd.testing.assert_series_equal(_by_cell(legacy, "allocated_val").sort_index(), _by_cell(new, "allocated_val").sort_index(),
                                   check_names=False, rtol=1e-12)


def test_area_weights_differ_only_by_the_measurement_crs():
    src = _polygons()
    _, w, legacy = _legacy_grid(src, ProportionalAreaWeighted(), A.SumAggregation())
    new = compat.run(src, "v", RES, "ProportionalAreaWeighted", "SumAggregation")["grid"]
    a, b = _by_cell(legacy, "allocated_val"), _by_cell(new, "allocated_val")
    common = a.index.intersection(b.index)
    # utm_measurement: ratios of areas in EPSG:3857 and in UTM agree closely over a few kilometres.
    assert np.allclose(a[common], b[common], rtol=2e-3, atol=1e-9)
    assert len(a.index.symmetric_difference(b.index)) == 0 or a[a.index.difference(common)].abs().max() < 1e-6


def test_density_differs_by_the_mercator_area_scale():
    src = _points()
    _, _, legacy = _legacy_grid(src, BinaryContainment(), A.DensityAggregation())
    new = compat.run(src, "v", RES, "BinaryContainment", "DensityAggregation")["grid"]
    a, b = _by_cell(legacy, "aggregated_value"), _by_cell(new, "aggregated_value")
    common = a.index.intersection(b.index)
    ratio = (b[common] / a[common]).median()
    # utm_measurement: EPSG:3857 inflates areas by sec²(latitude), about 1.74 at New York.
    assert ratio == pytest.approx(1 / np.cos(np.radians(LAT)) ** 2, rel=0.01)


def test_gaussian_kernel_matches_to_rounding():
    src = _points(80)
    alloc = GaussianKernel(bandwidth=400)
    _, _, legacy = _legacy_grid(src, alloc, A.SumAggregation())
    new = compat.run(src, "v", RES, "GaussianKernel", "SumAggregation", bandwidth=400)["grid"]
    a, b = _by_cell(legacy, "allocated_val").sort_index(), _by_cell(new, "allocated_val").sort_index()
    pd.testing.assert_series_equal(a, b, check_names=False, rtol=1e-9)


def test_nearest_and_length_weighted_match():
    src = _points(100)
    _, _, legacy = _legacy_grid(src, NearestAssignment(), A.SumAggregation())
    new = compat.run(src, "v", RES, "NearestAssignment", "SumAggregation")["grid"]
    pd.testing.assert_series_equal(_by_cell(legacy, "allocated_val").sort_index(), _by_cell(new, "allocated_val").sort_index(),
                                   check_names=False, rtol=1e-12)
    lines = _lines()
    _, _, legacy = _legacy_grid(lines, ProportionalLengthWeighted(), A.SumAggregation())
    new = compat.run(lines, "v", RES, "ProportionalLengthWeighted", "SumAggregation")["grid"]
    a, b = _by_cell(legacy, "allocated_val"), _by_cell(new, "allocated_val")
    common = a.index.intersection(b.index)
    assert np.allclose(a[common], b[common], rtol=2e-3)


def test_weighted_mean_with_missing_values():
    src = _polygons()
    src.loc[src.index[:5], "v"] = np.nan
    _, _, legacy = _legacy_grid(src, ProportionalAreaWeighted(), A.WeightedMeanAggregation())
    new = compat.run(src, "v", RES, "ProportionalAreaWeighted", "WeightedMeanAggregation")["grid"]
    a, b = _by_cell(legacy, "aggregated_value"), _by_cell(new, "aggregated_value")
    # missing_not_zero: legacy counts a missing value's weight in the denominator, and writes 0 where
    # every value is missing; urbanweave leaves missing values out and the cell missing.
    only_missing = a.index.difference(b.index)
    assert (a[only_missing] == 0).all()
    common = a.index.intersection(b.index)
    assert (b[common] >= a[common] * (1 - 2e-3) - 1e-9).all()


def _zones():
    return gpd.GeoDataFrame({"zone_id": ["w", "e"]},
                            geometry=[box(-73.99, 40.70, -73.975, 40.73), box(-73.975, 40.70, -73.96, 40.73)], crs=4326)


def _legacy_zoned(src, alloc, agg, mapper, zagg, zones):
    grid, _, vals = _legacy_grid(src, alloc, agg)
    zw = mapper.map_to_zones(grid, zones)
    return grid, zw, zagg.aggregate(zw, vals, zones)


def test_centroid_zoning_sum_matches():
    src = _points()
    _, _, legacy = _legacy_zoned(src, BinaryContainment(), A.SumAggregation(), ZM.CentroidZoning(), ZA.SumZoning(), _zones())
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation", zones_gdf=_zones(),
                     zoning_mapping="CentroidZoning", zoning_aggregation="SumZoning", output="zones")["zones"]
    pd.testing.assert_series_equal(legacy.set_index("zone_id")["zone_value"].sort_index(),
                                   new.set_index("zone_id")["zone_value"].astype(float).sort_index(), check_names=False, rtol=1e-12)


def test_area_zoning_weighted_mean_matches_up_to_the_measurement_crs():
    src = _polygons()
    _, _, legacy = _legacy_zoned(src, ProportionalAreaWeighted(), A.WeightedMeanAggregation(), ZM.AreaWeightedZoning(),
                                 ZA.WeightedMeanZoning(), _zones())
    new = compat.run(src, "v", RES, "ProportionalAreaWeighted", "WeightedMeanAggregation", zones_gdf=_zones(),
                     zoning_mapping="AreaWeightedZoning", zoning_aggregation="WeightedMeanZoning", output="zones")["zones"]
    a = legacy.set_index("zone_id")["zone_value"].sort_index()
    b = new.set_index("zone_id")["zone_value"].astype(float).sort_index()
    assert np.allclose(a, b, rtol=2e-3)


def test_point_zones_take_the_cell_holding_each_point():
    src = _points()
    stations = gpd.GeoDataFrame({"zone_id": ["s1", "s2"]}, geometry=[Point(-73.98, 40.71), Point(-73.97, 40.72)], crs=4326)
    _, _, legacy = _legacy_zoned(src, BinaryContainment(), A.SumAggregation(), ZM.CentroidZoning(), ZA.MaxZoning(), stations)
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation", zones_gdf=stations,
                     zoning_mapping="CentroidZoning", zoning_aggregation="MaxZoning", output="zones")["zones"]
    pd.testing.assert_series_equal(legacy.set_index("zone_id")["zone_value"].sort_index(),
                                   new.set_index("zone_id")["zone_value"].astype(float).sort_index(), check_names=False)


def test_line_zones_length_weighted_mean_and_the_target_normalized_sum():
    src = _points()
    streets = gpd.GeoDataFrame({"zone_id": ["a", "b"]}, geometry=[LineString([(-73.985, 40.705), (-73.965, 40.725)]),
                                                                  LineString([(-73.985, 40.72), (-73.97, 40.72)])], crs=4326)
    for zagg, name in ((ZA.LengthWeightedZoning(), "LengthWeightedZoning"), (ZA.SumZoning(), "SumZoning")):
        _, _, legacy = _legacy_zoned(src, BinaryContainment(), A.SumAggregation(), ZM.LengthWeightedZoning(), zagg, streets)
        new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation", zones_gdf=streets,
                         zoning_mapping="LengthWeightedZoning", zoning_aggregation=name, output="zones")["zones"]
        a = legacy.set_index("zone_id")["zone_value"].sort_index()
        b = new.set_index("zone_id")["zone_value"].astype(float).sort_index()
        assert np.allclose(a, b, rtol=2e-3), name


def test_zone_values_painted_back_onto_cells():
    src = _points()
    legacy_pipeline = __import__("tests.legacy.urbantrace.operators.zoning.mapping", fromlist=["x"])
    grid, zw, zv = _legacy_zoned(src, BinaryContainment(), A.SumAggregation(), ZM.CentroidZoning(), ZA.SumZoning(), _zones())
    painted = zw.merge(zv, on="zone_id").groupby("cell_id")["zone_value"].mean()
    new = compat.run(src, "v", RES, "BinaryContainment", "SumAggregation", zones_gdf=_zones(),
                     zoning_mapping="CentroidZoning", zoning_aggregation="SumZoning", output="grid_with_zone_values")["grid"]
    b = new.set_index("cell_id")["zone_aggregated_value"]
    common = painted.index.intersection(b.index)
    assert len(common) == len(painted)
    assert np.allclose(painted[common], b[common])


def test_operators_payload_comes_from_the_registry():
    payload = compat.operators_payload()
    gc = payload["geometry_constraints"]
    assert gc["Point"] == ["BinaryContainment", "BinaryCentroidContainment", "NearestAssignment", "GaussianKernel"]
    assert gc["Polygon"] == ["BinaryCentroidContainment", "ProportionalAreaWeighted"]
    assert gc["LineString"] == ["BinaryCentroidContainment", "ProportionalLengthWeighted", "GaussianKernel"]
    # Named differences from UrbanTrace's hand-written table: MultiPoint containment has no equivalent,
    # and centroid assignment of lines is new.
    assert "BinaryContainment" not in gc["MultiPoint"]
