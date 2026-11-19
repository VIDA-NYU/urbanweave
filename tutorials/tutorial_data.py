"""Riverton: a small synthetic town for the urbanweave tutorials.

Every function returns the same data on every call (fixed seeds), in UTM zone 18N (EPSG:32618,
metres) unless it says otherwise, so the notebooks need no downloads. The town is 3 km × 2 km around
(500 000, 4 500 000), which is near 75° W, 40.65° N.

- ``districts()``: five named districts that partition the town.
- ``tracts()``: 18 census tracts, a different partition, with ``population`` (people, extensive;
  the riverside park tract has 0) and ``median_income`` (dollars, intensive; one tract unreported).
- ``crashes_table()``: 600 crashes as a plain table with ``latitude``/``longitude``, the way a city
  portal publishes them; ``persons_injured``, ``hour`` and ``severity``.
- ``street_graph()``: an OSMnx-style graph: a 250 m grid of two-way streets and Main Blvd, a divided
  road whose two carriageways are separate one-way edges. ``save_street_graph(path)`` writes GraphML.
- ``bus_stops()``: 14 stops at intersections.
- ``heat()``: UTCI (°C) on 10 m cells: hot downtown, cooler by the river and in the park, with a
  sensor gap (nodata).
- ``land_cover()``: 1 built, 2 green, 3 water on the same 10 m grid.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box

CRS = "EPSG:32618"
X0, Y0 = 500_000.0, 4_500_000.0
HALF_W, HALF_H = 1500.0, 1000.0
TOWN = box(X0 - HALF_W, Y0 - HALF_H, X0 + HALF_W, Y0 + HALF_H)
BLOCK = 250.0
CELL = 10.0


def _voronoi(seeds) -> list[Polygon]:
    pts = MultiPoint([Point(X0 + x, Y0 + y) for x, y in seeds])
    cells = shapely.voronoi_polygons(pts, extend_to=TOWN)
    by_seed = {}
    for c in shapely.get_parts(cells):
        for i, p in enumerate(pts.geoms):
            if c.contains(p):
                by_seed[i] = c.intersection(TOWN)
    return [by_seed[i] for i in range(len(seeds))]


def river() -> Polygon:
    """The river: a band crossing the south-east corner."""
    line = LineString([(X0 + 200, Y0 - 1100), (X0 + 700, Y0 - 600), (X0 + 1100, Y0 - 450), (X0 + 1600, Y0 - 300)])
    return line.buffer(70)


def park() -> Polygon:
    return box(X0 - 1150, Y0 + 300, X0 - 650, Y0 + 750)


def districts() -> gpd.GeoDataFrame:
    seeds = [(-800, 500), (100, 150), (900, 550), (-700, -500), (700, -600)]
    names = ["Northgate", "Old Town", "Eastfield", "Mill District", "Riverside"]
    ids = ["NG", "OT", "EF", "MD", "RS"]
    return gpd.GeoDataFrame({"district_id": ids, "name": names}, geometry=_voronoi(seeds), crs=CRS)


def tracts() -> gpd.GeoDataFrame:
    rng = np.random.default_rng(7)
    xs = np.linspace(-1250, 1250, 6)
    ys = np.linspace(-700, 700, 3)
    seeds = [(x + rng.uniform(-120, 120), y + rng.uniform(-150, 150)) for y in ys for x in xs]
    geoms = _voronoi(seeds)
    centre = np.array([[x, y] for x, y in seeds])
    dist = np.hypot(centre[:, 0] - 100, centre[:, 1] - 150)
    pop = (5200 * np.exp(-(dist / 1100) ** 2) + rng.integers(300, 900, len(seeds))).round().astype("int64")
    income = 52_000 + 0.9 * np.abs(centre[:, 0]) * 30 + rng.normal(0, 6000, len(seeds))
    frame = gpd.GeoDataFrame({"tract_id": [f"T{i:02d}" for i in range(len(seeds))], "population": pop,
                              "median_income": income.round(-2)}, geometry=geoms, crs=CRS)
    park_tract = int(np.argmax([g.intersection(park()).area / g.area for g in geoms]))
    frame.loc[park_tract, "population"] = 0  # the park: nobody lives there, a true zero
    frame.loc[park_tract, "median_income"] = np.nan  # and so no income is reported
    frame.loc[(park_tract + 7) % len(frame), "median_income"] = np.nan  # suppressed for privacy
    frame["population"] = frame["population"].astype("int64")
    return frame


def _street_lines():
    rows = []
    xs = np.arange(-HALF_W, HALF_W + 1, BLOCK)
    ys = np.arange(-HALF_H, HALF_H + 1, BLOCK)
    for i, x in enumerate(xs):
        rows.append((f"{i + 1}{'st' if i == 0 else 'nd' if i == 1 else 'rd' if i == 2 else 'th'} Ave", "x", x))
    for j, y in enumerate(ys):
        if y == 0:
            continue  # Main Blvd, built separately
        rows.append((f"{'ABCDEFGHI'[j]} St", "y", y))
    return xs, ys, rows


def street_graph():
    """A MultiDiGraph in the shape OSMnx produces (node x/y, edge osmid, name, geometry, length)."""
    import networkx as nx

    G = nx.MultiDiGraph(crs=CRS)
    xs, ys, _ = _street_lines()
    nid = {}
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            nid[(i, j)] = len(nid) + 1
            G.add_node(nid[(i, j)], x=X0 + x, y=Y0 + y, street_count=0)
    way = 100

    def add(a, b, name, oneway, geom, highway="residential"):
        G.add_edge(a, b, osmid=way, name=name, highway=highway, oneway=oneway, reversed=False,
                   length=geom.length, geometry=geom)

    jmain = int(np.flatnonzero(ys == 0)[0])
    for i, x in enumerate(xs):  # avenues, two-way: reciprocal edges of one OSM way per block
        name = f"{i + 1}{'st' if i == 0 else 'nd' if i == 1 else 'rd' if i == 2 else 'th'} Ave"
        for j in range(len(ys) - 1):
            a, b = nid[(i, j)], nid[(i, j + 1)]
            g = LineString([(X0 + x, Y0 + ys[j]), (X0 + x, Y0 + ys[j + 1])])
            add(a, b, name, False, g)
            add(b, a, name, False, g.reverse())
            way += 1
    for j, y in enumerate(ys):
        for i in range(len(xs) - 1):
            a, b = nid[(i, j)], nid[(i + 1, j)]
            p, q = (X0 + xs[i], Y0 + y), (X0 + xs[i + 1], Y0 + y)
            if j == jmain:  # Main Blvd: two carriageways 12 m apart, each one-way
                east = LineString([p, (p[0] + 40, p[1] - 6), (q[0] - 40, q[1] - 6), q])
                west = LineString([q, (q[0] - 40, q[1] + 6), (p[0] + 40, p[1] + 6), p])
                add(a, b, "Main Blvd", True, east, "primary")
                way += 1
                add(b, a, "Main Blvd", True, west, "primary")
            else:
                g = LineString([p, q])
                name = f"{'ABCDEFGHI'[j]} St"
                add(a, b, name, False, g)
                add(b, a, name, False, g.reverse())
            way += 1
    return G


def save_street_graph(path) -> None:
    import osmnx as ox

    ox.save_graphml(street_graph(), path)


def _street_points(rng, n):
    """Random points along the street grid, weighted towards downtown and Main Blvd."""
    xs, ys, _ = _street_lines()
    out = []
    while len(out) < n:
        if rng.random() < 0.5:  # along an avenue
            x = rng.choice(xs)
            y = rng.normal(150, 450)
        else:  # along a street; Main Blvd (y=0) gets a third of these
            y = 0.0 if rng.random() < 0.35 else rng.choice(ys)
            x = rng.normal(100, 650)
        if abs(x) > HALF_W - 5 or abs(y) > HALF_H - 5:
            continue
        out.append((x + rng.normal(0, 4), y + rng.normal(0, 4)))
    return np.array(out)


def crashes() -> gpd.GeoDataFrame:
    """The crashes as points in UTM (what ``points_from_columns`` makes of ``crashes_table``)."""
    rng = np.random.default_rng(11)
    on_street = _street_points(rng, 560)
    off = np.column_stack([rng.uniform(-HALF_W + 50, HALF_W - 50, 40), rng.uniform(-HALF_H + 50, HALF_H - 50, 40)])
    xy = np.vstack([on_street, off])
    n = len(xy)
    injured = rng.poisson(0.45, n)
    severity = np.where(injured >= 2, "serious", np.where(injured == 1, "injury", "property"))
    return gpd.GeoDataFrame({"crash_id": [f"C{i:04d}" for i in range(n)], "persons_injured": injured.astype("int64"),
                             "hour": rng.integers(0, 24, n), "severity": severity},
                            geometry=gpd.points_from_xy(X0 + xy[:, 0], Y0 + xy[:, 1]), crs=CRS)


def crashes_table() -> pd.DataFrame:
    """The crashes as a portal would publish them: a table with latitude and longitude."""
    g = crashes().to_crs(4326)
    df = pd.DataFrame(g.drop(columns="geometry"))
    df["latitude"] = g.geometry.y.round(7)
    df["longitude"] = g.geometry.x.round(7)
    return df


def bus_stops() -> gpd.GeoDataFrame:
    rng = np.random.default_rng(5)
    xs, ys, _ = _street_lines()
    picks = set()
    while len(picks) < 14:
        picks.add((float(rng.choice(xs[1:-1])), float(rng.choice(ys[1:-1]))))
    picks = sorted(picks)
    return gpd.GeoDataFrame({"stop_id": [f"S{i:02d}" for i in range(len(picks))]},
                            geometry=[Point(X0 + x, Y0 + y) for x, y in picks], crs=CRS)


def _grid():
    from rasterio.transform import from_origin

    cols, rows = int(2 * HALF_W / CELL), int(2 * HALF_H / CELL)
    transform = from_origin(X0 - HALF_W, Y0 + HALF_H, CELL, CELL)
    cx = X0 - HALF_W + (np.arange(cols) + 0.5) * CELL
    cy = Y0 + HALF_H - (np.arange(rows) + 0.5) * CELL
    return transform, np.meshgrid(cx, cy)


def _cover_masks(XX, YY):
    pts = shapely.points(XX.ravel(), YY.ravel())
    water = shapely.contains_xy(river(), XX.ravel(), YY.ravel()).reshape(XX.shape)
    green = shapely.contains_xy(park(), XX.ravel(), YY.ravel()).reshape(XX.shape)
    del pts
    return water, green & ~water


def land_cover():
    """1 built, 2 green, 3 water (categorical), 10 m cells."""
    import urbanweave as uw

    transform, (XX, YY) = _grid()
    water, green = _cover_masks(XX, YY)
    rng = np.random.default_rng(3)
    lc = np.ones(XX.shape, dtype="uint8")
    lc[green] = 2
    lc[(rng.random(XX.shape) < 0.08) & ~water] = 2  # street trees and yards
    lc[water] = 3
    return uw.read_raster(lc, transform=transform, crs=CRS, value_kind="categorical", names=["land_cover"])


def heat():
    """UTCI in °C on 10 m cells, with a sensor gap (nodata)."""
    import urbanweave as uw

    transform, (XX, YY) = _grid()
    water, green = _cover_masks(XX, YY)
    dx, dy = XX - (X0 + 100), YY - (Y0 + 150)
    utci = 27.0 + 7.0 * np.exp(-(dx ** 2 + dy ** 2) / (2 * 700.0 ** 2))
    dist_river = shapely.distance(river(), shapely.points(XX.ravel(), YY.ravel())).reshape(XX.shape)
    utci -= 3.0 * np.exp(-dist_river / 150.0)
    utci[green] -= 3.5
    utci += np.random.default_rng(9).normal(0, 0.2, XX.shape)
    gap = (XX > X0 + 950) & (XX < X0 + 1250) & (YY > Y0 + 350) & (YY < Y0 + 650)
    return uw.read_raster(np.ma.masked_array(utci.round(2), mask=gap), transform=transform, crs=CRS,
                          value_kind="intensive", units="degC", names=["utci"])


def show(obj) -> None:
    """Print a report (or any JSON-like value) compactly: short lists stay on one line."""
    import json
    import re

    text = json.dumps(obj, indent=1, default=str, ensure_ascii=False)
    text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + " ".join(m.group(1).split()) + "]", text)
    print(text)
