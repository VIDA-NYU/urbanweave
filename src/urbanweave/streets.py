"""Streets: OpenStreetMap street and intersection targets, and line steps for street workflows.

Targets (``pip install urbanweave[osm]`` for OSMnx graphs):

- :func:`street_segments` turns an OSMnx graph into street segments, either one row per directed
  edge (``representation="directed"``, the topology routing uses) or one row per *physical*
  segment (``"physical"``, for lengths and exposure): opposite-direction edges that represent the same
  piece of street (same OSM way, reversed geometry) become one row, while distinct carriageways and
  parallel edges stay separate. Graph keys are kept (``u``, ``v``, ``key``, and ``edges`` listing
  every directed edge a physical segment stands for).
- :func:`intersections` gives the graph's nodes with at least ``min_degree`` incident physical
  segments (3 by default).
- :func:`osm_streets` and :func:`osm_intersections` build them from a saved graph (GraphML) or, live,
  from a place name or box through OSMnx.

Line steps (no OSMnx needed):

- :func:`split_lines` cuts lines at zone boundaries into pieces with stable IDs
  (``<line_id>|<zone_id>``); a stretch of line on the shared boundary of two zones goes to the lowest
  zone ID, so each metre of line belongs to at most one zone.
- :func:`along_lines` samples a raster along lines: the length of each line inside each cell,
  weighted means by valid length, and the valid length itself. A stretch of line lying exactly on a
  cell boundary belongs to one cell: each sub-segment goes to the cell holding its midpoint, cells
  being half-open (west and north edges included).
- :func:`reduce` groups rows by a key (such as ``zone_id``) onto targets with ``ratio_of_sums``
  (Σ numerator / Σ denominator over rows where both are valid) and plain sums.
"""

from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely
from shapely.geometry import LineString, Point

from . import measure as _measure
from .errors import InputError, MissingDependencyError, UnsupportedError
from .inputs import SUPPORT_ATTR, float_array, prepare_layer, resolve_ids
from .reducers import Reduction
from .reports import REPORT_ATTR, Report, id_list, plain

CONVERSIONS = {
    "split_lines": {"sources": ["LineString", "MultiLineString"], "targets": ["Polygon", "MultiPolygon"],
                    "params": {"shared_boundary": {"type": "string", "default": "lowest_target_id"}},
                    "summary": "Lines cut at zone boundaries into pieces with stable IDs; a boundary stretch goes to the lowest zone ID."},
    "along_lines": {"sources": ["Raster"], "targets": ["LineString", "MultiLineString"],
                    "reductions": ["weighted_mean", "min", "max", "count"],
                    "default_aggregation": {"intensive": "weighted_mean"},
                    "summary": "Raster values along lines, weighted by the valid length of line in each cell."},
    "reduce": {"reductions": ["ratio_of_sums", "sum"],
               "summary": "Rows grouped by a key onto targets: ratios of summed components, or sums."},
}


def _require_osmnx():
    try:
        import osmnx as ox  # noqa: F401

        return ox
    except ImportError as exc:
        raise MissingDependencyError("Street targets need the osm extra: pip install 'urbanweave[osm]'.") from exc


def _edge_geometry(G, u, v, data):
    geom = data.get("geometry")
    if geom is None:
        nu, nv = G.nodes[u], G.nodes[v]
        geom = LineString([(nu["x"], nu["y"]), (nv["x"], nv["y"])])
    return geom


def _same_way(a, b) -> bool:
    oa, ob = a.get("osmid"), b.get("osmid")
    return (oa == ob) if not isinstance(oa, list) and not isinstance(ob, list) else sorted(map(str, np.atleast_1d(oa))) == sorted(map(str, np.atleast_1d(ob)))


