"""Targets ("supports"): the places values are woven onto.

Built here: H3 cells (:func:`h3_cells`, :func:`h3_from_cells`) and zones from a GeoDataFrame
(:func:`zones`). Street and intersection targets are in :mod:`urbanweave.streets` (the ``osm``
extra); raster grids in :mod:`urbanweave.raster` (the ``raster`` extra).

A target built by urbanweave is a GeoDataFrame with a ``target_id`` column, its geometry in
EPSG:4326, and a description of how it was built in ``attrs["urbanweave_support"]`` (a plain JSON
dict, the target's spec). H3 targets keep their cell IDs (hex strings) as ``target_id``; their
polygons are derived from the IDs.
"""

from __future__ import annotations

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyproj
import shapely
from shapely.geometry import Polygon, box

from .errors import InputError, UnsupportedError
from .inputs import SUPPORT_ATTR, prepare_layer

_WGS84 = "EPSG:4326"


def _extent_shape(extent, cover: str):
    """The extent as one shapely geometry in EPSG:4326."""
    if isinstance(extent, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if extent.crs is None:
            raise InputError("The extent has no CRS.")
        ext = extent.to_crs(_WGS84)
        if cover == "bbox":
            return box(*ext.total_bounds)
        return shapely.union_all(np.asarray(ext.geometry.array if isinstance(ext, gpd.GeoDataFrame) else ext.array))
    if isinstance(extent, shapely.Geometry):
        return box(*extent.bounds) if cover == "bbox" else extent
    try:
        minx, miny, maxx, maxy = (float(v) for v in extent)
    except (TypeError, ValueError):
        raise InputError("The extent must be a GeoDataFrame, a GeoSeries, a shapely geometry, or "
                         "(minx, miny, maxx, maxy) in EPSG:4326.") from None
    return box(minx, miny, maxx, maxy)


def _latlng_poly(poly: Polygon) -> h3.LatLngPoly:
    outer = [(y, x) for x, y in poly.exterior.coords]
    holes = [[(y, x) for x, y in ring.coords] for ring in poly.interiors]
    return h3.LatLngPoly(outer, *holes)


def cell_polygon(cell: str) -> Polygon:
    """The polygon of an H3 cell, in EPSG:4326 (longitude, latitude)."""
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])


def h3_cells(extent, resolution: int, *, cover: str = "bbox", selection: str = "center") -> gpd.GeoDataFrame:
    """The H3 cells of *resolution* over *extent*.

    ``selection="center"`` keeps the cells whose center lies inside the extent, H3's own polygon
    fill (``h3shape_to_cells``). With ``cover="bbox"`` (the default) the extent is the bounding
    box of the input in EPSG:4326, which reproduces UrbanTrace's grid build; ``cover="geometry"``
    uses the geometry itself. A cell whose center falls outside the extent is not part of the
    support, so a source inside such a cell is reported as unmatched, never silently added.
    """
    if selection != "center":
        raise UnsupportedError("Only selection='center' is supported; a covering of every intersecting "
                               "cell is planned once benchmarked.")
    if cover not in ("bbox", "geometry"):
        raise InputError("cover must be 'bbox' or 'geometry'.")
    if not 0 <= int(resolution) <= 15:
        raise InputError("H3 resolution must be between 0 and 15.")
    shape = _extent_shape(extent, cover)
    parts = list(shape.geoms) if hasattr(shape, "geoms") else [shape]
    cells: set[str] = set()
    for part in parts:
        if isinstance(part, Polygon) and not part.is_empty:
            cells.update(h3.h3shape_to_cells(_latlng_poly(part), int(resolution)))
    spec = {"kind": "h3", "resolution": int(resolution), "selection": selection, "cover": cover,
            "extent": [float(v) for v in shape.bounds]}
    return h3_from_cells(sorted(cells), spec=spec)


def h3_from_cells(cells, *, spec: dict | None = None) -> gpd.GeoDataFrame:
    """An H3 target from cell IDs (one resolution), with their polygons."""
    cells = [str(c) for c in cells]
    for c in cells:
        if not h3.is_valid_cell(c):
            raise InputError(f"{c!r} is not a valid H3 cell.")
    resolutions = {h3.get_resolution(c) for c in cells} if cells else set()
    if len(resolutions) > 1:
        raise InputError(f"H3 cells of one target must share a resolution; found {sorted(resolutions)}.")
    if len(set(cells)) != len(cells):
        raise InputError("H3 cell IDs repeat.")
    frame = gpd.GeoDataFrame(
        {"target_id": pd.array(cells, dtype=object)},
        geometry=[cell_polygon(c) for c in cells],
        crs=_WGS84,
    )
    spec = dict(spec or {"kind": "h3", "resolution": resolutions.pop() if resolutions else None,
                         "selection": "given"})
    spec.setdefault("kind", "h3")
    frame.attrs[SUPPORT_ATTR] = spec
    return frame


def as_h3(frame: gpd.GeoDataFrame, id_column: str) -> gpd.GeoDataFrame:
    """Mark *frame*, whose *id_column* holds H3 cell IDs, as an H3 support (a copy).

    Use this for H3 data from elsewhere, such as a previous step's output, so that point lookups
    use the H3 index rather than polygon containment.
    """
    cells = frame[id_column].astype(str)
    if not all(h3.is_valid_cell(c) for c in cells):
        raise InputError(f"Column {id_column!r} does not hold valid H3 cell IDs.")
    resolutions = {h3.get_resolution(c) for c in cells}
    if len(resolutions) > 1:
        raise InputError(f"H3 cells must share a resolution; found {sorted(resolutions)}.")
    out = frame.copy()
    out.attrs[SUPPORT_ATTR] = {"kind": "h3", "resolution": resolutions.pop() if resolutions else None,
                               "id_column": id_column, "selection": "given"}
    return out


def zones(frame: gpd.GeoDataFrame, *, id_column: str | None = None, name: str | None = None) -> gpd.GeoDataFrame:
    """Zones (polygons) from a GeoDataFrame: checked, with a ``target_id`` column (a copy)."""
    layer = prepare_layer(frame, "target", id_column=id_column, families={"polygon"}, method="zones")
    out = frame.copy()
    out["target_id"] = layer.ids.to_numpy()
    out.attrs[SUPPORT_ATTR] = {"kind": "zones", "name": name, "id_column": layer.id_column}
    return out


def h3_resolution(layer_support: dict | None) -> int | None:
    if layer_support and layer_support.get("kind") == "h3":
        return layer_support.get("resolution")
    return None


def latlng_cells(points: np.ndarray, crs, resolution: int) -> list[str]:
    """The H3 cell of each shapely point (in *crs*) at *resolution*."""
    pts = np.asarray(points, dtype=object)
    xy = shapely.get_coordinates(pts)
    crs = pyproj.CRS.from_user_input(crs)
    if not crs.equals(pyproj.CRS.from_epsg(4326)):
        t = pyproj.Transformer.from_crs(crs, 4326, always_xy=True)
        x, y = t.transform(xy[:, 0], xy[:, 1])
    else:
        x, y = xy[:, 0], xy[:, 1]
    return [h3.latlng_to_cell(float(lat), float(lng), resolution) for lng, lat in zip(x, y)]
