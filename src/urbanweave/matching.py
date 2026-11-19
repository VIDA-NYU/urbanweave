"""Matching: which sources go to which targets, and with what quantities.

:func:`match` relates sources to targets by a named method and returns a :class:`MatchResult`: a
relation keyed by ``(source_id, target_id)`` with the quantities the method provides, the
measurement it used, and a report. Values are attached later, by :func:`urbanweave.aggregate`.

Quantities (columns of :attr:`MatchResult.pairs`):

``allocation_fraction``
    The share of the source's value assigned to the target. Used by ``sum``, ``weighted_count``
    and ``density``. Absent (NaN) for methods that sample rather than allocate.
``overlap_measure``
    Overlap area in m² or length in m. The basis of overlay means, medians and category shares.
``sample_weight``
    A target-side sampling coefficient (1 for a unit sample).
``distance_m``
    Distance in metres for distance methods; the "nearest first" order.

Every method shares these rules:

- Topology (containment, intersections, shared boundaries) is evaluated in the targets' own CRS,
  with sources reprojected into it, so a point on a target's edge stays on it. Areas, lengths and
  distances are measured in one projected CRS per call (:mod:`urbanweave.measure`), reported.
- Candidates come from a spatial index (Shapely's STRtree) or H3's own index, never row loops
  over all pairs.
- Exclusive methods give each source at most one target. Ties (a point on a shared boundary, two
  equally near targets) go to the lowest target ID.
- Inputs are never modified. Excluded and unmatched sources are counted by cause in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from . import measure as _measure
from .errors import InputError, UnsupportedError
from .inputs import LINE, MULTIPOINT, POINT, POLYGON, Layer, prepare_layer
from .reports import Report, id_list, plain
from .targets import h3_resolution, latlng_cells

# The Gaussian keeps a weight of at least 1% of its peak: exp(-d²/2σ²) >= 0.01 within this many σ.
GAUSSIAN_CUTOFF_SIGMAS = float(np.sqrt(2 * np.log(100)))  # about 3.03
_REL_EPS = 1e-12
#: How far a source's summed fractions may stray from 1 before the report calls it partial or
#: over-allocated. Overlays cut in the targets' CRS and measured after projection differ from the
#: whole by up to about 1e-7 (a cut point on an edge does not project exactly onto the edge).
ALLOCATION_TOLERANCE = 1e-6

QUANTITIES = ("allocation_fraction", "overlap_measure", "sample_weight", "distance_m")


# ----------------------------------------------------------------------------------------------
# Method definitions: the one table that dispatch, validation and the registry all read.


@dataclass(frozen=True)
class Param:
    type: str  # "number", "integer", "boolean", "string"
    default: Any = None
    unit: str | None = None
    choices: tuple | None = None
    required: bool = False
    minimum: float | None = None
    exclusive_minimum: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        d = {"type": self.type, "default": self.default}
        if self.unit:
            d["unit"] = self.unit
        if self.choices:
            d["choices"] = list(self.choices)
        if self.required:
            d["required"] = True
        if self.minimum is not None:
            d["exclusive_minimum" if self.exclusive_minimum else "minimum"] = self.minimum
        if self.summary:
            d["summary"] = self.summary
        return d


@dataclass(frozen=True)
class MethodSpec:
    name: str
    sources: frozenset
    targets: frozenset
    quantities: tuple
    basis: str  # the default statistical basis for weighted reductions
    assignment: str  # exclusive, independent, normalized, replicated, sampling
    order: str  # distance, overlap, source
    summary: str
    fn: Callable
    params: dict = field(default_factory=dict)
    source_supports: tuple = ("vector",)
    target_supports: tuple = ("vector",)
    conservation: dict = field(default_factory=dict)
    replaces: tuple = ()

    def check_params(self, given: dict) -> dict:
        unknown = sorted(set(given) - set(self.params))
        if unknown:
            raise InputError(f"{self.name} does not take {', '.join(unknown)}; it takes "
                             f"{', '.join(sorted(self.params)) or 'no parameters'}.")
        out = {}
        for name, p in self.params.items():
            v = given.get(name, p.default)
            if v is None:
                if p.required:
                    raise InputError(f"{self.name} needs {name}.")
                out[name] = None
                continue
            if p.type in ("number", "integer"):
                if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
                    raise InputError(f"{self.name}: {name} must be a number, not {v!r}.")
                if not np.isfinite(v):
                    raise InputError(f"{self.name}: {name} must be finite.")
                if p.type == "integer" and float(v) != int(v):
                    raise InputError(f"{self.name}: {name} must be a whole number.")
                if p.minimum is not None and (v <= p.minimum if p.exclusive_minimum else v < p.minimum):
                    op = ">" if p.exclusive_minimum else ">="
                    raise InputError(f"{self.name}: {name} must be {op} {p.minimum}.")
                v = int(v) if p.type == "integer" else float(v)
            elif p.type == "boolean":
                if not isinstance(v, (bool, np.bool_)):
                    raise InputError(f"{self.name}: {name} must be true or false.")
                v = bool(v)
            elif p.type == "string":
                if p.choices and v not in p.choices:
                    raise InputError(f"{self.name}: {name} must be one of {', '.join(map(str, p.choices))}.")
            out[name] = v
        return out

    def to_dict(self) -> dict:
        from .inputs import GEOJSON_TYPES

        return {
            "sources": [t for f in sorted(self.sources) for t in GEOJSON_TYPES[f]],
            "targets": [t for f in sorted(self.targets) for t in GEOJSON_TYPES[f]],
            "source_supports": list(self.source_supports),
            "target_supports": list(self.target_supports),
            "params": {k: p.to_dict() for k, p in self.params.items()},
            "match_quantities": list(self.quantities),
            "basis": self.basis,
            "assignment": self.assignment,
            "order": self.order,
            "conservation": self.conservation,
            "replaces": list(self.replaces),
            "summary": self.summary,
        }


METHODS: dict[str, MethodSpec] = {}


def _method(**kwargs):
    # H3 cells are polygons: every method that takes polygons takes an H3 support too.
    for role in ("source", "target"):
        families, key = kwargs[f"{role}s"], f"{role}_supports"
        supports = tuple(kwargs.get(key, ("vector",)))
        if POLYGON in families and "h3" not in supports:
            supports = supports + ("h3",)
        kwargs[key] = supports

    def register(fn):
        spec = MethodSpec(fn=fn, **kwargs)
        METHODS[spec.name] = spec
        return fn

    return register


# ----------------------------------------------------------------------------------------------
# The result.


@dataclass
class MatchResult:
    """What :func:`match` returns. ``pairs`` holds IDs; the arrays behind it hold positions."""

    method: str
    params: dict
    spec: MethodSpec
    measurement: _measure.Measurement
    sources: Layer
    targets: Layer
    positions: pd.DataFrame  # src, tgt (positions) and the quantities
    report: Report

    @property
    def pairs(self) -> pd.DataFrame:
        """The relation: ``source_id``, ``target_id`` and the quantities this method provides."""
        p = self.positions
        out = pd.DataFrame({
            "source_id": self.sources.ids.to_numpy()[p["src"].to_numpy()],
            "target_id": self.targets.ids.to_numpy()[p["tgt"].to_numpy()],
        })
        for q in self.spec.quantities:
            out[q] = p[q].to_numpy()
        return out

    @property
    def quantities(self) -> tuple:
        return self.spec.quantities

    def basis_values(self, basis: str | None = None) -> np.ndarray:
        """The statistical basis of each pair: overlap measure, sample weight, fraction or 1."""
        basis = basis or self.spec.basis
        if basis == "unit":
            return np.ones(len(self.positions))
        if basis not in self.spec.quantities:
            raise UnsupportedError(f"{self.method} does not provide {basis}.")
        return self.positions[basis].to_numpy(dtype=float)

    def target_sizes(self) -> tuple[np.ndarray, np.ndarray]:
        """Each target's size in km² (polygons), km (lines) or 1 node (points), and its unit."""
        geoms = _measure.project(self.targets.geometry, self.targets.crs, self.measurement)
        f = self.measurement.unit_to_m
        fam = self.targets.family
        size = np.full(len(geoms), np.nan)
        unit = np.full(len(geoms), None, dtype=object)
        poly = fam == POLYGON
        line = fam == LINE
        pt = (fam == POINT) | (fam == MULTIPOINT)
        if poly.any():
            size[poly] = shapely.area(geoms[poly]) * f * f / 1e6
            unit[poly] = "km2"
        if line.any():
            size[line] = shapely.length(geoms[line]) * f / 1e3
            unit[line] = "km"
        if pt.any():
            size[pt] = 1.0
            unit[pt] = "node"
        return size, unit


