"""Schematic figures for the urbanweave tutorials: the data models and what each operation does.

    import diagrams
    diagrams.geometry_types()        # shown inline in a notebook (an SVG figure)

Each function returns a :class:`Figure`: a row of small panels with captions, drawn in local
coordinates (x grows east, y grows north, as in a projected CRS). The style follows the Autark
tutorial's drawings: thin dark strokes, gray fills and labelled coordinates, with two accents used
the same way everywhere: **orange for sources, blue for targets**. Where a figure shows a number (an
allocation fraction, a length, a weight), urbanweave or Shapely computed it from the drawn geometry.
"""

from __future__ import annotations

import html
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box

STYLE = """
.uwfig { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#333333; --muted:#898781; --rule:#c3c2b7; --cell:#efefef;
  --pt:#bfbfbf; --src:#eb6834; --src-fill:#fbd9cb; --tgt:#2a78d6; --tgt-fill:#cde2fb; --sel:#9ec5f4;
  --axis-x:#d03b3b; --axis-y:#008300; --hatch:#c3c2b7 }
@media (prefers-color-scheme: dark) { .uwfig { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --rule:#52514e; --cell:#2c2c2a; --pt:#52514e; --src:#d95926; --src-fill:#5a2a17; --tgt:#3987e5;
  --tgt-fill:#1c3a5e; --sel:#256abf; --axis-x:#e66767; --axis-y:#0ca30c; --hatch:#52514e } }
.uwfig text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink2); font-size: 10.5px }
.uwfig .title { fill: var(--ink); font-size: 13px; font-weight: 600 }
.uwfig .cap { fill: var(--ink2); font-size: 11px }
.uwfig .cap-b { fill: var(--ink); font-size: 11px; font-weight: 600 }
.uwfig .lbl { fill: var(--ink); font-size: 10.5px; paint-order: stroke; stroke: var(--surface); stroke-width: 3px }
.uwfig .small { fill: var(--muted); font-size: 9.5px }
.uwfig .val { fill: var(--ink); font-size: 9px; paint-order: stroke; stroke: var(--surface); stroke-width: 2.5px }
.uwfig .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9.5px; fill: var(--ink2) }
"""

# drawing classes: (fill, stroke, stroke width)
KIND = {
    "geom": ("var(--cell)", "var(--ink2)", 1.6),
    "vertex": ("var(--pt)", "var(--ink2)", 1.2),
    "src": ("var(--src-fill)", "var(--src)", 1.8),
    "src-pt": ("var(--src)", "var(--surface)", 1.2),
    "tgt": ("var(--tgt-fill)", "var(--tgt)", 1.8),
    "tgt-pt": ("var(--tgt)", "var(--surface)", 1.2),
    "cell": ("var(--cell)", "var(--rule)", 1.0),
    "sel": ("var(--sel)", "var(--rule)", 1.0),
    "none": ("none", "var(--ink2)", 1.4),
    "ghost": ("none", "var(--muted)", 1.0),
    "hatch": ("url(#fig-hatch)", "var(--rule)", 1.0),
}


def _e(s) -> str:
    return html.escape(str(s))


