"""The vector acceptance fixtures of PLAN.md, computed by hand."""

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

import urbanweave as uw

from .conftest import TOL, X0, Y0, frame, ln, pt, sq


def test_unequal_areas_weighted_mean_and_shares():
    # Two polygons, 100 m² at 10 °C and 900 m² at 20 °C, under one target.
    src = frame([sq(0, 0, 10), sq(10, 0, 30, 30)], temp=[10.0, 20.0], landuse=["park", "housing"])
    tgt = frame([sq(-5, -5, 60)], target_id=["z"])
    m = uw.match(src, tgt, "area_overlap")
    assert m.pairs["allocation_fraction"].tolist() == pytest.approx([1.0, 1.0], **TOL)
    out = uw.aggregate(m, None, [uw.weighted_mean("temp"), uw.shares("landuse")])
    assert out["weighted_mean_temp"].iloc[0] == pytest.approx(19.0, **TOL)
    assert out["shares_landuse_park"].iloc[0] == pytest.approx(0.1, **TOL)
    assert out["shares_landuse_housing"].iloc[0] == pytest.approx(0.9, **TOL)


def _one_source_of_100():
    return frame([sq(0, 0, 100)], total=[100.0], source_id=["s"])


def test_complete_partition_conserves_the_total():
    tgt = frame([sq(0, 0, 30, 100), sq(30, 0, 70, 100)], target_id=["a", "b"])
    out = uw.aggregate(uw.match(_one_source_of_100(), tgt, "area_overlap"), None, [uw.sum("total")])
    assert out["sum_total"].sum() == pytest.approx(100.0, **TOL)
    assert out["sum_total"].tolist() == pytest.approx([30.0, 70.0], **TOL)


def test_disjoint_partial_coverage_reports_the_unallocated_share():
    tgt = frame([sq(0, 0, 30, 100), sq(40, 0, 50, 100)], target_id=["a", "b"])  # 30% and 50%
    out = uw.aggregate(uw.match(_one_source_of_100(), tgt, "area_overlap"), None, [uw.sum("total")])
    assert out["sum_total"].tolist() == pytest.approx([30.0, 50.0], **TOL)
    ext = uw.report_of(out)["aggregate"][0]["extensive"]
    assert ext["allocated"] == pytest.approx(80.0, **TOL)
    assert ext["unallocated"] == pytest.approx(20.0, **TOL)
    assert uw.report_of(out)["match"]["allocation"]["partial_sources"] == 1


def test_independent_overlapping_targets_each_get_their_overlap():
    tgt = frame([sq(0, 0, 80, 100), sq(20, 0, 80, 100)], target_id=["a", "b"])  # 80% each
    m = uw.match(_one_source_of_100(), tgt, "area_overlap")
    out = uw.aggregate(m, None, [uw.sum("total")])
    assert out["sum_total"].tolist() == pytest.approx([80.0, 80.0], **TOL)
    assert "union_coverage" in m.report["allocation"]  # pairwise weights alone leave union coverage undetermined
    ext = uw.report_of(out)["aggregate"][0]["extensive"]
    assert ext["unallocated"] is None and "coverage_note" in ext


def test_boundary_point_and_equidistant_point_each_match_once():
    zones = frame([sq(0, 0, 100), sq(100, 0, 100)], target_id=["b", "a"])  # IDs not in position order
    points = frame([pt(100, 50), pt(100, 100), pt(100, 0)], source_id=[1, 2, 3])  # an edge and two vertices
    m = uw.match(points, zones, "contain")
    assert len(m.pairs) == 3
    assert set(m.pairs["target_id"]) == {"a"}  # the lowest target ID
    assert m.report["notes"]["boundary_ties"] == 3

    nodes = frame([pt(0, 0), pt(20, 0)], target_id=["n2", "n1"])
    near = uw.match(frame([pt(10, 5)]), nodes, "nearest")
    assert near.pairs["target_id"].tolist() == ["n1"]
    assert near.pairs["distance_m"].iloc[0] == pytest.approx(np.hypot(10, 5), **TOL)


