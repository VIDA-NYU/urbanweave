"""Aggregation: one value per target per reduction, from a match and the sources' values.

Rules every reduction follows:

- **Targets.** The result has one row per target, in the targets' order, whether or not anything
  matched it.
- **Empty and missing.** A target with no matches gets a missing value. ``count``,
  ``weighted_count`` and ``sum`` can take ``fill_empty=0`` for those targets only. A target whose
  matches have no valid value stays missing; an observed zero stays zero. With ``where``, a target
  whose matches all fail the filter counts 0 (it was matched; nothing passed).
- **Valid values.** Missing values (null, NaN) never count. For numeric reductions a value that is
  not a number, or not finite, is invalid and reported separately from missing.
- **Basis.** Totals multiply by allocation fractions. Means, medians and category results weigh by
  the method's basis: overlap area or length for overlays, sampling weights for samples,
  allocation fractions for kernels, 1 for unit matches.
- **Integers.** An integer column stays integer for ``min``, ``max`` and a ``sum`` whose fractions
  are all 1. Such sums are exact; one outside the signed 64-bit range is missing and reported as
  an overflow, never rounded through a float.
- **Value kinds.** When a column's kind is declared (``value_kinds={"col": "extensive"}``), a
  reduction that does not suit it is refused before anything is computed.
"""

from __future__ import annotations

import builtins
from typing import Iterable

import numpy as np
import pandas as pd

from .errors import InputError, UnsupportedError
from .inputs import LINE, resolve_ids
from .matching import MatchResult
from .reducers import Reduction
from .reports import REPORT_ATTR, Report, id_list, plain

VALUE_KINDS = ("extensive", "intensive", "categorical")
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1


# The reduction table that dispatch, validation and the registry read.
REDUCERS: dict[str, dict] = {
    "count": {"value_kinds": list(VALUE_KINDS), "column": False, "summary": "Number of eligible matches."},
    "weighted_count": {"value_kinds": list(VALUE_KINDS), "column": False, "requires": ["allocation_fraction"],
                       "summary": "Sum of eligible matches' allocation fractions."},
    "sum": {"value_kinds": ["extensive"], "column": True, "numeric": True, "requires": ["allocation_fraction"],
            "summary": "Σ allocation fraction × value."},
    "density": {"value_kinds": ["extensive"], "column": True, "numeric": True,
                "requires": ["allocation_fraction", "density_denominator"],
                "params": {"denominator": {"type": "string", "default": "target_size",
                                           "choices": ["target_size", "overlap_length"]}},
                "summary": "Allocated total per km² (polygons), per km (lines) or per node (points), or per km of matched source lines."},
    "mean": {"value_kinds": ["intensive"], "column": True, "numeric": True, "summary": "Unweighted mean of matched values."},
    "weighted_mean": {"value_kinds": ["intensive"], "column": True, "numeric": True,
                      "summary": "Σ basis × value / Σ basis over valid values."},
    "median": {"value_kinds": ["intensive"], "column": True, "numeric": True, "summary": "Median of matched values."},
    "weighted_median": {"value_kinds": ["intensive"], "column": True, "numeric": True,
                        "summary": "Median weighted by the method's basis."},
    "min": {"value_kinds": ["intensive", "extensive"], "column": True, "numeric": True, "summary": "Smallest matched value."},
    "max": {"value_kinds": ["intensive", "extensive"], "column": True, "numeric": True, "summary": "Largest matched value."},
    "majority": {"value_kinds": ["categorical"], "column": True, "summary": "Category with the largest total basis."},
    "shares": {"value_kinds": ["categorical"], "column": True,
               "summary": "One column per category with its share of the valid matched basis."},
    "first": {"value_kinds": list(VALUE_KINDS), "column": True, "summary": "First valid match in the method's order."},
    "last": {"value_kinds": list(VALUE_KINDS), "column": True, "summary": "Last valid match in the method's order."},
    "join": {"value_kinds": list(VALUE_KINDS), "column": True, "summary": "Matched values as text in the method's order."},
    "custom": {"value_kinds": list(VALUE_KINDS), "column": False, "serializable": False,
               "summary": "A Python function of the matched rows (not serializable)."},
}