# ----------------------------------------------------------------------------------------------
# Helpers.


def _lowest(first: np.ndarray, second: np.ndarray, rank: np.ndarray, key: np.ndarray | None = None):
    """For each distinct value of *first*, the pair with the smallest (*key*, rank of *second*)."""
    if len(first) == 0:
        return np.array([], dtype=np.int64)
    keys = [rank[second]] if key is None else [rank[second], key]
    order = np.lexsort((*keys, first))
    _, idx = np.unique(first[order], return_index=True)
    return order[idx]


def _frame(src, tgt, **quantities) -> pd.DataFrame:
    n = len(src)
    data = {"src": np.asarray(src, dtype=np.int64), "tgt": np.asarray(tgt, dtype=np.int64)}
    for q in QUANTITIES:
        v = quantities.get(q)
        data[q] = np.full(n, np.nan) if v is None else np.asarray(v, dtype=float)
    data["order_key"] = np.asarray(quantities.get("order_key", np.full(n, np.nan)), dtype=float)
    return pd.DataFrame(data)


@dataclass
class _Ctx:
    """What a method sees: eligible positions, and geometry in two CRSs.

    ``src_t``/``tgt_t`` are in the topology CRS (the targets' own); ``src_m``/``tgt_m`` in the
    measurement CRS. Both are eligible-only arrays aligned with ``src_pos``/``tgt_pos``.
    """

    src: Layer
    tgt: Layer
    m: _measure.Measurement
    params: dict
    src_pos: np.ndarray
    tgt_pos: np.ndarray
    src_t: np.ndarray
    tgt_t: np.ndarray
    src_m: np.ndarray
    tgt_m: np.ndarray
    tgt_rank: np.ndarray  # rank of every target position
    src_rank: np.ndarray
    unmatched_causes: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)

    @property
    def topo_crs(self):
        return self.tgt.crs

    def tree_t(self):
        if not hasattr(self, "_tree_t"):
            self._tree_t = STRtree(self.tgt_t)
        return self._tree_t

    def tree_m(self):
        if not hasattr(self, "_tree_m"):
            self._tree_m = STRtree(self.tgt_m)
        return self._tree_m

    def area_m2(self, geoms_t) -> np.ndarray:
        """Area in m² of geometries given in the topology CRS."""
        return shapely.area(_measure.reproject(geoms_t, self.topo_crs, self.m.crs)) * self.m.unit_to_m ** 2

    def length_m(self, geoms_t) -> np.ndarray:
        """Length in m of geometries given in the topology CRS."""
        return shapely.length(_measure.reproject(geoms_t, self.topo_crs, self.m.crs)) * self.m.unit_to_m


