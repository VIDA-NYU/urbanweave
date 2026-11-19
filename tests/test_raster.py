"""Zonal statistics: the raster acceptance fixtures of PLAN.md, windows, ownership and references."""

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("exactextract")
from rasterio.transform import Affine, from_origin  # noqa: E402

import urbanweave as uw  # noqa: E402
from urbanweave.errors import UnsupportedError  # noqa: E402

from .conftest import TOL, UTM18, X0, Y0, frame, sq  # noqa: E402

pytestmark = pytest.mark.raster


def mem(arr, *, cell=1.0, crs=UTM18, **kw):
    arr = np.asarray(arr, dtype=float)
    rows = arr.shape[-2]
    return uw.read_raster(arr, transform=from_origin(X0, Y0 + rows * cell, cell, cell), crs=crs, **kw)


def test_one_quarter_of_a_valid_cell_with_value_8():
    r = mem([[8.0]])
    zone = frame([sq(0, 0, 0.5)], target_id=["q"])  # the lower-left quarter; the center is its corner
    out = uw.zonal_stats(r, zone, [uw.mean(1, as_="mean"), uw.sum(1, as_="sum"), uw.count(), uw.weighted_count()])
    assert out["mean"].iloc[0] == 8 and out["sum"].iloc[0] == pytest.approx(2.0, **TOL)
    assert out["count"].iloc[0] == 1 and out["weighted_count"].iloc[0] == pytest.approx(0.25, **TOL)
    away = frame([sq(0, 0, 0.4)], target_id=["q"])  # a quarter-ish that excludes the center
    centers = uw.zonal_stats(r, away, [uw.mean(1, as_="mean"), uw.count()], method="cell_center")
    assert pd.isna(centers["mean"].iloc[0]) and pd.isna(centers["count"].iloc[0]) and centers["cells"].iloc[0] == 0


def test_one_valid_and_one_nodata_cell():
    r = mem([[5.0, -1.0], [7.0, 7.0]], nodata=-1.0)
    zone = frame([sq(0, 1, 2, 1)], target_id=["top"])  # the top row: 5 and nodata, 1 m² each
    out = uw.zonal_stats(r, zone, [uw.mean(1, as_="mean"), uw.sum(1, as_="sum")])
    assert out["coverage"].iloc[0] == pytest.approx(1.0, **TOL)
    assert out["valid_coverage"].iloc[0] == pytest.approx(0.5, **TOL)
    assert out["mean"].iloc[0] == 5.0 and out["sum"].iloc[0] == 5.0
    # A second band with a different mask gets its own valid coverage.
    two = np.array([[[5.0, 1.0], [7.0, 7.0]], [[1.0, 2.0], [3.0, 4.0]]])
    valid = np.array([[[True, False], [True, True]], [[True, True], [True, True]]])
    r2 = uw.read_raster(two, transform=from_origin(X0, Y0 + 2, 1, 1), crs=UTM18, mask=valid, names=["a", "b"])
    out = uw.zonal_stats(r2, zone, [uw.sum("a", as_="sa"), uw.sum("b", as_="sb")])
    assert out["valid_coverage_a"].iloc[0] == pytest.approx(0.5, **TOL)
    assert out["valid_coverage_b"].iloc[0] == pytest.approx(1.0, **TOL)
    assert out["sa"].iloc[0] == 5.0 and out["sb"].iloc[0] == 3.0


def test_partly_outside_wholly_outside_and_rotated():
    r = mem([[2.0, 2.0], [2.0, 2.0]])
    zones = frame([sq(1, 0, 2, 2), sq(10, 10, 1)], target_id=["half", "out"])
    out = uw.zonal_stats(r, zones, [uw.sum(1, as_="sum"), uw.weighted_mean(1, as_="wm")])
    assert out["coverage"].tolist()[0] == pytest.approx(0.5, **TOL)  # the full zone's area is the denominator
    assert out["sum"].iloc[0] == pytest.approx(4.0, **TOL)
    assert out["coverage"].iloc[1] == 0 and pd.isna(out["sum"].iloc[1]) and pd.isna(out["wm"].iloc[1])
    assert uw.report_of(out)["zones"]["outside_raster"]["sample"] == ["out"]
    rotated = uw.read_raster(np.ones((2, 2)), transform=Affine.rotation(10) * from_origin(X0, Y0, 1, 1), crs=UTM18)
    with pytest.raises(UnsupportedError, match="north-up"):
        uw.zonal_stats(rotated, zones, [uw.sum(1)])


def test_geographic_grids_allow_centers_only():
    r = uw.read_raster(np.ones((10, 10)), transform=from_origin(-74.0, 40.8, 0.01, 0.01), crs=4326)
    import geopandas as gpd

    zone = gpd.GeoDataFrame(geometry=[box(-73.99, 40.70, -73.95, 40.74)], crs=4326)  # 4 × 4 centers
    with pytest.raises(UnsupportedError, match="geographic"):
        uw.zonal_stats(r, zone, [uw.sum(1)])
    out = uw.zonal_stats(r, zone, [uw.count()], method="cell_center")
    assert out["count"].iloc[0] == 16