_OPS = {
    "==": lambda s, v: s == v, "!=": lambda s, v: s != v, "<": lambda s, v: s < v, "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v, ">=": lambda s, v: s >= v, "in": lambda s, v: s.isin(list(v)),
    "not in": lambda s, v: ~s.isin(list(v)), "isnull": lambda s, v: s.isna(), "notnull": lambda s, v: s.notna(),
}


def check_reduction(r: Reduction, match: MatchResult | None, kinds: dict, columns) -> None:
    """Refuse an unknown reduction, a missing column, an unsuitable value kind or match."""
    spec = REDUCERS.get(r.method)
    if spec is None:
        raise UnsupportedError(f"Unknown reduction {r.method!r}; known: {', '.join(REDUCERS)}.")
    if spec["column"]:
        if r.column is None:
            raise InputError(f"{r.method} needs a column.")
        if columns is not None and r.column not in columns:
            raise InputError(f"{r.method}: column {r.column!r} is not in the values.")
    kind = kinds.get(r.column) if r.column is not None else None
    if kind is not None:
        if kind not in VALUE_KINDS:
            raise InputError(f"Unknown value kind {kind!r} for {r.column!r}; use one of {', '.join(VALUE_KINDS)}.")
        if kind not in spec["value_kinds"]:
            raise UnsupportedError(f"{r.method} does not suit {kind} values ({r.column!r}); it takes "
                                   f"{', '.join(spec['value_kinds'])}.")
    if match is not None:
        for q in spec.get("requires", []):
            if q == "density_denominator":
                continue
            if q not in match.quantities:
                raise UnsupportedError(f"{r.method} needs {q}, which {match.method} does not provide "
                                       f"(it provides {', '.join(match.quantities)}).")
        if r.method == "density" and r.options.get("denominator", "target_size") == "overlap_length":
            if ("overlap_measure" not in match.quantities or LINE not in match.spec.sources
                    or match.sources.families() - {LINE}):
                raise UnsupportedError(
                    f"density per overlap length needs overlap lengths from source lines. "
                    f"The {match.method} match does not provide a length-only overlap measure."
                )
        basis = r.options.get("basis")
        if basis and basis != "unit" and basis not in match.quantities:
            raise UnsupportedError(f"{r.method}: basis {basis!r} is not provided by {match.method}.")
    if r.method == "density" and r.options.get("denominator", "target_size") not in ("target_size", "overlap_length"):
        raise InputError("density's denominator must be 'target_size' or 'overlap_length'.")
    if r.fill_empty is not None and (r.method not in ("count", "weighted_count", "sum") or r.fill_empty != 0):
        raise InputError("fill_empty=0 is available for count, weighted_count and sum only.")
    if r.where is not None and not callable(r.where):
        conditions = r.where if isinstance(r.where, list) else [r.where]
        for c in conditions:
            if not isinstance(c, dict) or "column" not in c or c.get("op") not in _OPS:
                raise InputError(f"where must be {{'column', 'op', 'value'}} with op in {', '.join(_OPS)}.")
            if columns is not None and c["column"] not in columns:
                raise InputError(f"where: column {c['column']!r} is not in the values.")


def _where_mask(where, rows: pd.DataFrame) -> np.ndarray:
    if where is None:
        return np.ones(len(rows), dtype=bool)
    if callable(where):
        return np.asarray(where(rows), dtype=bool)
    conditions = where if isinstance(where, list) else [where]
    mask = np.ones(len(rows), dtype=bool)
    for c in conditions:
        res = _OPS[c["op"]](rows[c["column"]], c.get("value"))
        mask &= np.asarray(res.fillna(False) if hasattr(res, "fillna") else res, dtype=bool)
    return mask


def _is_integer(series: pd.Series) -> bool:
    return pd.api.types.is_integer_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)


