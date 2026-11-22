"""Static SVG charts for the taxi-over-time notebook, in the tutorials' map style (``svgmap``).

    line_chart(frame, "Pickups per month")     # index: months; columns: series (at most three)
    heat_grid(frame, "Pickups per km", bounds) # rows x columns of classed cells
    grid([map1, map2, ...], columns=5)         # small multiples of svgmap maps in one SVG

Same palette, light and dark variants and hover tooltips (``<title>``) as the maps; NumPy and
pandas only, so the notebook renders the same on GitHub and offline.
"""

from __future__ import annotations

import html
import re

import numpy as np
import pandas as pd

from svgmap import CAT_DARK, CAT_LIGHT, DIV_DARK, DIV_LIGHT, SEQ_DARK, SEQ_LIGHT, STYLE, _short, _vars

FONT_W = 6.2  # approximate width of an 11 px character, for layout


def _style() -> str:
    return STYLE % {"seq_l": _vars("s", SEQ_LIGHT), "seq_d": _vars("s", SEQ_DARK),
                    "div_l": _vars("d", DIV_LIGHT), "div_d": _vars("d", DIV_DARK),
                    "cat_l": _vars("c", CAT_LIGHT), "cat_d": _vars("c", CAT_DARK)}


class _SVG:
    def __init__(self, svg: str):
        self.svg = svg

    def _repr_svg_(self) -> str:
        return self.svg

    def save(self, path) -> None:
        from pathlib import Path
        Path(path).write_text(self.svg)


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = max(hi - lo, 1e-12)
    step = 10 ** np.floor(np.log10(span / n))
    for m in (1, 2, 5, 10):
        if span / (m * step) <= n:
            step *= m
            break
    return list(np.arange(np.ceil(lo / step) * step, hi + step * 1e-9, step))


