"""Small static SVG maps for the urbanweave tutorials.

    from svgmap import Map
    Map("Crashes per cell").fill(cells, "crashes").outline(zones, label="name").dots(crashes)

A ``Map`` collects layers and renders them as one self-contained SVG (shown inline by Jupyter
through ``_repr_svg_``, saved with ``save``). It needs NumPy, Shapely and pyproj only, so the
notebooks render the same on GitHub, in CI and offline.

Conventions (from the data-visualization guidance these maps follow):

- One CRS per map: the first layer's, or a local UTM zone when that is geographic.
- Magnitudes use one hue, light to dark, in up to seven classes, with the class bounds in the legend.
  Categories use at most three hues; further categories fold into "other".
- Missing values are hatched and named in the legend, so they never read as a measured zero.
- Every feature carries a hover tooltip (its ID and the mapped value).
- Light and dark variants come from the same ramps, chosen by the viewer's color scheme.
"""

from __future__ import annotations

import base64
import html
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np
import shapely
import shapely.ops
from pyproj import CRS, Transformer

# Reference palette (light, dark). Sequential: blue 100..700 in seven classes.
SEQ_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_DARK = ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]
CAT_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a"]
CAT_DARK = ["#3987e5", "#d95926", "#199e70"]
OTHER = "#898781"

STYLE = """
.uwmap { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --rule:#c3c2b7;
  --line:#52514e; --dot:#0b0b0b; --link:#eb6834; --halo:#fcfcfb; --hatch:#c3c2b7;
  %(seq_l)s %(cat_l)s }
@media (prefers-color-scheme: dark) { .uwmap { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7;
  --muted:#898781; --rule:#383835; --line:#c3c2b7; --dot:#f0efec; --link:#d95926; --halo:#1a1a19;
  --hatch:#52514e; %(seq_d)s %(cat_d)s }
  .uwmap .light-only { display:none } }
@media not (prefers-color-scheme: dark) { .uwmap .dark-only { display:none } }
.uwmap text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink2); font-size: 11px }
.uwmap .title { fill: var(--ink); font-size: 14px; font-weight: 600 }
.uwmap .label { fill: var(--ink); font-size: 11px; font-weight: 600; paint-order: stroke;
  stroke: var(--halo); stroke-width: 3px; stroke-linejoin: round }
.uwmap .feature:hover { stroke: var(--ink); stroke-width: 2px }
"""


def _vars(prefix, colors):
    return " ".join(f"--{prefix}{i}:{c};" for i, c in enumerate(colors))


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "missing"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        a = abs(float(v))
        if a != 0 and (a >= 1e5 or a < 1e-3):
            return f"{float(v):.3g}"
        return f"{float(v):,.3f}".rstrip("0").rstrip(".") if a < 100 else f"{float(v):,.0f}"
    return str(v)


def _png(rgba: np.ndarray) -> str:
    """An RGBA uint8 array as a base64 PNG (no imaging library needed)."""
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode()


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


@dataclass
class _Scale:
    """How a column maps to a color slot: sequential classes or categories."""

    kind: str  # "sequential" | "categorical"
    bounds: list = field(default_factory=list)  # class edges (sequential)
    categories: list = field(default_factory=list)
    title: str = ""
    has_missing: bool = False

    def slot(self, v) -> str | None:
        """The CSS variable for value *v*, or None when missing."""
        if v is None or (isinstance(v, float) and np.isnan(v)) or (v is not None and _isna(v)):
            return None
        if self.kind == "categorical":
            i = self.categories.index(v) if v in self.categories else None
            return f"var(--c{i})" if i is not None else OTHER
        k = int(np.searchsorted(self.bounds[1:-1], float(v), side="right"))
        k = min(k, len(self.bounds) - 2)
        return f"var(--s{k})"

    def hex(self, v, dark: bool) -> str | None:
        s = self.slot(v)
        if s is None:
            return None
        if s == OTHER:
            return OTHER
        i = int(s[s.index("--") + 3:-1])
        return ((SEQ_DARK if dark else SEQ_LIGHT) if s.startswith("var(--s") else (CAT_DARK if dark else CAT_LIGHT))[i]