class Panel:
    """A drawing area of *w* × *h* pixels showing *extent* = (x0, y0, x1, y1) in local units."""

    def __init__(self, caption: str = "", *, w: int = 150, h: int = 130, extent=(0, 0, 100, 100), pad: int = 12,
                 heading: str = ""):
        self.caption, self.heading, self.w, self.h, self.pad = caption, heading, w, h, pad
        x0, y0, x1, y1 = extent
        k = min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0))
        self._k = k
        self._ox = pad + ((w - 2 * pad) - k * (x1 - x0)) / 2 - k * x0
        self._oy = h - pad - ((h - 2 * pad) - k * (y1 - y0)) / 2 + k * y0
        self.parts: list[str] = []

    # coordinates --------------------------------------------------------------------------
    def xy(self, x, y):
        return self._ox + self._k * x, self._oy - self._k * y

    def _pts(self, coords) -> str:
        return " ".join("{:.1f},{:.1f}".format(*self.xy(x, y)) for x, y in coords)

    # shapes -------------------------------------------------------------------------------
    def geom(self, g, kind: str = "geom", *, dash: bool = False, opacity: float = 1.0, width: float | None = None,
             title: str | None = None):
        fill, stroke, sw = KIND[kind]
        sw = width or sw
        d = ' stroke-dasharray="4 3"' if dash else ""
        tip = f"<title>{_e(title)}</title>" if title else ""
        for p in shapely.get_parts(g):
            if p.geom_type == "Polygon":
                path = "".join("M" + self._pts(r.coords) + "Z" for r in (p.exterior, *p.interiors))
                path = path.replace(" ", "L").replace("ML", "M")
                self.parts.append(f'<path d="{path}" fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" '
                                  f'stroke-width="{sw}" fill-rule="evenodd" stroke-linejoin="round"{d}>{tip}</path>')
            elif p.geom_type in ("LineString", "LinearRing"):
                self.parts.append(f'<polyline points="{self._pts(p.coords)}" fill="none" stroke="{stroke}" '
                                  f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"{d}>{tip}</polyline>')
            elif p.geom_type == "Point":
                self.point(p.x, p.y, kind if kind.endswith("pt") or kind == "vertex" else "vertex")
        return self

    def line(self, coords, kind: str = "none", *, width: float | None = None, dash: bool = False, arrow: bool = False):
        fill, stroke, sw = KIND[kind]
        sw = width or sw
        d = ' stroke-dasharray="4 3"' if dash else ""
        a = ' marker-end="url(#fig-arrow)"' if arrow else ""
        self.parts.append(f'<polyline points="{self._pts(coords)}" fill="none" stroke="{stroke}" stroke-width="{sw}" '
                          f'stroke-linecap="round"{d}{a}/>')
        return self

    def point(self, x, y, kind: str = "vertex", *, r: float = 5.0, label: str | None = None, dx: float = 8,
              dy: float = 4, anchor: str = "start"):
        fill, stroke, sw = KIND[kind]
        px, py = self.xy(x, y)
        self.parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        if label:
            self.text(x, y, label, dx=dx, dy=dy, anchor=anchor)
        return self

    def cross(self, x, y, *, size: float = 4.5):
        px, py = self.xy(x, y)
        s = size
        self.parts.append(f'<path d="M{px - s:.1f},{py - s:.1f}L{px + s:.1f},{py + s:.1f}M{px - s:.1f},{py + s:.1f}'
                          f'L{px + s:.1f},{py - s:.1f}" stroke="var(--ink)" stroke-width="2" stroke-linecap="round"/>')
        return self

    def circle(self, x, y, radius, kind: str = "ghost", *, dash: bool = True):
        fill, stroke, sw = KIND[kind]
        px, py = self.xy(x, y)
        d = ' stroke-dasharray="4 3"' if dash else ""
        self.parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{radius * self._k:.1f}" fill="{fill}" '
                          f'fill-opacity="0.35" stroke="{stroke}" stroke-width="{sw}"{d}/>')
        return self

    def text(self, x, y, s, *, dx: float = 0, dy: float = 4, anchor: str = "middle", cls: str = "lbl"):
        px, py = self.xy(x, y)
        self.parts.append(f'<text class="{cls}" x="{px + dx:.1f}" y="{py + dy:.1f}" text-anchor="{anchor}">{_e(s)}</text>')
        return self

    def raw(self, svg: str):
        self.parts.append(svg)
        return self

    def axes(self, length: float = 100, *, labels: bool = True):
        """x (east, red) and y (north, green) axes from the origin, like the Autark tutorial's drawings."""
        o = self.xy(0, 0)
        ex, ny = self.xy(length, 0), self.xy(0, length)
        self.parts.append(f'<line x1="{o[0]:.1f}" y1="{o[1]:.1f}" x2="{ex[0]:.1f}" y2="{ex[1]:.1f}" stroke="var(--axis-x)"/>'
                          f'<line x1="{o[0]:.1f}" y1="{o[1]:.1f}" x2="{ny[0]:.1f}" y2="{ny[1]:.1f}" stroke="var(--axis-y)"/>'
                          f'<circle cx="{o[0]:.1f}" cy="{o[1]:.1f}" r="3" fill="var(--ink2)"/>')
        if labels:
            self.parts.append(f'<text class="small" x="{ex[0] - 2:.1f}" y="{ex[1] + 11:.1f}" text-anchor="end">x</text>'
                              f'<text class="small" x="{ny[0] - 6:.1f}" y="{ny[1] + 8:.1f}" text-anchor="end">y</text>')
        return self

    def grid(self, x0, y0, nx, ny, size, *, kind="cell", values=None, fmt="{:g}", shade=None, nodata=()):
        """A raster: nx × ny cells of *size*, lower-left at (x0, y0). *values* is listed top row first
        (as rasters store them); *shade* maps a value to a gray level 0..1; *nodata* are (row, col)."""
        for r in range(ny):
            for c in range(nx):
                cx0, cy1 = x0 + c * size, y0 + (ny - r) * size
                cell = box(cx0, cy1 - size, cx0 + size, cy1)
                if (r, c) in nodata:
                    self.geom(cell, "hatch")
                    self.text(cx0 + size / 2, cy1 - size / 2, "–", cls="small")
                    continue
                if values is not None and shade is not None:
                    level = shade(values[r][c])
                    px0, py0 = self.xy(cx0, cy1)
                    wpx = size * self._k  # ink over the cell color: darker is more, in both themes
                    self.parts.append(f'<rect x="{px0:.1f}" y="{py0:.1f}" width="{wpx:.1f}" height="{wpx:.1f}" '
                                      f'fill="var(--cell)" stroke="var(--rule)"/><rect x="{px0:.1f}" y="{py0:.1f}" '
                                      f'width="{wpx:.1f}" height="{wpx:.1f}" fill="var(--ink2)" '
                                      f'fill-opacity="{0.05 + 0.6 * max(0.0, min(1.0, level)):.2f}" stroke="var(--rule)"/>')
                else:
                    self.geom(cell, kind)
                if values is not None:
                    v = values[r][c]
                    self.text(cx0 + size / 2, cy1 - size / 2, fmt.format(v), cls="val", dy=3)
        return self

    def svg(self, x: float, y: float, cap_lines: list[str]) -> str:
        cap = "".join(f'<text class="{"cap-b" if i == 0 and self.heading else "cap"}" x="{x + 2:.1f}" '
                      f'y="{y + self.h + 14 + 13 * i:.1f}">{_e(t)}</text>' for i, t in enumerate(cap_lines))
        return (f'<g transform="translate({x:.1f},{y:.1f})"><rect width="{self.w}" height="{self.h}" rx="6" '
                f'fill="var(--surface)" stroke="var(--rule)"/>{"".join(self.parts)}</g>{cap}')


def _wrap(text: str, width_px: float) -> list[str]:
    per_line = max(10, int(width_px / 5.9))
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > per_line and cur:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


