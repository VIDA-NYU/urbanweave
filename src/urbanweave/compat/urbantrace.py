"""UrbanTrace compatibility: its operator names and column conventions, run on urbanweave.

UrbanTrace's backend can call :func:`run` with the operator IDs it already stores
(``BinaryContainment``, ``SumAggregation``, ``CentroidZoning``, ``SumZoning``...) and receive frames
with its column names (``cell_id``, ``area``, ``aggregated_value`` or ``allocated_val``,
``zone_id``, ``zone_value``, ``zone_aggregated_value``). :data:`OPERATORS` documents how each legacy
operator maps onto urbanweave, and :func:`operators_payload` rebuilds ``/api/operators`` from the
registry.

Where urbanweave corrects a legacy rule, the result changes; each change has a name
(:data:`CHANGES`) so a before/after comparison can attribute every difference:

``boundary_once``
    A point on a shared cell boundary goes to one cell (the lowest ID), not to every cell touching it.
``utm_measurement``
    Areas and lengths are measured in the local UTM zone, not Web Mercator (EPSG:3857), whose
    areas are about 1.74× too large at New York's latitude.
``missing_not_zero``
    A weighted mean with no valid value, or an empty density, is missing rather than 0.
``h3_index_lookup``
    Points find their H3 cell through the H3 index, so a point lies in exactly one cell.
``overlap_basis``
    New default only: intensive means over overlays weigh by overlap area. ``legacy_basis=True``
    (the default here) keeps UrbanTrace's basis, the allocation fraction, so results match.

Legacy behaviour kept on purpose, with ``legacy_units=True`` (the default):

- density per m² (UrbanTrace's wire unit), from the UTM area;
- grid rows only for cells that received a value (UrbanTrace's inner merge);
- a centroid computed in the source's own CRS (EPSG:4326 in UrbanTrace);
- ``SumZoning`` on line zones, whose legacy weight is the share of the *zone's* length in each cell
  (target-normalized), through :func:`target_normalized_sum`.

Not supported, with an error naming the reason: ``BinaryContainment`` on MultiPoint sources
(each part's cell got the whole value, replicating it; explode the points or use
``BinaryCentroidContainment``).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from .. import reducers as R
from ..aggregation import aggregate
from ..errors import InputError, UnsupportedError
from ..matching import match
from ..registry import problems, registry
from ..targets import h3_cells

CHANGES = ("boundary_once", "utm_measurement", "missing_not_zero", "h3_index_lookup", "overlap_basis")

#: How each legacy operator maps onto urbanweave: (method or reduction, parameters, notes).
ALLOCATION = {
    "BinaryContainment": ("contain", {}, "boundary points go to one cell; H3 index lookup"),
    "BinaryCentroidContainment": ("centroid", {"point_crs": "source"}, "centroid in the source CRS, as UrbanTrace computes it"),
    "ProportionalAreaWeighted": ("area_overlap", {}, "areas in UTM instead of EPSG:3857"),
    "ProportionalLengthWeighted": ("length_weighted", {}, "lengths in UTM instead of EPSG:3857"),
    "NearestAssignment": ("nearest", {}, "distance ties go to the lowest cell ID"),
    "GaussianKernel": ("gaussian", {"outside": "nearest", "to": "centroid"}, "UrbanTrace's nearest fallback, explicit and reported"),
}
GRID_AGGREGATION = {
    "SumAggregation": ("sum", "allocated_val"),
    "MeanAggregation": ("mean", "source_value"),
    "WeightedMeanAggregation": ("weighted_mean", "aggregated_value"),
    "DensityAggregation": ("density", "aggregated_value"),
    "MajorityAggregation": ("majority", "aggregated_value"),
    "MaxAggregation": ("max", "aggregated_value"),
    "MinAggregation": ("min", "aggregated_value"),
    "LengthWeightedAggregation": ("weighted_mean", "aggregated_value"),
}
ZONING_MAPPING = {
    "CentroidZoning": ("centroid", {"point_crs": "source"}, "point zones use sample (the cell holding each point)"),
    "AreaWeightedZoning": ("area_overlap", {}, "the cells are the sources"),
    "LengthWeightedZoning": ("polygon_to_lines", {}, "length of each line inside each cell"),
}
ZONING_AGGREGATION = {
    "SumZoning": "sum", "WeightedMeanZoning": "weighted_mean", "DensityZoning": "density",
    "MajorityZoning": "majority", "MaxZoning": "max", "MinZoning": "min", "LengthWeightedZoning": "weighted_mean",
}
OPERATORS = {"allocation": ALLOCATION, "grid_aggregation": GRID_AGGREGATION,
             "zoning_mapping": ZONING_MAPPING, "zoning_aggregation": ZONING_AGGREGATION}

_GEOMETRIES = ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]


def geometry_constraints() -> dict:
    """UrbanTrace's ``GEOMETRY_CONSTRAINTS``, generated from the registry."""
    out = {}
    for geom in _GEOMETRIES:
        out[geom] = [legacy for legacy, (method, _, _) in ALLOCATION.items()
                     if not problems(geom, "Polygon", method, source_support="vector", target_support="h3")]
    return out


