"""urbanweave: weave data from many sources onto the places urban analysis asks about.

The core is two functions::

    m = uw.match(sources, targets, method="contain")      # who goes where, with what quantities
    out = uw.aggregate(m, sources, [uw.count(), uw.sum("population")])

Targets are any GeoDataFrame (zones, streets, points) or a support built by :mod:`urbanweave.targets`
(H3 cells). Zonal statistics on rasters are in :mod:`urbanweave.raster` (``pip install
urbanweave[raster]``); street targets in :mod:`urbanweave.streets` (``urbanweave[osm]``); saved,
replayable plans in :mod:`urbanweave.plan`.
"""

from . import targets
from ._version import __version__
from .aggregation import aggregate
from .dasymetric import dasymetric
from .errors import InputError, MissingDependencyError, PlanError, UnsupportedError, UrbanweaveError
from .inputs import points_from_columns
from .matching import METHODS, MatchResult, match
from .reducers import (
    Reduction,
    count,
    custom,
    density,
    first,
    join,
    last,
    majority,
    max,
    mean,
    median,
    min,
    shares,
    sum,
    weighted_count,
    weighted_mean,
    weighted_median,
)
from .registry import registry, validate
from .reports import Report, report_of


def __getattr__(name):
    # Optional parts load on first use, so the core imports without the extras.
    if name in ("read_raster", "zonal_stats", "Raster"):
        from . import raster

        return getattr(raster, name)
    if name in ("Plan",):
        from .plan import Plan

        return Plan
    raise AttributeError(f"module 'urbanweave' has no attribute {name!r}")


__all__ = [
    "__version__", "match", "aggregate", "dasymetric", "MatchResult", "METHODS", "targets", "points_from_columns",
    "registry", "validate", "report_of", "Report", "Reduction",
    "count", "weighted_count", "sum", "density", "mean", "weighted_mean", "median", "weighted_median",
    "min", "max", "majority", "shares", "first", "last", "join", "custom",
    "UrbanweaveError", "InputError", "UnsupportedError", "PlanError", "MissingDependencyError",
    "read_raster", "zonal_stats", "Raster", "Plan",
]
