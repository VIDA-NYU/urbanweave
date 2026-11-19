"""Benchmarks, run apart from the test suite.

    python tools/benchmark.py points --n 2000000            # points onto H3 resolution 9 and onto zones
    python tools/benchmark.py raster --size 20000           # zonal statistics on a tiled GeoTIFF

Each run prints one JSON record: the dataset and CRS, engine versions, hardware, candidate counts,
windows and cells read, wall time, peak memory (resident set size) and result checks. Synthetic data
stands in for NYC collisions and land cover until the real datasets are wired in; pass --data to use
a file instead.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np

import urbanweave as uw
from urbanweave.plan import engine_versions

NYC = (-74.05, 40.60, -73.75, 40.88)


def _peak_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 2 ** 20 if platform.system() == "Darwin" else rss / 2 ** 10


def _record(**kw):
    kw.update(engines=engine_versions(), hardware={"machine": platform.machine(), "processor": platform.processor(),
                                                   "system": platform.system()}, peak_rss_mb=round(_peak_mb(), 1))
    print(json.dumps(kw, indent=1, default=str))


def points(args):
    if args.data:
        pts = gpd.read_file(args.data).to_crs(4326)
    else:
        rng = np.random.default_rng(0)
        pts = gpd.GeoDataFrame({"v": rng.integers(0, 5, args.n)},
                               geometry=gpd.points_from_xy(rng.uniform(NYC[0], NYC[2], args.n), rng.uniform(NYC[1], NYC[3], args.n)),
                               crs=4326)
    t0 = time.time()
    cells = uw.targets.h3_cells(NYC, 9)
    t1 = time.time()
    m = uw.match(pts, cells, "contain")
    t2 = time.time()
    out = uw.aggregate(m, None, [uw.sum("v"), uw.count()])
    t3 = time.time()
    _record(benchmark="points_to_h3", dataset=args.data or f"synthetic uniform points over NYC (n={len(pts)})",
            crs="EPSG:4326 (measured in UTM 18N)", cells=len(cells), pairs=len(m.positions),
            seconds={"grid": round(t1 - t0, 2), "match": round(t2 - t1, 2), "aggregate": round(t3 - t2, 2)},
            check={"total_preserved": bool(np.isclose(out["sum_v"].sum(), pts["v"][m.positions["src"].unique()].sum()))})


def raster(args):
    import rasterio
    from rasterio.transform import from_origin

    size = args.size
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "landcover.tif"
        with rasterio.open(path, "w", driver="GTiff", height=size, width=size, count=1, dtype="uint8", crs="EPSG:32618",
                           transform=from_origin(580_000, 4_530_000, 1, 1), tiled=True, blockxsize=512, blockysize=512,
                           compress="deflate") as ds:
            rng = np.random.default_rng(1)
            for row in range(0, size, 512):
                h = min(512, size - row)
                ds.write(rng.integers(1, 9, (h, size), dtype="uint8"), 1, window=((row, row + h), (0, size)))
        rng = np.random.default_rng(2)
        n = args.zones
        xs = rng.uniform(580_000, 580_000 + size - 600, n)
        ys = rng.uniform(4_530_000 - size, 4_530_000 - 600, n)
        zones = gpd.GeoDataFrame(geometry=[gpd.points_from_xy([x], [y])[0].buffer(rng.uniform(50, 300)) for x, y in zip(xs, ys)],
                                 crs="EPSG:32618")
        r = uw.read_raster(path, value_kind="categorical")
        t0 = time.time()
        out = uw.zonal_stats(r, zones, [uw.shares(1, as_="lc")], max_cells_in_memory=args.max_cells)
        t1 = time.time()
        rep = uw.report_of(out)
        shares = out.filter(like="lc_").astype(float).sum(axis=1)
        _record(benchmark="zonal_shares", dataset=f"synthetic land cover {size}×{size} at 1 m, {n} circular zones",
                crs="EPSG:32618", seconds=round(t1 - t0, 2), reads=rep["reads"],
                check={"shares_sum_to_1": bool(np.allclose(shares.dropna(), 1.0))})
        r.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("points")
    p.add_argument("--n", type=int, default=200_000)
    p.add_argument("--data")
    p.set_defaults(fn=points)
    q = sub.add_parser("raster")
    q.add_argument("--size", type=int, default=5_000)
    q.add_argument("--zones", type=int, default=500)
    q.add_argument("--max-cells", type=int, default=4_000_000)
    q.set_defaults(fn=raster)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