def operators_payload() -> dict:
    """The body of UrbanTrace's ``/api/operators``, generated from the registry."""
    return {
        "allocation": list(ALLOCATION),
        "grid_aggregation": list(GRID_AGGREGATION),
        "zoning_mapping": list(ZONING_MAPPING),
        "zoning_aggregation": list(ZONING_AGGREGATION),
        "geometry_constraints": geometry_constraints(),
        "registry": registry(),
    }


def _reduction(name: str, column: str | None, alias: str, legacy_basis: bool, value_column: str = "v"):
    basis = {"basis": "allocation_fraction"} if legacy_basis else {}
    if name == "sum":
        return R.sum(value_column, as_=alias)
    if name == "mean":
        return R.mean(value_column, as_=alias)
    if name == "weighted_mean":
        return R.weighted_mean(value_column, as_=alias, **basis)
    if name == "density":
        return R.density(value_column, as_=alias)
    if name == "majority":
        return R.majority(value_column, as_=alias, **basis)
    if name in ("max", "min"):
        return getattr(R, name)(value_column, as_=alias)
    raise UnsupportedError(f"No mapping for {name!r}.")


def _basis_ok(m, legacy_basis):
    return legacy_basis and "allocation_fraction" in m.quantities


def target_normalized_sum(m, values: pd.Series) -> np.ndarray:
    """UrbanTrace's ``SumZoning`` on line zones: Σ (overlap length / zone length) × cell value."""
    p = m.positions
    size, _ = m.target_sizes()  # km
    length_m = size * 1e3
    v = values.to_numpy(dtype=float)[p["src"].to_numpy()]
    contrib = p["overlap_measure"].to_numpy() / length_m[p["tgt"].to_numpy()] * v
    ok = np.isfinite(contrib)
    out = np.bincount(p["tgt"].to_numpy()[ok], weights=contrib[ok], minlength=len(m.targets))
    has = np.bincount(p["tgt"].to_numpy()[ok], minlength=len(m.targets)) > 0
    return np.where(has, out, np.nan)


