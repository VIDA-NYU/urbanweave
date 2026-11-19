"""Shared helpers. Projected fixtures sit at UTM zone 18N's central meridian (x = 500 000 m), so the
measurement CRS urbanweave resolves is the fixtures' own CRS and hand-calculated areas, lengths and
distances hold to 1e-9."""

import geopandas as gpd
import pytest
from shapely.geometry import box

UTM18 = "EPSG:32618"
X0, Y0 = 500_000.0, 4_500_000.0
TOL = dict(rel=1e-9, abs=1e-9)


def frame(geoms, crs=UTM18, **columns):
    return gpd.GeoDataFrame(dict(columns), geometry=list(geoms), crs=crs)


def sq(x, y, w, h=None):
    """A box with its lower-left corner at (X0 + x, Y0 + y)."""
    h = w if h is None else h
    return box(X0 + x, Y0 + y, X0 + x + w, Y0 + y + h)


def pt(x, y):
    from shapely.geometry import Point

    return Point(X0 + x, Y0 + y)


def ln(*coords):
    from shapely.geometry import LineString

    return LineString([(X0 + x, Y0 + y) for x, y in coords])


@pytest.fixture
def approx():
    return lambda v: pytest.approx(v, **TOL)
