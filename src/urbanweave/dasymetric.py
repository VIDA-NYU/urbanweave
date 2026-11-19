"""Dasymetric disaggregation: zone totals spread over finer targets in proportion to prior layers.

A zone's total (trips, people, cases) is known; where inside the zone it happened is not. Prior
layers (an earlier year's events, points of interest, any point data thought to share the pattern)
say where. :func:`dasymetric` spreads each zone's total over the targets inside it in proportion to
a weighted combination of the priors, so that every zone keeps its total exactly.

It is built from :func:`urbanweave.match` and :func:`urbanweave.aggregate`, in three stages:

1. **Pieces.** Each target is split by the zone boundaries: ``area_overlap`` from targets to zones
   gives each (target, zone) piece and its area in m².
2. **Priors on pieces.** Each prior layer's points are matched to zones and to targets
   (``contain``), so each point is counted in exactly the piece it lies in; with ``column=`` its values
   are summed instead (hotel rooms, say). Layers are then normalized (``"share"``: each divided by
   its total, so a layer's weight is the share of mass it controls; ``"minmax"``: scaled to [0, 1] as
   in CRIF; ``None``: as is) and combined with ``weights`` into one propensity per piece.
3. **Calibration.** Each zone's total goes to its pieces in proportion to their propensity, and the
   pieces add up per target. A zone whose pieces have no prior at all is spread by area
   (``fallback="area"``) or left unallocated (``fallback="none"``); both are reported.

The result is a copy of the targets with the estimate, and a report: totals in, allocated, by
fallback, unallocated by cause (zone with no targets, zone total missing or not numeric, no prior and
no fallback), and the prior points that fell outside every zone or every target.
"""

from __future__ import annotations

from collections.abc import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd

from .errors import InputError
from .inputs import resolve_ids
from .matching import match
from .reports import REPORT_ATTR, Report, id_list, plain

NORMALIZATIONS = ("share", "minmax", None)


def _layer(spec):
    """(frame, column) from a frame or a (frame, column) pair."""
    if isinstance(spec, tuple):
        if len(spec) != 2:
            raise InputError("A prior layer is a GeoDataFrame or a (GeoDataFrame, column) pair.")
        return spec
    return spec, None


