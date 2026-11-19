"""Measurement: the one projected CRS in which a step measures distances, lengths and areas.

A step either takes an explicit projected CRS (``crs=``) or resolves the local UTM zone of the
study area (every eligible source and target geometry) once, and uses it for all its geometry.
Degrees and Web Mercator are never used for measurement.

The UTM resolution refuses extents it cannot measure well, rather than measuring them badly:

- latitudes beyond 80°S or 84°N (UTM's limits; polar regions need another strategy);
- extents crossing the antimeridian;
- extents wider than :data:`MAX_UTM_SPAN_DEGREES` of longitude, where UTM's scale error grows past
  about 1%. Pass an explicit equal-area or local CRS for those.

An explicit CRS must be projected, with a linear unit (metres, feet...); its unit is converted to
metres in every result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyproj
import shapely
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info

from .errors import UnsupportedError

#: The widest extent, in degrees of longitude, that urbanweave measures in one UTM zone.
MAX_UTM_SPAN_DEGREES = 12.0
_LAT_MIN, _LAT_MAX = -80.0, 84.0


@dataclass(frozen=True)
class Measurement:
    """How a step measures: its CRS, the factor from CRS units to metres, and where it came from."""

    crs: pyproj.CRS
    unit_to_m: float
    resolved: str  # "explicit" or "utm"

    def to_dict(self) -> dict:
        name = self.crs.name
        code = self.crs.to_epsg()
        return {
            "crs": f"EPSG:{code}" if code else self.crs.to_wkt(),
            "crs_name": name,
            "basis": "planar",
            "unit_to_m": self.unit_to_m,
            "resolved": self.resolved,
        }

    def metres_to_crs(self, metres: float) -> float:
        return float(metres) / self.unit_to_m


def explicit(crs) -> Measurement:
    """A measurement in the caller's CRS, after checking that it can measure."""
    crs = pyproj.CRS.from_user_input(crs)
    if not crs.is_projected:
        raise UnsupportedError(
            f"The measurement CRS {crs.name!r} is not projected; distances, lengths and areas need a "
            "projected CRS with linear units (for example the local UTM zone)."
        )
    axis = crs.axis_info[0]
    factor = axis.unit_conversion_factor
    if not factor or axis.unit_name in ("degree", "radian"):
        raise UnsupportedError(f"The measurement CRS {crs.name!r} has no linear unit.")
    return Measurement(crs=crs, unit_to_m=float(factor), resolved="explicit")


def resolve(geometry_sets, crs=None) -> Measurement:
    """The measurement for a step: *crs* when given, else the UTM zone of every geometry given.

    *geometry_sets* is a list of ``(geometries, crs)`` pairs, the eligible geometries of each layer.
    """
    if crs is not None:
        return explicit(crs)
    bounds = []
    for geoms, layer_crs in geometry_sets:
        geoms = np.asarray(geoms, dtype=object)
        if len(geoms) == 0:
            continue
        b = shapely.bounds(geoms)
        box = np.array([np.nanmin(b[:, 0]), np.nanmin(b[:, 1]), np.nanmax(b[:, 2]), np.nanmax(b[:, 3])])
        layer_crs = pyproj.CRS.from_user_input(layer_crs)
        if not layer_crs.equals(pyproj.CRS.from_epsg(4326)):
            t = pyproj.Transformer.from_crs(layer_crs, 4326, always_xy=True)
            box = np.array(t.transform_bounds(*box, densify_pts=21))
        bounds.append(box)
    if not bounds:
        raise UnsupportedError("There is no eligible geometry to resolve a measurement CRS from; pass crs=.")
    b = np.vstack(bounds)
    west, south, east, north = b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()
    if south < _LAT_MIN or north > _LAT_MAX:
        raise UnsupportedError(
            f"The study area reaches latitude {south if south < _LAT_MIN else north:.2f}, beyond UTM's "
            "range (80°S to 84°N). Polar measurement needs an explicit projected CRS (crs=)."
        )
    if (b[:, 0] > b[:, 2]).any() or east - west > 180:
        raise UnsupportedError(
            "The study area crosses the antimeridian, which urbanweave does not measure yet; pass an "
            "explicit projected CRS (crs=) whose domain covers it."
        )
    if east - west > MAX_UTM_SPAN_DEGREES:
        raise UnsupportedError(
            f"The study area spans {east - west:.1f}° of longitude, wider than one UTM zone can measure "
            f"accurately ({MAX_UTM_SPAN_DEGREES:.0f}° at most). Pass an explicit projected CRS (crs=), "
            "equal-area when areas are compared."
        )
    lon = (west + east) / 2
    lat = (south + north) / 2
    infos = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(lon, lat, lon, lat),
    )
    if not infos:
        raise UnsupportedError("No UTM zone found for the study area; pass crs=.")
    utm = pyproj.CRS.from_epsg(int(infos[0].code))
    return Measurement(crs=utm, unit_to_m=1.0, resolved="utm")


def project(geoms, from_crs, measurement: Measurement) -> np.ndarray:
    """*geoms* (shapely, in *from_crs*) in the measurement CRS."""
    return reproject(geoms, from_crs, measurement.crs)


def reproject(geoms, from_crs, to_crs) -> np.ndarray:
    """*geoms* (shapely, in *from_crs*) in *to_crs*, vertex by vertex."""
    geoms = np.asarray(geoms, dtype=object)
    from_crs = pyproj.CRS.from_user_input(from_crs)
    to_crs = pyproj.CRS.from_user_input(to_crs)
    if from_crs.equals(to_crs):
        return geoms
    t = pyproj.Transformer.from_crs(from_crs, to_crs, always_xy=True)
    out = np.empty(len(geoms), dtype=object)
    present = np.array([g is not None for g in geoms], dtype=bool)
    if present.any():
        out[present] = shapely.transform(geoms[present], lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))
    return out
