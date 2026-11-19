"""Curio compatibility: drop-in versions of Curio's zonal means, built on :func:`urbanweave.zonal_stats`.

Each function keeps its Curio node's contract, inputs and outputs, and selects urbanweave's
``cell_center`` rule, which is the rule Curio's functions use (a cell counts when its center lies in
the polygon; nodata and NaN cells never count; a polygon over no valid cell gets NaN).

- :func:`uhvi_zonal_mean` replaces ``zonal_mean`` of ``ai.utk.uhvi@1`` (``uhvi_statistics.py``).
- :func:`utci_zonal_mean` replaces ``utci_zonal_mean`` of ``curio.weather@1`` (``weather_census.py``).

Differences from the Curio originals, by design: a polygon outside the raster gets NaN without a
NumPy warning, and the full report of what each polygon held is in ``attrs["urbanweave_report"]``.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np

from ..inputs import float_array
from ..raster import read_raster, zonal_stats
from ..reducers import mean


def uhvi_zonal_mean(first, second):
    """UHVI Zonal Stats: the mean of a raster's first band under each polygon, as ``uhvi_mean``.

    *first* and *second* are an open Rasterio dataset and a GeoDataFrame, in either order (one may
    be None). Polygons are reprojected to the raster's CRS, or given it when they have none. The
    result is the polygons in the raster's CRS with ``uhvi_mean`` and ``metadata = {"name": "uhvi_zonal"}``.
    """
    import rasterio

    received = [x for x in (first, second) if x is not None]
    raster = next((x for x in received if isinstance(x, rasterio.io.DatasetReader)), None)
    polygons = next((x for x in received if isinstance(x, gpd.GeoDataFrame)), None)
    if raster is None or polygons is None:
        raise RuntimeError("UHVI Zonal Stats expects a Raster + GeoDataFrame pair. "
                           f"Got: {[type(x).__name__ for x in received]}")
    polygons = polygons.set_crs(raster.crs) if polygons.crs is None else polygons.to_crs(raster.crs)
    r = read_raster(raster, bands=[1])
    out = zonal_stats(r, polygons.reset_index(drop=True), [mean(1, as_="uhvi_mean")], method="cell_center",
                      coverage_as=None)
    result = polygons.copy()
    result["uhvi_mean"] = float_array(out["uhvi_mean"])
    result.attrs.update(out.attrs)
    result.__dict__["metadata"] = {"name": "uhvi_zonal"}  # as Curio sets it, without a pandas warning
    return result


def utci_zonal_mean(raster, utci, census):
    """UTCI Zonal Mean: the mean UTCI of each census polygon, as ``mean``, with ``gt_65``.

    *raster* places the grid (its transform, scaled to the grid's shape); *utci* is ``(grid, shape)``
    with the grid as a list of rows and its shape as ``[width, height]``; *census* holds polygons in
    the raster's CRS with ``gt_65``. NaN cells count toward no mean. Like the original, *census*
    gains the ``mean`` column; the result is its geometry, ``mean`` and ``gt_65``.
    """
    grid = np.asarray(utci[0], dtype=float)
    width, height = utci[1]
    if grid.ndim != 2:
        raise ValueError(f"Expected 2D UTCI array, got shape={grid.shape}, ndim={grid.ndim}")
    transform = raster.transform @ raster.transform.scale(raster.width / width, raster.height / height)
    r = read_raster(np.ma.masked_invalid(grid), transform=transform, crs=raster.crs)
    zones = census.reset_index(drop=True)
    if zones.crs is None:
        zones = zones.set_crs(raster.crs)
    out = zonal_stats(r, zones, [mean(1, as_="mean")], method="cell_center", coverage_as=None)
    census["mean"] = float_array(out["mean"])
    return census.loc[:, [census.geometry.name, "mean", "gt_65"]]