class Figure:
    """Panels in rows (wrapping at *max_width*), each with its caption, under an optional title."""

    def __init__(self, title: str = "", panels=(), *, max_width: int = 680, gap: int = 16):
        self.title, self.panels, self.max_width, self.gap = title, list(panels), max_width, gap

    def to_svg(self) -> str:
        y = 26 if self.title else 6
        x, row_h, body, width = 4.0, 0.0, [], 0.0
        for p in self.panels:
            lines = ([p.heading] if p.heading else []) + _wrap(p.caption, p.w)
            h = p.h + 8 + 13 * len(lines)
            if x + p.w > self.max_width and x > 4:
                x, y = 4.0, y + row_h + self.gap
                row_h = 0.0
            body.append(p.svg(x, y, lines))
            width = max(width, x + p.w)
            x += p.w + self.gap
            row_h = max(row_h, h)
        H = y + row_h + 4
        W = max(width + 4, 200)
        title = f'<text class="title" x="4" y="17">{_e(self.title)}</text>' if self.title else ""
        defs = ('<defs><pattern id="fig-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
                'patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--surface)"/>'
                '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch)" stroke-width="2"/></pattern>'
                '<marker id="fig-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
                'orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="var(--ink2)"/></marker></defs>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="uwfig" width="{W:.0f}" height="{H:.0f}" '
                f'viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{_e(self.title)}"><style>{STYLE}</style>'
                f'{defs}<rect width="{W:.0f}" height="{H:.0f}" fill="var(--surface)"/>{title}{"".join(body)}</svg>')

    def _repr_svg_(self) -> str:
        return self.to_svg()

    def save(self, path) -> None:
        from pathlib import Path

        Path(path).write_text(self.to_svg())


# ===================================================================================== data models
def coordinates() -> Figure:
    p = Panel("Coordinates are (x, y): x grows east (red), y grows north (green). urbanweave measures in metres, "
              "in a projected CRS.", heading="Coordinates", w=170)
    p.axes(100)
    p.point(80, 40, "vertex", label="(80, 40)")
    p.line([(80, 0), (80, 40)], "ghost", dash=True).line([(0, 40), (80, 40)], "ghost", dash=True)
    q = Panel("Geographic coordinates are degrees of (longitude, latitude). A degree of longitude shrinks "
              "towards the poles, so distances and areas need a projection.", heading="Degrees are not metres",
              w=250, extent=(-2, -5, 120, 80))
    for lat, y in ((0, 62), (40.65, 38), (60, 14)):
        km = 111.32 * math.cos(math.radians(lat))
        q.line([(0, y), (km, y)], "src", width=7)
        where = " (Riverton)" if lat == 40.65 else ""
        q.text(0, y, f"1° of longitude at {lat:g}°{where}: {km:.0f} km", dx=0, dy=-9, anchor="start", cls="small")
    return Figure("Coordinates", [p, q])


def geometry_types() -> Figure:
    def panel(heading, caption, shapes, w=150):
        p = Panel(caption, heading=heading, w=w)
        p.axes(100, labels=False)
        for g in shapes:
            p.geom(g, "geom")
        for g in shapes:
            for c in shapely.get_coordinates(g):
                p.point(*c, "vertex")
        return p

    poly = Polygon([(20, 80), (80, 60), (40, 20), (20, 40)])
    with_hole = Polygon([(10, 90), (90, 90), (90, 10), (10, 10)], [[(35, 65), (65, 65), (65, 35), (35, 35)]])
    return Figure("Vector data: points, lines and polygons", [
        panel("Point", "One coordinate, e.g. a crash at (80, 60).", [Point(80, 60)]),
        panel("MultiPoint", "Several points that form one feature.", [Point(80, 60), Point(40, 20)]),
        panel("LineString", "Connected points, e.g. a street segment.", [LineString([(80, 60), (40, 20)])]),
        panel("MultiLineString", "Several lines that form one feature.",
              [LineString([(80, 60), (40, 20)]), LineString([(20, 80), (20, 40)])]),
        panel("Polygon", "A closed ring, e.g. a district or a building.", [poly]),
        panel("Polygon with a hole", "An outer ring and inner rings: a block around a courtyard.", [with_hole]),
        panel("MultiPolygon", "Several polygons that form one feature: a district with an island.",
              [Polygon([(10, 90), (60, 85), (50, 40), (10, 50)]), Polygon([(70, 30), (95, 35), (85, 8)])]),
    ])


_UTCI = [[26.1, 27.4, 28.9, 29.6], [27.0, 29.2, 31.5, 30.8], [26.4, 30.1, 33.2, 31.9], [25.2, 27.8, None, 30.3]]


def raster_anatomy() -> Figure:
    a = Panel("A grid of rows × columns of equal cells, placed by the position of its top-left corner (the "
              "origin) and the cell size.", heading="A raster", w=200, h=170, extent=(-18, -14, 108, 112))
    a.grid(0, 0, 4, 4, 25)
    a.point(0, 100, "vertex", r=4).text(0, 100, "origin (x₀, y₀)", dx=-2, dy=-8, anchor="start", cls="small")
    a.line([(0, -6), (25, -6)], "none", width=1).text(12.5, -6, "cell size", dy=10, cls="small")
    a.text(-9, 87.5, "row 0", cls="small", anchor="end", dx=6).text(-9, 12.5, "row 3", cls="small", anchor="end", dx=6)
    b = Panel("Each cell holds a value for the area it covers; here UTCI in °C. A cell with no measurement is "
              "nodata (hatched), which is not zero.", heading="Cell values and nodata", w=200, h=170, extent=(-6, -6, 106, 106))
    b.grid(0, 0, 4, 4, 25, values=_UTCI, shade=lambda v: (v - 25) / 9, fmt="{:.1f}", nodata=[(3, 2)])
    c = Panel("A raster can have several bands on the same grid: here UTCI and land cover. urbanweave reads "
              "each band with its own nodata, units and value kind.", heading="Bands", w=220, h=170, extent=(-5, -16, 135, 122))
    c.grid(30, 30, 4, 4, 20, values=[[1, 1, 2, 2], [1, 1, 1, 2], [3, 1, 1, 1], [3, 3, 1, 1]])
    c.grid(0, 0, 4, 4, 20, values=[[r[i] if r[i] is not None else 0 for i in range(4)] for r in _UTCI],
           shade=lambda v: (v - 25) / 9 if v else 0, fmt="{:.0f}", nodata=[(3, 2)])
    c.text(110, 118, "band 2: land cover", anchor="end", cls="small").text(0, -9, "band 1: UTCI", anchor="start", cls="small", dy=0)
    d = Panel("A raster answers 'what is the value here?' with the cell containing the point.",
              heading="Reading a value at a point", w=200, h=170, extent=(-6, -6, 106, 106))
    d.grid(0, 0, 4, 4, 25, values=_UTCI, shade=lambda v: (v - 25) / 9, fmt="{:.1f}", nodata=[(3, 2)])
    d.geom(box(50, 50, 75, 75), "none", width=2.5)
    d.point(55, 70, "src-pt", r=4)
    return Figure("Raster data: a grid of values", [a, b, c, d])