def line_chart(frame: pd.DataFrame, title: str, *, y_label: str = "", events: dict | None = None,
               width: int = 680, height: int = 280, y_min: float | None = 0, fmt=_short, note: str = "") -> _SVG:
    """One line per column (fixed categorical order, at most three), the index as monthly time
    ('YYYY-MM' strings or timestamps). *events* maps an index value to a short label drawn as a
    dashed vertical rule. Each point has a hover tooltip; lines are labelled at their right end."""
    if frame.shape[1] > 3:
        raise ValueError("At most three series (fold the rest into 'other' or use small multiples).")
    idx = pd.PeriodIndex(pd.to_datetime(pd.Index(frame.index).astype(str)), freq="M")
    x_num = np.arange(len(idx), dtype=float)
    vals = frame.to_numpy(float)
    multi = frame.shape[1] > 1
    label_w = max((len(str(c)) for c in frame.columns), default=0) * FONT_W + 12 if multi else 8
    left, right, top, bottom = 52, label_w + 4, 70 if multi else 50, 30 + (16 if note else 0)
    pw, ph = width - left - right, height - top - bottom
    lo = np.nanmin(vals) if y_min is None else y_min
    hi = np.nanmax(vals)
    ticks = _ticks(lo, hi)
    hi = max(hi, ticks[-1])
    X = lambda i: left + pw * i / max(len(idx) - 1, 1)
    Y = lambda v: top + ph * (1 - (v - lo) / (hi - lo if hi > lo else 1))
    out = [f'<text class="title" x="1" y="18">{html.escape(title)}</text>']
    if multi:  # legend row: identity is never color alone
        x = 1.0
        for i, c in enumerate(frame.columns):
            out.append(f'<line x1="{x}" y1="35" x2="{x + 16}" y2="35" stroke="var(--c{i})" stroke-width="2.5" '
                       f'stroke-linecap="round"/><text x="{x + 21}" y="39">{html.escape(str(c))}</text>')
            x += 34 + FONT_W * len(str(c))
    for t in ticks:
        y = Y(t)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" stroke="var(--rule)" '
                   f'stroke-width="{1 if t == lo else 0.5}"/>'
                   f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt(t)}</text>')
    if y_label:
        out.append(f'<text x="1" y="{top - 14}" style="fill:var(--muted)">{html.escape(y_label)}</text>')
    for i, p in enumerate(idx):
        if p.month == 1:
            x = X(i)
            out.append(f'<line x1="{x:.1f}" y1="{top + ph}" x2="{x:.1f}" y2="{top + ph + 4}" stroke="var(--muted)"/>'
                       f'<text x="{x:.1f}" y="{top + ph + 16}" text-anchor="middle">{p.year}</text>')
    for k, (key, text) in enumerate((events or {}).items()):
        p = pd.Period(str(key), freq="M")
        if p not in idx:
            continue
        x = X(idx.get_loc(p))
        near_end = x + 8 + FONT_W * len(text) > left + pw
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + ph}" stroke="var(--muted)" '
                   f'stroke-dasharray="3 3"/><text x="{x - 4 if near_end else x + 4:.1f}" '
                   f'y="{top + 10 + 13 * (k % 2):.1f}" text-anchor="{"end" if near_end else "start"}" '
                   f'style="fill:var(--muted)">{html.escape(text)}</text>')
    ends = []
    for j, c in enumerate(frame.columns):
        v = vals[:, j]
        ok = np.isfinite(v)
        pts = " ".join(f"{X(i):.1f},{Y(v[i]):.1f}" for i in np.flatnonzero(ok))
        out.append(f'<polyline points="{pts}" fill="none" stroke="var(--c{j})" stroke-width="2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        last = np.flatnonzero(ok)[-1]
        ends.append([Y(v[last]), str(c), j])
    if multi:  # direct labels at the line ends, nudged apart
        ends.sort()
        for a in range(1, len(ends)):
            ends[a][0] = max(ends[a][0], ends[a - 1][0] + 13)
        for y, name, j in ends:
            out.append(f'<text x="{left + pw + 6}" y="{y + 4:.1f}" style="fill:var(--ink)">{html.escape(name)}</text>')
    for i, p in enumerate(idx):  # hover: one band per month, its tooltip lists every series
        tip = f"{p.strftime('%b %Y')}\n" + "\n".join(f"{c}: {fmt(vals[i, j])}" for j, c in enumerate(frame.columns))
        out.append(f'<rect x="{X(i) - pw / len(idx) / 2:.1f}" y="{top}" width="{pw / len(idx):.2f}" height="{ph}" '
                   f'fill="transparent" class="feature"><title>{html.escape(tip)}</title></rect>')
    if note:
        out.append(f'<text x="1" y="{height - 4}" style="fill:var(--muted)">{html.escape(note)}</text>')
    return _SVG(f'<svg xmlns="http://www.w3.org/2000/svg" class="uwmap" width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
                f'<style>{_style()}</style><rect width="{width}" height="{height}" fill="var(--surface)"/>'
                f'{"".join(out)}</svg>')


def heat_grid(frame: pd.DataFrame, title: str, bounds: list[float], *, legend: str = "", fmt=_short,
              cell: tuple[int, int] = (44, 20), note: str = "") -> _SVG:
    """Rows x columns of cells classed by *bounds* on the sequential ramp, a 2 px gap between cells,
    row labels at the left, column labels on top, a tooltip on every cell."""
    cw, ch = cell
    left = int(max(len(str(r)) for r in frame.index) * FONT_W) + 10
    top = 46
    W = left + cw * frame.shape[1] + 4
    H = top + ch * frame.shape[0] + 52 + (16 if note else 0)
    out = [f'<text class="title" x="1" y="18">{html.escape(title)}</text>']
    for j, c in enumerate(frame.columns):
        out.append(f'<text x="{left + j * cw + cw / 2:.1f}" y="{top - 6}" text-anchor="middle">{html.escape(str(c))}</text>')
    edges = np.asarray(bounds, float)
    for i, r in enumerate(frame.index):
        y = top + i * ch
        out.append(f'<text x="{left - 6}" y="{y + ch / 2 + 4:.1f}" text-anchor="end" style="fill:var(--ink)">'
                   f'{html.escape(str(r))}</text>')
        for j, c in enumerate(frame.columns):
            v = frame.iat[i, j]
            if not np.isfinite(v):
                fill = "var(--surface)"
            else:
                k = min(int(np.searchsorted(edges[1:-1], v, side="right")), len(edges) - 2)
                fill = f"var(--s{k})"
            out.append(f'<rect class="feature" x="{left + j * cw + 1:.1f}" y="{y + 1:.1f}" width="{cw - 2}" '
                       f'height="{ch - 2}" rx="2" style="fill:{fill}"><title>{html.escape(f"{r}, {c}: {fmt(v)}")}'
                       f'</title></rect>')
    y = top + ch * frame.shape[0] + 14
    if legend:
        out.append(f'<text x="1" y="{y:.1f}" style="fill:var(--ink);font-weight:600">{html.escape(legend)}</text>')
    n = len(edges) - 1
    sw = min(56, (W - 20) / n)
    for k in range(n):
        out.append(f'<rect x="{1 + k * sw:.1f}" y="{y + 6:.1f}" width="{sw - 2:.1f}" height="10" rx="2" style="fill:var(--s{k})"/>')
    for k, e in enumerate(edges):
        out.append(f'<text x="{1 + k * sw:.1f}" y="{y + 29:.1f}" text-anchor="{"start" if k == 0 else "middle"}">{fmt(e)}</text>')
    if note:
        out.append(f'<text x="1" y="{H - 4}" style="fill:var(--muted)">{html.escape(note)}</text>')
    return _SVG(f'<svg xmlns="http://www.w3.org/2000/svg" class="uwmap" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
                f'role="img" aria-label="{html.escape(title)}"><style>{_style()}</style>'
                f'<rect width="{W}" height="{H}" fill="var(--surface)"/>{"".join(out)}</svg>')


def grid(maps, *, columns: int = 5, gap: int = 8, title: str = "", shared_legend: bool = False) -> _SVG:
    """Small multiples: svgmap maps (or anything with ``to_svg``) side by side in one SVG; ids are
    made unique per map. With *shared_legend*, the maps are drawn without their legends (give them the
    same bounds) and the first map's legend is drawn once, under the grid."""
    svgs = []
    maps = list(maps)
    for m in maps:
        if shared_legend:
            m.show_legend = False
    for i, m in enumerate(maps):
        s = m.to_svg() if hasattr(m, "to_svg") else m._repr_svg_()
        s = s.replace("uw-hatch", f"uw{i}-hatch").replace("uw-clip", f"uw{i}-clip")
        w, h = (float(v) for v in re.search(r'width="([\d.]+)" height="([\d.]+)"', s).groups())
        svgs.append((s, w, h))
    cw = max(w for _, w, _ in svgs)
    rows = [svgs[k:k + columns] for k in range(0, len(svgs), columns)]
    top = 26 if title else 0
    out, y = [], top
    for row in rows:
        rh = max(h for _, _, h in row)
        for j, (s, w, h) in enumerate(row):
            out.append(s.replace("<svg ", f'<svg x="{j * (cw + gap):.0f}" y="{y:.0f}" ', 1))
        y += rh + gap
    W = int(min(columns, len(svgs)) * (cw + gap) - gap)
    if shared_legend:
        from svgmap import Map
        key = Map(width=W)
        key._legends, key._notes = maps[0]._legends, maps[0]._notes
        legend, lh = key._legend_svg(y)
        out.append('<defs><pattern id="uw-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
                   'patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--surface)"/>'
                   '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch)" stroke-width="2"/></pattern></defs>' + legend)
        y += lh + gap
    head = f'<text class="title" x="1" y="18">{html.escape(title)}</text>' if title else ""
    return _SVG(f'<svg xmlns="http://www.w3.org/2000/svg" class="uwmap" width="{W}" height="{y - gap:.0f}" '
                f'viewBox="0 0 {W} {y - gap:.0f}" role="img" aria-label="{html.escape(title)}"><style>{_style()}</style>'
                f'<rect width="{W}" height="{y - gap:.0f}" fill="var(--surface)"/>{head}{"".join(out)}</svg>')