def _isna(v) -> bool:
    try:
        return bool(np.isnan(v))
    except (TypeError, ValueError):
        return v is None or v is getattr(np, "nan", None) or str(v) in ("<NA>", "nan", "None")


def _nice_bounds(values: np.ndarray, classes: int) -> list[float]:
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    if hi == lo:
        return [lo, hi + 1]
    step = (hi - lo) / classes
    mag = 10 ** np.floor(np.log10(step))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= step), default=step)
    start = np.floor(lo / step) * step
    edges = [start + i * step for i in range(classes + 2) if start + (i - 1) * step < hi]
    if edges[-1] < hi:
        edges.append(edges[-1] + step)
    return [float(e) for e in edges]


class Map:
    """A static SVG map built from layers. Methods return the map, so calls chain."""

    def __init__(self, title: str = "", *, width: int = 640, crs=None, extent=None, pad: float = 0.03):
        self.title, self.width, self.crs, self.extent, self.pad = title, width, crs, extent, pad
        self._layers: list[tuple] = []
        self._legends: list[_Scale] = []
        self._notes: list[str] = []

    # ---------------------------------------------------------------- layers
    def fill(self, frame, column: str | None = None, *, scheme: str | None = None, classes: int = 6,
             bounds=None, legend: str | None = None, tooltip=(), opacity: float = 1.0, order=None):
        """Polygons filled by *column* (sequential for numbers, categorical otherwise), or plain."""
        scale = self._scale(frame, column, scheme, classes, bounds, legend, order) if column else None
        self._layers.append(("fill", frame, column, scale, tuple(tooltip), opacity))
        return self

    def outline(self, frame, *, label: str | None = None, width: float = 1.2, tooltip=()):
        """Polygon or line outlines, optionally labelled at each feature's interior point."""
        self._layers.append(("outline", frame, label, width, tuple(tooltip)))
        return self

    def lines(self, frame, column: str | None = None, *, scheme: str | None = None, classes: int = 6, bounds=None,
              legend: str | None = None, width: float = 2.0, tooltip=(), order=None):
        """Lines, colored by *column* or in the line ink."""
        scale = self._scale(frame, column, scheme, classes, bounds, legend, order) if column else None
        self._layers.append(("lines", frame, column, scale, width, tuple(tooltip)))
        return self

    def dots(self, frame, column: str | None = None, *, scheme: str | None = None, classes: int = 6, bounds=None,
             legend: str | None = None, radius: float = 3.0, tooltip=(), label: str | None = None, order=None):
        """Points as dots, colored by *column* or in the dot ink."""
        scale = self._scale(frame, column, scheme, classes, bounds, legend, order) if column else None
        self._layers.append(("dots", frame, column, scale, radius, tuple(tooltip), label))
        return self

    def raster(self, raster, band=1, *, scheme: str = "sequential", classes: int = 6, bounds=None,
               legend: str | None = None, labels: dict | None = None, order=None, opacity: float = 1.0):
        """A north-up urbanweave Raster band, drawn as an embedded image in its own cells; *labels*
        names categorical codes and *order* fixes which code takes which color slot."""
        b = raster.band(band)
        data, valid = raster.read(b, 0, raster.height, 0, raster.width)
        vals = np.where(valid, data.astype(float), np.nan)
        if scheme == "categorical":
            cats = sorted(np.unique(vals[~np.isnan(vals)]).tolist())
            if order is not None:
                cats = [c for c in order if c in cats] + [c for c in cats if c not in order]
            names = labels or {}
            scale = _Scale("categorical", categories=cats[:3], title=legend or b.name,
                           has_missing=bool(np.isnan(vals).any()))
            scale.labels = {c: names.get(c, _fmt(c)) for c in cats}
            scale.folded = cats[3:]
        else:
            edges = list(bounds) if bounds is not None else _nice_bounds(vals, classes)
            scale = _Scale("sequential", bounds=edges, title=legend or b.name, has_missing=bool(np.isnan(vals).any()))
        self._legends.append(scale)
        self._layers.append(("raster", raster, vals, scale, opacity))
        return self

    def links(self, match, *, width: str | None = None, max_width: float = 4.0):
        """One segment per matched pair, from the source to the target (interior points), as
        :func:`urbanweave.match` paired them; *width* names a quantity to scale the stroke by."""
        self._layers.append(("links", match, width, max_width))
        return self

    def note(self, text: str):
        """A line of text under the legend (data source, units, caveats)."""
        self._notes.append(text)
        return self

    # ---------------------------------------------------------------- scales
    def _scale(self, frame, column, scheme, classes, bounds, legend, order=None) -> _Scale:
        import pandas as pd

        s = frame[column]
        nonnull = s.dropna()
        numeric = bool(pd.to_numeric(nonnull, errors="coerce").notna().all()) and not pd.api.types.is_bool_dtype(s)
        kind = scheme or ("sequential" if numeric else "categorical")
        if kind == "sequential":
            s = pd.to_numeric(s, errors="coerce")
        missing = bool(s.isna().any())
        if kind == "categorical":
            counts = s.dropna().value_counts()
            cats = sorted(counts.index.tolist(), key=lambda c: (-counts[c], str(c)))
            if order is not None:  # color follows the entity: a fixed slot per category
                cats = [c for c in order if c in cats] + [c for c in cats if c not in order]
            scale = _Scale("categorical", categories=cats[:3], title=legend or column, has_missing=missing)
            scale.labels = {c: str(c) for c in cats}
            scale.folded = cats[3:]
        else:
            vals = np.asarray(s, dtype=float)
            edges = list(bounds) if bounds is not None else _nice_bounds(vals, classes)
            scale = _Scale("sequential", bounds=edges, title=legend or column, has_missing=missing)
        self._legends.append(scale)
        return scale

    # ---------------------------------------------------------------- geometry
    def _map_crs(self):
        if self.crs is not None:
            return CRS.from_user_input(self.crs)
        for layer in self._layers:
            obj = layer[1]
            crs = obj.crs if layer[0] != "links" else obj.targets.frame.crs
            if crs is None:
                continue
            crs = CRS.from_user_input(crs)
            if crs.is_projected:
                return crs
            frame = obj if layer[0] not in ("links", "raster") else obj.targets.frame
            if hasattr(frame, "estimate_utm_crs"):
                return frame.estimate_utm_crs()
        return None

    def _project(self, geoms, crs):
        geoms = np.asarray(geoms, dtype=object)
        if crs is None or self._crs is None or CRS.from_user_input(crs).equals(self._crs):
            return geoms
        t = Transformer.from_crs(CRS.from_user_input(crs), self._crs, always_xy=True)
        return shapely.transform(geoms, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))

    def _xy(self, x, y):
        return (x - self._x0) * self._k + self._ox, (self._y1 - y) * self._k + self._oy

    def _path(self, g) -> str:
        parts = []
        if g is None or g.is_empty:
            return ""
        polys = shapely.get_parts(g) if g.geom_type.startswith("Multi") or g.geom_type == "GeometryCollection" else [g]
        for p in polys:
            if p.geom_type == "Polygon":
                rings = [p.exterior, *p.interiors]
                for r in rings:
                    c = np.asarray(r.coords)
                    xs, ys = self._xy(c[:, 0], c[:, 1])
                    parts.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in zip(xs, ys)) + "Z")
            elif p.geom_type in ("LineString", "LinearRing"):
                c = np.asarray(p.coords)
                xs, ys = self._xy(c[:, 0], c[:, 1])
                parts.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in zip(xs, ys)))
        return "".join(parts)

    @staticmethod
    def _tip(frame, i, column, extra) -> str:
        row = frame.iloc[i]
        idc = next((c for c in ("target_id", "source_id", "piece_id", "zone_id") if c in frame.columns), None)
        head = f"{row[idc]}" if idc else f"{frame.index[i]}"
        bits = [head] + [f"{c}: {_fmt(row[c])}" for c in ((column,) if column else ()) + tuple(extra) if c in frame.columns]
        return html.escape("\n".join(bits))

    # ---------------------------------------------------------------- render
    def _bounds(self, projected):
        if self.extent is not None:
            return self.extent
        b = np.array([shapely.total_bounds(g) for g in projected if len(g)])
        b = b[~np.isnan(b).any(axis=1)]
        return b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()

    def to_svg(self) -> str:
        self._crs = self._map_crs()
        prepared = []
        for layer in self._layers:
            kind = layer[0]
            if kind == "raster":
                r = layer[1]
                t = r.transform
                x0, y1 = t.c, t.f
                x1, y0 = x0 + t.a * r.width, y1 + t.e * r.height
                box = shapely.box(x0, y0, x1, y1)
                prepared.append(self._project([box], r.crs))
            elif kind == "links":
                m = layer[1]
                prepared.append(self._project(m.targets.geometry, m.targets.frame.crs))
            else:
                prepared.append(self._project(np.asarray(layer[1].geometry.array, dtype=object), layer[1].crs))
        x0, y0, x1, y1 = self._bounds(prepared)
        dx, dy = (x1 - x0) * self.pad, (y1 - y0) * self.pad
        x0, x1, y0, y1 = x0 - dx, x1 + dx, y0 - dy, y1 + dy
        W = self.width
        self._k = (W - 2) / max(x1 - x0, 1e-9)
        top = 28 if self.title else 6
        H_map = (y1 - y0) * self._k
        self._x0, self._y1, self._ox, self._oy = x0, y1, 1, top
        body, defs = [], []
        defs.append('<pattern id="uw-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
                    'patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--surface)"/>'
                    '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch)" stroke-width="2"/></pattern>')
        defs.append(f'<clipPath id="uw-clip"><rect x="1" y="{top}" width="{W - 2}" height="{H_map:.1f}"/></clipPath>')
        labels = []
        for layer, geoms in zip(self._layers, prepared):
            kind = layer[0]
            if kind == "fill":
                _, frame, column, scale, tips, opacity = layer
                vals = frame[column].tolist() if column else [None] * len(frame)
                for i, g in enumerate(geoms):
                    d = self._path(g)
                    if not d:
                        continue
                    if scale is None:
                        fill = "var(--rule)"
                    else:
                        fill = scale.slot(vals[i]) or "url(#uw-hatch)"
                    body.append(f'<path class="feature" d="{d}" style="fill:{fill};fill-opacity:{opacity}" '
                                f'stroke="var(--surface)" stroke-width="1" fill-rule="evenodd">'
                                f'<title>{self._tip(frame, i, column, tips)}</title></path>')
            elif kind == "outline":
                _, frame, label, width, tips = layer
                for i, g in enumerate(geoms):
                    d = self._path(g)
                    if d:
                        body.append(f'<path d="{d}" fill="none" stroke="var(--ink2)" stroke-width="{width}" '
                                    f'stroke-linejoin="round"><title>{self._tip(frame, i, label, tips)}</title></path>')
                    if label and g is not None and not g.is_empty:
                        p = g.representative_point() if g.geom_type != "LineString" else g.interpolate(0.5, normalized=True)
                        x, y = self._xy(p.x, p.y)
                        labels.append(f'<text class="label" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">'
                                      f'{html.escape(str(frame[label].iloc[i]))}</text>')
            elif kind == "lines":
                _, frame, column, scale, width, tips = layer
                vals = frame[column].tolist() if column else [None] * len(frame)
                for i, g in enumerate(geoms):
                    d = self._path(g)
                    if not d:
                        continue
                    color = "var(--line)" if scale is None else (scale.slot(vals[i]) or "var(--muted)")
                    dash = ' stroke-dasharray="2 3"' if scale is not None and scale.slot(vals[i]) is None else ""
                    if scale is not None and not dash:  # a hairline casing keeps the lightest classes visible
                        body.append(f'<path d="{d}" fill="none" stroke="var(--muted)" stroke-opacity="0.55" '
                                    f'stroke-width="{width + 1.2}" stroke-linecap="round"/>')
                    body.append(f'<path class="feature" d="{d}" fill="none" style="stroke:{color}" '
                                f'stroke-width="{width}" stroke-linecap="round"{dash}>'
                                f'<title>{self._tip(frame, i, column, tips)}</title></path>')
            elif kind == "dots":
                _, frame, column, scale, radius, tips, label = layer
                vals = frame[column].tolist() if column else [None] * len(frame)
                for i, g in enumerate(geoms):
                    if g is None or g.is_empty:
                        continue
                    p = g if g.geom_type == "Point" else g.representative_point()
                    x, y = self._xy(p.x, p.y)
                    color = "var(--dot)" if scale is None else (scale.slot(vals[i]) or "url(#uw-hatch)")
                    body.append(f'<circle class="feature" cx="{x:.1f}" cy="{y:.1f}" r="{radius}" style="fill:{color}" '
                                f'stroke="var(--surface)" stroke-width="1">'
                                f'<title>{self._tip(frame, i, column, tips)}</title></circle>')
                    if label:
                        labels.append(f'<text class="label" x="{x + radius + 3:.1f}" y="{y + 4:.1f}">'
                                      f'{html.escape(str(frame[label].iloc[i]))}</text>')
            elif kind == "raster":
                _, r, vals, scale, opacity = layer
                g = geoms[0]
                bx0, by0, bx1, by1 = g.bounds
                px, py = self._xy(bx0, by1)
                qx, qy = self._xy(bx1, by0)
                for dark, cls in ((False, "light-only"), (True, "dark-only")):
                    rgba = np.zeros(vals.shape + (4,), dtype=np.uint8)
                    for key in ([*scale.categories] if scale.kind == "categorical" else range(len(scale.bounds) - 1)):
                        if scale.kind == "categorical":
                            sel = vals == key
                            color = scale.hex(key, dark)
                        else:
                            lo, hi = scale.bounds[key], scale.bounds[key + 1]
                            sel = (vals >= lo) & ((vals < hi) | (key == len(scale.bounds) - 2) & (vals <= hi))
                            color = (SEQ_DARK if dark else SEQ_LIGHT)[key]
                        rgba[sel, :3] = _hex_rgb(color)
                        rgba[sel, 3] = 255
                    if scale.kind == "categorical":
                        other = ~np.isnan(vals) & ~np.isin(vals, scale.categories)
                        rgba[other, :3] = _hex_rgb(OTHER)
                        rgba[other, 3] = 255
                    missing = np.isnan(vals)
                    if missing.any():  # diagonal stripes, like the vector hatch
                        rr, cc = np.indices(vals.shape)
                        stripe = missing & (((rr + cc) % 4) == 0)
                        rgba[missing, :3] = _hex_rgb("#1a1a19" if dark else "#fcfcfb")
                        rgba[stripe, :3] = _hex_rgb("#52514e" if dark else "#c3c2b7")
                        rgba[missing, 3] = 255
                    body.append(f'<image class="{cls}" x="{px:.1f}" y="{py:.1f}" width="{qx - px:.1f}" '
                                f'height="{qy - py:.1f}" preserveAspectRatio="none" opacity="{opacity}" '
                                f'style="image-rendering:pixelated" href="data:image/png;base64,{_png(rgba)}"/>')
            elif kind == "links":
                _, m, qty, max_w = layer
                pos = m.positions
                src = self._project(m.sources.geometry, m.sources.frame.crs)
                tgt = geoms
                w = (pos[qty].to_numpy(float) if qty else np.ones(len(pos)))
                w = np.where(np.isfinite(w), w, 0)
                wmax = w.max() if len(w) and w.max() > 0 else 1
                for s_i, t_i, wi, sid, tid in zip(pos["src"], pos["tgt"], w, m.pairs["source_id"], m.pairs["target_id"]):
                    a = src[s_i].representative_point() if src[s_i].geom_type != "Point" else src[s_i]
                    tg = tgt[t_i]
                    b = tg.representative_point() if tg.geom_type not in ("Point", "LineString", "MultiLineString") \
                        else shapely.ops.nearest_points(tg, a)[0] if tg.geom_type != "Point" else tg
                    (ax, ay), (bx, by) = self._xy(a.x, a.y), self._xy(b.x, b.y)
                    tip = html.escape(f"{sid} → {tid}" + (f"\n{qty}: {_fmt(wi)}" if qty else ""))
                    body.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="var(--link)" '
                                f'stroke-width="{max(0.75, max_w * wi / wmax) if qty else 1.5:.2f}" stroke-linecap="round">'
                                f'<title>{tip}</title></line>')
        legend, lh = self._legend_svg(top + H_map + 10)
        H = top + H_map + lh + 6
        style = STYLE % {"seq_l": _vars("s", SEQ_LIGHT), "seq_d": _vars("s", SEQ_DARK),
                         "cat_l": _vars("c", CAT_LIGHT), "cat_d": _vars("c", CAT_DARK)}
        title = f'<text class="title" x="1" y="18">{html.escape(self.title)}</text>' if self.title else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="uwmap" width="{W}" height="{H:.0f}" '
                f'viewBox="0 0 {W} {H:.0f}" role="img" aria-label="{html.escape(self.title)}">'
                f'<style>{style}</style><defs>{"".join(defs)}</defs>'
                f'<rect width="{W}" height="{H:.0f}" fill="var(--surface)"/>{title}'
                f'<g clip-path="url(#uw-clip)">{"".join(body)}{"".join(labels)}</g>'
                f'<rect x="1" y="{top}" width="{W - 2}" height="{H_map:.1f}" fill="none" stroke="var(--rule)"/>'
                f'{legend}</svg>')

    def _legend_svg(self, y: float) -> tuple[str, float]:
        out, h = [], 0.0
        for scale in self._legends:
            x = 1.0
            out.append(f'<text x="{x}" y="{y + h + 10:.1f}" style="fill:var(--ink);font-weight:600">'
                       f'{html.escape(str(scale.title))}</text>')
            yy = y + h + 16
            if scale.kind == "sequential":
                n = len(scale.bounds) - 1
                sw = min(64, (self.width - 120) / max(n, 1))
                for k in range(n):
                    out.append(f'<rect x="{x + k * sw:.1f}" y="{yy:.1f}" width="{sw - 2:.1f}" height="10" rx="2" '
                               f'style="fill:var(--s{k})"/>')
                for k, e in enumerate(scale.bounds):
                    out.append(f'<text x="{x + k * sw - (1 if k else 0):.1f}" y="{yy + 23:.1f}" '
                               f'text-anchor="{"start" if k == 0 else "middle"}">{_fmt(e)}</text>')
                xm = x + n * sw + 14
            else:
                xm = x
                items = [(f"var(--c{i})", scale.labels.get(c, str(c))) for i, c in enumerate(scale.categories)]
                if getattr(scale, "folded", None):
                    items.append((OTHER, f"other ({len(scale.folded)})"))
                for color, name in items:
                    out.append(f'<rect x="{xm:.1f}" y="{yy:.1f}" width="10" height="10" rx="2" style="fill:{color}"/>'
                               f'<text x="{xm + 14:.1f}" y="{yy + 9:.1f}">{html.escape(str(name))}</text>')
                    xm += 22 + 6.5 * len(str(name))
            if scale.has_missing:
                out.append(f'<rect x="{xm:.1f}" y="{yy:.1f}" width="10" height="10" rx="2" fill="url(#uw-hatch)" '
                           f'stroke="var(--rule)"/><text x="{xm + 14:.1f}" y="{yy + 9:.1f}">missing</text>')
            h += 46 if scale.kind == "sequential" else 34
        for note in self._notes:
            out.append(f'<text x="1" y="{y + h + 8:.1f}" style="fill:var(--muted)">{html.escape(note)}</text>')
            h += 16
        return "".join(out), h

    def _repr_svg_(self) -> str:
        return self.to_svg()

    def save(self, path) -> None:
        from pathlib import Path

        Path(path).write_text(self.to_svg())
