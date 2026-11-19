"""UrbanTrace's GaussianKernel tests (backend/tests/test_kernel.py), ported to urbanweave's API."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

import urbanweave as uw

BOUNDS = (-74.05, 40.60, -73.75, 40.88)  # NYC


@pytest.fixture(scope="module")
def grid():
    return uw.targets.h3_cells(BOUNDS, 8)  # cells about 0.7 km²


def _sources(geometries):
    return gpd.GeoDataFrame({"source_id": [str(i) for i in range(len(geometries))]}, geometry=geometries, crs="EPSG:4326")


def _kernel(src, grid, bandwidth, outside="nearest"):
    return uw.match(src, grid, "gaussian", bandwidth=bandwidth, outside=outside).pairs


def test_weights_sum_to_one_per_source(grid):
    src = _sources([Point(-73.98, 40.75), Point(-73.90, 40.70), LineString([(-73.95, 40.65), (-73.93, 40.67)])])
    w = _kernel(src, grid, 1000)
    assert np.allclose(w.groupby("source_id")["allocation_fraction"].sum().values, 1.0)


def test_reach_follows_the_bandwidth_in_meters(grid):
    src = _sources([Point(-73.98, 40.75)])
    metric = grid.estimate_utm_crs()
    centroids = grid.to_crs(metric).geometry.centroid
    here = src.to_crs(metric).geometry.iloc[0]
    for bandwidth in (500, 1000, 2000):
        w = _kernel(src, grid, bandwidth)
        reached = centroids[grid["target_id"].isin(w["target_id"])]
        assert reached.distance(here).max() <= 3.1 * bandwidth
        assert 1 < len(w) < len(grid)
    assert len(_kernel(src, grid, 500)) < len(_kernel(src, grid, 2000))


def test_sum_aggregation_preserves_the_total(grid):
    src = _sources([Point(-73.98, 40.75), Point(-73.95, 40.72)]).assign(v=[3.0, 5.0])
    out = uw.aggregate(uw.match(src, grid, "gaussian", bandwidth=800), None, [uw.sum("v")])
    assert out["sum_v"].sum() == pytest.approx(8.0)


def test_nearer_cells_get_more_weight(grid):
    src = _sources([Point(-73.98, 40.75)])
    w = _kernel(src, grid, 1000)
    order = np.argsort(w["distance_m"].values)
    assert np.all(np.diff(w["allocation_fraction"].values[order]) <= 1e-12)


def test_source_far_from_every_cell_goes_to_the_nearest_cell_only_when_asked(grid):
    src = _sources([Point(-73.40, 40.75)])  # about 30 km east of the grid
    w = _kernel(src, grid, 500)
    assert len(w) == 1 and w["allocation_fraction"].iloc[0] == pytest.approx(1.0)
    assert _kernel(src, grid, 500, outside="drop").empty  # urbanweave's default drops it, and reports it


def test_invalid_bandwidth(grid):
    with pytest.raises(uw.InputError):
        uw.match(_sources([Point(-73.98, 40.75)]), grid, "gaussian", bandwidth=0)