def street_segments(G, *, representation: str = "physical") -> gpd.GeoDataFrame:
    """Street segments of an OSMnx graph (see the module docstring)."""
    if representation not in ("physical", "directed"):
        raise InputError("representation must be 'physical' or 'directed'.")
    crs = G.graph.get("crs", "EPSG:4326")
    rows = []
    seen = set()
    for u, v, k, data in G.edges(keys=True, data=True):
        if (u, v, k) in seen:
            continue
        geom = _edge_geometry(G, u, v, data)
        edges = [(u, v, k)]
        seen.add((u, v, k))
        if representation == "physical" and G.has_edge(v, u):
            for k2, d2 in G.get_edge_data(v, u).items():
                if (v, u, k2) in seen:
                    continue
                g2 = _edge_geometry(G, v, u, d2)
                if _same_way(data, d2) and shapely.equals_exact(geom, g2.reverse(), tolerance=1e-9):
                    edges.append((v, u, k2))
                    seen.add((v, u, k2))
                    break
        a, b = (u, v) if (len(edges) == 1 or str(u) <= str(v)) else (v, u)
        if a != u:
            geom = geom.reverse()
            key = edges[1][2]
        else:
            key = k
        osmid = data.get("osmid")
        rows.append({
            "target_id": f"{a}-{b}-{key}",
            "u": a, "v": b, "key": key,
            "osmid": ",".join(map(str, osmid)) if isinstance(osmid, list) else osmid,
            "name": ",".join(map(str, data["name"])) if isinstance(data.get("name"), list) else data.get("name"),
            "highway": ",".join(map(str, data["highway"])) if isinstance(data.get("highway"), list) else data.get("highway"),
            "oneway": bool(data.get("oneway", False)),
            "edges": ";".join(f"{x}-{y}-{z}" for x, y, z in edges),
            "geometry": geom,
        })
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    if len(frame):
        m = _measure.resolve([(frame.geometry.to_numpy(), frame.crs)])
        frame["length_m"] = shapely.length(_measure.project(frame.geometry.to_numpy(), frame.crs, m)) * m.unit_to_m
    frame.attrs[SUPPORT_ATTR] = {"kind": "osm_streets", "representation": representation}
    return frame


def intersections(G, *, min_degree: int = 3) -> gpd.GeoDataFrame:
    """Nodes with at least *min_degree* incident physical street segments (a self-loop counts twice)."""
    segments = street_segments(G, representation="physical")
    degree: dict = {}
    for u, v in zip(segments["u"], segments["v"]):
        degree[u] = degree.get(u, 0) + 1
        degree[v] = degree.get(v, 0) + 1
    rows = [{"target_id": n, "degree": d, "geometry": Point(G.nodes[n]["x"], G.nodes[n]["y"])}
            for n, d in degree.items() if d >= min_degree]
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=G.graph.get("crs", "EPSG:4326"))
    frame.attrs[SUPPORT_ATTR] = {"kind": "osm_intersections", "min_degree": min_degree}
    return frame


def _graph(place=None, bbox=None, graphml=None, network_type="drive"):
    ox = _require_osmnx()
    if graphml is not None:
        return ox.load_graphml(graphml)
    if place is not None:
        return ox.graph_from_place(place, network_type=network_type, simplify=True)
    if bbox is not None:
        return ox.graph_from_bbox(tuple(bbox), network_type=network_type, simplify=True)
    raise InputError("Give a saved graph (graphml=), a place name, or a bbox.")


def osm_streets(*, place=None, bbox=None, graphml=None, network_type: str = "drive",
                representation: str = "physical") -> gpd.GeoDataFrame:
    """Street segments from a saved GraphML graph or, live, from OSM (OSMnx)."""
    out = street_segments(_graph(place, bbox, graphml, network_type), representation=representation)
    out.attrs[SUPPORT_ATTR].update({"place": place, "bbox": bbox, "graphml": str(graphml) if graphml else None,
                                    "network_type": network_type})
    return out


def osm_intersections(*, place=None, bbox=None, graphml=None, network_type: str = "drive",
                      min_degree: int = 3) -> gpd.GeoDataFrame:
    """Intersections from a saved GraphML graph or, live, from OSM (OSMnx)."""
    return intersections(_graph(place, bbox, graphml, network_type), min_degree=min_degree)


# ----------------------------------------------------------------------------------------------
# split_lines


