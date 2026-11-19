"""Rasters and zonal statistics (``pip install urbanweave[raster]``).

:func:`read_raster` describes a raster: a file or open Rasterio dataset, or an in-memory array
with its affine transform, CRS and validity mask. Band selection, nodata and masks, scale, offset,
value kind and units are per band. A dataset urbanweave opened is closed by :meth:`Raster.close`
(or a ``with`` block); a dataset the caller opened stays open.

:func:`zonal_stats` summarizes a raster's cells under polygons, with two rules for which cells a
zone holds:

``cell_coverage`` (default)
    Every cell the zone covers, weighted by the exact fraction covered (exactextract). Supported on
    north-up projected grids with linear units, where coverage fractions are planar areas.
``cell_center``
    Every cell whose center lies in the zone, unweighted (GDAL's rule, as Curio's UHVI and Weather
    nodes and rasterstats use). Also supported on north-up geographic grids, for unweighted
    summaries.

Rotated or skewed grids, and exact area weighting on geographic grids, are refused in this release:
urbanweave never warps a raster implicitly.

Geometry and validity are separate. A zone's *coverage* is the share of its planar area inside the
raster; its *valid coverage* (per band) is the share covered by cells with a valid value. Both use
the zone's full area as denominator. Statistics are accumulated window by window and merged before
ratios are taken, so results do not depend on the window size (``max_cells_in_memory``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely

from . import measure as _measure
from .errors import InputError, MissingDependencyError, UnsupportedError
from .inputs import prepare_layer
from .reducers import Reduction
from .reports import REPORT_ATTR, Report, id_list, plain

try:
    import rasterio
    from rasterio import features as _features
    from rasterio import windows as _windows
    from rasterio.transform import Affine
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise MissingDependencyError("Raster support needs the raster extra: pip install 'urbanweave[raster]'.") from exc

VALUE_KINDS = ("extensive", "intensive", "categorical")
DEFAULT_MAX_CELLS = 4_000_000

#: The registry entry of the raster conversions.
CONVERSIONS = {
    "zonal_stats": {
        "sources": ["Raster"],
        "targets": ["Polygon", "MultiPolygon"],
        "methods": {
            "cell_coverage": {"grids": ["north-up projected (linear units)"], "basis": "coverage fraction × cell area (m²)"},
            "cell_center": {"grids": ["north-up projected", "north-up geographic"], "basis": "selected cells (unweighted)"},
        },
        "reductions": ["count", "weighted_count", "sum", "mean", "weighted_mean", "min", "max", "majority", "shares"],
        "default_aggregation": {"extensive": "sum", "intensive": "weighted_mean", "categorical": "shares"},
        "summary": "Raster cells under each polygon: exact coverage fractions or cell centers.",
    }
}

_SUPPORTED = set(CONVERSIONS["zonal_stats"]["reductions"])


@dataclass
class Band:
    index: int  # 1-based position in the source
    name: str
    nodata: float | None = None
    scale: float = 1.0
    offset: float = 0.0
    value_kind: str | None = None
    units: str | None = None

    def to_dict(self) -> dict:
        return plain({"index": self.index, "name": self.name, "nodata": self.nodata, "scale": self.scale,
                      "offset": self.offset, "value_kind": self.value_kind, "units": self.units})


@dataclass
class Raster:
    """A raster urbanweave can read: a grid (transform, CRS, shape) plus bands."""

    transform: Affine
    crs: pyproj.CRS
    width: int
    height: int
    bands: list[Band]
    dataset: object | None = None  # a Rasterio dataset
    array: np.ndarray | None = None  # (bands, rows, cols)
    valid: np.ndarray | None = None  # (bands, rows, cols) or (rows, cols), True where valid
    owned: bool = False
    stats: dict = field(default_factory=lambda: {"windows_read": 0, "cells_read": 0})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        if self.owned and self.dataset is not None:
            self.dataset.close()
            self.dataset = None

    def band(self, key) -> Band:
        if key is None:
            return self.bands[0]
        for b in self.bands:
            if key == b.index or key == b.name:
                return b
        raise InputError(f"No band {key!r}; bands are {[b.name for b in self.bands]} (or their numbers).")

    @property
    def cell_size(self) -> tuple[float, float]:
        return abs(self.transform.a), abs(self.transform.e)

    def unit_to_m(self) -> float | None:
        """Metres per CRS unit, or None for a geographic CRS."""
        if self.crs.is_geographic:
            return None
        return float(self.crs.axis_info[0].unit_conversion_factor)

    def cell_area_m2(self) -> float:
        u = self.unit_to_m()
        if u is None:
            raise UnsupportedError("Cell areas on a geographic grid vary with latitude; exact area weighting is not supported yet.")
        a, e = self.cell_size
        return a * e * u * u

    def check_north_up(self) -> None:
        t = self.transform
        if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
            raise UnsupportedError(
                "Only north-up grids are supported (no rotation or skew, rows going south). Warp the raster "
                "explicitly first, for example with rasterio.warp.reproject."
            )

    def read(self, band: Band, row0: int, row1: int, col0: int, col1: int) -> tuple[np.ndarray, np.ndarray]:
        """(values, valid) of a window, values scaled and offset, valid False for nodata, masked or NaN."""
        self.stats["windows_read"] += 1
        self.stats["cells_read"] += (row1 - row0) * (col1 - col0)
        if self.dataset is not None:
            w = _windows.Window(col0, row0, col1 - col0, row1 - row0)
            data = self.dataset.read(band.index, window=w, masked=True)
            values = np.ma.getdata(data).astype(float)
            valid = ~np.ma.getmaskarray(data)
        else:
            values = self.array[band.index - 1, row0:row1, col0:col1].astype(float)
            if self.valid is None:
                valid = np.ones(values.shape, dtype=bool)
            elif self.valid.ndim == 2:
                valid = self.valid[row0:row1, col0:col1].copy()
            else:
                valid = self.valid[band.index - 1, row0:row1, col0:col1].copy()
        if band.nodata is not None and not np.isnan(band.nodata):
            valid &= values != band.nodata
        valid &= np.isfinite(values)
        if band.scale != 1.0 or band.offset != 0.0:
            values = values * band.scale + band.offset
        return values, valid

    def describe(self) -> dict:
        code = self.crs.to_epsg()
        return plain({"crs": f"EPSG:{code}" if code else self.crs.to_wkt(), "width": self.width, "height": self.height,
                      "transform": list(self.transform)[:6], "bands": [b.to_dict() for b in self.bands]})


def _per_band(value, n, names):
    if isinstance(value, dict):
        return [value.get(nm, value.get(i + 1)) for i, nm in enumerate(names)]
    return [value] * n


def read_raster(source, *, bands=None, value_kind=None, units=None, nodata=None, transform=None, crs=None,
                mask=None, names=None) -> Raster:
    """Describe a raster for urbanweave (see the module docstring).

    *source* is a path, an open Rasterio dataset, or a NumPy array of shape (rows, cols) or
    (bands, rows, cols) with ``transform`` and ``crs``. Valid cells are those not masked in a masked
    array and, when ``mask`` is given, True in ``mask``. ``bands`` selects bands by number;
    ``value_kind``, ``units`` and ``nodata`` are one value for every band or a dict by band name or
    number.
    """
    if isinstance(source, np.ndarray):
        if transform is None or crs is None:
            raise InputError("An in-memory raster needs transform= and crs=.")
        arr = np.ma.asarray(source)
        data = np.ma.getdata(arr)
        valid = ~np.ma.getmaskarray(arr)
        if data.ndim == 2:
            data, valid = data[None], valid[None]
        if data.ndim != 3:
            raise InputError(f"An in-memory raster must have 2 or 3 dimensions, not {data.ndim}.")
        if mask is not None:
            m = np.asarray(mask, dtype=bool)
            valid = valid & (m if m.ndim == 3 else m[None])
        count = data.shape[0]
        selected = list(bands) if bands is not None else list(range(1, count + 1))
        nm = names or [f"band_{i}" for i in selected]
        nodatas = _per_band(nodata, len(selected), nm)
        kinds = _per_band(value_kind, len(selected), nm)
        unit = _per_band(units, len(selected), nm)
        sub = data[[i - 1 for i in selected]]
        vsub = valid[[i - 1 for i in selected]] if valid.shape[0] == count else valid
        blist = [Band(index=k + 1, name=nm[k], nodata=nodatas[k], value_kind=kinds[k], units=unit[k]) for k in range(len(selected))]
        r = Raster(transform=Affine(*list(transform)[:6]), crs=pyproj.CRS.from_user_input(crs), width=data.shape[2],
                   height=data.shape[1], bands=blist, array=sub, valid=vsub, owned=False)
    else:
        owned = isinstance(source, (str, bytes)) or hasattr(source, "__fspath__")
        ds = rasterio.open(source) if owned else source
        if not hasattr(ds, "read") or not hasattr(ds, "transform"):
            raise InputError(f"Cannot read a raster from {type(source).__name__}.")
        selected = list(bands) if bands is not None else list(range(1, ds.count + 1))
        descriptions = list(ds.descriptions or [None] * ds.count)
        nm = names or [descriptions[i - 1] or f"band_{i}" for i in selected]
        nodatas = _per_band(nodata, len(selected), nm)
        kinds = _per_band(value_kind, len(selected), nm)
        unit = _per_band(units, len(selected), nm)
        ds_units = list(getattr(ds, "units", None) or [None] * ds.count)
        blist = []
        for k, i in enumerate(selected):
            blist.append(Band(index=i, name=nm[k], nodata=nodatas[k] if nodatas[k] is not None else ds.nodatavals[i - 1],
                              scale=float(ds.scales[i - 1]) if ds.scales else 1.0,
                              offset=float(ds.offsets[i - 1]) if ds.offsets else 0.0,
                              value_kind=kinds[k], units=unit[k] or ds_units[i - 1] or None))
        if ds.crs is None and crs is None:
            raise InputError("The raster has no CRS; pass crs=.")
        r = Raster(transform=ds.transform, crs=pyproj.CRS.from_user_input(crs or ds.crs), width=ds.width,
                   height=ds.height, bands=blist, dataset=ds, owned=owned)
    for b in r.bands:
        if b.value_kind is not None and b.value_kind not in VALUE_KINDS:
            raise InputError(f"Unknown value kind {b.value_kind!r}; use one of {', '.join(VALUE_KINDS)}.")
    return r


# ----------------------------------------------------------------------------------------------
# Streaming accumulators: one per reduction and zone, merged window by window.


class _Acc:
    def __init__(self, method: str):
        self.method = method
        self.n = 0
        self.w = 0.0
        self.wv = 0.0
        self.sum_v = 0.0
        self.min = np.inf
        self.max = -np.inf
        self.cats: dict = {}

    def update(self, v: np.ndarray, w: np.ndarray, basis: np.ndarray):
        if len(v) == 0:
            return
        self.n += len(v)
        self.w += float(w.sum())
        self.wv += float((w * v).sum())
        self.sum_v += float(v.sum())
        self.min = min(self.min, float(v.min()))
        self.max = max(self.max, float(v.max()))
        if self.method in ("majority", "shares"):
            uniq, inv = np.unique(v, return_inverse=True)
            sums = np.bincount(inv, weights=basis, minlength=len(uniq))
            for c, s in zip(uniq.tolist(), sums.tolist()):
                self.cats[c] = self.cats.get(c, 0.0) + s


def _zone_windows(rows: np.ndarray, cols: np.ndarray, width: int, max_cells: int):
    """Row bands of the cells' bounding box, each at most *max_cells* cells."""
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    per = max(1, max_cells // max(1, c1 - c0))
    for start in range(r0, r1, per):
        yield start, min(r1, start + per), c0, c1


def zonal_stats(
    raster: Raster,
    zones: gpd.GeoDataFrame,
    reductions: Reduction | Iterable[Reduction],
    *,
    method: str = "cell_coverage",
    zone_id: str | None = None,
    coverage_as: str | None = "coverage",
    max_cells_in_memory: int = DEFAULT_MAX_CELLS,
    full_ids: bool = False,
) -> gpd.GeoDataFrame:
    """Summaries of *raster*'s cells under each zone (see the module docstring).

    Each reduction's ``column`` names a band (its number or name; the first band when omitted).
    The result is a copy of *zones* with a column per reduction and, unless ``coverage_as=None``,
    coverage columns: ``<coverage_as>`` and ``valid_<coverage_as>_<band>`` (exact mode, fractions of
    the zone's area), or ``cells`` and ``valid_cells_<band>`` (center mode, counts).
    """
    if not isinstance(raster, Raster):
        raster = read_raster(raster)
    if isinstance(reductions, Reduction):
        reductions = [reductions]
    reductions = list(reductions)
    if method not in ("cell_coverage", "cell_center"):
        raise InputError("method must be 'cell_coverage' or 'cell_center'.")
    raster.check_north_up()
    if method == "cell_coverage" and raster.unit_to_m() is None:
        raise UnsupportedError(
            "Exact coverage needs a projected grid with linear units; this raster is geographic. Use "
            "method='cell_center' for unweighted summaries, or reproject the raster explicitly."
        )
    layer = prepare_layer(zones, "target", id_column=zone_id, families={"polygon"}, method="zonal_stats")
    aliases = []
    for r in reductions:
        if r.method not in _SUPPORTED:
            raise UnsupportedError(f"zonal_stats does not offer {r.method!r} yet (exact medians and custom reducers need a "
                                   f"memory policy); it offers {', '.join(sorted(_SUPPORTED))}.")
        band = raster.band(r.column)
        kind = band.value_kind
        if kind is not None:
            from .aggregation import REDUCERS

            if kind not in REDUCERS[r.method]["value_kinds"]:
                raise UnsupportedError(f"{r.method} does not suit {kind} values (band {band.name!r}).")
        if r.fill_empty is not None and (r.method not in ("count", "weighted_count", "sum") or r.fill_empty != 0):
            raise InputError("fill_empty=0 is available for count, weighted_count and sum only.")
        if r.where is not None:
            raise UnsupportedError("where is not available for raster reductions; use a mask step first.")
        aliases.append(r.alias)
        for extra in ("weighted_total_as", "valid_measure_as"):
            if r.options.get(extra):
                aliases.append(r.options[extra])
    dupes = sorted({a for a in aliases if aliases.count(a) > 1})
    if dupes:
        raise InputError(f"Output names repeat: {', '.join(dupes)}.")

    geoms = _measure.reproject(layer.geometry, layer.crs, raster.crs)
    n = len(geoms)
    bands_used = []
    for r in reductions:
        b = raster.band(r.column)
        if b not in bands_used:
            bands_used.append(b)

    exact = method == "cell_coverage"
    cell_area = raster.cell_area_m2() if exact else None
    u = raster.unit_to_m()
    zone_area = shapely.area(geoms) * (u * u) if u is not None else np.full(n, np.nan)

    acc = {(z, r_i): _Acc(r.method) for z in range(n) for r_i, r in enumerate(reductions)}
    geo_w = np.zeros(n)
    valid_w = {b.name: np.zeros(n) for b in bands_used}
    valid_n = {b.name: np.zeros(n, dtype=np.int64) for b in bands_used}
    selected = np.zeros(n, dtype=np.int64)
    for z, (rows, cols, w) in _zone_cells(raster, geoms, exact, max_cells_in_memory):
        if len(rows) == 0:
            continue
        selected[z] = len(rows)
        geo_w[z] = float(w.sum())
        for r0, r1, c0, c1 in _zone_windows(rows, cols, raster.width, max_cells_in_memory):
            inside = (rows >= r0) & (rows < r1)
            rr, cc, ww = rows[inside] - r0, cols[inside] - c0, w[inside]
            for b in bands_used:
                values, valid = raster.read(b, r0, r1, c0, c1)
                v, ok = values[rr, cc], valid[rr, cc]
                valid_w[b.name][z] += float(ww[ok].sum())
                valid_n[b.name][z] += int(ok.sum())
                for r_i, r in enumerate(reductions):
                    if raster.band(r.column) is not b:
                        continue
                    basis = ww[ok] * (cell_area if exact else 1.0)
                    acc[(z, r_i)].update(v[ok], ww[ok], basis)

    out_cols: dict[str, pd.Series] = {}
    rep_reductions = []
    for r_i, r in enumerate(reductions):
        b = raster.band(r.column)
        cols = _finish(r, [acc[(z, r_i)] for z in range(n)], selected, exact, cell_area, b)
        out_cols.update(cols)
        rep_reductions.append({"method": r.method, "as": r.alias, "band": b.name,
                               "basis": ("coverage fraction × cell area (m²)" if exact else "selected cells")})
    if coverage_as:
        if exact:
            with np.errstate(divide="ignore", invalid="ignore"):
                out_cols[coverage_as] = _float(np.where(zone_area > 0, geo_w * cell_area / zone_area, np.nan))
                for b in bands_used:
                    name = f"valid_{coverage_as}" if len(bands_used) == 1 else f"valid_{coverage_as}_{b.name}"
                    out_cols[name] = _float(np.where(zone_area > 0, valid_w[b.name] * cell_area / zone_area, np.nan))
        else:
            out_cols["cells"] = pd.Series(pd.array(selected, dtype="Int64"))
            for b in bands_used:
                name = "valid_cells" if len(bands_used) == 1 else f"valid_cells_{b.name}"
                out_cols[name] = pd.Series(pd.array(valid_n[b.name], dtype="Int64"))

    collide = [c for c in out_cols if c in zones.columns]
    if collide:
        raise InputError(f"Output names {', '.join(collide)} are already columns of the zones; rename with as_ or coverage_as.")
    out = zones.copy()
    for name, col in out_cols.items():
        out[name] = col.to_numpy() if not isinstance(col.dtype, pd.api.extensions.ExtensionDtype) else col.array
    no_cells = selected == 0
    outside = np.array([not g.intersects(shapely.box(*_raster_bounds(raster))) for g in geoms])
    any_valid = np.zeros(n, dtype=bool)
    for b in bands_used:
        any_valid |= valid_n[b.name] > 0
    report = Report(
        conversion="zonal_stats",
        method=method,
        raster=raster.describe(),
        measurement={"crs": raster.describe()["crs"], "basis": "planar" if exact else "cell centers",
                     "cell_area_m2": cell_area, "zone_area": "planar, in the raster CRS" if u is not None else "not measured"},
        zones={
            "total": n,
            "outside_raster": id_list(layer.ids[outside], full=full_ids),
            "no_cells": id_list(layer.ids[no_cells & ~outside], full=full_ids),
            "cells_without_valid_values": id_list(layer.ids[~no_cells & ~any_valid], full=full_ids),
        },
        reductions=rep_reductions,
        reads={"windows": raster.stats["windows_read"], "cells": raster.stats["cells_read"],
               "max_cells_in_memory": max_cells_in_memory},
    )
    out.attrs[REPORT_ATTR] = report
    return out


def _float(arr) -> pd.Series:
    arr = np.asarray(arr, dtype=float)
    col = pd.array(arr, dtype="Float64")
    col[np.isnan(arr)] = pd.NA
    return pd.Series(col)


def _finish(r: Reduction, accs: list[_Acc], selected: np.ndarray, exact: bool, cell_area, band: Band) -> dict:
    m = r.method
    n = len(accs)
    has_cells = selected > 0
    if m == "count":
        col = pd.array([a.n for a in accs], dtype="Int64")
        if r.fill_empty is None:
            col[~has_cells] = pd.NA
        return {r.alias: pd.Series(col)}
    if m == "weighted_count":
        col = pd.array([a.w for a in accs], dtype="Float64")
        if r.fill_empty is None:
            col[~has_cells] = pd.NA
        return {r.alias: pd.Series(col)}
    has_valid = np.array([a.n > 0 for a in accs])
    if m == "sum":
        col = pd.array([a.wv if a.n else np.nan for a in accs], dtype="Float64")
        col[~has_valid] = pd.NA
        if r.fill_empty is not None:
            col[~has_cells] = 0.0
        return {r.alias: pd.Series(col)}
    if m == "mean":
        return {r.alias: _float([a.sum_v / a.n if a.n else np.nan for a in accs])}
    if m == "weighted_mean":
        cols = {r.alias: _float([a.wv / a.w if a.w > 0 else np.nan for a in accs])}
        scale = cell_area if exact else 1.0
        if r.options.get("weighted_total_as"):
            cols[r.options["weighted_total_as"]] = _float([a.wv * scale if a.n else np.nan for a in accs])
        if r.options.get("valid_measure_as"):
            cols[r.options["valid_measure_as"]] = _float([a.w * scale if s else np.nan for a, s in zip(accs, selected)])
        return cols
    if m in ("min", "max"):
        return {r.alias: _float([getattr(a, m) if a.n else np.nan for a in accs])}
    if m == "majority":
        res = []
        for a in accs:
            if not a.cats:
                res.append(None)
                continue
            res.append(max(sorted(a.cats.items()), key=lambda kv: kv[1])[0])
        return {r.alias: pd.Series(res, dtype=object)}
    if m == "shares":
        cats = sorted({c for a in accs for c in a.cats})
        cols = {}
        for c in cats:
            vals = []
            for a in accs:
                total = sum(a.cats.values())
                vals.append(a.cats.get(c, 0.0) / total if total > 0 else np.nan)
            label = int(c) if float(c).is_integer() else c
            cols[f"{r.alias}_{label}"] = _float(vals)
        return cols
    raise UnsupportedError(m)


def _raster_bounds(raster: Raster):
    t = raster.transform
    return (t.c, t.f + t.e * raster.height, t.c + t.a * raster.width, t.f)


def _zone_cells(raster: Raster, geoms: np.ndarray, exact: bool, max_cells: int):
    """(zone index, rows, cols, weights) per zone, in batches whose cells fit in *max_cells*.

    Each batch's cells are computed, yielded and dropped before the next, so memory stays bounded
    by the batch, not by the whole set of zones.
    """
    t = raster.transform
    b = shapely.bounds(np.asarray([g if g is not None else shapely.Point() for g in geoms], dtype=object))
    est = np.nan_to_num(((b[:, 2] - b[:, 0]) / abs(t.a) + 2) * ((b[:, 3] - b[:, 1]) / abs(t.e) + 2), nan=0.0)
    start = 0
    n = len(geoms)
    while start < n:
        end, total = start, 0.0
        while end < n and (end == start or total + est[end] <= max_cells):
            total += est[end]
            end += 1
        idx = np.arange(start, end)
        batch = _exact_cells(raster, geoms[idx], max_cells) if exact else _center_cells(raster, geoms[idx])
        for k, cells in zip(idx, batch):
            yield int(k), cells
        start = end


def _exact_cells(raster: Raster, geoms: np.ndarray, max_cells: int):
    """Per zone: (rows, cols, coverage fractions) from exactextract, nodata cells included."""
    from exactextract import exact_extract

    # A geometry-only grid of zeros: exactextract reads it for coverage; band values are read apart,
    # so geometric coverage stays independent of each band's validity.
    grid = _LazyGrid(raster)
    frame = gpd.GeoDataFrame({"_z": np.arange(len(geoms))}, geometry=list(geoms), crs=raster.crs)
    present = np.array([g is not None and not g.is_empty for g in geoms])
    out = [(np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([]))] * len(geoms)
    if not present.any():
        return out
    res = exact_extract(grid, frame[present], ["cell_id(default_value=0)", "coverage(default_value=0)"], output="pandas",
                        max_cells_in_memory=max(max_cells, 1), include_cols=["_z"])
    for z, ids, cov in zip(res["_z"], res["cell_id"], res["coverage"]):
        ids = np.asarray(ids, dtype=np.int64)
        cov = np.asarray(cov, dtype=float)
        keep = cov > 0
        ids, cov = ids[keep], cov[keep]
        out[int(z)] = (ids // raster.width, ids % raster.width, cov)
    return out


class _LazyGrid:
    """A zero-valued raster source of the raster's grid for exactextract, without allocating it whole."""

    def __new__(cls, raster: Raster):
        from exactextract.raster import RasterSource

        class _Grid(RasterSource):
            def __init__(self):
                super().__init__()
                self._r = raster

            def res(self):
                return abs(raster.transform.a), abs(raster.transform.e)

            def extent(self):
                return _raster_bounds(raster)

            def srs_wkt(self):
                return raster.crs.to_wkt()

            def nodata_value(self):
                return None

            def read_window(self, x0, y0, nx, ny):
                return np.zeros((ny, nx), dtype=np.uint8)

        return _Grid()


def _center_cells(raster: Raster, geoms: np.ndarray):
    """Per zone: (rows, cols, ones) for the cells whose center lies in it (GDAL's rule)."""
    out = []
    xmin, ymin, xmax, ymax = _raster_bounds(raster)
    t = raster.transform
    for g in geoms:
        if g is None or g.is_empty:
            out.append((np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([])))
            continue
        gx0, gy0, gx1, gy1 = g.bounds
        c0 = max(0, int(np.floor((gx0 - t.c) / t.a)))
        c1 = min(raster.width, int(np.ceil((gx1 - t.c) / t.a)))
        r0 = max(0, int(np.floor((gy1 - t.f) / t.e)))
        r1 = min(raster.height, int(np.ceil((gy0 - t.f) / t.e)))
        if c1 <= c0 or r1 <= r0:
            out.append((np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([])))
            continue
        wt = t @ Affine.translation(c0, r0)
        sel = _features.geometry_mask([g], out_shape=(r1 - r0, c1 - c0), transform=wt, invert=True, all_touched=False)
        rr, cc = np.nonzero(sel)
        out.append((rr + r0, cc + c0, np.ones(len(rr))))
    return out