def run(
    source_gdf: gpd.GeoDataFrame,
    target_column: str,
    resolution: int,
    allocation: str,
    grid_aggregation: str,
    *,
    zones_gdf: gpd.GeoDataFrame | None = None,
    zoning_mapping: str | None = None,
    zoning_aggregation: str | None = None,
    output: str = "grid",
    bandwidth: float | None = None,
    legacy_units: bool = True,
    legacy_basis: bool = True,
) -> dict:
    """Run an UrbanTrace integration on urbanweave, returning UrbanTrace's frames.

    ``output`` is ``"grid"``, ``"zones"``, ``"both"`` or ``"grid_with_zone_values"`` (zone values
    painted back onto the cells). The result is a dict with ``"grid"`` and/or ``"zones"`` frames
    and ``"reports"``, the urbanweave reports of each step.
    """
    if allocation not in ALLOCATION:
        raise InputError(f"Unknown allocation operator {allocation!r}.")
    if grid_aggregation not in GRID_AGGREGATION:
        raise InputError(f"Unknown grid aggregation operator {grid_aggregation!r}.")
    method, params, _ = ALLOCATION[allocation]
    params = dict(params)
    if method == "gaussian":
        params["bandwidth"] = 1000.0 if bandwidth is None else float(bandwidth)
    if method == "contain" and set(source_gdf.geometry.geom_type) & {"MultiPoint"}:
        raise UnsupportedError("BinaryContainment on MultiPoint sources has no urbanweave equivalent: UrbanTrace "
                               "gave every part's cell the whole value. Explode the points or use BinaryCentroidContainment.")

    src = source_gdf
    if "source_id" not in src.columns:
        src = src.copy()
        src["source_id"] = src.index.astype(str)
    src = src.to_crs(4326) if src.crs is not None and not src.crs.equals("EPSG:4326") else src
    values = pd.DataFrame({"source_id": src["source_id"].to_numpy(), "v": src[target_column].to_numpy()})

    cells = h3_cells(tuple(src.total_bounds), resolution)
    m1 = match(src, cells, method, **params)
    red_name, legacy_col = GRID_AGGREGATION[grid_aggregation]
    red = _reduction(red_name, target_column, legacy_col, _basis_ok(m1, legacy_basis))
    grid = aggregate(m1, values, [red])
    reports = {"allocation": grid.attrs.get("urbanweave_report")}
    if red_name == "density" and legacy_units:
        grid[legacy_col] = grid[legacy_col] / 1e6  # per km² -> per m² (UrbanTrace's wire unit)
    size, _ = m1.target_sizes()
    grid = grid.rename(columns={"target_id": "cell_id"})
    grid["area"] = size * 1e6  # m², in UTM
    result: dict = {"reports": reports}

    if output in ("zones", "both", "grid_with_zone_values"):
        if zones_gdf is None or zoning_mapping is None or zoning_aggregation is None:
            raise InputError("Zone output needs zones_gdf, zoning_mapping and zoning_aggregation.")
        zones = zones_gdf
        if "zone_id" not in zones.columns:
            zones = zones.copy()
            zones["zone_id"] = zones.index.astype(str)
        zones = zones.to_crs(4326) if zones.crs is not None and not zones.crs.equals("EPSG:4326") else zones
        zmethod, zparams, _ = ZONING_MAPPING[zoning_mapping]
        point_zones = set(zones.geometry.geom_type) <= {"Point", "MultiPoint"}
        if zoning_mapping == "CentroidZoning" and point_zones:
            zmethod, zparams = "sample", {}
        cell_values = grid[["cell_id", legacy_col, "geometry"]].rename(columns={legacy_col: "x"})
        cell_values = gpd.GeoDataFrame(cell_values, geometry="geometry", crs=4326)
        cell_values.attrs["urbanweave_support"] = {"kind": "h3", "resolution": int(resolution), "id_column": "cell_id"}
        m2 = match(cell_values, zones, zmethod, source_id="cell_id", target_id="zone_id", **zparams)
        zname = ZONING_AGGREGATION[zoning_aggregation]
        if zoning_aggregation == "SumZoning" and zmethod == "polygon_to_lines":
            zv = target_normalized_sum(m2, cell_values["x"])
            zone_out = zones[["zone_id", "geometry"]].copy()
            zone_out["zone_value"] = zv
        else:
            zred = _reduction(zname, "x", "zone_value", _basis_ok(m2, legacy_basis), value_column="x")
            zone_out = aggregate(m2, cell_values, [zred], targets=zones[["zone_id", "geometry"]])
            if zname == "density" and legacy_units:
                zone_out["zone_value"] = zone_out["zone_value"] / 1e6
            reports["zoning"] = zone_out.attrs.get("urbanweave_report")
        if output in ("zones", "both"):
            result["zones"] = zone_out[zone_out["zone_value"].notna()].reset_index(drop=True) if legacy_units else zone_out
        if output == "grid_with_zone_values":
            p = m2.positions
            gamma = p["allocation_fraction"].to_numpy() if "allocation_fraction" in m2.quantities else p["overlap_measure"].to_numpy()
            zvals = pd.to_numeric(zone_out["zone_value"], errors="coerce").to_numpy(dtype=float)[p["tgt"].to_numpy()]
            ok = np.isfinite(zvals)
            n = len(m2.sources)
            num = np.bincount(p["src"].to_numpy()[ok], weights=(gamma * zvals)[ok], minlength=n)
            den = np.bincount(p["src"].to_numpy()[ok], weights=gamma[ok], minlength=n)
            with np.errstate(divide="ignore", invalid="ignore"):
                painted = np.where(den > 0, num / den, np.nan)
            g = grid[["cell_id", "geometry", "area"]].copy()
            g["zone_aggregated_value"] = painted
            result["grid"] = g[g["zone_aggregated_value"].notna()].reset_index(drop=True) if legacy_units else g
            return result
    if output in ("grid", "both"):
        g = grid[["cell_id", "geometry", "area", legacy_col]]
        result["grid"] = g[g[legacy_col].notna()].reset_index(drop=True) if legacy_units else g
    return result