def split_lines(lines: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, *, line_id: str | None = None,
                zone_id: str | None = None, shared_boundary: str = "lowest_target_id") -> gpd.GeoDataFrame:
    """Lines cut at zone boundaries: one piece per (line, zone) with ``piece_id``, ``line_id``,
    ``zone_id``, its geometry (in the zones' CRS) and ``length_m``. Parts of lines outside every zone
    are dropped and reported."""
    from .matching import _sequential_pieces

    if shared_boundary not in ("lowest_target_id", "independent"):
        raise InputError("shared_boundary must be 'lowest_target_id' or 'independent'.")
    src = prepare_layer(lines, "source", id_column=line_id, families={"line"}, method="split_lines")
    tgt = prepare_layer(zones, "target", id_column=zone_id, families={"polygon"}, method="split_lines")
    sp = np.flatnonzero(src.eligible)
    lines_t = _measure.reproject(src.geometry[sp], src.crs, tgt.crs)
    tree = shapely.STRtree(tgt.geometry)
    s, t = tree.query(lines_t, predicate="intersects")
    if shared_boundary == "lowest_target_id":
        pieces = _sequential_pieces(lines_t, tgt.geometry, s, t, tgt.rank()[t])
    else:
        pieces = shapely.intersection(lines_t[s], tgt.geometry[t])
    pieces = np.array([_linear_part(p) for p in pieces], dtype=object)
    m = _measure.resolve([(lines_t, tgt.crs), (tgt.geometry, tgt.crs)])
    length = shapely.length(_measure.reproject(pieces, tgt.crs, m.crs)) * m.unit_to_m if len(pieces) else np.array([])
    keep = length > 0
    s, t, pieces, length = s[keep], t[keep], pieces[keep], length[keep]
    lid = src.ids.to_numpy()[sp[s]]
    zid = tgt.ids.to_numpy()[t]
    out = gpd.GeoDataFrame({"piece_id": [f"{a}|{b}" for a, b in zip(lid, zid)], "line_id": lid, "zone_id": zid,
                            "length_m": length}, geometry=list(pieces), crs=tgt.crs)
    total = shapely.length(_measure.reproject(lines_t, tgt.crs, m.crs)) * m.unit_to_m
    out.attrs[SUPPORT_ATTR] = {"kind": "line_pieces", "id_column": "piece_id"}
    out.attrs[REPORT_ATTR] = Report(conversion="split_lines", shared_boundary=shared_boundary,
                                    measurement=m.to_dict(), lines=int(len(sp)), pieces=int(len(out)),
                                    length_m={"lines": float(total.sum()), "pieces": float(length.sum()),
                                              "outside_zones": float(total.sum() - length.sum())},
                                    excluded={c: id_list(src.ids[p]) for c, p in src.excluded.items()})
    return out


def _linear_part(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type in ("LineString", "MultiLineString"):
        return shapely.line_merge(geom) if geom.geom_type == "MultiLineString" else geom
    parts = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("LineString", "MultiLineString")]
    if not parts:
        return shapely.LineString()
    return shapely.line_merge(shapely.union_all(parts))


# ----------------------------------------------------------------------------------------------
# along_lines


def _cell_pieces(px: np.ndarray, xy: np.ndarray):
    """Split a polyline at every grid line; *px* holds its vertices in pixel coordinates (col, row as
    floats), *xy* the same vertices in CRS units.

    Returns (col, row, length in CRS units) per piece, each piece owned by the cell holding its
    midpoint (the floor of the midpoint's pixel coordinates: west and north edges included).
    """
    out_c, out_r, out_len = [], [], []
    for (x0, y0), (x1, y1), (a0, b0), (a1, b1) in zip(px[:-1], px[1:], xy[:-1], xy[1:]):
        dx, dy = x1 - x0, y1 - y0
        ts = [0.0, 1.0]
        if dx != 0:
            ts += [(gx - x0) / dx for gx in range(int(np.floor(min(x0, x1))) + 1, int(np.ceil(max(x0, x1))))]
        if dy != 0:
            ts += [(gy - y0) / dy for gy in range(int(np.floor(min(y0, y1))) + 1, int(np.ceil(max(y0, y1))))]
        ts = np.unique(np.clip(ts, 0, 1))
        seg = np.hypot(a1 - a0, b1 - b0)
        for ta, tb in zip(ts[:-1], ts[1:]):
            if tb <= ta:
                continue
            tm = (ta + tb) / 2
            out_c.append(int(np.floor(x0 + tm * dx)))
            out_r.append(int(np.floor(y0 + tm * dy)))
            out_len.append((tb - ta) * seg)
    return np.asarray(out_c, dtype=np.int64), np.asarray(out_r, dtype=np.int64), np.asarray(out_len, dtype=float)