def _hex(cx, cy, r):
    return Polygon([(cx + r * math.cos(math.radians(30 + 60 * i)), cy + r * math.sin(math.radians(30 + 60 * i)))
                    for i in range(6)])


def _hex_lattice(r, x0, x1, y0, y1):
    w, h = math.sqrt(3) * r, 1.5 * r
    out = []
    for j in range(int((y1 - y0) / h) + 3):
        cy = y0 + (j - 1) * h
        off = w / 2 if j % 2 else 0
        for i in range(int((x1 - x0) / w) + 3):
            cx = x0 + (i - 1) * w + off
            out.append((cx, cy))
    return out


def h3_support() -> Figure:
    r = 14
    centres = _hex_lattice(r, 0, 100, 0, 100)
    a = Panel("H3 covers the Earth with hexagonal cells. Each cell has an ID and a resolution: a raster whose "
              "cells are named, not numbered by row and column.", heading="H3 is a raster with IDs", w=180)
    names = iter("abcdefghijklmnopqrstuvwxyz")
    for cx, cy in centres:
        if 0 <= cx <= 100 and 0 <= cy <= 100:
            a.geom(_hex(cx, cy, r), "cell")
            a.text(cx, cy, f"…{next(names)}", cls="mono", dy=3)
    b = Panel("A grid over an extent (dashed) keeps the cells whose centres lie inside it, as UrbanTrace does. "
              "A point in a cell left out (×) is unmatched, and the report says so.",
              heading="Choosing the cells", w=200, extent=(-12, -12, 112, 112))
    ext = box(8, 8, 92, 92)
    for cx, cy in centres:
        h = _hex(cx, cy, r)
        if not h.intersects(ext.buffer(10)):
            continue
        inside = ext.contains(Point(cx, cy))
        b.geom(h, "sel" if inside else "ghost", dash=not inside)
        b.point(cx, cy, "vertex", r=2)
    b.geom(ext.exterior, "none", dash=True, width=1.6)
    b.point(50, 40, "src-pt", r=4.5)
    b.point(6, 98, "src-pt", r=4.5).cross(6, 98, size=3.5)
    c = Panel("Resolutions nest roughly: each step makes cells about 7 times smaller (resolution 9 ≈ 0.1 km², "
              "10 ≈ 0.015 km²).", heading="Resolution", w=170)
    c.geom(_hex(50, 50, 40), "cell", width=2)
    for cx, cy in _hex_lattice(40 / math.sqrt(7), 0, 100, 0, 100):
        if Point(cx, cy).distance(Point(50, 50)) < 36:
            c.geom(_hex(cx, cy, 40 / math.sqrt(7)), "ghost")
    return Figure("H3 cells", [a, b, c])


def street_graph() -> Figure:
    A, B, C, D, E = (10, 50), (55, 50), (100, 50), (55, 95), (55, 5)
    a = Panel("OSMnx stores streets as a directed graph: a two-way street is two edges, one each way.",
              heading="Directed edges", w=170, extent=(0, -5, 110, 105))
    a.line([(A[0] + 4, 53), (B[0] - 5, 53)], arrow=True).line([(B[0] - 4, 47), (A[0] + 5, 47)], arrow=True)
    a.line([(B[0] + 4, 53), (C[0] - 5, 53)], arrow=True).line([(C[0] - 4, 47), (B[0] + 5, 47)], arrow=True)
    a.line([(55, 55), (55, 90)], arrow=True)
    a.line([(58, 45), (58, 10)], arrow=True).line([(52, 10), (52, 45)], arrow=True)
    for n, (x, y) in zip("ABCDE", (A, B, C, D, E)):
        a.point(x, y, "vertex", r=4.5)
    a.text(10, 50, "A", dy=-9).text(100, 50, "C", dy=-9).text(55, 95, "D", dx=10).text(55, 5, "E", dx=12)
    b = Panel("urbanweave merges the two edges of one street into one physical segment, so its length counts "
              "once. A divided road's carriageways (B–E) stay two: they are two roadways.",
              heading="Physical segments", w=200, extent=(0, -5, 110, 105))
    b.line([A, B], width=3).line([B, C], width=3).line([B, D], width=3)
    b.line([(57, 45), (60, 25), (57, 7)], width=3).line([(53, 45), (50, 25), (53, 7)], width=3)
    for x, y in (A, B, C, D, E):
        b.point(x, y, "vertex", r=4.5)
    b.text(32, 50, "1 segment", dy=-12, cls="small").text(64, 25, "2 carriageways", anchor="start", cls="small")
    c = Panel("An intersection is a node where three or more physical segments meet; B has 5 here.",
              heading="Intersections", w=160, extent=(0, -5, 110, 105))
    c.line([A, B], width=3).line([B, C], width=3).line([B, D], width=3)
    c.line([(57, 45), (60, 25), (57, 7)], width=3).line([(53, 45), (50, 25), (53, 7)], width=3)
    for x, y in (A, C, D, E):
        c.point(x, y, "vertex", r=4)
    c.point(*B, "tgt-pt", r=7).text(55, 50, "5", dx=12, dy=-6)
    return Figure("Streets: from a graph to physical segments", [a, b, c])