def test_zones_tiling_the_raster_sum_to_the_valid_raster_sum():
    rng = np.random.default_rng(0)
    arr = rng.uniform(0, 10, (40, 50))
    arr[rng.random(arr.shape) < 0.1] = np.nan
    r = mem(arr, cell=10.0)
    xs = np.linspace(0, 500, 7)
    ys = np.linspace(0, 400, 5)
    tiles = [sq(a, b, c - a, d - b) for a, c in zip(xs[:-1], xs[1:]) for b, d in zip(ys[:-1], ys[1:])]
    out = uw.zonal_stats(r, frame(tiles), [uw.sum(1, as_="s")])
    # exactextract keeps coverage fractions in single precision, so cut cells add up to 1 within ~1e-7.
    assert out["s"].sum() == pytest.approx(np.nansum(arr), rel=1e-7)


def test_results_do_not_depend_on_the_window_size():
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 4, (60, 60)).astype(float)
    zones = frame([sq(3.3, 4.1, 40.2, 33.7), sq(10.5, 10.5, 45, 45), sq(0, 0, 60, 60), sq(20, 20, 30, 1.5)])
    reds = [uw.sum(1, as_="s"), uw.weighted_mean(1, as_="wm"), uw.min(1, as_="lo"), uw.max(1, as_="hi"),
            uw.count(), uw.weighted_count(), uw.shares(1, as_="sh"), uw.majority(1, as_="mj")]
    results = []
    for cells in (10_000_000, 600, 61):
        out = uw.zonal_stats(mem(arr), zones, reds, max_cells_in_memory=cells)
        results.append((out.drop(columns="geometry"), uw.report_of(out)["reads"]["windows"]))
    base = results[0][0]
    for other, _ in results[1:]:
        pd.testing.assert_frame_equal(base, other, rtol=1e-12)
    assert results[2][1] > results[0][1]  # smaller windows mean more reads


def test_geotiff_nodata_scale_offset_and_ownership(tmp_path):
    path = tmp_path / "t.tif"
    data = np.array([[10, 20], [0, 40]], dtype="int16")
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1, dtype="int16", crs=UTM18,
                       transform=from_origin(X0, Y0 + 2, 1, 1), nodata=0) as ds:
        ds.write(data, 1)
        ds.scales = (0.5,)
        ds.offsets = (1.0,)
    zone = frame([sq(0, 0, 2)])
    r = uw.read_raster(path, value_kind="intensive", units="degC")
    out = uw.zonal_stats(r, zone, [uw.mean(1, as_="m")])
    assert out["m"].iloc[0] == pytest.approx(np.mean([6.0, 11.0, 21.0]), **TOL)  # 0 is nodata
    r.close()
    assert r.dataset is None
    with rasterio.open(path) as ds:
        mine = uw.read_raster(ds)
        uw.zonal_stats(mine, zone, [uw.count()])
        mine.close()
        assert not ds.closed  # the caller's dataset stays open
    with pytest.raises(UnsupportedError, match="intensive"):
        uw.zonal_stats(uw.read_raster(path, value_kind="intensive"), zone, [uw.sum(1)])


def test_exact_mode_agrees_with_exactextract():
    from exactextract import exact_extract
    from exactextract.raster import NumPyRasterSource

    rng = np.random.default_rng(4)
    arr = rng.uniform(0, 100, (30, 30))
    r = mem(arr, cell=5.0)
    import shapely

    zones = frame([shapely.Point(X0 + 40, Y0 + 70).buffer(23), shapely.Point(X0 + 100, Y0 + 30).buffer(17)])
    out = uw.zonal_stats(r, zones, [uw.weighted_mean(1, as_="m"), uw.sum(1, as_="s")])
    src = NumPyRasterSource(arr, X0, Y0, X0 + 150, Y0 + 150, srs_wkt=r.crs.to_wkt())
    ref = exact_extract(src, zones, ["mean", "sum"], output="pandas")
    assert np.allclose(out["m"].astype(float), ref["mean"], rtol=1e-12)
    assert np.allclose(out["s"].astype(float), ref["sum"], rtol=1e-12)


def test_center_mode_agrees_with_rasterstats():
    rasterstats = pytest.importorskip("rasterstats")
    rng = np.random.default_rng(5)
    arr = rng.uniform(0, 100, (30, 30))
    arr[rng.random(arr.shape) < 0.05] = -999
    import shapely

    zones = frame([shapely.Point(X0 + 40, Y0 + 70).buffer(23), shapely.Point(X0 + 100, Y0 + 30).buffer(17),
                   sq(1000, 1000, 5)])
    out = uw.zonal_stats(mem(arr, cell=5.0, nodata=-999), zones, [uw.mean(1, as_="m"), uw.count()], method="cell_center")
    ref = rasterstats.zonal_stats(zones, arr, affine=from_origin(X0, Y0 + 150, 5, 5), nodata=-999, stats=["mean", "count"])
    assert np.allclose(out["m"].astype(float).fillna(-1), [d["mean"] if d["mean"] is not None else -1 for d in ref])
    assert out["count"].fillna(0).tolist() == [d["count"] for d in ref]


def test_unsupported_reductions_and_options_are_refused():
    r = mem([[1.0]])
    zone = frame([sq(0, 0, 1)])
    with pytest.raises(UnsupportedError, match="median"):
        uw.zonal_stats(r, zone, [uw.median(1)])
    with pytest.raises(UnsupportedError, match="where"):
        uw.zonal_stats(r, zone, [uw.count(where={"column": "x", "op": ">", "value": 1})])