def _h3_cells_of(layer: Layer) -> np.ndarray:
    support = layer.support or {}
    column = support.get("id_column") or ("target_id" if "target_id" in layer.frame.columns else None)
    values = layer.frame[column].to_numpy() if column else layer.ids.to_numpy()
    return np.asarray([str(v) for v in values], dtype=object)


def _points_to_polygons(ctx: _Ctx, points: np.ndarray, points_crs):
    """Exclusive assignment of one point per eligible source to covering targets, lowest ID on ties.

    H3 targets use the H3 index of the point; other targets use polygon coverage (boundary
    included) in the targets' CRS, so a point on a shared edge has several candidates and goes to
    the lowest target ID.
    """
    res = h3_resolution(ctx.tgt.support)
    if res is not None:
        cells = latlng_cells(points, points_crs, res)
        lookup = {c: i for i, c in enumerate(_h3_cells_of(ctx.tgt))}
        src_i, tgt_i = [], []
        for i, c in enumerate(cells):
            j = lookup.get(c)
            if j is not None and ctx.tgt.eligible[j]:
                src_i.append(i)
                tgt_i.append(j)
        src_i = np.asarray(src_i, dtype=np.int64)
        tgt_i = np.asarray(tgt_i, dtype=np.int64)
        missing = np.setdiff1d(np.arange(len(points)), src_i)
        if len(missing):
            ctx.unmatched_causes["outside_support"] = ctx.src_pos[missing]
        ctx.notes["lookup"] = "h3_index"
        return ctx.src_pos[src_i], tgt_i
    points = _measure.reproject(points, points_crs, ctx.topo_crs)
    s, t = ctx.tree_t().query(points, predicate="intersects")
    t = ctx.tgt_pos[t]
    pick = _lowest(s, t, ctx.tgt_rank)
    ctx.notes["boundary_ties"] = int((np.bincount(s, minlength=len(points)) > 1).sum()) if len(s) else 0
    missing = np.setdiff1d(np.arange(len(points)), s[pick])
    if len(missing):
        ctx.unmatched_causes["no_target"] = ctx.src_pos[missing]
    return ctx.src_pos[s[pick]], t[pick]


def _nearest(ctx: _Ctx, max_distance):
    tree = ctx.tree_m()
    if max_distance is not None:
        reach = ctx.m.metres_to_crs(max_distance) * (1 + 1e-9) + 1e-9
        (s, t), d = tree.query_nearest(ctx.src_m, max_distance=reach, return_distance=True, all_matches=True)
    else:
        (s, t), d = tree.query_nearest(ctx.src_m, return_distance=True, all_matches=True)
    d_m = d * ctx.m.unit_to_m
    if max_distance is not None:
        keep = d_m <= max_distance * (1 + 1e-12)
        s, t, d_m = s[keep], t[keep], d_m[keep]
    # Equal distances within floating noise count as ties, settled by target ID.
    if len(s):
        best = np.full(len(ctx.src_m), np.inf)
        np.minimum.at(best, s, d_m)
        keep = d_m <= best[s] * (1 + 1e-9) + 1e-9
        s, t, d_m = s[keep], t[keep], d_m[keep]
    t = ctx.tgt_pos[t]
    pick = _lowest(s, t, ctx.tgt_rank)
    ctx.notes["distance_ties"] = int((np.bincount(s, minlength=len(ctx.src_m)) > 1).sum()) if len(s) else 0
    missing = np.setdiff1d(np.arange(len(ctx.src_m)), s[pick])
    if len(missing):
        ctx.unmatched_causes["beyond_max_distance" if max_distance is not None else "no_target"] = ctx.src_pos[missing]
    dist = d_m[pick]
    one = np.ones(len(pick))
    return _frame(ctx.src_pos[s[pick]], t[pick], allocation_fraction=one, sample_weight=one, distance_m=dist,
                  order_key=dist)


