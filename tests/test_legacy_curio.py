"""Curio's UHVI and Weather zonal means (copied at tests/legacy/curio/REVISION) against
urbanweave.compat.curio, on synthetic rasters and on Curio's Milan sample data when available."""

import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import shapely

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("rasterstats")
from rasterio.transform import from_origin  # noqa: E402

from urbanweave.compat import curio as compat  # noqa: E402

from .conftest import UTM18, X0, Y0, frame, sq  # noqa: E402
from .legacy.curio.uhvi_statistics import zonal_mean as legacy_uhvi  # noqa: E402
from .legacy.curio.weather_census import utci_zonal_mean as legacy_utci  # noqa: E402

pytestmark = [pytest.mark.legacy, pytest.mark.raster]
CURIO = Path(os.environ.get("CURIO_REPO", Path(__file__).resolve().parents[2] / "curio"))
MRT = CURIO / "datasets/data.utk.milan-mrt@1/data/milan-mrt.tif"
CENSUS = CURIO / "datasets/data.utk.milan-census-gt65@1/data/milan-census-gt65.geojson"


@pytest.fixture
def tif(tmp_path):
    rng = np.random.default_rng(7)
    data = rng.uniform(20, 45, (37, 23)).astype("float32")  # rectangular, to catch width/height swaps
    data[rng.random(data.shape) < 0.08] = -9999
    path = tmp_path / "r.tif"
    with rasterio.open(path, "w", driver="GTiff", height=37, width=23, count=1, dtype="float32", crs=UTM18,
                       transform=from_origin(X0, Y0 + 370, 10, 10), nodata=-9999) as ds:
        ds.write(data, 1)
    return path


def _zones():
    z = frame([shapely.Point(X0 + 60, Y0 + 200).buffer(55), sq(120, 40, 70, 120), sq(3, 3, 4, 4), sq(900, 900, 50),
               shapely.Point(X0 + 150, Y0 + 300).buffer(3)], gt_65=[10, 20, 30, 40, 50])
    return z


def _same(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    assert np.array_equal(np.isnan(a), np.isnan(b))
    assert np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=1e-12)


def test_uhvi_zonal_mean_matches_in_either_order(tif):
    with rasterio.open(tif) as ds:
        with pytest.warns(RuntimeWarning):  # the original warns on a polygon over no valid cell
            old = legacy_uhvi(ds, _zones())
        new = compat.uhvi_zonal_mean(_zones(), ds)
        _same(old["uhvi_mean"], new["uhvi_mean"])
        assert new.metadata == {"name": "uhvi_zonal"} and new.crs == ds.crs
        assert list(new.columns) == list(old.columns)
        no_crs = _zones().set_crs(None, allow_override=True)
        _same(compat.uhvi_zonal_mean(ds, no_crs)["uhvi_mean"], old["uhvi_mean"])


def test_utci_zonal_mean_matches_on_a_rescaled_grid(tif):
    rng = np.random.default_rng(8)
    with rasterio.open(tif) as ds:
        grid = rng.uniform(25, 40, (74, 46))  # twice the raster's resolution: rows × cols
        grid[rng.random(grid.shape) < 0.05] = np.nan
        utci = (grid.tolist(), [46, 74])
        old = legacy_utci(ds, utci, _zones())
        new = compat.utci_zonal_mean(ds, utci, _zones())
    _same(old["mean"], new["mean"])
    assert list(new.columns) == list(old.columns) and new["gt_65"].tolist() == old["gt_65"].tolist()


@pytest.mark.slow  # the legacy UHVI function masks the whole raster once per polygon: minutes
@pytest.mark.skipif(not (MRT.exists() and CENSUS.exists()), reason="Curio's Milan sample data is not available")
def test_milan_sample_dataflow_matches():
    census = gpd.read_file(CENSUS)
    with rasterio.open(MRT) as ds:
        census = census.to_crs(ds.crs)
        old = legacy_uhvi(ds, census.copy())
        new = compat.uhvi_zonal_mean(ds, census.copy())
        _same(old["uhvi_mean"], new["uhvi_mean"])
        band = ds.read(1).astype(float)
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        utci = (band.tolist(), [ds.width, ds.height])
        old = legacy_utci(ds, utci, census.copy())
        new = compat.utci_zonal_mean(ds, utci, census.copy())
        _same(old["mean"], new["mean"])
