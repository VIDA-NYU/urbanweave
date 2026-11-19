"""Generated checks: conservation over partitions, fraction bounds, and order independence."""

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import urbanweave as uw

from .conftest import X0, Y0, frame, pt, sq

grid_sizes = st.integers(min_value=1, max_value=4)


def _grid(nx, ny, size):
    return frame([sq(i * size, j * size, size) for i in range(nx) for j in range(ny)],
                 target_id=[f"c{i}-{j}" for i in range(nx) for j in range(ny)])


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(nx=grid_sizes, ny=grid_sizes, data=st.data())
def test_area_overlap_conserves_totals_over_a_partition(nx, ny, data):
    size = 100.0
    n = data.draw(st.integers(1, 6))
    boxes, vals = [], []
    for _ in range(n):
        x = data.draw(st.floats(0, nx * size - 1))
        y = data.draw(st.floats(0, ny * size - 1))
        w = data.draw(st.floats(0.5, nx * size - x))
        h = data.draw(st.floats(0.5, ny * size - y))
        boxes.append(sq(x, y, w, h))
        vals.append(data.draw(st.floats(0, 1e6)))
    src = frame(boxes, v=vals)
    m = uw.match(src, _grid(nx, ny, size), "area_overlap")
    frac = m.positions.groupby("src")["allocation_fraction"].sum()
    assert ((m.positions["allocation_fraction"] > 0) & (m.positions["allocation_fraction"] <= 1 + 1e-9)).all()
    assert np.allclose(frac.to_numpy(), 1.0, rtol=1e-9, atol=1e-9)
    out = uw.aggregate(m, None, [uw.sum("v")])
    assert out["sum_v"].sum() == pytest.approx(sum(vals), rel=1e-9, abs=1e-6)


@settings(max_examples=40, deadline=None)
@given(nx=grid_sizes, ny=grid_sizes, coords=st.lists(st.tuples(st.integers(0, 400), st.integers(0, 400)), min_size=1, max_size=30))
def test_contain_assigns_each_covered_point_exactly_once(nx, ny, coords):
    # Integer coordinates on a 100 m grid put many points on edges and vertices.
    cells = _grid(nx, ny, 100.0)
    src = frame([pt(x, y) for x, y in coords], v=list(range(len(coords))))
    m = uw.match(src, cells, "contain")
    inside = [x <= nx * 100 and y <= ny * 100 for x, y in coords]
    assert m.pairs["source_id"].is_unique
    assert len(m.pairs) == sum(inside)


def test_shuffled_rows_give_the_same_matches_and_reductions():
    rng = np.random.default_rng(3)
    n = 300
    xs, ys = rng.uniform(0, 400, n), rng.uniform(0, 400, n)
    xs[:40] = np.round(xs[:40] / 100) * 100  # some on edges
    src = frame([pt(x, y) for x, y in zip(xs, ys)], source_id=[f"s{i}" for i in range(n)], v=rng.normal(size=n))
    cells = _grid(4, 4, 100.0)
    polys = frame([sq(x, y, 30) for x, y in zip(xs[:60], ys[:60])], source_id=[f"p{i}" for i in range(60)], v=rng.normal(size=60))
    for method, source in (("contain", src), ("nearest", src), ("area_overlap", polys), ("centroid", polys)):
        a = uw.aggregate(uw.match(source, cells, method), None, [uw.sum("v"), uw.weighted_mean("v")])
        perm = rng.permutation(len(source))
        b = uw.aggregate(uw.match(source.iloc[perm], cells.iloc[rng.permutation(len(cells))], method), None,
                         [uw.sum("v"), uw.weighted_mean("v")])
        a = a.set_index("target_id").sort_index()
        b = b.set_index("target_id").sort_index()
        pd.testing.assert_series_equal(a["sum_v"].astype(float), b["sum_v"].astype(float), rtol=1e-12, atol=1e-12)
        pd.testing.assert_series_equal(a["weighted_mean_v"].astype(float), b["weighted_mean_v"].astype(float), rtol=1e-12)
        ma = uw.match(source, cells, method).pairs.sort_values(["source_id", "target_id"]).reset_index(drop=True)
        mb = uw.match(source.iloc[perm], cells, method).pairs.sort_values(["source_id", "target_id"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(ma, mb, rtol=1e-12)
