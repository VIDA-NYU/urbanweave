"""Dasymetric disaggregation: zone totals spread over finer targets in proportion to prior layers.

A zone's total (trips, people, cases) is known; where inside the zone it happened is not. Prior
layers (an earlier year's events, points of interest, any point data thought to share the pattern)
say where. :func:`dasymetric` spreads each zone's total over the targets inside it in proportion to
a weighted combination of the priors, so that every zone keeps its total exactly.

It is built from :func:`urbanweave.match` and :func:`urbanweave.aggregate`, in three stages:

1. **Pieces.** Each target is split by the zone boundaries: ``area_overlap`` from targets to zones
   gives each (target, zone) piece and its area in m².
2. **Priors on pieces.** Each point layer's points are matched to zones and to targets
   (``contain``), so each point is counted in exactly the piece it lies in; with ``column=`` its values
   are summed instead (hotel rooms, say). A per-target layer (a :class:`pandas.Series` indexed by
   target id: a smoothed density, a model's output) gives one non-negative value per target; a target
   split by zone boundaries passes its value to its pieces by their share of its area inside the
   zones. Point and per-target layers can be mixed in one call. Layers are then normalized (``"share"``: each divided by
   its total, so a layer's weight is the share of mass it controls; ``"minmax"``: scaled to [0, 1] as
   in CRIF; ``None``: as is) and combined with ``weights`` into one propensity per piece.
3. **Calibration.** Each zone's total goes to its pieces in proportion to their propensity, and the
   pieces add up per target. A zone whose pieces have no prior at all is spread by area
   (``fallback="area"``) or left unallocated (``fallback="none"``); both are reported.

Several totals (one column per month, say) can be spread in one call with the same priors:
``total=[...]`` names the columns, and the matching, which is most of the work, is done once.

The result is a copy of the targets with the estimate, and a report: totals in, allocated, by
fallback, unallocated by cause (zone with no targets, zone total missing or not numeric, no prior and
no fallback), and the prior points that fell outside every zone or every target (for a per-target
layer: the ids that are not targets, the targets that lie in no zone, and the missing values).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from .errors import InputError
from .inputs import resolve_ids
from .matching import match
from .reports import REPORT_ATTR, Report, id_list, plain

NORMALIZATIONS = ("share", "minmax", None)


def _layer(spec):
    """(frame, column) from a frame or a (frame, column) pair; (series, None) for a per-target layer."""
    if isinstance(spec, pd.Series):
        return spec, None
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
    total: str | Sequence[str],
    zone_id: str | None = None,
    target_id: str | None = None,
    weights: Mapping | None = None,
    normalize: str | None = "share",
    fallback: str = "area",
    as_: str | Sequence[str] | None = None,
) -> gpd.GeoDataFrame:
    """Spread ``zones[total]`` over *targets* in proportion to the *priors* (see the module docstring).

    *priors* is one layer or a dict ``name -> layer``; a layer is a GeoDataFrame of points, a
    ``(GeoDataFrame, column)`` pair, or a per-target :class:`pandas.Series` of non-negative values
    indexed by target id (targets it leaves out count as 0; within a target split by zone boundaries,
    the value goes to the pieces by area share). Layer kinds can be mixed. *weights* maps layer names to weights (equal by default; they
    are rescaled to sum to 1).

    *total* is one column or a list of columns, each spread the same way into a column of the
    output (named by *as_*, a name or a list of the same length, or after the total). With a list,
    the report's ``total`` maps each column to its own block of totals.
    """
    if normalize not in NORMALIZATIONS:
        raise InputError(f"normalize must be one of {NORMALIZATIONS}.")
    if fallback not in ("area", "none"):
        raise InputError("fallback must be 'area' or 'none'.")
    multi = not isinstance(total, str)
    cols = list(total) if multi else [total]
    if not cols:
        raise InputError("total names no column.")
    missing_cols = [c for c in cols if c not in zones.columns]
    if missing_cols:
        raise InputError(f"Column(s) {missing_cols} not in the zones.")
    if len(set(cols)) != len(cols):
        raise InputError("total repeats a column.")
    if as_ is None:
        out_cols = cols
    elif multi:
        if isinstance(as_, str) or len(as_) != len(cols):
            raise InputError("With several totals, as_ is a list of output names of the same length.")
        out_cols = list(as_)
    else:
        if not isinstance(as_, str):
            raise InputError("With one total, as_ is one output name.")
        out_cols = [as_]
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
    totals = pd.DataFrame({c: pd.to_numeric(pd.Series(zones[c].to_numpy()), errors="coerce").to_numpy() for c in cols},
                          index=zone_ids)

    # 1. Pieces: (target, zone) overlaps with their areas.
    m = match(targets, zones, "area_overlap", source_id=target_id, target_id=zone_id)
    pieces = m.pairs.rename(columns={"source_id": "target", "target_id": "zone", "overlap_measure": "area_m2"})
    pieces = pieces[["target", "zone", "area_m2"]]

    # 2. Priors on pieces.
    layer_reports = {}
    target_index = pd.Index(tids)
    for name, spec in layers.items():
        frame, column = _layer(spec)
        if isinstance(frame, pd.Series):
            values = pd.to_numeric(frame, errors="coerce")
            if (values < 0).any():
                raise InputError(f"Prior {name!r}: per-target values must be non-negative.")
            missing = values.index[values.isna()]
            not_targets = values.index.difference(target_index)
            values = values[values.notna() & values.index.isin(target_index)]
            if values.index.has_duplicates:
                raise InputError(f"Prior {name!r}: the per-target values repeat a target id.")
            area = pieces["area_m2"].fillna(0.0)  # a point layer's merge may have added zero-area pieces
            per_target = area.groupby(pieces["target"]).transform("sum")
            n_pieces = area.groupby(pieces["target"]).transform("size")
            area_share = np.where(per_target > 0, area / per_target.where(per_target > 0, 1), 1.0 / n_pieces)
            pieces[name] = values.reindex(pieces["target"]).fillna(0.0).to_numpy() * area_share
            in_no_zone = values.index.difference(pd.Index(pieces["target"].unique()))
            layer_reports[name] = {
                "kind": "per_target",
                "targets_with_value": int(len(values)),
                "value": float(values.sum()),
                "value_in_zones": float(pieces[name].sum()),
                "not_targets": id_list(list(not_targets)),
                "targets_in_no_zone": id_list(list(in_no_zone)),
                "missing_values": id_list(list(missing)),
            }
            continue
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
            "kind": "points",
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
    zp = per_zone["propensity"].reindex(pieces["zone"]).to_numpy()
    za = per_zone["area_m2"].reindex(pieces["zone"]).to_numpy()
    use_prior = zp > 0
    share = np.where(use_prior, pieces["propensity"].to_numpy() / np.where(use_prior, zp, 1),
                     np.where((fallback == "area") & (za > 0), pieces["area_m2"].to_numpy() / np.where(za > 0, za, 1), np.nan))
    zt = totals.reindex(pieces["zone"]).to_numpy()  # pieces x totals
    estimate = zt * share[:, None]
    est = pd.DataFrame(estimate, columns=cols).groupby(pieces["target"].to_numpy()).sum(min_count=1)

    if len(set(out_cols)) != len(out_cols):
        raise InputError("as_ repeats an output name.")
    est = est.reindex(tids).fillna(0.0)
    base = targets.drop(columns=[c for c in out_cols if c in targets.columns])
    values = pd.DataFrame(est[cols].to_numpy(), columns=out_cols, index=base.index)
    out = gpd.GeoDataFrame(pd.concat([pd.DataFrame(base), values], axis=1),  # one block, however many totals
                           geometry=targets.geometry.name, crs=targets.crs)

    zones_in_pieces = set(pieces["zone"])
    no_target = [z for z in zone_ids if z not in zones_in_pieces]
    no_prior = per_zone.index[per_zone["propensity"] <= 0]

    def block(i, c):
        t = totals[c]
        valid = t.notna()
        no_prior_total = float(t.reindex(no_prior).fillna(0).sum())
        return {
            "input": float(t[valid].sum()),
            "allocated": float(np.nansum(estimate[:, i])),
            "by_area_fallback": no_prior_total if fallback == "area" else 0.0,
            "unallocated": {
                "zone_without_targets": {"total": float(t.reindex(no_target).fillna(0).sum()), **id_list(no_target)},
                "zone_total_missing": {"count": int((~valid).sum()), **id_list(list(zone_ids[~valid.to_numpy()]))},
                "no_prior_no_fallback": {"total": no_prior_total if fallback == "none" else 0.0,
                                         **id_list(list(no_prior) if fallback == "none" else [])},
            },
        }

    report = Report(
        dasymetric={
            "zones": int(len(zone_ids)),
            "targets": int(len(tids)),
            "pieces": int(len(pieces)),
            "weights": plain(w),
            "normalize": normalize,
            "fallback": fallback,
            "total": {c: block(i, c) for i, c in enumerate(cols)} if multi else block(0, cols[0]),
            "zones_without_prior": id_list(list(no_prior)),
            "priors": plain(layer_reports),
            "measurement": plain(m.report.get("measurement")),
        }
    )
    out.attrs[REPORT_ATTR] = report
    return out