def test_line_on_a_shared_boundary_counts_once_under_the_partition_rule():
    zones = frame([sq(0, 0, 100), sq(100, 0, 100)], target_id=["a", "b"])
    line = frame([ln((100, 10), (100, 60))], source_id=["edge"])
    independent = uw.match(line, zones, "length_weighted")
    assert independent.pairs["overlap_measure"].sum() == pytest.approx(100.0, **TOL)  # counted in both
    once = uw.match(line, zones, "length_weighted", shared_boundary="lowest_target_id")
    assert once.pairs["target_id"].tolist() == ["a"]
    assert once.pairs["overlap_measure"].tolist() == pytest.approx([50.0], **TOL)
    assert once.pairs["allocation_fraction"].tolist() == pytest.approx([1.0], **TOL)


def test_centroid_and_representative_point_select_different_targets():
    # A U shape whose centroid lies in its notch, outside the polygon.
    u = Polygon([(X0, Y0), (X0 + 30, Y0), (X0 + 30, Y0 + 30), (X0 + 20, Y0 + 30), (X0 + 20, Y0 + 10),
                 (X0 + 10, Y0 + 10), (X0 + 10, Y0 + 30), (X0, Y0 + 30)])
    assert not u.contains(u.centroid)
    notch = sq(10, 10, 10, 20)
    rest = frame([notch, sq(-10, -10, 50).difference(notch)], target_id=["notch", "rest"])
    src = frame([u], source_id=["u"])
    by_centroid = uw.match(src, rest, "centroid").pairs["target_id"].tolist()
    by_point = uw.match(src, rest, "representative_point").pairs["target_id"].tolist()
    assert by_centroid == ["notch"] and by_point == ["rest"]


def test_gaussian_cutoff_drops_by_default_and_falls_back_when_asked():
    cells = frame([sq(0, 0, 100), sq(100, 0, 100)], target_id=["c1", "c2"])
    far = frame([pt(5_000, 50)], source_id=["far"], v=[7.0])
    dropped = uw.match(far, cells, "gaussian", bandwidth=100)
    assert dropped.pairs.empty
    assert dropped.report["sources"]["unmatched"]["beyond_cutoff"]["count"] == 1
    kept = uw.match(far, cells, "gaussian", bandwidth=100, outside="nearest")
    assert kept.pairs["target_id"].tolist() == ["c2"]
    assert kept.pairs["allocation_fraction"].tolist() == [1.0]
    assert kept.report["notes"]["fallbacks"] == 1
    capped = uw.match(far, cells, "gaussian", bandwidth=100, outside="nearest", max_distance=1_000)
    assert capped.pairs.empty and capped.report["sources"]["unmatched"]["beyond_max_distance"]["count"] == 1


def test_valid_zeros_invalid_values_and_overflow():
    zones = frame([sq(0, 0, 10), sq(10, 0, 10), sq(20, 0, 10), sq(30, 0, 10)], target_id=["zero", "empty", "nan", "mixed"])
    pts = frame([pt(5, 5), pt(25, 5), pt(35, 5), pt(36, 5)], zero_or_nan=[0.0, np.nan, 4.0, np.nan])
    m = uw.match(pts, zones, "contain")
    out = uw.aggregate(m, None, [uw.sum("zero_or_nan", as_="s"), uw.sum("zero_or_nan", as_="s0", fill_empty=0),
                                 uw.count(as_="n"), uw.count(as_="n0", fill_empty=0)]).set_index("target_id")
    assert out.loc["zero", "s"] == 0  # a real zero stays zero
    assert pd.isna(out.loc["empty", "s"]) and out.loc["empty", "s0"] == 0  # the fill responds to no matches only
    assert pd.isna(out.loc["nan", "s"]) and pd.isna(out.loc["nan", "s0"])  # all-missing stays missing
    assert out.loc["mixed", "s"] == 4.0
    assert pd.isna(out.loc["empty", "n"]) and out.loc["empty", "n0"] == 0 and out.loc["mixed", "n"] == 2

    big = frame([pt(5, 5), pt(6, 5), pt(15, 5)], big=pd.array([2 ** 62, 2 ** 62, 5], dtype="Int64"))
    out = uw.aggregate(uw.match(big, zones, "contain"), None, [uw.sum("big")]).set_index("target_id")
    assert pd.isna(out.loc["zero", "sum_big"])  # 2**63 is past the int64 range
    assert out.loc["empty", "sum_big"] == 5 and str(out["sum_big"].dtype) == "Int64"
    assert uw.report_of(out)["aggregate"][0]["overflow_targets"] == 1
