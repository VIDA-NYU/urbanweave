"""Dasymetric disaggregation, on hand-calculated fixtures (UTM 18N, metres)."""

import numpy as np
import pandas as pd
import pytest

import urbanweave as uw
from urbanweave.errors import InputError

from .conftest import TOL, frame, pt, sq

# Zones A (x 0-100) and B (x 100-200), 100 m tall; C lies away from every target; D has no total.
ZONES = frame([sq(0, 0, 100), sq(100, 0, 100), sq(500, 0, 50), sq(600, 0, 50)],
              target_id=["A", "B", "C", "D"], trips=[100.0, 50.0, 10.0, np.nan])
# Eight 50 m cells over A and B: a0 a1 (bottom), a2 a3 (top) in A; b0..b3 likewise in B.
CELLS = frame([sq(x, y, 50) for x0 in (0, 100) for y in (0, 50) for x in (x0, x0 + 50)],
              target_id=["a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3"])


def _est(out, col="trips"):
    return out.set_index("target_id")[col]


def test_one_prior_spreads_each_zone_total_like_its_points_and_falls_back_to_area():
    prior = frame([pt(10, 10), pt(20, 20), pt(30, 30), pt(60, 10)])  # 3 in a0, 1 in a1; none in B
    out = uw.dasymetric(ZONES, CELLS, prior, total="trips")
    e = _est(out)
    assert e["a0"] == pytest.approx(75.0, **TOL) and e["a1"] == pytest.approx(25.0, **TOL)
    assert e["a2"] == e["a3"] == 0
    assert [e[c] for c in ("b0", "b1", "b2", "b3")] == pytest.approx([12.5] * 4, **TOL)  # by area
    rep = uw.report_of(out)["dasymetric"]
    assert rep["total"]["allocated"] == pytest.approx(150.0, **TOL) == pytest.approx(e.sum(), **TOL)
    assert rep["total"]["by_area_fallback"] == pytest.approx(50.0)
    assert rep["total"]["unallocated"]["zone_without_targets"]["total"] == pytest.approx(10.0)
    assert rep["total"]["unallocated"]["zone_total_missing"]["count"] == 1
    assert rep["zones_without_prior"]["sample"] == ["B"]


def test_without_fallback_a_zone_without_prior_is_reported_unallocated():
    prior = frame([pt(10, 10)])
    out = uw.dasymetric(ZONES, CELLS, prior, total="trips", fallback="none")
    e = _est(out)
    assert e[["b0", "b1", "b2", "b3"]].sum() == 0
    rep = uw.report_of(out)["dasymetric"]["total"]
    assert rep["allocated"] == pytest.approx(100.0) and rep["unallocated"]["no_prior_no_fallback"]["total"] == pytest.approx(50.0)


def test_a_cell_straddling_two_zones_gets_each_zones_share_by_where_the_points_are():
    cells = frame([sq(80, 0, 40, 100), sq(0, 0, 80, 100), sq(120, 0, 80, 100)], target_id=["mid", "west", "east"])
    prior = frame([pt(90, 50), pt(90, 60), pt(40, 50), pt(110, 50)])  # mid∩A: 2, west: 1, mid∩B: 1
    e = _est(uw.dasymetric(ZONES, cells, prior, total="trips"))
    assert e["mid"] == pytest.approx(100 * 2 / 3 + 50 * 1, **TOL)  # all of B's prior lies in mid
    assert e["west"] == pytest.approx(100 / 3, **TOL) and e["east"] == pytest.approx(0, abs=1e-9)


def test_weighted_layers_with_share_and_minmax_normalization():
    zones = frame([sq(0, 0, 100)], target_id=["A"], trips=[100.0])
    cells = frame([sq(0, 0, 50, 100), sq(50, 0, 50, 100)], target_id=["left", "right"])
    hotels = frame([pt(10, 10)] * 4)       # 4 in left
    shops = frame([pt(60, 10)] * 2)        # 2 in right
    share = _est(uw.dasymetric(zones, cells, {"hotels": hotels, "shops": shops}, total="trips",
                               weights={"hotels": 3, "shops": 1}))
    assert share["left"] == pytest.approx(75.0, **TOL) and share["right"] == pytest.approx(25.0, **TOL)
    raw = _est(uw.dasymetric(zones, cells, {"hotels": hotels, "shops": shops}, total="trips", normalize=None))
    assert raw["left"] == pytest.approx(100 * 4 / 6, **TOL)  # counts as they are
    mm = _est(uw.dasymetric(zones, cells, {"hotels": hotels, "shops": shops}, total="trips", normalize="minmax"))
    assert mm["left"] == pytest.approx(50.0, **TOL)  # each layer scaled to [0, 1], equal weights