def _missing_from(ctx: _Ctx, matched_eligible_idx, cause="no_target"):
    missing = np.setdiff1d(np.arange(len(ctx.src_pos)), np.unique(matched_eligible_idx))
    if len(missing):
        ctx.unmatched_causes[cause] = ctx.src_pos[missing]


def _sequential_pieces(lines: np.ndarray, polys: np.ndarray, pairs_line, pairs_poly, poly_rank):
    """The part of each line inside each polygon, a shared boundary taken once (lowest rank first).

    For each line, its candidate polygons are visited in rank order; each takes the part of the
    line it covers that no earlier polygon took. Returns the pieces, aligned with the pairs.
    """
    pieces = np.empty(len(pairs_line), dtype=object)
    order = np.lexsort((poly_rank, pairs_line))
    start, n = 0, len(order)
    while start < n:
        li = pairs_line[order[start]]
        end = start
        while end < n and pairs_line[order[end]] == li:
            end += 1
        remaining = lines[li]
        for k in order[start:end]:
            poly = polys[pairs_poly[k]]
            pieces[k] = shapely.intersection(remaining, poly)
            remaining = shapely.difference(remaining, poly)
        start = end
    return pieces


# ----------------------------------------------------------------------------------------------
# Methods.

_P_MAX_DIST = Param("number", None, unit="m", minimum=0,
                    summary="Only targets within this distance; farther sources stay unmatched.")
_P_POINT_CRS = Param("string", "measurement", choices=("measurement", "source"),
                     summary="Where the point is computed: the measurement CRS, or the source's own CRS (UrbanTrace's legacy rule).")


def _derived_points(ctx: _Ctx, kind: str):
    """A centroid or point on surface per eligible source, and the CRS it is in."""
    fn = shapely.centroid if kind == "centroid" else shapely.point_on_surface
    if ctx.params.get("point_crs") == "source":
        return fn(ctx.src.geometry[ctx.src_pos]), ctx.src.crs
    return fn(ctx.src_m), ctx.m.crs


@_method(name="contain", sources=frozenset({POINT}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "sample_weight"), basis="unit", assignment="exclusive", order="source",
         target_supports=("vector", "h3"),
         conservation={"scope": "eligible_sources", "excludes": ["no_target", "outside_support"]},
         replaces=("BinaryContainment",),
         summary="Each point goes to the polygon covering it; a point on a shared boundary goes to the lowest target ID. "
                 "H3 targets use the point's H3 cell.")
def _contain(ctx: _Ctx):
    s, t = _points_to_polygons(ctx, ctx.src.geometry[ctx.src_pos], ctx.src.crs)
    one = np.ones(len(s))
    return _frame(s, t, allocation_fraction=one, sample_weight=one)


@_method(name="centroid", sources=frozenset({POINT, MULTIPOINT, LINE, POLYGON}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "sample_weight"), basis="unit", assignment="exclusive", order="source",
         params={"point_crs": _P_POINT_CRS}, target_supports=("vector", "h3"),
         conservation={"scope": "eligible_sources", "excludes": ["no_target", "outside_support"]},
         replaces=("BinaryCentroidContainment", "CentroidZoning (polygon zones)"),
         summary="Each source goes to the polygon covering its geometric centroid, which can lie outside a concave source.")
def _centroid(ctx: _Ctx):
    pts, crs = _derived_points(ctx, "centroid")
    s, t = _points_to_polygons(ctx, pts, crs)
    one = np.ones(len(s))
    return _frame(s, t, allocation_fraction=one, sample_weight=one)


@_method(name="representative_point", sources=frozenset({LINE, POLYGON}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "sample_weight"), basis="unit", assignment="exclusive", order="source",
         params={"point_crs": _P_POINT_CRS}, target_supports=("vector", "h3"),
         conservation={"scope": "eligible_sources", "excludes": ["no_target", "outside_support"]},
         summary="Each source goes to the polygon covering a point guaranteed to lie on the source (point on surface).")
def _representative_point(ctx: _Ctx):
    pts, crs = _derived_points(ctx, "representative_point")
    s, t = _points_to_polygons(ctx, pts, crs)
    one = np.ones(len(s))
    return _frame(s, t, allocation_fraction=one, sample_weight=one)


_NEAREST_KW = dict(quantities=("allocation_fraction", "sample_weight", "distance_m"), basis="unit",
                   assignment="exclusive", order="distance", params={"max_distance": _P_MAX_DIST},
                   conservation={"scope": "eligible_sources", "excludes": ["beyond_max_distance"]})