def match_and_aggregate() -> Figure:
    """The two steps, on three points and two zones."""
    zones = [box(0, 0, 50, 60), box(50, 0, 100, 60)]
    pts = [(15, 40, 2), (35, 15, 1), (75, 30, 4)]

    def base(p):
        for z, name in zip(zones, ("A", "B")):
            p.geom(z, "tgt")
            p.text(z.centroid.x, 52, name, cls="lbl")
        return p

    a = base(Panel("Sources (orange) carry values; targets (blue) are the places asked about.",
                   heading="1 · Inputs", w=150, extent=(-4, -4, 104, 64)))
    for i, (x, y, v) in enumerate(pts):
        a.point(x, y, "src-pt", r=5, label=f"p{i + 1}: {v}")
    b = base(Panel("match decides who goes where, with what quantities: here each point to the zone containing it.",
                   heading="2 · match", w=150, extent=(-4, -4, 104, 64)))
    for i, (x, y, v) in enumerate(pts):
        z = zones[0] if x < 50 else zones[1]
        b.line([(x, y), (z.centroid.x, 48)], "none", width=1.2, dash=True)
        b.point(x, y, "src-pt", r=5)
    t = Panel("The pairs: one row per (source, target) with the method's quantities.", heading="pairs",
              w=150, extent=(0, 0, 100, 60))
    rows = [("source", "target", "fraction"), ("p1", "A", "1.0"), ("p2", "A", "1.0"), ("p3", "B", "1.0")]
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            t.text(8 + j * 32, 55 - i * 13, cell, anchor="start", cls="cap-b" if i == 0 else "mono")
    c = base(Panel("aggregate reduces the pairs to one row per target: count and sum.", heading="3 · aggregate",
                   w=150, extent=(-4, -4, 104, 64)))
    c.text(25, 30, "count 2", cls="lbl").text(25, 18, "sum 3", cls="lbl")
    c.text(75, 30, "count 1", cls="lbl").text(75, 18, "sum 4", cls="lbl")
    return Figure("match, then aggregate", [a, b, t, c])


def value_kinds() -> Figure:
    tgt = [box(0, 0, 60, 60), box(60, 0, 100, 60)]
    src = box(20, 10, 80, 50)
    frac = [src.intersection(t).area / src.area for t in tgt]
    a = Panel(f"Extensive values (people, crashes) are split: a tract of 100 people lying {frac[0]:.0%} in A gives "
              f"A {100 * frac[0]:.0f} people.", heading="Extensive: split", w=200, extent=(-4, -4, 104, 64))
    for t, n in zip(tgt, "AB"):
        a.geom(t, "tgt").text(t.bounds[0] + 6, 52, n, anchor="start")
    a.geom(src, "src", opacity=0.75)
    a.text(40, 30, f"{100 * frac[0]:.0f}").text(70, 30, f"{100 * frac[1]:.0f}")
    b = Panel("Intensive values (temperature, income) are averaged, weighted by the overlap: 20° over 3/4 of A "
              "and 30° over 1/4 gives 22.5°.", heading="Intensive: averaged", w=200, extent=(-4, -4, 104, 64))
    b.geom(box(0, 0, 100, 60), "tgt").text(6, 52, "A", anchor="start")
    b.geom(box(0, 0, 75, 60), "src", opacity=0.55).geom(box(75, 0, 100, 60), "src", opacity=0.95)
    b.text(37, 30, "20°").text(87, 30, "30°").text(50, 8, "A: 22.5°", cls="lbl")
    c = Panel("Categorical values (land use) become shares of each class: 60% built, 40% green.",
              heading="Categorical: shares", w=180, extent=(-4, -4, 104, 64))
    c.geom(box(0, 0, 100, 60), "tgt").text(6, 52, "A", anchor="start")
    c.geom(box(0, 0, 60, 60), "cell").geom(box(60, 0, 100, 60), "sel")
    c.text(30, 30, "built").text(80, 30, "green")
    return Figure("Three kinds of value, three ways to move them", [a, b, c])


# ===================================================================================== matching
def _uw_frames(sources, targets, src_ids=None, tgt_ids=None):
    """Toy shapes (local metres) as UTM frames placed at Riverton's origin, for urbanweave to measure."""
    import geopandas as gpd

    from shapely import affinity

    X0, Y0 = 500_000.0, 4_500_000.0
    mv = lambda g: affinity.translate(g, X0, Y0)  # noqa: E731
    s = gpd.GeoDataFrame({"source_id": src_ids or [f"s{i}" for i in range(len(sources))]},
                         geometry=[mv(g) for g in sources], crs="EPSG:32618")
    t = gpd.GeoDataFrame({"target_id": tgt_ids or [chr(65 + i) for i in range(len(targets))]},
                         geometry=[mv(g) for g in targets], crs="EPSG:32618")
    return s, t


def contain() -> Figure:
    import urbanweave as uw

    zones = [box(0, 0, 50, 60), box(50, 0, 100, 60)]
    pts = [Point(20, 35), Point(80, 20), Point(50, 30)]
    s, t = _uw_frames(pts, zones, ["p1", "p2", "on edge"])
    got = dict(zip(*uw.match(s, t, "contain").pairs[["source_id", "target_id"]].T.values))
    p = Panel(f"Each point goes to the polygon containing it. A point on a shared edge goes to one polygon only, "
              f"the lowest ID ({got['on edge']}), so it is never counted twice.", heading="contain", w=220,
              extent=(-4, -4, 104, 64))
    for z, n in zip(zones, "AB"):
        p.geom(z, "tgt").text(z.centroid.x, 50, n)
    for g, sid in zip(pts, ("p1", "p2", "on edge")):
        p.point(g.x, g.y, "src-pt", label=f"{sid} → {got[sid]}")
    return Figure("", [p])


