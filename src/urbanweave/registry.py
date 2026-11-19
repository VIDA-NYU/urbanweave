"""The operator registry: one JSON description of every installed operator.

Generated from the same tables that dispatch and validation read (:data:`matching.METHODS`,
:data:`aggregation.REDUCERS`, and the conversions of installed extras), so it cannot disagree with
what runs. UrbanTrace's interface, its backend validation and its copilot can all read it.
"""

from __future__ import annotations

from ._version import __version__
from .aggregation import REDUCERS
from .errors import UnsupportedError
from .inputs import GEOJSON_TYPES
from .matching import METHODS

#: Bumped when the registry's shape changes (not when operators are added).
REGISTRY_VERSION = 1

_FAMILY_OF = {t: f for f, types in GEOJSON_TYPES.items() for t in types}


def _conversions() -> dict:
    out = {}
    try:
        from .raster import CONVERSIONS  # noqa: WPS433

        out.update(CONVERSIONS)
    except ImportError:
        pass
    try:
        import importlib.util

        from .streets import CONVERSIONS as STREET_CONVERSIONS

        has_raster = importlib.util.find_spec("rasterio") is not None
        out.update({k: v for k, v in STREET_CONVERSIONS.items() if k != "along_lines" or has_raster})
    except ImportError:
        pass
    return out


def registry() -> dict:
    """The registry as JSON-compatible data."""
    aggregation = {}
    for name, spec in REDUCERS.items():
        entry = {k: v for k, v in spec.items() if k not in ("column", "numeric")}
        entry["needs_column"] = spec["column"]
        entry.setdefault("serializable", True)
        aggregation[name] = entry
    return {
        "registry_version": REGISTRY_VERSION,
        "package": "urbanweave",
        "package_version": __version__,
        "matching": {name: spec.to_dict() for name, spec in METHODS.items()},
        "aggregation": aggregation,
        "conversion": _conversions(),
    }


def problems(source_geometry, target_geometry, method: str, value_kind: str | None = None,
             aggregation: str | None = None, *, source_support: str = "vector",
             target_support: str = "vector") -> list[str]:
    """Why a combination is not supported, as a list of reasons (empty when it is supported).

    Geometries are GeoJSON type names (``"Point"``, ``"MultiLineString"``...) or lists of them.
    """
    out: list[str] = []
    spec = METHODS.get(method)
    if spec is None:
        return [f"Unknown matching method {method!r}."]
    for role, given, accepted, support, supports in (
        ("source", source_geometry, spec.sources, source_support, spec.source_supports),
        ("target", target_geometry, spec.targets, target_support, spec.target_supports),
    ):
        types = [given] if isinstance(given, str) else list(given)
        for t in types:
            fam = _FAMILY_OF.get(t)
            if fam is None:
                out.append(f"Unknown geometry type {t!r}.")
            elif fam not in accepted:
                out.append(f"{method} does not accept {role} geometry {t}.")
        if support not in supports:
            out.append(f"{method} does not accept {support} {role}s.")
    if method == "contain":
        types = [source_geometry] if isinstance(source_geometry, str) else list(source_geometry)
        if "MultiPoint" in types:
            out.append("contain takes single points; for multipoints use centroid or nearest.")
    if aggregation is not None:
        red = REDUCERS.get(aggregation)
        if red is None:
            out.append(f"Unknown reduction {aggregation!r}.")
        else:
            if value_kind is not None and value_kind not in red["value_kinds"]:
                out.append(f"{aggregation} does not suit {value_kind} values.")
            for q in red.get("requires", []):
                if q != "density_denominator" and q not in spec.quantities:
                    out.append(f"{aggregation} needs {q}, which {method} does not provide.")
    return out


def validate(source_geometry, target_geometry, method: str, value_kind: str | None = None,
             aggregation: str | None = None, **supports) -> None:
    """Raise :class:`UnsupportedError` when the combination is not supported."""
    reasons = problems(source_geometry, target_geometry, method, value_kind, aggregation, **supports)
    if reasons:
        raise UnsupportedError(" ".join(reasons))