@_method(name="nearest", sources=frozenset({POINT, MULTIPOINT}), targets=frozenset({POINT, MULTIPOINT, LINE, POLYGON}),
         target_supports=("vector", "h3"), replaces=("NearestAssignment",),
         summary="Each point goes to the nearest target (distance 0 inside a polygon), optionally within max_distance; "
                 "equally near targets go to the lowest target ID.", **_NEAREST_KW)
def _nearest_method(ctx: _Ctx):
    return _nearest(ctx, ctx.params["max_distance"])


@_method(name="nearest_segment", sources=frozenset({POINT, MULTIPOINT}), targets=frozenset({LINE}),
         summary="Each point goes to the nearest line segment (street, sidewalk), optionally within max_distance.",
         **_NEAREST_KW)
def _nearest_segment(ctx: _Ctx):
    return _nearest(ctx, ctx.params["max_distance"])


@_method(name="nearest_node", sources=frozenset({POINT, MULTIPOINT}), targets=frozenset({POINT}),
         summary="Each point goes to the nearest node (intersection), optionally within max_distance.",
         **_NEAREST_KW)
def _nearest_node(ctx: _Ctx):
    return _nearest(ctx, ctx.params["max_distance"])


@_method(name="within_distance", sources=frozenset({POINT, MULTIPOINT, LINE}),
         targets=frozenset({POINT, MULTIPOINT, LINE, POLYGON}),
         quantities=("allocation_fraction", "sample_weight", "distance_m"), basis="allocation_fraction",
         assignment="normalized", order="distance",
         params={"distance": Param("number", None, unit="m", required=True, minimum=0),
                 "split": Param("boolean", True, summary="Split each source equally among its targets (true), or give each target the whole source (false, one-to-many)."),
                 "k": Param("integer", None, minimum=1, summary="Only the k nearest targets.")},
         target_supports=("vector", "h3"),
         conservation={"scope": "eligible_sources", "excludes": ["beyond_distance"], "requires": {"split": True}},
         summary="Each source goes to every target within distance, nearest first: split equally (split=true) "
                 "or whole to each (split=false, which replicates the source).")
def _within_distance(ctx: _Ctx):
    p = ctx.params
    reach = ctx.m.metres_to_crs(p["distance"]) * (1 + 1e-9) + 1e-9
    s, t = ctx.tree_m().query(ctx.src_m, predicate="dwithin", distance=reach)
    d = shapely.distance(ctx.src_m[s], ctx.tgt_m[t]) * ctx.m.unit_to_m
    keep = d <= p["distance"] * (1 + 1e-12)
    s, t, d = s[keep], ctx.tgt_pos[t[keep]], d[keep]
    order = np.lexsort((ctx.tgt_rank[t], d, s))
    s, t, d = s[order], t[order], d[order]
    if p["k"] is not None and len(s):
        first = np.r_[0, np.flatnonzero(np.diff(s)) + 1]
        within = np.arange(len(s)) - np.repeat(first, np.diff(np.r_[first, len(s)]))
        keep = within < p["k"]
        s, t, d = s[keep], t[keep], d[keep]
    counts = np.bincount(s, minlength=len(ctx.src_m))
    frac = 1.0 / counts[s] if p["split"] else np.ones(len(s))
    _missing_from(ctx, s, "beyond_distance")
    ctx.notes["replicating"] = not p["split"]
    return _frame(ctx.src_pos[s], t, allocation_fraction=frac, sample_weight=np.ones(len(s)), distance_m=d, order_key=d)


@_method(name="area_overlap", sources=frozenset({POLYGON}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "overlap_measure"), basis="overlap_measure", assignment="independent",
         order="overlap", source_supports=("vector", "h3"), target_supports=("vector", "h3"),
         conservation={"scope": "covered_share", "condition": "targets partition the sources without overlap"},
         replaces=("ProportionalAreaWeighted", "AreaWeightedZoning"),
         summary="Each target receives its overlap with each source: the area in m² and the share of the source's area.")
def _area_overlap(ctx: _Ctx):
    s, t = ctx.tree_t().query(ctx.src_t, predicate="intersects")
    src_area = ctx.area_m2(ctx.src_t)
    if len(s):
        a = ctx.area_m2(shapely.intersection(ctx.src_t[s], ctx.tgt_t[t]))
        keep = a > _REL_EPS * src_area[s]
        s, t, a = s[keep], t[keep], a[keep]
    else:
        a = np.array([])
    _missing_from(ctx, s)
    return _frame(ctx.src_pos[s], ctx.tgt_pos[t], allocation_fraction=a / src_area[s] if len(s) else a,
                  overlap_measure=a, order_key=-a)


