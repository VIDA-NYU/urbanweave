"""Reductions: rules for kinds, bases, order, filters, integers and outputs."""

import numpy as np
import pandas as pd
import pytest

import urbanweave as uw
from urbanweave.errors import InputError, UnsupportedError

from .conftest import TOL, frame, ln, pt, sq


@pytest.fixture
def two_zones():
    return frame([sq(0, 0, 10), sq(10, 0, 10)], target_id=["a", "b"])


@pytest.fixture
def pts():
    return frame([pt(1, 1), pt(2, 2), pt(3, 3), pt(12, 2)],
                 n=pd.array([3, 1, 2, 7], dtype="int64"), x=[1.0, 2.0, 10.0, 5.0],
                 kind=["oak", "elm", "elm", "oak"], txt=["1", "two", None, "4"])


def test_mean_median_min_max_and_integer_types(two_zones, pts):
    out = uw.aggregate(uw.match(pts, two_zones, "contain"), None,
                       [uw.mean("x"), uw.median("x"), uw.min("n"), uw.max("n"), uw.sum("n")]).set_index("target_id")
    assert out.loc["a", "mean_x"] == pytest.approx(13 / 3, **TOL)
    assert out.loc["a", "median_x"] == 2.0
    assert out.loc["a", "min_n"] == 1 and out.loc["a", "max_n"] == 3 and out.loc["a", "sum_n"] == 6
    assert str(out["min_n"].dtype) == "Int64" and str(out["sum_n"].dtype) == "Int64"


def test_majority_ties_go_to_the_smallest_category(two_zones):
    src = frame([pt(1, 1), pt(2, 2)], kind=["oak", "elm"])
    out = uw.aggregate(uw.match(src, two_zones, "contain"), None, [uw.majority("kind")])
    assert out["majority_kind"].iloc[0] == "elm" and pd.isna(out["majority_kind"].iloc[1])


def test_weighted_median(two_zones):
    src = frame([sq(0, 0, 10, 1), sq(0, 1, 10, 2), sq(0, 3, 10, 7)], v=[1.0, 2.0, 3.0])
    out = uw.aggregate(uw.match(src, two_zones, "area_overlap"), None, [uw.weighted_median("v")])
    assert out["weighted_median_v"].iloc[0] == 3.0  # 70% of the area holds 3


@pytest.mark.parametrize("method", ["area_overlap", "largest_overlap"])
def test_overlap_length_density_refuses_area(two_zones, method):
    sources = frame([sq(0, 0, 10)], total=[20])
    m = uw.match(sources, two_zones, method)
    with pytest.raises(UnsupportedError, match="overlap lengths from source lines"):
        uw.aggregate(m, reductions=uw.density("total", denominator="overlap_length"))


@pytest.mark.parametrize("method", ["length_weighted", "largest_overlap"])
def test_overlap_length_density_accepts_lengths(two_zones, method):
    sources = frame([ln((0, 1), (10, 1))], total=[20])
    m = uw.match(sources, two_zones, method)
    out = uw.aggregate(m, reductions=uw.density("total", denominator="overlap_length"))
    assert out["density_total"].iloc[0] == pytest.approx(2000, **TOL)
    assert pd.isna(out["density_total"].iloc[1])


def test_not_numeric_values_are_reported_apart_from_missing(two_zones, pts):
    out = uw.aggregate(uw.match(pts, two_zones, "contain"), None, [uw.mean("txt")])
    vals = uw.report_of(out)["aggregate"][0]["values"]
    assert vals == {"missing": 1, "not_numeric": 1, "not_finite": 0, "valid": 2}
    assert out["mean_txt"].tolist() == pytest.approx([1.0, 4.0], **TOL)


def test_where_filters_and_counts_zero_for_matched_targets(two_zones, pts):
    out = uw.aggregate(uw.match(pts, two_zones, "contain"), None,
                       [uw.count(as_="oaks", where={"column": "kind", "op": "==", "value": "oak"}),
                        uw.count(as_="big", where=[{"column": "x", "op": ">", "value": 4}, {"column": "kind", "op": "==", "value": "elm"}])])
    assert out["oaks"].tolist() == [1, 1]
    assert out["big"].tolist() == [1, 0]


def test_value_kinds_refuse_unsuitable_reductions(two_zones, pts):
    m = uw.match(pts, two_zones, "contain")
    with pytest.raises(UnsupportedError, match="intensive"):
        uw.aggregate(m, None, [uw.sum("x")], value_kinds={"x": "intensive"})
    with pytest.raises(UnsupportedError, match="extensive"):
        uw.aggregate(m, None, [uw.weighted_mean("n")], value_kinds={"n": "extensive"})
    with pytest.raises(UnsupportedError, match="categorical"):
        uw.aggregate(m, None, [uw.mean("kind")], value_kinds={"kind": "categorical"})


def test_output_names_and_columns_are_checked(two_zones, pts):
    m = uw.match(pts, two_zones, "contain")
    with pytest.raises(InputError, match="repeat"):
        uw.aggregate(m, None, [uw.sum("x", as_="s"), uw.mean("x", as_="s")])
    with pytest.raises(InputError, match="not in the values"):
        uw.aggregate(m, None, [uw.sum("nope")])
    with pytest.raises(InputError, match="already columns"):
        uw.aggregate(m, None, [uw.count(as_="target_id")])
    with pytest.raises(InputError, match="fill_empty"):
        uw.aggregate(m, None, [uw.mean("x", ) .__class__("mean", "x", None, None, 0)])


def test_values_from_another_table_and_missing_ids(two_zones):
    src = frame([pt(1, 1), pt(12, 1)], source_id=["p", "q"])
    values = pd.DataFrame({"source_id": ["p"], "v": [5.0]})
    out = uw.aggregate(uw.match(src, two_zones, "contain"), values, [uw.sum("v")])
    assert out["sum_v"].iloc[0] == 5.0 and pd.isna(out["sum_v"].iloc[1])
    assert uw.report_of(out)["aggregate"][0]["values"]["sources_not_in_values"] == 1


def test_custom_reduction_is_flagged_unserializable(two_zones, pts):
    r = uw.custom(lambda rows: rows["x"].max() - rows["x"].min(), as_="spread")
    out = uw.aggregate(uw.match(pts, two_zones, "contain"), None, [r])
    assert out["spread"].tolist()[0] == 9.0
    with pytest.raises(TypeError):
        r.to_dict()


def test_result_keeps_target_order_and_given_targets(two_zones, pts):
    m = uw.match(pts, two_zones, "contain")
    reordered = two_zones.iloc[::-1]
    out = uw.aggregate(m, None, [uw.count()], targets=reordered)
    assert out["target_id"].tolist() == ["b", "a"] and out["count"].tolist() == [1, 3]


def test_reduction_json_round_trip():
    r = uw.weighted_mean("utci", as_="utci_mean", weighted_total_as="t", valid_measure_as="m")
    assert uw.Reduction.from_dict(r.to_dict()) == r
    assert uw.count(fill_empty=0).to_dict() == {"method": "count", "as": "count", "fill_empty": 0}