def dasymetric(
    zones: gpd.GeoDataFrame,
    targets: gpd.GeoDataFrame,
    priors,
    *,
    total: str,
    zone_id: str | None = None,
    target_id: str | None = None,
    weights: Mapping | None = None,
    normalize: str | None = "share",
    fallback: str = "area",
    as_: str | None = None,
) -> gpd.GeoDataFrame:
    """Spread ``zones[total]`` over *targets* in proportion to the *priors* (see the module docstring).

    *priors* is one layer or a dict ``name -> layer``; a layer is a GeoDataFrame of points or a
    ``(GeoDataFrame, column)`` pair. *weights* maps layer names to weights (equal by default; they
    are rescaled to sum to 1).
    """
    if normalize not in NORMALIZATIONS:
        raise InputError(f"normalize must be one of {NORMALIZATIONS}.")
    if fallback not in ("area", "none"):
        raise InputError("fallback must be 'area' or 'none'.")
    if total not in zones.columns:
        raise InputError(f"Column {total!r} is not in the zones.")
    layers = dict(priors) if isinstance(priors, Mapping) else {"prior": priors}
    if not layers:
        raise InputError("At least one prior layer is needed.")
    w = {k: 1.0 for k in layers} if weights is None else {k: float(weights.get(k, 0.0)) for k in layers}
    unknown = set(weights or {}) - set(layers)
    if unknown:
        raise InputError(f"weights name layers that are not priors: {sorted(unknown)}.")
    if any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise InputError("weights must be non-negative with a positive sum.")
    s = sum(w.values())
    w = {k: v / s for k, v in w.items()}

    zids, _ = resolve_ids(zones, "target", zone_id)
    tids, _ = resolve_ids(targets, "target", target_id)
    zone_ids = pd.Index(zids)
    totals = pd.to_numeric(pd.Series(zones[total].to_numpy(), index=zone_ids), errors="coerce")

    # 1. Pieces: (target, zone) overlaps with their areas.
    m = match(targets, zones, "area_overlap", source_id=target_id, target_id=zone_id)
    pieces = m.pairs.rename(columns={"source_id": "target", "target_id": "zone", "overlap_measure": "area_m2"})
    pieces = pieces[["target", "zone", "area_m2"]]

    # 2. Priors on pieces.
    layer_reports = {}
    for name, spec in layers.items():
        frame, column = _layer(spec)
        if column is not None and column not in frame.columns:
            raise InputError(f"Prior {name!r}: column {column!r} is not in the layer.")
        point_ids = pd.Index(resolve_ids(frame, "source", None)[0])
        in_zone = match(frame, zones, "contain", target_id=zone_id).pairs[["source_id", "target_id"]]
        in_target = match(frame, targets, "contain", target_id=target_id).pairs[["source_id", "target_id"]]
        both = in_zone.merge(in_target, on="source_id", suffixes=("_zone", "_target"))
        if column is None:
            both["v"] = 1.0
        else:
            values = pd.to_numeric(pd.Series(frame[column].to_numpy(), index=point_ids), errors="coerce")
            both["v"] = values.reindex(both["source_id"]).to_numpy()
        counts = both.groupby(["target_id_target", "target_id_zone"])["v"].sum().rename(name).reset_index()
        counts = counts.rename(columns={"target_id_target": "target", "target_id_zone": "zone"})
        pieces = pieces.merge(counts, on=["target", "zone"], how="outer")
        layer_reports[name] = {
            "points": int(len(frame)),
            "in_a_zone": int(in_zone["source_id"].nunique()),
            "in_a_zone_and_target": int(both["source_id"].nunique()),
            "outside_zones_or_targets": id_list(point_ids.difference(pd.Index(both["source_id"].unique()))),
            "column": column,
        }
    pieces[list(layers)] = pieces[list(layers)].fillna(0.0)
    pieces["area_m2"] = pieces["area_m2"].fillna(0.0)

    prop = np.zeros(len(pieces))
    for name in layers:
        v = pieces[name].to_numpy(float)
        if normalize == "share":
            tot = v.sum()
            v = v / tot if tot > 0 else v * 0
        elif normalize == "minmax":
            lo, hi = v.min(), v.max()
            v = (v - lo) / (hi - lo) if hi > lo else v * 0
        prop += w[name] * v
    pieces["propensity"] = prop

    # 3. Calibration per zone.
    per_zone = pieces.groupby("zone")[["propensity", "area_m2"]].sum()
    zt = totals.reindex(pieces["zone"]).to_numpy()
    zp = per_zone["propensity"].reindex(pieces["zone"]).to_numpy()
    za = per_zone["area_m2"].reindex(pieces["zone"]).to_numpy()
    use_prior = zp > 0
    share = np.where(use_prior, pieces["propensity"].to_numpy() / np.where(use_prior, zp, 1),
                     np.where((fallback == "area") & (za > 0), pieces["area_m2"].to_numpy() / np.where(za > 0, za, 1), np.nan))
    pieces["estimate"] = zt * share
    est = pieces.groupby("target")["estimate"].sum(min_count=1)

    out_col = as_ or total
    out = targets.copy()
    out[out_col] = est.reindex(tids).fillna(0.0).to_numpy()

    valid = totals.notna()
    zones_in_pieces = set(pieces["zone"])
    no_target = [z for z in zone_ids if z not in zones_in_pieces]
    no_prior = per_zone.index[per_zone["propensity"] <= 0]
    by_fallback = float(totals.reindex(no_prior).fillna(0).sum()) if fallback == "area" else 0.0
    unallocated_no_prior = float(totals.reindex(no_prior).fillna(0).sum()) if fallback == "none" else 0.0
    report = Report(
        dasymetric={
            "zones": int(len(zone_ids)),
            "targets": int(len(tids)),
            "pieces": int(len(pieces)),
            "weights": plain(w),
            "normalize": normalize,
            "fallback": fallback,
            "total": {
                "input": float(totals[valid].sum()),
                "allocated": float(np.nansum(pieces["estimate"].to_numpy())),
                "by_area_fallback": by_fallback,
                "unallocated": {
                    "zone_without_targets": {"total": float(totals.reindex(no_target).fillna(0).sum()), **id_list(no_target)},
                    "zone_total_missing": {"count": int((~valid).sum()), **id_list(list(zone_ids[~valid.to_numpy()]))},
                    "no_prior_no_fallback": {"total": unallocated_no_prior,
                                             **id_list(list(no_prior) if fallback == "none" else [])},
                },
            },
            "zones_without_prior": id_list(list(no_prior)),
            "priors": plain(layer_reports),
            "measurement": plain(m.report.get("measurement")),
        }
    )
    out.attrs[REPORT_ATTR] = report
    return out