@_method(name="length_weighted", sources=frozenset({LINE}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "overlap_measure"), basis="overlap_measure", assignment="independent",
         order="overlap", target_supports=("vector", "h3"),
         params={"shared_boundary": Param("string", "independent", choices=("independent", "lowest_target_id"),
                                          summary="A line on the shared boundary of two targets counts in both (independent) or only in the lowest target ID.")},
         conservation={"scope": "covered_share", "condition": "targets partition the lines; shared_boundary='lowest_target_id' for lines on boundaries"},
         replaces=("ProportionalLengthWeighted",),
         summary="Each target receives the length of each line inside it, in m, and the share of the line's length.")
def _length_weighted(ctx: _Ctx):
    s, t = ctx.tree_t().query(ctx.src_t, predicate="intersects")
    src_len = ctx.length_m(ctx.src_t)
    if len(s):
        if ctx.params["shared_boundary"] == "lowest_target_id":
            pieces = _sequential_pieces(ctx.src_t, ctx.tgt_t, s, t, ctx.tgt_rank[ctx.tgt_pos[t]])
        else:
            pieces = shapely.intersection(ctx.src_t[s], ctx.tgt_t[t])
        lengths = ctx.length_m(pieces)
        keep = lengths > _REL_EPS * np.maximum(src_len[s], 1.0)
        s, t, lengths = s[keep], t[keep], lengths[keep]
    else:
        lengths = np.array([])
    _missing_from(ctx, s)
    return _frame(ctx.src_pos[s], ctx.tgt_pos[t], allocation_fraction=lengths / src_len[s] if len(s) else lengths,
                  overlap_measure=lengths, order_key=-lengths)


@_method(name="largest_overlap", sources=frozenset({LINE, POLYGON}), targets=frozenset({POLYGON}),
         quantities=("allocation_fraction", "overlap_measure"), basis="unit", assignment="exclusive", order="source",
         target_supports=("vector", "h3"),
         conservation={"scope": "eligible_sources", "excludes": ["no_target"]},
         summary="Each source goes whole to the target covering most of it (area for polygons, length for lines); "
                 "ties go to the lowest target ID.")
def _largest_overlap(ctx: _Ctx):
    s, t = ctx.tree_t().query(ctx.src_t, predicate="intersects")
    pick = np.array([], dtype=np.int64)
    meas = np.array([])
    if len(s):
        inter = shapely.intersection(ctx.src_t[s], ctx.tgt_t[t])
        poly = ctx.src.family[ctx.src_pos[s]] == POLYGON
        meas = np.where(poly, ctx.area_m2(inter), ctx.length_m(inter))
        keep = meas > 0
        s, t, meas = s[keep], t[keep], meas[keep]
    t = ctx.tgt_pos[t]
    if len(s):  # the largest measure first, then the lowest target ID
        order = np.lexsort((ctx.tgt_rank[t], -meas, s))
        _, idx = np.unique(s[order], return_index=True)
        pick = order[idx]
    _missing_from(ctx, s[pick])
    return _frame(ctx.src_pos[s[pick]], t[pick], allocation_fraction=np.ones(len(pick)), overlap_measure=meas[pick])


@_method(name="polygon_to_lines", sources=frozenset({POLYGON}), targets=frozenset({LINE}),
         quantities=("overlap_measure", "sample_weight"), basis="overlap_measure", assignment="sampling", order="overlap",
         source_supports=("vector", "h3"),
         params={"shared_boundary": Param("string", "independent", choices=("independent", "lowest_source_id"),
                                          summary="A line on the shared boundary of two source polygons counts in both (independent) or only in the lowest source ID.")},
         conservation={"scope": "none", "note": "samples source values onto lines; for intensive and categorical values"},
         replaces=("LengthWeightedZoning",),
         summary="Each line receives the values of the polygons it crosses, weighted by the length of line inside each "
                 "(for intensive and categorical values).")
def _polygon_to_lines(ctx: _Ctx):
    tree = STRtree(ctx.src_t)
    t, s = tree.query(ctx.tgt_t, predicate="intersects")  # t: target index, s: source index
    if len(t):
        if ctx.params["shared_boundary"] == "lowest_source_id":
            pieces = _sequential_pieces(ctx.tgt_t, ctx.src_t, t, s, ctx.src_rank[ctx.src_pos[s]])
        else:
            pieces = shapely.intersection(ctx.tgt_t[t], ctx.src_t[s])
        lengths = ctx.length_m(pieces)
        keep = lengths > 0
        s, t, lengths = s[keep], t[keep], lengths[keep]
    else:
        lengths = np.array([])
    _missing_from(ctx, s, "no_line")
    return _frame(ctx.src_pos[s], ctx.tgt_pos[t], overlap_measure=lengths, sample_weight=np.ones(len(s)),
                  order_key=-lengths)