def test_a_column_is_summed_instead_of_counted_and_ids_can_come_from_a_column():
    zones = frame([sq(0, 0, 100)], target_id=["A"], trips=[60.0])
    cells = frame([sq(0, 0, 50, 100), sq(50, 0, 50, 100)], target_id=["left", "right"])
    hotels = frame([pt(10, 10), pt(60, 10)], source_id=["h1", "h2"], rooms=[100, 200])
    e = _est(uw.dasymetric(zones, cells, (hotels, "rooms"), total="trips", as_="est"), "est")
    assert e["left"] == pytest.approx(20.0, **TOL) and e["right"] == pytest.approx(40.0, **TOL)


def test_points_outside_zones_or_targets_are_reported_and_inputs_checked():
    prior = frame([pt(10, 10), pt(400, 10)], source_id=["in", "out"])
    rep = uw.report_of(uw.dasymetric(ZONES, CELLS, prior, total="trips"))["dasymetric"]["priors"]["prior"]
    assert rep["outside_zones_or_targets"] == {"count": 1, "sample": ["out"]}
    with pytest.raises(InputError, match="normalize"):
        uw.dasymetric(ZONES, CELLS, prior, total="trips", normalize="zscore")
    with pytest.raises(InputError, match="not priors"):
        uw.dasymetric(ZONES, CELLS, {"a": prior}, total="trips", weights={"b": 1})
    with pytest.raises(InputError, match="not in the zones"):
        uw.dasymetric(ZONES, CELLS, prior, total="nope")


def test_a_per_target_series_spreads_each_zone_total_like_its_values_and_falls_back_to_area():
    density = pd.Series({"a0": 3.0, "a1": 1.0, "a2": 0.0})  # a3 and every B cell left out: 0
    out = uw.dasymetric(ZONES, CELLS, density, total="trips")
    e = _est(out)
    assert e["a0"] == pytest.approx(75.0, **TOL) and e["a1"] == pytest.approx(25.0, **TOL)
    assert e["a2"] == e["a3"] == 0
    assert [e[c] for c in ("b0", "b1", "b2", "b3")] == pytest.approx([12.5] * 4, **TOL)  # B by area
    rep = uw.report_of(out)["dasymetric"]
    assert rep["total"]["by_area_fallback"] == pytest.approx(50.0)
    assert rep["zones_without_prior"]["sample"] == ["B"]
    layer = rep["priors"]["prior"]
    assert layer["kind"] == "per_target" and layer["targets_with_value"] == 3
    assert layer["value"] == pytest.approx(4.0) and layer["value_in_zones"] == pytest.approx(4.0, **TOL)


def test_a_target_split_by_zones_passes_its_value_to_its_pieces_by_area_share():
    cells = frame([sq(80, 0, 40, 100), sq(0, 0, 80, 100), sq(120, 0, 80, 100)], target_id=["mid", "west", "east"])
    # mid is half in A, half in B: 2 to each piece. A: mid 2, west 2 -> 50 / 50. B: mid 2, east 0 -> 50 to mid.
    e = _est(uw.dasymetric(ZONES, cells, pd.Series({"mid": 4.0, "west": 2.0, "east": 0.0}), total="trips"))
    assert e["mid"] == pytest.approx(50 + 50, **TOL)
    assert e["west"] == pytest.approx(50.0, **TOL) and e["east"] == pytest.approx(0, abs=1e-9)
    # Unequal split: a cell 30 m in A and 10 m in B passes 3/4 of its value to A's piece.
    cells = frame([sq(70, 0, 40, 100), sq(0, 0, 70, 100), sq(110, 0, 90, 100)], target_id=["mid", "west", "east"])
    e = _est(uw.dasymetric(ZONES, cells, pd.Series({"mid": 4.0, "west": 1.0, "east": 3.0}), total="trips"))
    # A: mid 3, west 1 -> 75 / 25. B: mid 1, east 3 -> 12.5 / 37.5.
    assert e["mid"] == pytest.approx(75 + 12.5, **TOL)
    assert e["west"] == pytest.approx(25.0, **TOL) and e["east"] == pytest.approx(37.5, **TOL)