def _classify(values: pd.Series, numeric: bool):
    """(valid mask, numeric values or raw, counts by cause) for the values of the pairs."""
    missing = values.isna().to_numpy()
    if not numeric:
        return ~missing, values, {"missing": int(missing.sum())}
    num = pd.to_numeric(values, errors="coerce")
    if pd.api.types.is_bool_dtype(values.dtype):
        num = values.astype(float)
    num_arr = num.to_numpy(dtype=float, na_value=np.nan)
    invalid_type = np.isnan(num_arr) & ~missing
    non_finite = np.isinf(num_arr)
    valid = ~missing & ~invalid_type & ~non_finite
    return valid, num, {"missing": int(missing.sum()), "not_numeric": int(invalid_type.sum()),
                        "not_finite": int(non_finite.sum())}


def _group_sum(tgt: np.ndarray, weights: np.ndarray, n: int) -> np.ndarray:
    return np.bincount(tgt, weights=weights, minlength=n) if len(tgt) else np.zeros(n)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values, kind="stable")
    v, w = values[order], weights[order]
    keep = w > 0
    v, w = v[keep], w[keep]
    if len(v) == 0:
        return np.nan
    cum = np.cumsum(w)
    half = cum[-1] / 2
    i = int(np.searchsorted(cum, half, side="left"))
    if np.isclose(cum[i], half, rtol=1e-12, atol=0) and i + 1 < len(v):
        return float((v[i] + v[i + 1]) / 2)
    return float(v[i])


def _order(match: MatchResult, pairs: pd.DataFrame) -> np.ndarray:
    """The method's declared order of the pairs within each target: distance, overlap, or source ID."""
    rank = match.sources.rank()[pairs["src"].to_numpy()]
    key = pairs["order_key"].to_numpy(dtype=float)
    key = np.where(np.isnan(key), 0.0, key)
    return np.lexsort((rank, key, pairs["tgt"].to_numpy()))


def _sort_categories(cats):
    try:
        return sorted(cats)
    except TypeError:
        return sorted(cats, key=lambda c: (type(c).__name__, str(c)))


def aggregate(
    matches: MatchResult,
    values: pd.DataFrame | None = None,
    reductions: Reduction | Iterable[Reduction] = (),
    *,
    targets=None,
    value_kinds: dict | None = None,
    full_ids: bool = False,
):
    """One value per target per reduction (see the module docstring for the rules).

    *values* holds the sources' attribute columns, matched by source ID; it defaults to the
    sources given to :func:`urbanweave.match`. The result is a copy of *targets* (default: the
    targets given to ``match``) with one column per reduction, in the targets' order, and the
    report under ``attrs["urbanweave_report"]`` (:func:`urbanweave.report_of`).
    """
    if isinstance(reductions, Reduction):
        reductions = [reductions]
    reductions = list(reductions)
    if not reductions:
        raise InputError("Give at least one reduction, such as uw.count() or uw.sum('column').")
    kinds = dict(value_kinds or {})
    src = matches.sources
    values = src.frame if values is None else values
    columns = set(values.columns)

    aliases: list[str] = []
    for r in reductions:
        check_reduction(r, matches, kinds, columns)
        aliases.append(r.alias)
    dupes = sorted({a for a in aliases if aliases.count(a) > 1})
    if dupes:
        raise InputError(f"Output names repeat: {', '.join(dupes)}.")

    # Values by source position.
    if values is src.frame:
        rows_by_pos = values.reset_index(drop=True)
        absent = np.zeros(len(src), dtype=bool)
    else:
        if src.id_column is not None:
            if src.id_column not in values.columns:
                raise InputError(f"The values have no {src.id_column!r} column to match the sources' IDs.")
            vids = pd.Index(values[src.id_column].to_numpy())
        else:
            vids = pd.Index(values.index.to_numpy())
        if not vids.is_unique:
            raise InputError("The values' source IDs are not unique.")
        pos = vids.get_indexer(src.ids)
        absent = pos < 0
        rows_by_pos = values.iloc[np.where(absent, 0, pos)].reset_index(drop=True) if len(values) else values.reindex(range(len(src)))
        if absent.any() and len(values):
            rows_by_pos.loc[absent, :] = None

    base = matches.targets.frame if targets is None else targets
    if targets is not None:
        base_ids, _ = resolve_ids(base, "target", matches.targets.id_column)
        tpos = base_ids.get_indexer(matches.targets.ids)
        if (tpos < 0).any() or len(base_ids) != len(matches.targets.ids):
            raise InputError("targets= must hold the same target IDs as the match.")
        order_in_base = matches.targets.ids.get_indexer(base_ids)
    else:
        order_in_base = np.arange(len(matches.targets))
    n_t = len(matches.targets)
    P = matches.positions
    pair_rows = rows_by_pos.iloc[P["src"].to_numpy()].reset_index(drop=True)
    has_pair = np.bincount(P["tgt"].to_numpy(), minlength=n_t) > 0 if len(P) else np.zeros(n_t, dtype=bool)

    out_cols: dict[str, object] = {}
    reports = []
    for r in reductions:
        mask = _where_mask(r.where, pair_rows)
        sub = P[mask].reset_index(drop=True)
        rows = pair_rows[mask].reset_index(drop=True)
        tgt = sub["tgt"].to_numpy()
        matched_any = (np.bincount(tgt, minlength=n_t) > 0) if len(tgt) else np.zeros(n_t, dtype=bool)
        rep = {"method": r.method, "as": r.alias}
        if r.column is not None:
            rep["column"] = r.column
        if r.where is not None:
            rep["filtered_out"] = int((~mask).sum())
        result, extra = _reduce(r, matches, sub, rows, tgt, n_t, has_pair, matched_any, src, rows_by_pos, absent)
        rep.update(extra)
        for name, col in result.items():
            if name in out_cols:
                raise InputError(f"Output name {name!r} repeats.")
            out_cols[name] = col
        reports.append(rep)

    collide = [c for c in out_cols if c in base.columns]
    if collide:
        raise InputError(f"Output names {', '.join(collide)} are already columns of the targets; choose other names with as_.")
    out = base.copy()
    for name, col in out_cols.items():
        arr = col
        if isinstance(arr, pd.Series):
            out[name] = arr.iloc[order_in_base].to_numpy() if len(arr) else arr.to_numpy()
            out[name] = out[name].astype(arr.dtype)
        else:
            out[name] = np.asarray(arr)[order_in_base] if n_t else np.asarray(arr)
    out.attrs[REPORT_ATTR] = Report(match=matches.report, aggregate=plain(reports))
    return out