def centroid_and_representative_point() -> Figure:
    import urbanweave as uw

    U = box(0, 0, 90, 60).difference(box(30, 20, 60, 60))
    court, rest = box(25, 15, 65, 64), box(-5, -5, 95, 64).difference(box(25, 15, 65, 64))
    s, t = _uw_frames([U], [court, rest], ["lot"], ["courtyard", "building"])
    c = uw.match(s, t, "centroid").pairs["target_id"].iloc[0]
    r = uw.match(s, t, "representative_point").pairs["target_id"].iloc[0]
    out = []
    for method, pt, got in (("centroid", U.centroid, c), ("representative_point", U.representative_point(), r)):
        p = Panel(f"{'The geometric centre, which can fall outside a concave shape' if method == 'centroid' else 'A point guaranteed inside the polygon'}: "
                  f"the lot goes to the {got}.", heading=method, w=200, extent=(-8, -8, 98, 68))
        p.geom(rest, "tgt", opacity=0.25).geom(U, "src", opacity=0.85).geom(court, "tgt", opacity=0.45)
        p.text(45, 55, "courtyard", cls="small").text(80, 63, "building", cls="small")
        p.point(pt.x, pt.y, "vertex", r=5).text(pt.x, pt.y, method.replace("_", " "), dy=-9, cls="lbl")
        out.append(p)
    return Figure("One point per polygon", out)


def area_overlap() -> Figure:
    import urbanweave as uw

    zones = [box(0, 0, 60, 60), box(60, 0, 100, 40), box(60, 40, 100, 60)]
    tract = Polygon([(20, 10), (85, 15), (90, 52), (30, 50)])
    s, t = _uw_frames([tract], zones)
    pairs = uw.match(s, t, "area_overlap").pairs.set_index("target_id")
    p = Panel("area_overlap splits the source among the targets it overlaps: allocation_fraction is each "
              "target's share of the source, overlap_measure the area in m².", heading="area_overlap", w=230,
              extent=(-4, -4, 104, 64))
    corner = {"A": (4, 52, "start"), "B": (96, 3, "end"), "C": (96, 52, "end")}
    for z, n in zip(zones, "ABC"):
        p.geom(z, "tgt").text(corner[n][0], corner[n][1], n, anchor=corner[n][2])
    p.geom(tract, "src", opacity=0.7)
    for z, n in zip(zones, "ABC"):
        piece = tract.intersection(z)
        if not piece.is_empty and n in pairs.index:
            c = piece.representative_point()
            p.text(c.x, c.y, f"{pairs.loc[n, 'allocation_fraction']:.2f}", cls="lbl")
    q = Panel(f"largest_overlap sends the whole source to the target it overlaps most ({pairs['allocation_fraction'].idxmax()}).",
              heading="largest_overlap", w=180, extent=(-4, -4, 104, 64))
    for z, n in zip(zones, "ABC"):
        q.geom(z, "tgt", opacity=1 if n == pairs["allocation_fraction"].idxmax() else 0.35)
        q.text(corner[n][0], corner[n][1], n, anchor=corner[n][2])
    q.geom(tract, "src", opacity=0.7).text(*tract.representative_point().coords[0], "1.00", cls="lbl")
    return Figure("Splitting a polygon by area", [p, q])


def nearest_and_within_distance() -> Figure:
    import urbanweave as uw

    stops = [Point(25, 30), Point(75, 35)]
    crashes = [Point(10, 40), Point(40, 18), Point(50, 52), Point(95, 5), Point(62, 28)]
    s, t = _uw_frames(crashes, stops, [f"c{i}" for i in range(5)], ["S1", "S2"])
    near = uw.match(s, t, "nearest", max_distance=25).pairs
    p = Panel("nearest: each crash to its nearest stop, within max_distance (dashed). Beyond it (×), a crash is "
              "reported as unmatched, not forced onto a far stop.", heading="nearest, max_distance = 25 m", w=220,
              extent=(-4, -4, 104, 64))
    for st in stops:
        p.circle(st.x, st.y, 25)
    matched = set(near["source_id"])
    for i, c in enumerate(crashes):
        sid = f"c{i}"
        if sid in matched:
            tgt = stops[0] if near.set_index("source_id").loc[sid, "target_id"] == "S1" else stops[1]
            p.line([(c.x, c.y), (tgt.x, tgt.y)], "none", width=1.3)
            p.point(c.x, c.y, "src-pt", r=4.5)
        else:
            p.point(c.x, c.y, "src-pt", r=4.5).cross(c.x, c.y, size=3.5)
    for st, n in zip(stops, ("S1", "S2")):
        p.point(st.x, st.y, "tgt-pt", r=6, label=n)
    one = [Point(50, 30)]
    s1, t1 = _uw_frames(one, stops, ["c"], ["S1", "S2"])
    split = uw.match(s1, t1, "within_distance", distance=30).pairs["allocation_fraction"].tolist()
    q = Panel(f"within_distance: a crash within 30 m of two stops is split between them ({split[0]:g} each) "
              "with split=True, or counted whole at both with split=False.", heading="within_distance",
              w=200, extent=(-4, -4, 104, 64))
    q.circle(50, 30, 30)
    for st, n in zip(stops, ("S1", "S2")):
        q.line([(50, 30), (st.x, st.y)], "none", width=1.3).point(st.x, st.y, "tgt-pt", r=6, label=n)
    q.point(50, 30, "src-pt", r=5).text(50, 30, f"{split[0]:g} | {split[1]:g}", dy=-10, cls="lbl")
    return Figure("Distance-based matching", [p, q])


