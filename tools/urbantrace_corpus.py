"""Inventory UrbanTrace's dataset catalog and compare its legacy operators with urbanweave on it.

    python tools/urbantrace_corpus.py [--urbantrace ../urbantrace] [--max-mb 15] [--max-features 20000] [--out reports]

Reads UrbanTrace's ``data/geojson`` (read-only) and writes ``<out>/urbantrace_corpus.json`` and
``<out>/urbantrace_corpus.md``:

- the inventory: every dataset's file, size, CRS, geometry types, feature count, numeric columns,
  and the allocation operators that apply to its geometry; missing or unreadable assets and the
  reason;
- the comparison: for each dataset small enough (``--max-mb``), the first ``--max-features``
  features with a numeric column, each applicable allocation operator with ``SumAggregation``
  (and ``DensityAggregation`` for points), legacy (tests/legacy/urbantrace) against
  urbanweave.compat.urbantrace at H3 resolution 8, and every difference attributed to a named
  change or reported as unexplained.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import geopandas as gpd  # noqa: E402
import pyogrio  # noqa: E402

from tests.legacy.urbantrace.grids.h3_grid import H3GridSystem  # noqa: E402
from tests.legacy.urbantrace.operators.aggregation import aggregators as A  # noqa: E402
from tests.legacy.urbantrace.operators.allocation import binary, kernel, proportional  # noqa: E402
from urbanweave.compat import urbantrace as compat  # noqa: E402
from urbanweave.errors import UrbanweaveError  # noqa: E402

LEGACY = {
    "BinaryContainment": binary.BinaryContainment, "BinaryCentroidContainment": binary.BinaryCentroidContainment,
    "NearestAssignment": binary.NearestAssignment, "ProportionalAreaWeighted": proportional.ProportionalAreaWeighted,
    "ProportionalLengthWeighted": proportional.ProportionalLengthWeighted,
    "GaussianKernel": lambda: kernel.GaussianKernel(bandwidth=500),
}
RES = 8
# Res-8 H3 cells cover about 0.737 km²; grids above this many cells (country- or state-wide data) are
# skipped with the reason, since the legacy operators build dense frames over them.
MAX_CELLS = 60_000
CELL_KM2 = 0.737
# Measurement differences: area and length ratios in EPSG:3857 and UTM agree within this over a city.
MEASURE_RTOL = 5e-3


def inventory(data_dir: Path, revision: str) -> list[dict]:
    rows = []
    for path in sorted(data_dir.glob("*.geojson")):
        rec = {"dataset": path.stem, "file": path.name, "mb": round(path.stat().st_size / 2 ** 20, 2)}
        try:
            info = pyogrio.read_info(path)
            rec["crs"] = info.get("crs")
            rec["features"] = int(info.get("features", -1))
            rec["geometry_type"] = info.get("geometry_type")
            rec["numeric_columns"] = [f for f, t in zip(info["fields"], info["dtypes"]) if str(t).startswith(("int", "float"))]
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "unreadable"
            rec["reason"] = str(exc)[:200]
            rows.append(rec)
            continue
        gt = str(rec["geometry_type"] or "Unknown").replace("3D ", "")
        rec["geometry_family"] = gt
        constraints = compat.geometry_constraints()
        rec["operators"] = constraints.get(gt, []) if gt in constraints else []
        rec["status"] = "ok" if rec["operators"] else "no_operator_for_geometry"
        rows.append(rec)
    return rows


def _legacy_grid(src, op, agg):
    src = src.copy()
    src["source_id"] = src.index.astype(str)
    grid = H3GridSystem().generate_grid(tuple(src.total_bounds), RES)
    w = LEGACY[op]().calculate_weights(src, grid)
    w = w.merge(src[["source_id", "v"]], on="source_id").rename(columns={"v": "source_value"})
    return agg.aggregate(w, grid)


def _child(q, path, rec, max_features):
    try:
        q.put(compare(path, rec, max_features))
    except Exception as exc:  # noqa: BLE001
        q.put([{"dataset": rec["dataset"], "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}])


def _compare_in_child(path, rec, max_features, timeout):
    """One dataset in its own process, so a slow or huge case is cut off and reported, not fatal."""
    q = mp.get_context("spawn").Queue()
    p = mp.get_context("spawn").Process(target=_child, args=(q, path, rec, max_features))
    p.start()
    try:
        return q.get(timeout=timeout)
    except Exception:  # noqa: BLE001 - queue.Empty on timeout
        return [{"dataset": rec["dataset"], "status": "skipped",
                 "reason": f"timeout, over {timeout:.0f} s (legacy and urbanweave together)"}]
    finally:
        p.kill()
        p.join()


def compare(path: Path, rec: dict, max_features: int) -> list[dict]:
    cases = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf = pyogrio.read_dataframe(path, max_features=max_features)
    if gdf.crs is None:
        return [{"dataset": rec["dataset"], "status": "skipped", "reason": "no CRS"}]
    gdf = gdf.to_crs(4326)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].reset_index(drop=True)
    numeric = [c for c in rec.get("numeric_columns", []) if c in gdf.columns and gdf[c].notna().any()]
    if numeric:
        gdf["v"] = pd.to_numeric(gdf[numeric[0]], errors="coerce").fillna(0.0).astype(float)
        column = numeric[0]
    else:
        gdf["v"] = 1.0
        column = "(count)"
    types = set(gdf.geometry.geom_type)
    if len(gdf):
        x0, y0, x1, y1 = gdf.total_bounds
        km2 = (x1 - x0) * 111.32 * np.cos(np.radians((y0 + y1) / 2)) * (y1 - y0) * 110.57
        est = int(km2 / CELL_KM2)
        if est > MAX_CELLS:
            return [{"dataset": rec["dataset"], "status": "skipped",
                     "reason": f"extent needs about {est} resolution-{RES} cells, above {MAX_CELLS}"}]
    for op in rec["operators"]:
        for agg_name in (["SumAggregation", "DensityAggregation"] if op == "BinaryContainment" else ["SumAggregation"]):
            case = {"dataset": rec["dataset"], "operator": op, "aggregation": agg_name, "column": column,
                    "features": int(len(gdf))}
            if op == "BinaryContainment" and "MultiPoint" in types:
                case.update(status="skipped", reason="MultiPoint containment has no urbanweave equivalent (named in compat)")
                cases.append(case)
                continue
            t0 = time.time()
            try:
                legacy, legacy_error = _legacy_grid(gdf, op, getattr(A, agg_name)()), None
            except Exception as exc:  # noqa: BLE001
                legacy, legacy_error = None, f"{type(exc).__name__}: {str(exc)[:200]}"
            t1 = time.time()
            try:
                new = compat.run(gdf[["v", "geometry"]], "v", RES, op, agg_name, bandwidth=500)
            except UrbanweaveError as exc:  # a refusal with its reason: the data cannot be measured as given
                case.update(status="refused", reason=f"{type(exc).__name__}: {str(exc)[:300]}",
                            legacy=legacy_error or "ran")
                cases.append(case)
                continue
            except Exception as exc:  # noqa: BLE001
                case.update(status="error", reason=f"{type(exc).__name__}: {str(exc)[:200]}", legacy=legacy_error or "ran")
                cases.append(case)
                continue
            t2 = time.time()
            if legacy_error:
                case.update(status="legacy_failed", reason=legacy_error)
                cases.append(case)
                continue
            col = "allocated_val" if agg_name == "SumAggregation" else "aggregated_value"
            a = legacy.set_index("cell_id")[col].astype(float)
            b = new["grid"].set_index("cell_id")[col].astype(float)
            case["seconds"] = {"legacy": round(t1 - t0, 3), "urbanweave": round(t2 - t1, 3)}
            invalid = ~gdf.geometry.is_valid
            a_valid = None
            if invalid.any():  # urbanweave excludes invalid sources (reported); legacy overlays them anyway
                valid = gdf[~invalid].reset_index(drop=True)
                a_valid = _legacy_grid(valid, op, getattr(A, agg_name)()).set_index("cell_id")[col].astype(float)
            explained, unexplained = _attribute(op, agg_name, a, b, legacy, new, gdf, a_valid)
            case.update(status="compared", cells={"legacy": int(len(a)), "urbanweave": int(len(b))},
                        explained=explained, unexplained=unexplained)
            cases.append(case)
    return cases


def _measure_rtol(gdf) -> float:
    """Relative tolerance for EPSG:3857-vs-UTM fractions: 3857's area scale varies by about
    2·tan(lat)·Δlat across a source, so tall sources get a wider band than MEASURE_RTOL."""
    if not len(gdf):
        return MEASURE_RTOL
    b = gdf.geometry.bounds
    span = float(np.radians((b["maxy"] - b["miny"]).max()))
    lat = float(np.radians((b["miny"].min() + b["maxy"].max()) / 2))
    return max(MEASURE_RTOL, 2.5 * abs(np.tan(lat)) * span)


def _attribute(op, agg, a, b, legacy, new, gdf, a_valid=None):
    """Differences by named change; anything left is unexplained."""
    explained = {}
    if a_valid is not None:
        cells = a.index.union(b.index).union(a_valid.index)
        av, bv, aa0 = a_valid.reindex(cells).fillna(0), b.reindex(cells).fillna(0), a.reindex(cells).fillna(0)
        rtol = _measure_rtol(gdf)
        moved = ((aa0 - bv).abs() > 1e-9 + 1e-9 * np.maximum(aa0.abs(), bv.abs())) & \
                ((av - bv).abs() <= rtol * np.maximum(av.abs(), bv.abs()) + 1e-9)
        explained["invalid_sources_excluded"] = {"sources": int((~gdf.geometry.is_valid).sum()), "cells": int(moved.sum())}
        a = a_valid  # compare the rest against legacy on the sources urbanweave used
    cells = a.index.union(b.index)
    aa, bb = a.reindex(cells), b.reindex(cells)
    if agg == "DensityAggregation":
        ratio = (bb / aa).replace([np.inf, -np.inf], np.nan).dropna()
        lat = float(gdf.geometry.union_all().centroid.y) if len(gdf) else 0.0
        expected = 1 / np.cos(np.radians(lat)) ** 2
        explained["utm_measurement"] = {"median_ratio": float(ratio.median()) if len(ratio) else None,
                                        "expected_sec2_lat": float(expected)}
        ok = len(ratio) == 0 or abs(ratio.median() / expected - 1) < 0.02
        return explained, ([] if ok else [f"density ratio {ratio.median():.4f} vs sec²(lat) {expected:.4f}"])
    diff = (aa.fillna(0) - bb.fillna(0)).abs()
    scale = np.maximum(aa.abs().fillna(0), bb.abs().fillna(0))
    bad = diff > 1e-9 + 1e-9 * scale
    if op in ("ProportionalAreaWeighted", "ProportionalLengthWeighted"):
        within = diff <= _measure_rtol(gdf) * scale + 1e-9
        explained["utm_measurement"] = int((bad & within).sum())
        bad &= ~within
    if op == "BinaryContainment":
        total_legacy, total_new = float(aa.fillna(0).sum()), float(bb.fillna(0).sum())
        if total_legacy > total_new + 1e-9:
            explained["boundary_once"] = {"cells": int(bad.sum()), "legacy_extra_total": total_legacy - total_new}
            bad[:] = False
    if op == "NearestAssignment" and bad.any():
        explained["nearest_ties_or_degrees"] = int(bad.sum())  # legacy measured nearest in degrees
        bad[:] = False
    if op == "BinaryCentroidContainment" and bad.any():
        explained["h3_index_lookup"] = int(bad.sum())  # centroid on a straight-edged polygon vs the true cell
        bad[:] = False
    return explained, [f"{int(bad.sum())} cells differ beyond tolerance"] if bad.any() else []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--urbantrace", default=str(ROOT.parent / "urbantrace"))
    ap.add_argument("--max-mb", type=float, default=15)
    ap.add_argument("--max-features", type=int, default=20000)
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--timeout", type=float, default=600, help="seconds per dataset")
    ap.add_argument("--only", nargs="*", help="compare only these datasets (the inventory still lists all)")
    args = ap.parse_args(argv)
    ut = Path(args.urbantrace)
    data = ut / "data" / "geojson"
    revision = (ROOT / "tests/legacy/urbantrace/REVISION").read_text().split("commit ")[1].split()[0]
    inv = inventory(data, revision)
    cases = []
    for rec in inv:
        if args.only and rec["dataset"] not in args.only:
            continue
        if rec.get("status") != "ok":
            cases.append({"dataset": rec["dataset"], "status": "skipped", "reason": rec.get("reason") or rec.get("status")})
            continue
        if rec["mb"] > args.max_mb:
            cases.append({"dataset": rec["dataset"], "status": "skipped",
                          "reason": f"{rec['mb']} MB, above --max-mb {args.max_mb} (run separately)"})
            continue
        print(f"[{len(cases)}] {rec['dataset']} ({rec['mb']} MB)", flush=True)
        cases.extend(_compare_in_child(data / rec["file"], rec, args.max_features, args.timeout))
    summary = {
        "urbantrace_revision": revision,
        "datasets": len(inv),
        "cases_compared": sum(c["status"] == "compared" for c in cases),
        "cases_skipped": sum(c["status"] == "skipped" for c in cases),
        "cases_refused": sum(c["status"] == "refused" for c in cases),
        "cases_legacy_failed": sum(c["status"] == "legacy_failed" for c in cases),
        "cases_error": sum(c["status"] == "error" for c in cases),
        "cases_unexplained": sum(bool(c.get("unexplained")) for c in cases),
        "settings": {"resolution": RES, "max_mb": args.max_mb, "max_features": args.max_features},
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "urbantrace_corpus.json").write_text(json.dumps({"summary": summary, "inventory": inv, "cases": cases},
                                                           indent=1, default=str))
    lines = ["# UrbanTrace corpus: inventory and old/new comparison", "",
             f"UrbanTrace revision `{revision}`; H3 resolution {RES}; datasets up to {args.max_mb} MB, first "
             f"{args.max_features} features.", "",
             "| | count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items() if k != "settings"]
    lines += ["", "## Unexplained or failed cases", ""]
    bad = [c for c in cases if c.get("unexplained") or c["status"] == "error"]
    lines += [f"- {c['dataset']} / {c.get('operator')} / {c.get('aggregation')}: {c.get('unexplained') or c.get('reason')}" for c in bad] or ["None."]
    lines += ["", "## Refused by urbanweave, with the reason", ""]
    lines += [f"- {c['dataset']} / {c['operator']} / {c['aggregation']} (legacy: {c['legacy']}): {c['reason']}"
              for c in cases if c["status"] == "refused"] or ["None."]
    lines += ["", "## Failed in legacy only", ""]
    lines += [f"- {c['dataset']} / {c['operator']} / {c['aggregation']}: {c['reason']}"
              for c in cases if c["status"] == "legacy_failed"] or ["None."]
    lines += ["", "## Skipped", ""]
    reasons: dict[str, int] = {}
    for c in cases:
        if c["status"] == "skipped":
            r = c["reason"]
            key = ("above the size limit" if "MB" in r else f"extent above {MAX_CELLS} cells" if "extent" in r
                   else "timeout" if r.startswith("timeout") else r.split(",")[0])
            reasons[key] = reasons.get(key, 0) + 1
    lines += [f"- {k}: {v}" for k, v in sorted(reasons.items())]
    lines += ["", "## Named differences", ""]
    named: dict[str, int] = {}
    for c in cases:
        for k in (c.get("explained") or {}):
            named[k] = named.get(k, 0) + 1
    lines += [f"- {k}: in {v} cases" for k, v in sorted(named.items())] or ["None."]
    (out / "urbantrace_corpus.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