def _reduce(r, match, sub, rows, tgt, n_t, has_pair, matched_any, src, rows_by_pos, absent):
    """(columns, report entries) for one reduction."""
    m = r.method
    extra: dict = {}
    na = np.full(n_t, np.nan)

    def empty_mask():
        return ~has_pair

    if m in ("count", "weighted_count"):
        if m == "count":
            vals = np.bincount(tgt, minlength=n_t) if len(tgt) else np.zeros(n_t, dtype=np.int64)
            col = pd.array(vals.astype("int64"), dtype="Int64")
        else:
            w = sub["allocation_fraction"].to_numpy(dtype=float)
            col = pd.array(_group_sum(tgt, w, n_t), dtype="Float64")
        if r.fill_empty is None:
            col[empty_mask()] = pd.NA
        extra["empty_targets"] = int(empty_mask().sum())
        return {r.alias: pd.Series(col)}, extra

    if m == "custom":
        fn = r.options["fn"]
        cols = r.options.get("columns")
        data = rows if cols is None else rows[list(cols)]
        data = data.copy()
        for q in match.quantities:
            data[q] = sub[q].to_numpy()
        res = np.full(n_t, None, dtype=object)
        for t_i, idx in pd.Series(np.arange(len(tgt))).groupby(tgt):
            res[t_i] = fn(data.iloc[idx.to_numpy()])
        extra["serializable"] = False
        return {r.alias: pd.Series(res)}, extra

    spec = REDUCERS[m]
    raw = rows[r.column]
    valid, num, causes = _classify(raw, spec.get("numeric", False))
    extra["values"] = causes | {"valid": int(valid.sum())}
    if absent.any():
        extra["values"]["sources_not_in_values"] = int(absent.sum())
    vt = tgt[valid]
    has_valid = (np.bincount(vt, minlength=n_t) > 0) if len(vt) else np.zeros(n_t, dtype=bool)
    extra["empty_targets"] = int((~has_pair).sum())
    extra["targets_without_valid_value"] = int((has_pair & ~has_valid).sum())

    if m in ("sum", "density"):
        frac = sub["allocation_fraction"].to_numpy(dtype=float)
        is_int = _is_integer(rows_by_pos[r.column]) if r.column in rows_by_pos else False
        unit = bool(len(frac) == 0 or np.all(frac[valid] == 1.0))
        if m == "sum" and is_int and unit:
            totals = [0] * n_t
            for t_i, v in zip(vt, num[valid].to_numpy()):
                totals[t_i] += int(v)
            overflow = np.array([not (_INT64_MIN <= x <= _INT64_MAX) for x in totals], dtype=bool)
            col = pd.array([x if not o else None for x, o in zip(totals, overflow)], dtype="Int64")
            extra["overflow_targets"] = int(overflow.sum())
            allocated = builtins.sum(int(x) for x, o, h in zip(totals, overflow, has_valid) if h and not o)
        else:
            vals = num.to_numpy(dtype=float, na_value=np.nan)
            totals = _group_sum(vt, frac[valid] * vals[valid], n_t)
            col = pd.array(totals, dtype="Float64")
            allocated = float(totals[has_valid].sum())
        if m == "sum":
            col[~has_valid] = pd.NA
            if r.fill_empty is not None:
                col[~has_pair] = 0
        extra["extensive"] = _extensive_report(match, r.column, rows_by_pos, absent, allocated)
        if m == "sum":
            return {r.alias: pd.Series(col)}, extra
        # density
        numer = np.asarray(pd.Series(col).astype("Float64").to_numpy(dtype=float, na_value=np.nan))
        numer[~has_valid] = np.nan
        if r.options.get("denominator", "target_size") == "overlap_length":
            denom = _group_sum(tgt, sub["overlap_measure"].to_numpy(dtype=float), n_t) / 1e3
            unit_name = "per km of matched source lines"
        else:
            size, units = match.target_sizes()
            denom = size
            unit_name = "per " + "/".join(sorted({u for u in units if u}))
        with np.errstate(divide="ignore", invalid="ignore"):
            dens = np.where((denom > 0) & np.isfinite(denom), numer / denom, np.nan)
        extra["denominator"] = unit_name
        extra["zero_denominator_targets"] = int(((denom == 0) | ~np.isfinite(denom)).sum())
        return {r.alias: pd.Series(pd.array(dens, dtype="Float64")).mask(np.isnan(dens))}, extra

    if m in ("weighted_mean", "weighted_median", "majority", "shares"):
        basis = _basis_for(match, r, sub)
    if m == "weighted_mean":
        vals = num.to_numpy(dtype=float, na_value=np.nan)
        b = basis[valid]
        wsum = _group_sum(vt, b * vals[valid], n_t)
        bsum = _group_sum(vt, b, n_t)
        with np.errstate(divide="ignore", invalid="ignore"):
            res = np.where(bsum > 0, wsum / bsum, np.nan)
        cols = {r.alias: _float_col(res)}
        if r.options.get("weighted_total_as"):
            cols[r.options["weighted_total_as"]] = _float_col(np.where(has_valid, wsum, np.nan))
        if r.options.get("valid_measure_as"):
            cols[r.options["valid_measure_as"]] = _float_col(np.where(has_pair, bsum, np.nan))
        extra["basis"] = r.options.get("basis") or match.spec.basis
        return cols, extra

    if m in ("mean", "median", "min", "max", "weighted_median"):
        series = num[valid]
        frame = pd.DataFrame({"t": vt, "v": series.to_numpy()})
        if m == "weighted_median":
            frame["b"] = basis[valid]
            res = np.full(n_t, np.nan)
            for t_i, g in frame.groupby("t"):
                res[t_i] = _weighted_median(g["v"].to_numpy(dtype=float), g["b"].to_numpy(dtype=float))
            extra["basis"] = r.options.get("basis") or match.spec.basis
            return {r.alias: _float_col(res)}, extra
        is_int = _is_integer(rows_by_pos[r.column]) and m in ("min", "max")
        if is_int:
            frame["v"] = series.astype("int64").to_numpy()
        agg = frame.groupby("t")["v"].agg(m)
        if is_int:
            col = pd.array([pd.NA] * n_t, dtype="Int64")
            col[agg.index.to_numpy()] = agg.to_numpy()
            return {r.alias: pd.Series(col)}, extra
        res = np.full(n_t, np.nan)
        res[agg.index.to_numpy()] = agg.to_numpy(dtype=float)
        return {r.alias: _float_col(res)}, extra

    if m in ("majority", "shares"):
        cats = raw[valid].to_numpy()
        frame = pd.DataFrame({"t": vt, "c": cats, "b": basis[valid]})
        totals = frame.groupby(["t", "c"], sort=False)["b"].sum()
        categories = _sort_categories(pd.unique(cats))
        extra["basis"] = r.options.get("basis") or match.spec.basis
        if m == "majority":
            res = np.full(n_t, None, dtype=object)
            rank = {c: i for i, c in enumerate(categories)}
            for t_i, g in totals.groupby(level=0):
                best = builtins.max(g.items(), key=lambda kv: (kv[1], -rank[kv[0][1]]))
                res[t_i] = best[0][1]
            return {r.alias: pd.Series(res)}, extra
        tot = totals.groupby(level=0).sum()
        cols = {}
        for c in categories:
            share = np.full(n_t, np.nan)
            share[has_valid] = 0.0
            sel = totals.xs(c, level=1) if c in totals.index.get_level_values(1) else pd.Series(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                share[sel.index.to_numpy()] = sel.to_numpy() / tot.loc[sel.index].to_numpy()
            cols[f"{r.alias}_{c}"] = _float_col(share)
        extra["categories"] = plain(categories)
        return cols, extra

    if m in ("first", "last", "join"):
        order = _order(match, sub)
        res = np.full(n_t, None, dtype=object)
        vals = raw.to_numpy()
        ordered = [i for i in order if valid[i]]
        groups: dict[int, list] = {}
        for i in ordered:
            groups.setdefault(int(tgt[i]), []).append(vals[i])
        for t_i, lst in groups.items():
            if m == "first":
                res[t_i] = lst[0]
            elif m == "last":
                res[t_i] = lst[-1]
            else:
                res[t_i] = r.options.get("delimiter", ", ").join(str(v) for v in lst)
        extra["order"] = match.spec.order
        return {r.alias: pd.Series(res)}, extra

    raise UnsupportedError(f"Reduction {m!r} is not implemented.")


def _basis_for(match: MatchResult, r: Reduction, sub: pd.DataFrame) -> np.ndarray:
    basis = r.options.get("basis") or match.spec.basis
    if basis == "unit":
        return np.ones(len(sub))
    return sub[basis].to_numpy(dtype=float)


def _float_col(arr) -> pd.Series:
    arr = np.asarray(arr, dtype=float)
    col = pd.array(arr, dtype="Float64")
    col[np.isnan(arr)] = pd.NA
    return pd.Series(col)


def _extensive_report(match: MatchResult, column, rows_by_pos, absent, allocated) -> dict:
    src = match.sources
    eligible = src.eligible & ~absent
    v = pd.to_numeric(rows_by_pos[column], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    ok = eligible & np.isfinite(v)
    input_total = float(v[ok].sum())
    matched = np.zeros(len(src), dtype=bool)
    if len(match.positions):
        matched[np.unique(match.positions["src"].to_numpy())] = True
    matched_total = float(v[ok & matched].sum())
    out = {
        "valid_input": input_total,
        "matched_input": matched_total,
        "unmatched_input": input_total - matched_total,
        "allocated": float(allocated),
    }
    a = match.spec.assignment
    if a in ("exclusive", "normalized") and not match.report.get("notes", {}).get("replicating"):
        out["unallocated"] = input_total - float(allocated)
    elif match.report.get("notes", {}).get("replicating"):
        out["replicated"] = float(allocated) - matched_total
    elif a == "independent":
        over = match.report.get("allocation", {}).get("over_allocated_sources", 0)
        if over:
            out["unallocated"] = None
            out["coverage_note"] = "targets overlap: pairwise allocations can exceed the input; union coverage not measured"
        else:
            out["unallocated"] = input_total - float(allocated)
    return out