def along_lines(raster, lines: gpd.GeoDataFrame, reductions: Reduction | Iterable[Reduction], *,
                line_id: str | None = None, coverage_as: str | None = "valid_fraction") -> gpd.GeoDataFrame:
    """Raster values along each line, by the length of line in each cell (see the module docstring).

    Reductions: ``weighted_mean`` (by valid length, with ``weighted_total_as`` and
    ``valid_measure_as`` giving Σ value × metres and the valid metres), ``min``, ``max``, ``count``
    (cells with a valid value). Each reduction's ``column`` names a band. The result is a copy of
    *lines* with one column per output and ``<coverage_as>``: the valid length of the first band
    used, as a share of the line's length.
    """
    from .raster import Raster, read_raster

    if not isinstance(raster, Raster):
        raster = read_raster(raster)
    raster.check_north_up()
    u = raster.unit_to_m()
    if u is None:
        raise UnsupportedError("along_lines measures length in the raster's CRS, which must be projected; "
                               "reproject the raster explicitly.")
    if isinstance(reductions, Reduction):
        reductions = [reductions]
    reductions = list(reductions)
    for r in reductions:
        if r.method not in ("weighted_mean", "min", "max", "count"):
            raise UnsupportedError(f"along_lines offers weighted_mean, min, max and count, not {r.method!r}.")
    layer = prepare_layer(lines, "target", id_column=line_id, families={"line"}, method="along_lines")
    geoms = _measure.reproject(layer.geometry, layer.crs, raster.crs)
    inv = ~raster.transform
    n = len(geoms)
    bands = []
    for r in reductions:
        b = raster.band(r.column)
        if b not in bands:
            bands.append(b)
    total_len = np.zeros(n)
    acc = {b.name: {"wv": np.zeros(n), "w": np.zeros(n), "min": np.full(n, np.inf), "max": np.full(n, -np.inf),
                    "n": np.zeros(n, dtype=np.int64)} for b in bands}
    for z, g in enumerate(geoms):
        if g is None or g.is_empty:
            continue
        pieces = []
        for part in (list(g.geoms) if g.geom_type == "MultiLineString" else [g]):
            xy = np.asarray(part.coords)[:, :2]
            px = np.column_stack(inv * (xy[:, 0], xy[:, 1]))
            pieces.append(_cell_pieces(px, xy))
        c = np.concatenate([p[0] for p in pieces])
        rr = np.concatenate([p[1] for p in pieces])
        ll = np.concatenate([p[2] for p in pieces]) * u
        total_len[z] = ll.sum()
        inside = (c >= 0) & (c < raster.width) & (rr >= 0) & (rr < raster.height)
        c, rr, ll = c[inside], rr[inside], ll[inside]
        if len(c) == 0:
            continue
        r0, r1, c0, c1 = int(rr.min()), int(rr.max()) + 1, int(c.min()), int(c.max()) + 1
        for b in bands:
            values, valid = raster.read(b, r0, r1, c0, c1)
            v, ok = values[rr - r0, c - c0], valid[rr - r0, c - c0]
            a = acc[b.name]
            a["wv"][z] += float((ll[ok] * v[ok]).sum())
            a["w"][z] += float(ll[ok].sum())
            if ok.any():
                a["min"][z] = min(a["min"][z], float(v[ok].min()))
                a["max"][z] = max(a["max"][z], float(v[ok].max()))
                a["n"][z] += int(len(set(zip(rr[ok].tolist(), c[ok].tolist()))))
    out = lines.copy()
    for r in reductions:
        a = acc[raster.band(r.column).name]
        if r.method == "weighted_mean":
            with np.errstate(divide="ignore", invalid="ignore"):
                out[r.alias] = _f(np.where(a["w"] > 0, a["wv"] / a["w"], np.nan))
            if r.options.get("weighted_total_as"):
                out[r.options["weighted_total_as"]] = _f(np.where(a["w"] > 0, a["wv"], np.nan))
            if r.options.get("valid_measure_as"):
                out[r.options["valid_measure_as"]] = _f(a["w"])
        elif r.method in ("min", "max"):
            arr = a[r.method]
            out[r.alias] = _f(np.where(np.isfinite(arr), arr, np.nan))
        else:
            out[r.alias] = pd.array(a["n"], dtype="Int64")
    if coverage_as and bands:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[coverage_as] = _f(np.where(total_len > 0, acc[bands[0].name]["w"] / total_len, np.nan))
    out.attrs[REPORT_ATTR] = Report(conversion="along_lines", raster=raster.describe(),
                                    ownership="each sub-segment goes to the cell holding its midpoint (west and north edges included)",
                                    lines=n, length_m=float(total_len.sum()),
                                    valid_length_m={b.name: float(acc[b.name]["w"].sum()) for b in bands})
    return out