@_method(name="gaussian", sources=frozenset({POINT, MULTIPOINT, LINE}), targets=frozenset({POINT, LINE, POLYGON}),
         quantities=("allocation_fraction", "distance_m"), basis="allocation_fraction", assignment="normalized",
         order="distance", target_supports=("vector", "h3"),
         params={"bandwidth": Param("number", None, unit="m", required=True, minimum=0, exclusive_minimum=True,
                                    summary="The Gaussian's standard deviation σ."),
                 "outside": Param("string", "drop", choices=("drop", "nearest"),
                                  summary="A source with no target within reach (about 3σ) is dropped, or goes whole to its nearest target (reported)."),
                 "to": Param("string", "centroid", choices=("centroid", "geometry"),
                             summary="Measure distance to each target's centroid (UrbanTrace's rule) or to its geometry."),
                 "max_distance": Param("number", None, unit="m", minimum=0,
                                       summary="With outside='nearest', the farthest a fallback may go.")},
         conservation={"scope": "matched_sources", "excludes": ["beyond_cutoff"]},
         replaces=("GaussianKernel",),
         summary="Each source spreads over targets by a Gaussian of distance in metres (σ = bandwidth), cut at 1% of "
                 "the peak (about 3σ) and normalized to sum to 1 per source.")
def _gaussian(ctx: _Ctx):
    p = ctx.params
    sigma = p["bandwidth"]
    anchors = shapely.centroid(ctx.tgt_m) if p["to"] == "centroid" else ctx.tgt_m
    tree = STRtree(anchors)
    cutoff = GAUSSIAN_CUTOFF_SIGMAS * sigma
    s, t = tree.query(ctx.src_m, predicate="dwithin", distance=ctx.m.metres_to_crs(cutoff) * (1 + 1e-9))
    d = shapely.distance(ctx.src_m[s], anchors[t]) * ctx.m.unit_to_m
    w = np.exp(-(d ** 2) / (2 * sigma ** 2))
    keep = w >= 0.01
    s, t, d, w = s[keep], t[keep], d[keep], w[keep]
    missing = np.setdiff1d(np.arange(len(ctx.src_m)), s)
    fallback = 0
    if len(missing) and p["outside"] == "nearest":
        kw = {}
        if p["max_distance"] is not None:
            kw["max_distance"] = ctx.m.metres_to_crs(p["max_distance"]) * (1 + 1e-9) + 1e-9
        (ms, mt), md = tree.query_nearest(ctx.src_m[missing], return_distance=True, all_matches=True, **kw)
        md = md * ctx.m.unit_to_m
        if p["max_distance"] is not None:
            ok = md <= p["max_distance"] * (1 + 1e-12)
            ms, mt, md = ms[ok], mt[ok], md[ok]
        pick = _lowest(ms, ctx.tgt_pos[mt], ctx.tgt_rank)
        ms, mt, md = missing[ms[pick]], mt[pick], md[pick]
        fallback = len(ms)
        s, t, d, w = np.r_[s, ms], np.r_[t, mt], np.r_[d, md], np.r_[w, np.ones(len(ms))]
        missing = np.setdiff1d(missing, ms)
    if len(missing):
        ctx.unmatched_causes["beyond_cutoff" if p["outside"] == "drop" else "beyond_max_distance"] = ctx.src_pos[missing]
    totals = np.bincount(s, weights=w, minlength=len(ctx.src_m))
    frac = w / totals[s] if len(s) else w
    ctx.notes["fallbacks"] = fallback
    ctx.notes["cutoff_m"] = cutoff
    return _frame(ctx.src_pos[s], ctx.tgt_pos[t], allocation_fraction=frac, distance_m=d, order_key=d)


@_method(name="sample", sources=frozenset({POLYGON}), targets=frozenset({POINT}),
         quantities=("sample_weight",), basis="sample_weight", assignment="sampling", order="source",
         source_supports=("vector", "h3"),
         conservation={"scope": "none", "note": "copies source values to points; one source can reach several points"},
         replaces=("CentroidZoning (point zones)",),
         summary="Each point receives the value of the cell or polygon containing it (H3 sources use the point's cell; "
                 "a point on a shared boundary takes the lowest source ID).")
def _sample(ctx: _Ctx):
    res = h3_resolution(ctx.src.support)
    if res is not None:
        cells = latlng_cells(ctx.tgt.geometry[ctx.tgt_pos], ctx.tgt.crs, res)
        lookup = dict(zip(_h3_cells_of(ctx.src)[ctx.src_pos], ctx.src_pos))
        tg, sp = [], []
        for i, c in enumerate(cells):
            pos = lookup.get(c)
            if pos is not None:
                tg.append(i)
                sp.append(pos)
        tg = np.asarray(tg, dtype=np.int64)
        sp = np.asarray(sp, dtype=np.int64)
        ctx.notes["lookup"] = "h3_index"
    else:
        tree = STRtree(ctx.src_t)
        tq, sq = tree.query(ctx.tgt_t, predicate="intersects")
        sp_all = ctx.src_pos[sq]
        pick = _lowest(tq, sp_all, ctx.src_rank)
        tg, sp = tq[pick], sp_all[pick]
    ctx.notes["targets_without_source"] = int(len(np.setdiff1d(np.arange(len(ctx.tgt_pos)), tg)))
    missing = np.setdiff1d(ctx.src_pos, np.unique(sp))
    if len(missing):
        ctx.unmatched_causes["no_point"] = missing
    return _frame(sp, ctx.tgt_pos[tg], sample_weight=np.ones(len(tg)))