def gaussian() -> Figure:
    sigma = 20.0
    d = np.linspace(0, 70, 120)
    w = np.exp(-0.5 * (d / sigma) ** 2)
    p = Panel("Each point spreads over nearby targets with weight exp(−d²/2σ²), normalized so the point's "
              "weights sum to 1. Beyond about 3σ the weight is negligible.", heading="gaussian, σ = 20 m",
              w=320, h=170, extent=(-6, -14, 76, 60))
    p.line([(0, 0), (72, 0)], "ghost").line([(0, 0), (0, 52)], "ghost")
    p.line(list(zip(d, 50 * w)), "src", width=2.2)
    targets = [8.0, 25.0, 41.0, 63.0]
    raw = np.exp(-0.5 * (np.array(targets) / sigma) ** 2)
    norm = raw / raw.sum()
    for x, v, n in zip(targets, raw, norm):
        p.line([(x, 0), (x, 50 * v)], "tgt", width=2).point(x, 50 * v, "tgt-pt", r=4)
        p.text(x, 50 * v, f"{n:.2f}", dy=-8, cls="lbl")
    p.text(36, 0, "distance from the point (m)", dy=14, cls="small")
    for k in (1, 2, 3):
        p.text(k * sigma, 0, f"{k}σ", dy=24, cls="small")
    return Figure("Smoothing with a Gaussian kernel", [p])