def test_point_and_per_target_layers_mix_with_weights_and_normalization():
    zones = frame([sq(0, 0, 100)], target_id=["A"], trips=[100.0])
    cells = frame([sq(0, 0, 50, 100), sq(50, 0, 50, 100)], target_id=["left", "right"])
    hotels = frame([pt(10, 10)] * 4)                       # 4 in left: shares 1, 0
    density = pd.Series({"left": 1.0, "right": 3.0})       # shares 0.25, 0.75
    layers = {"hotels": hotels, "density": density}
    share = _est(uw.dasymetric(zones, cells, layers, total="trips", weights={"hotels": 3, "density": 1}))
    assert share["left"] == pytest.approx(100 * (0.75 * 1 + 0.25 * 0.25), **TOL)  # 81.25
    raw = _est(uw.dasymetric(zones, cells, {"density": density, "hotels": hotels}, total="trips", normalize=None))
    assert raw["left"] == pytest.approx(100 * (4 + 1) / (4 + 1 + 3), **TOL)  # 62.5, layer order irrelevant
    mm = _est(uw.dasymetric(zones, cells, layers, total="trips", normalize="minmax"))
    assert mm["left"] == pytest.approx(50.0, **TOL)  # hotels [1, 0], density [0, 1]


def test_per_target_layers_report_unknown_ids_targets_outside_zones_and_missing_values():
    cells = frame([sq(0, 0, 100), sq(900, 0, 50)], target_id=["in", "far"])
    zones = frame([sq(0, 0, 100)], target_id=["A"], trips=[10.0])
    density = pd.Series({"in": 2.0, "far": 5.0, "ghost": 1.0, "blank": np.nan})
    out = uw.dasymetric(zones, cells, density, total="trips")
    assert _est(out)["in"] == pytest.approx(10.0, **TOL) and _est(out)["far"] == 0
    rep = uw.report_of(out)["dasymetric"]["priors"]["prior"]
    assert rep["value"] == pytest.approx(7.0) and rep["value_in_zones"] == pytest.approx(2.0, **TOL)
    assert rep["targets_in_no_zone"] == {"count": 1, "sample": ["far"]}
    assert rep["not_targets"]["count"] == 2 and set(rep["not_targets"]["sample"]) == {"ghost", "blank"}
    assert rep["missing_values"] == {"count": 1, "sample": ["blank"]}
    with pytest.raises(InputError, match="non-negative"):
        uw.dasymetric(zones, cells, pd.Series({"in": -1.0}), total="trips")


def test_several_totals_are_spread_in_one_call_like_separate_calls():
    prior = frame([pt(10, 10), pt(20, 20), pt(30, 30), pt(60, 10)])
    zones = ZONES.assign(jan=[10.0, 4.0, 1.0, 2.0], feb=[np.nan, 8.0, 0.0, 3.0])
    out = uw.dasymetric(zones, CELLS, prior, total=["trips", "jan", "feb"], as_=["t", "j", "f"])
    for col, name in (("trips", "t"), ("jan", "j"), ("feb", "f")):
        one = uw.dasymetric(zones, CELLS, prior, total=col)
        assert _est(out, name).to_numpy() == pytest.approx(_est(one, col).to_numpy(), **TOL)
        assert uw.report_of(out)["dasymetric"]["total"][col] == uw.report_of(one)["dasymetric"]["total"]
    assert uw.report_of(out)["dasymetric"]["total"]["feb"]["unallocated"]["zone_total_missing"]["sample"] == ["A"]
    assert list(uw.dasymetric(zones, CELLS, prior, total=["jan", "feb"]).columns[-2:]) == ["jan", "feb"]
    with pytest.raises(InputError):
        uw.dasymetric(zones, CELLS, prior, total=["jan", "feb"], as_="x")
    with pytest.raises(InputError):
        uw.dasymetric(zones, CELLS, prior, total=["jan", "nope"])