# ----------------------------------------------------------------------------------------------
# The entry point.


def _support_kind(layer: Layer) -> str:
    return "h3" if h3_resolution(layer.support) is not None else "vector"


def match(
    sources,
    targets,
    method: str,
    *,
    source_id: str | None = None,
    target_id: str | None = None,
    crs=None,
    full_ids: bool = False,
    **params,
) -> MatchResult:
    """Match *sources* to *targets* by *method* (see :data:`METHODS` or :func:`urbanweave.registry`).

    ``source_id`` and ``target_id`` name the ID columns (see :mod:`urbanweave.inputs` for the rule
    when they are omitted). ``crs`` fixes the measurement CRS; otherwise the local UTM zone of the
    study area is used. Method parameters are keyword arguments, checked against the method.
    """
    spec = METHODS.get(method)
    if spec is None:
        raise UnsupportedError(f"Unknown matching method {method!r}; known: {', '.join(sorted(METHODS))}.")
    checked = spec.check_params(params)
    src = prepare_layer(sources, "source", id_column=source_id, families=set(spec.sources), method=method)
    tgt = prepare_layer(targets, "target", id_column=target_id, families=set(spec.targets), method=method)
    if _support_kind(src) not in spec.source_supports:
        raise UnsupportedError(f"{method} does not accept {_support_kind(src)} sources.")
    if _support_kind(tgt) not in spec.target_supports:
        raise UnsupportedError(f"{method} does not accept {_support_kind(tgt)} targets.")
    if method == "contain" and MULTIPOINT in src.families():
        raise UnsupportedError("contain takes single points; for multipoints use centroid or nearest.")

    src_pos = np.flatnonzero(src.eligible)
    tgt_pos = np.flatnonzero(tgt.eligible)
    m = _measure.resolve([(src.geometry[src_pos], src.crs), (tgt.geometry[tgt_pos], tgt.crs)], crs=crs)
    ctx = _Ctx(
        src=src, tgt=tgt, m=m, params=checked,
        src_pos=src_pos, tgt_pos=tgt_pos,
        src_t=_measure.reproject(src.geometry[src_pos], src.crs, tgt.crs),
        tgt_t=tgt.geometry[tgt_pos],
        src_m=_measure.project(src.geometry[src_pos], src.crs, m),
        tgt_m=_measure.project(tgt.geometry[tgt_pos], tgt.crs, m),
        tgt_rank=tgt.rank(), src_rank=src.rank(),
    )
    if len(src_pos) == 0 or len(tgt_pos) == 0:
        positions = _frame([], [])
        if len(src_pos):
            ctx.unmatched_causes["no_target"] = src_pos
    else:
        positions = spec.fn(ctx)
    positions = positions.sort_values(["tgt", "src"], kind="stable").reset_index(drop=True)
    report = _match_report(spec, checked, m, src, tgt, positions, ctx, full_ids)
    return MatchResult(method=method, params=checked, spec=spec, measurement=m, sources=src, targets=tgt,
                       positions=positions, report=report)


def _match_report(spec, params, m, src, tgt, positions, ctx, full_ids) -> Report:
    n_src = len(src)
    matched_src = np.unique(positions["src"].to_numpy()) if len(positions) else np.array([], dtype=np.int64)
    excluded = {cause: id_list(src.ids[pos], full=full_ids) for cause, pos in src.excluded.items()}
    unmatched = {cause: id_list(src.ids[pos], full=full_ids) for cause, pos in ctx.unmatched_causes.items()}
    report = Report(
        method=spec.name,
        params=plain(params),
        measurement=m.to_dict(),
        assignment=spec.assignment,
        sources={
            "total": n_src,
            "eligible": int(src.eligible.sum()),
            "excluded": excluded,
            "matched": int(len(matched_src)),
            "unmatched": unmatched,
        },
        targets={
            "total": len(tgt),
            "matched": int(positions["tgt"].nunique()) if len(positions) else 0,
        },
        pairs=int(len(positions)),
    )
    if "allocation_fraction" in spec.quantities and len(positions):
        per_source = positions.groupby("src")["allocation_fraction"].sum()
        tol = ALLOCATION_TOLERANCE
        report["allocation"] = {
            "partial_sources": int((per_source < 1 - tol).sum()),
            "over_allocated_sources": int((per_source > 1 + tol).sum()),
            "tolerance": tol,
        }
        if spec.assignment == "independent" and (per_source > 1 + tol).any():
            report["allocation"]["union_coverage"] = "not measured: targets overlap, so pairwise fractions double count"
    for key, value in ctx.notes.items():
        report.setdefault("notes", {})[key] = plain(value)
    return report
