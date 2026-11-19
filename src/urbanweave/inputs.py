"""Input layers: IDs, CRS, geometry families and which features are eligible.

Every entry point takes ordinary GeoDataFrames. :func:`prepare_layer` checks one and describes
it without modifying it.

**ID rule.** A feature's ID is, in order of preference:

1. the column named by the caller (``source_id=`` or ``target_id=``);
2. otherwise the column named ``source_id`` (for sources) or ``target_id`` (for targets), when
   the frame has one;
3. otherwise, for sources, a ``target_id`` column, so a step's output (or a target, such as
   streets) keeps its IDs when it becomes the next step's sources, even after a round trip
   through a file;
4. otherwise the frame's index.

IDs must be unique and non-null. They are kept as they are (no conversion to strings) and carried
through every match, report and output.

**Eligibility.** A source with a null, empty or invalid geometry is *excluded* and reported by
cause; it never raises. A target with such a geometry raises :class:`InputError`, since a support
must be well defined before anything is matched to it. A geometry type the method does not
accept raises :class:`UnsupportedError` for sources and targets alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .errors import InputError, UnsupportedError

#: Geometry families. A family is what a method declares it accepts.
POINT, MULTIPOINT, LINE, POLYGON = "point", "multipoint", "line", "polygon"

_FAMILY_OF_TYPE = {
    "Point": POINT,
    "MultiPoint": MULTIPOINT,
    "LineString": LINE,
    "LinearRing": LINE,
    "MultiLineString": LINE,
    "Polygon": POLYGON,
    "MultiPolygon": POLYGON,
}

#: GeoJSON type names of each family, as the registry lists them.
GEOJSON_TYPES = {
    POINT: ["Point"],
    MULTIPOINT: ["MultiPoint"],
    LINE: ["LineString", "MultiLineString"],
    POLYGON: ["Polygon", "MultiPolygon"],
}

#: The attribute key under which urbanweave records how a support was built (H3 cells, grids).
SUPPORT_ATTR = "urbanweave_support"


@dataclass
class Layer:
    """A checked input layer. ``frame`` is the caller's frame, never modified.

    Positions (0..n-1) index every array here; ``ids[i]`` is the ID of the feature at position i.
    """

    role: str
    frame: gpd.GeoDataFrame
    id_column: str | None
    ids: pd.Index
    geometry: np.ndarray  # shapely geometries in the frame's CRS, by position
    family: np.ndarray  # family per position, None where excluded
    eligible: np.ndarray  # bool per position
    excluded: dict[str, np.ndarray] = field(default_factory=dict)  # cause -> positions
    support: dict | None = None

    @property
    def crs(self):
        return self.frame.crs

    def __len__(self) -> int:
        return len(self.ids)

    def rank(self) -> np.ndarray:
        """The position of each feature in the sorted order of IDs: the stable tie-break."""
        return id_rank(self.ids)

    def families(self) -> set[str]:
        return {f for f in self.family[self.eligible]}


def id_rank(ids) -> np.ndarray:
    """Rank of each ID in ascending order; IDs that cannot be compared sort by their text."""
    values = list(ids)
    n = len(values)
    try:
        order = sorted(range(n), key=values.__getitem__)
    except TypeError:
        order = sorted(range(n), key=lambda i: (type(values[i]).__name__, str(values[i])))
    rank = np.empty(n, dtype=np.int64)
    rank[np.asarray(order, dtype=np.int64)] = np.arange(n, dtype=np.int64)
    return rank


def resolve_ids(frame: pd.DataFrame, role: str, id_column: str | None) -> tuple[pd.Index, str | None]:
    """The IDs of *frame* by the ID rule (module docstring), checked unique and non-null."""
    if id_column is not None:
        if id_column not in frame.columns:
            raise InputError(f"{role} ID column {id_column!r} is not in the {role}s' columns.")
        ids, used = pd.Index(frame[id_column].to_numpy(), name=id_column), id_column
    elif f"{role}_id" in frame.columns:
        used = f"{role}_id"
        ids = pd.Index(frame[used].to_numpy(), name=used)
    elif role == "source" and "target_id" in frame.columns:
        used = "target_id"
        ids = pd.Index(frame[used].to_numpy(), name=used)
    else:
        ids, used = pd.Index(frame.index.to_numpy(), name=frame.index.name), None
    if ids.isna().any():
        where = "column " + repr(used) if used else "index"
        raise InputError(f"{role} IDs ({where}) contain missing values.")
    if not ids.is_unique:
        dupes = ids[ids.duplicated()].unique()[:5]
        where = "column " + repr(used) if used else "index"
        raise InputError(f"{role} IDs ({where}) are not unique; for example {list(dupes)}.")
    return ids, used


def prepare_layer(
    frame: gpd.GeoDataFrame,
    role: str,
    *,
    id_column: str | None = None,
    families: set[str] | None = None,
    method: str = "",
) -> Layer:
    """Check *frame* and describe it as a :class:`Layer` (see the module docstring)."""
    if not isinstance(frame, gpd.GeoDataFrame):
        raise InputError(f"The {role}s must be a GeoDataFrame, not {type(frame).__name__}.")
    if frame.crs is None:
        raise InputError(f"The {role}s have no CRS; set one with GeoDataFrame.set_crs before matching.")
    ids, used = resolve_ids(frame, role, id_column)

    geoms = np.asarray(frame.geometry.array, dtype=object)
    n = len(geoms)
    family = np.empty(n, dtype=object)
    eligible = np.ones(n, dtype=bool)
    excluded: dict[str, list[int]] = {}

    null = np.array([g is None for g in geoms], dtype=bool)
    empty = np.zeros(n, dtype=bool)
    present = ~null
    if present.any():
        empty[present] = shapely.is_empty(geoms[present])
    usable = present & ~empty
    types = np.full(n, None, dtype=object)
    if usable.any():
        types[usable] = shapely.get_type_id(geoms[usable])
    names = {0: "Point", 1: "LineString", 2: "LinearRing", 3: "Polygon", 4: "MultiPoint",
             5: "MultiLineString", 6: "MultiPolygon", 7: "GeometryCollection"}
    for i in np.flatnonzero(usable):
        family[i] = _FAMILY_OF_TYPE.get(names[types[i]])

    bad_types = sorted({names[types[i]] for i in np.flatnonzero(usable) if family[i] is None})
    if bad_types:
        raise UnsupportedError(f"{method or 'This operation'} does not accept {role} geometry {', '.join(bad_types)}.")
    if families is not None:
        wrong = sorted({names[types[i]] for i in np.flatnonzero(usable) if family[i] not in families})
        if wrong:
            accepted = ", ".join(t for f in sorted(families) for t in GEOJSON_TYPES[f])
            raise UnsupportedError(
                f"{method or 'This operation'} does not accept {role} geometry {', '.join(wrong)}; "
                f"it accepts {accepted}."
            )

    invalid = np.zeros(n, dtype=bool)
    if usable.any():
        invalid[usable] = ~shapely.is_valid(geoms[usable])

    if role == "target":
        problems = []
        if null.any():
            problems.append(f"{int(null.sum())} null")
        if empty.any():
            problems.append(f"{int(empty.sum())} empty")
        if invalid.any():
            problems.append(f"{int(invalid.sum())} invalid")
        if problems:
            sample = list(ids[null | empty | invalid][:5])
            raise InputError(
                f"Target geometry must be valid before a support is built: {', '.join(problems)} "
                f"geometries (IDs {sample}). Repair them first, for example with shapely.make_valid."
            )
    for cause, mask in (("null_geometry", null), ("empty_geometry", empty), ("invalid_geometry", invalid)):
        if mask.any():
            excluded[cause] = np.flatnonzero(mask)
            eligible &= ~mask
    family[~eligible] = None

    return Layer(
        role=role,
        frame=frame,
        id_column=used,
        ids=ids,
        geometry=geoms,
        family=family,
        eligible=eligible,
        excluded={k: np.asarray(v, dtype=np.int64) for k, v in excluded.items()},
        support=frame.attrs.get(SUPPORT_ATTR),
    )


def points_from_columns(df: pd.DataFrame, *, lat: str, lon: str, crs="EPSG:4326") -> gpd.GeoDataFrame:
    """Points from latitude and longitude columns.

    Rows whose coordinates are missing, not numeric, not finite, or out of range (latitude outside
    [-90, 90], longitude outside [-180, 180]) are dropped; the number dropped by cause is in the
    result's ``attrs["urbanweave_dropped"]``. The input is not modified and its index is kept, so
    the index can serve as the source ID.
    """
    for column in (lat, lon):
        if column not in df.columns:
            raise InputError(f"Column {column!r} is not in the table.")
    y = pd.to_numeric(df[lat], errors="coerce")
    x = pd.to_numeric(df[lon], errors="coerce")
    missing = df[lat].isna() | df[lon].isna()
    not_numeric = (y.isna() | x.isna()) & ~missing
    infinite = ~np.isfinite(y.fillna(0)) | ~np.isfinite(x.fillna(0))
    out_of_range = ~missing & ~not_numeric & ~infinite & ((y.abs() > 90) | (x.abs() > 180))
    keep = ~(missing | not_numeric | infinite | out_of_range)
    kept = df.loc[keep]
    result = gpd.GeoDataFrame(kept.copy(), geometry=gpd.points_from_xy(x[keep], y[keep]), crs=crs)
    result.attrs["urbanweave_dropped"] = {
        "missing_coordinates": int(missing.sum()),
        "not_numeric": int(not_numeric.sum()),
        "not_finite": int((infinite & ~missing & ~not_numeric).sum()),
        "out_of_range": int(out_of_range.sum()),
    }
    return result