# ===================================================================================== grids, rasters, lines
def grid_to_targets() -> Figure:
    cells = [(cx, cy) for cx, cy in _hex_lattice(13, 0, 100, 0, 100) if 5 <= cx <= 95 and 5 <= cy <= 95]
    vals = {c: (i * 7) % 5 for i, c in enumerate(cells)}

    def base(caption, heading):
        p = Panel(caption, heading=heading, w=200, h=160, extent=(-4, -4, 104, 104))
        for c in cells:
            p.geom(_hex(*c, 13), "cell")
        return p

    a = base("To polygons: by each cell's centroid (whole cells) or by area (split at the boundary).", "grid → polygons")
    a.geom(Polygon([(10, 10), (70, 15), (80, 80), (20, 70)]), "tgt", opacity=0.55)
    for c in cells:
        a.point(*c, "vertex", r=2)
    b = base("To points: each point takes its cell's value; two points in one cell get the same value.", "grid → points")
    tc = cells[len(cells) // 2]
    b.geom(_hex(*tc, 13), "sel")
    b.point(tc[0] - 4, tc[1] + 3, "tgt-pt", r=4.5).point(tc[0] + 5, tc[1] - 4, "tgt-pt", r=4.5)
    b.point(cells[2][0], cells[2][1], "tgt-pt", r=4.5)
    c = base("To lines: the length of the line inside each cell weights the cell's value.", "grid → lines")
    line = LineString([(5, 20), (95, 75)])
    for cc in cells:
        piece = line.intersection(_hex(*cc, 13))
        if piece.length > 0:
            c.geom(_hex(*cc, 13), "sel")
            m = piece.interpolate(0.5, normalized=True)
            c.text(m.x, m.y, f"{piece.length:.0f}", dx=-7, dy=-5, cls="val")
    c.geom(line, "tgt", width=2.5)
    return Figure("From a grid to other targets", [a, b, c])


def zonal_rules() -> Figure:
    size, n = 20, 5
    zone = Point(52, 48).buffer(31, quad_segs=32)
    cells = [(c, r, box(c * size, (n - 1 - r) * size, (c + 1) * size, (n - r) * size)) for r in range(n) for c in range(n)]
    cov = {(c, r): g.intersection(zone).area / g.area for c, r, g in cells}
    centre_in = {(c, r): zone.contains(g.centroid) for c, r, g in cells}
    touched = sum(v > 0 for v in cov.values())
    covered = sum(cov.values())
    a = Panel(f"cell_coverage: every cell the zone touches, weighted by the share it covers: {touched} cells "
              f"touched, {covered:.1f} cells' worth of area (count and weighted_count).",
              heading="cell_coverage (exact)", w=210, h=180, extent=(-4, -4, 104, 104))
    for c, r, g in cells:
        f = cov[(c, r)]
        px, py = a.xy(g.bounds[0], g.bounds[3])
        a.raw(f'<rect x="{px:.1f}" y="{py:.1f}" width="{size * a._k:.1f}" height="{size * a._k:.1f}" '
              f'fill="var(--sel)" fill-opacity="{f:.2f}" stroke="var(--rule)"/>')
        if f > 0:
            a.text(g.centroid.x, g.centroid.y, f"{f:.1f}".lstrip("0") if f < 0.95 else "1", cls="val", dy=3)
    a.geom(zone, "tgt", opacity=0)
    kept = sum(centre_in.values())
    b = Panel(f"cell_center: a cell counts wholly if its centre is inside the zone: {kept} cells. Simple and "
              "fast; small zones can miss most of their area.", heading="cell_center", w=210, h=180,
              extent=(-4, -4, 104, 104))
    for c, r, g in cells:
        b.geom(g, "sel" if centre_in[(c, r)] else "cell")
        b.point(g.centroid.x, g.centroid.y, "vertex", r=2)
    b.geom(zone, "tgt", opacity=0)
    nod = {(2, 1), (3, 1)}
    valid = sum(v for k, v in cov.items() if k not in nod)
    c = Panel(f"Nodata cells (hatched) are left out: coverage stays {covered / covered:.0%} of the zone's area, "
              f"valid_coverage drops to {valid / covered:.0%}.", heading="coverage and valid coverage", w=200, h=180,
              extent=(-4, -4, 104, 104))
    for cc, r, g in cells:
        c.geom(g, "hatch" if (cc, r) in nod else "cell")
    c.geom(zone, "tgt", opacity=0.35)
    return Figure("Which cells count: two rules", [a, b, c])


def along_lines_and_split() -> Figure:
    size = 25
    vals = [10, 10, 30, 20]
    line = LineString([(5, 5), (95, 5)])
    a = Panel("along_lines: the line's length in each cell weights the cell's value: a mean by valid length.",
              heading="along_lines", w=240, h=110, extent=(-4, -14, 104, 36))
    pieces = []
    for i, v in enumerate(vals):
        cell = box(i * size, 0, (i + 1) * size, size)
        piece = line.intersection(cell)
        pieces.append((v, piece.length))
        a.grid(i * size, 0, 1, 1, size, values=[[v]], shade=lambda x: (x - 5) / 30, fmt="{:g}")
        a.text(cell.centroid.x, -6, f"{piece.length:.0f} m", cls="small")
    a.geom(line, "tgt", width=3)
    mean = sum(v * l for v, l in pieces) / sum(l for _, l in pieces)
    a.text(50, 33, f"mean = Σ value × m / Σ m = {mean:.1f}", dy=-2, cls="lbl")
    b = Panel("A line exactly on a cell edge belongs to one cell: a cell owns its west and north edges, so here "
              "the east cells. Its length counts once.", heading="Lines on a cell edge",
              w=200, extent=(-4, -4, 54, 54))
    b.grid(0, 0, 2, 2, 25, values=[[1, 2], [3, 4]])
    b.geom(box(25, 0, 50, 50), "sel", opacity=0.5)
    b.geom(LineString([(25, 3), (25, 47)]), "tgt", width=3)
    c = Panel("split_lines cuts lines at zone boundaries into pieces with stable IDs (line|zone); pieces are "
              "summarised, then pooled per zone with ratio_of_sums.", heading="split_lines", w=210,
              extent=(-4, -4, 104, 54))
    c.geom(box(0, 0, 60, 50), "cell").geom(box(60, 0, 100, 50), "cell")
    c.text(5, 43, "z1", anchor="start").text(65, 43, "z2", anchor="start")
    c.geom(LineString([(8, 22), (60, 22)]), "tgt", width=3).geom(LineString([(60, 22), (95, 22)]), "src", width=3)
    c.point(60, 22, "vertex", r=3.5)
    c.text(34, 22, "main|z1", dy=-9, cls="lbl").text(78, 22, "main|z2", dy=-9, cls="lbl")
    return Figure("Raster values along streets", [a, b, c])


def plan_flow() -> Figure:
    p = Panel("", w=660, h=150, extent=(0, 0, 660, 150), pad=0)

    def node(x, y, w, h, title, sub, kind="cell"):
        p.geom(box(x, y, x + w, y + h), kind, width=1.4)
        p.text(x + w / 2, y + h - 16, title, cls="cap-b").text(x + w / 2, y + h - 31, sub, cls="small")

    node(10, 85, 110, 50, "plan.json", "sources · targets · steps")
    node(150, 85, 110, 50, "validate", "before anything runs", "tgt")
    node(290, 85, 110, 50, "run", "steps in order", "tgt")
    node(430, 85, 100, 50, "result", "one row per target")
    node(290, 10, 110, 50, "cache", "artifacts by content hash")
    node(430, 10, 100, 50, "manifest", "fingerprints · versions")
    node(555, 10, 95, 50, "replay", "verifies, then reruns", "src")
    for a, b in (((120, 110), (148, 110)), ((260, 110), (288, 110)), ((400, 110), (428, 110)), ((345, 85), (345, 62)),
                 ((400, 35), (428, 35)), ((530, 35), (553, 35))):
        p.line([a, b], arrow=True)
    p.line([(602, 60), (602, 100), (532, 100)], arrow=True, dash=True)
    return Figure("A plan: validate, run, record, replay", [p])


def dasymetric() -> Figure:
    """Dasymetric disaggregation: a zone total spread over cells the way a prior sample spreads."""
    zone = Polygon([(8, 12), (70, 5), (95, 40), (80, 92), (25, 88), (5, 55)])
    rng = np.random.default_rng(4)
    pts = []
    while len(pts) < 70:  # pickups crowd along an avenue (x ≈ 55) and a cross street (y ≈ 45)
        if rng.random() < 0.55:
            x, y = 55 + rng.normal(0, 3.5), rng.uniform(8, 92)
        else:
            x, y = rng.uniform(5, 95), 45 + rng.normal(0, 3.5)
        if zone.contains(Point(x, y)):
            pts.append((x, y))
    r = 9.0
    hexes = [(c, _hex(*c, r)) for c in _hex_lattice(r, -5, 105, -5, 105)]
    hexes = [(c, h) for c, h in hexes if zone.contains(Point(c))]
    counts = {c: sum(h.contains(Point(p)) for p in pts) for c, h in hexes}
    total, prior = 1200, sum(counts.values())

    a = Panel(f"Later years report only the zone's total: {total:,} pickups, with no locations.",
              heading="1 · Zone totals only", w=200, h=170)
    a.geom(zone, "tgt").text(50, 50, f"{total:,}", cls="title")
    b = Panel("An earlier year with exact coordinates shows where, inside the zone, pickups happen.",
              heading="2 · A prior with locations", w=200, h=170)
    b.geom(zone, "tgt", opacity=0.35)
    for x, y in pts:
        b.point(x, y, "src-pt", r=2.6)
    c = Panel(f"Each cell gets the total times its share of the prior: the {total:,} trips land where taxis "
              "actually stop, and the zone's total is kept.", heading="3 · Total spread like the prior", w=220, h=170)
    top = max(counts.values()) or 1
    for cc, h in hexes:
        k = counts[cc]
        px, py = c.xy(*h.exterior.coords[0])
        c.geom(h, "cell")
        if k:
            c.geom(h, "sel", opacity=0.25 + 0.75 * k / top)
            c.text(cc[0], cc[1], f"{total * k / prior:.0f}", cls="val", dy=3)
    c.geom(zone, "none", width=1.8)
    return Figure("Dasymetric disaggregation", [a, b, c])