def _f(arr):
    arr = np.asarray(arr, dtype=float)
    col = pd.array(arr, dtype="Float64")
    col[np.isnan(arr)] = pd.NA
    return col


# ----------------------------------------------------------------------------------------------
# reduce


def ratio_of_sums(numerator: str, denominator: str, *, as_: str) -> Reduction:
    """Σ numerator / Σ denominator over rows where both are valid; missing when that Σ is 0."""
    return Reduction("ratio_of_sums", None, as_, None, None, {"numerator": numerator, "denominator": denominator})


def reduce(table: pd.DataFrame, *, by: str, targets: gpd.GeoDataFrame, reductions, target_id: str | None = None):
    """Rows of *table* grouped by *by* onto *targets* (joined on the targets' IDs), in target order."""
    if by not in table.columns:
        raise InputError(f"Column {by!r} is not in the table.")
    if isinstance(reductions, Reduction):
        reductions = [reductions]
    ids, _ = resolve_ids(targets, "target", target_id)
    unknown = set(table[by].dropna()) - set(ids)
    out = targets.copy()
    rep = []
    groups = table.groupby(by, sort=False)
    for r in reductions:
        if r.method == "ratio_of_sums":
            num, den = r.options["numerator"], r.options["denominator"]
            for c in (num, den):
                if c not in table.columns:
                    raise InputError(f"Column {c!r} is not in the table.")
            a = pd.Series(float_array(table[num]), index=table.index)
            b = pd.Series(float_array(table[den]), index=table.index)
            both = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            sa = a[both].groupby(table.loc[both, by]).sum()
            sb = b[both].groupby(table.loc[both, by]).sum()
            ratio = (sa / sb.where(sb != 0)).reindex(ids)
            out[r.alias] = _f(float_array(ratio))
            rep.append({"method": r.method, "as": r.alias, "rows_used": int(both.sum()), "rows_skipped": int((~both).sum()),
                        "zero_denominator_targets": int((sb == 0).sum())})
        elif r.method == "sum":
            v = pd.Series(float_array(table[r.column]), index=table.index)
            s = v.groupby(table[by]).sum(min_count=1).reindex(ids)
            out[r.alias] = _f(float_array(s))
            rep.append({"method": "sum", "as": r.alias})
        else:
            raise UnsupportedError(f"reduce offers ratio_of_sums and sum, not {r.method!r}.")
    out.attrs[REPORT_ATTR] = Report(conversion="reduce", by=by, groups=int(groups.ngroups),
                                    unknown_keys=id_list(sorted(map(str, unknown))), reductions=rep)
    return out
