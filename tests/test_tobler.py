"""Area-weighted interpolation against Tobler (dev extra), on projected fixtures.

Tobler's extensive interpolation with allocate_total=False divides each source's value by its area,
which is urbanweave's allocation_fraction (allocate_total=True instead renormalizes each source over
the targets it touches, so overlapping targets split its total rather than each receiving its own
share). Its intensive interpolation weights by intersection area over target area, which equals
urbanweave's overlap-weighted mean where the sources cover the target; Tobler computes these in single
precision, hence rtol 1e-6. Shares compare with Tobler's categorical (area fraction of the target per
category).
"""

import numpy as np
import pytest

import urbanweave as uw

from .conftest import frame, sq

tobler_area = pytest.importorskip("tobler.area_weighted")


def _sources():
    # A 3 x 3 grid of 100 m squares with uneven values; ids s0..s8.
    rng = np.random.default_rng(3)
    geoms = [sq(100 * i, 100 * j, 100) for j in range(3) for i in range(3)]
    return frame(geoms, source_id=[f"s{k}" for k in range(9)], pop=rng.integers(0, 500, 9).astype(float),
                 temp=rng.uniform(15, 35, 9), land=rng.choice(["park", "built", "water"], 9))


def _targets():
    # Overlapping, offset targets wholly inside the sources' footprint, plus one straddling two rows.
    return frame([sq(30, 40, 120), sq(150, 10, 130), sq(10, 170, 270, 90)], target_id=["a", "b", "c"])


def test_extensive_sum_matches_tobler():
    src, tgt = _sources(), _targets()
    ours = uw.aggregate(uw.match(src, tgt, "area_overlap"), None, [uw.sum("pop", as_="pop")]).set_index("target_id")
    theirs = tobler_area.area_interpolate(src, tgt, extensive_variables=["pop"], allocate_total=False)
    np.testing.assert_allclose(ours.loc[["a", "b", "c"], "pop"].to_numpy(float), theirs["pop"].to_numpy(), rtol=1e-9)


def test_intensive_weighted_mean_matches_tobler():
    src, tgt = _sources(), _targets()
    ours = uw.aggregate(uw.match(src, tgt, "area_overlap"), None,
                        [uw.weighted_mean("temp", as_="temp")]).set_index("target_id")
    theirs = tobler_area.area_interpolate(src, tgt, intensive_variables=["temp"])
    np.testing.assert_allclose(ours.loc[["a", "b", "c"], "temp"].to_numpy(float), theirs["temp"].to_numpy(), rtol=1e-6)


def test_category_shares_match_tobler():
    src, tgt = _sources(), _targets()
    ours = uw.aggregate(uw.match(src, tgt, "area_overlap"), None, [uw.shares("land", as_="land")]).set_index("target_id")
    theirs = tobler_area.area_interpolate(src, tgt, categorical_variables=["land"])
    for cat in sorted(set(src["land"])):
        mine = ours.loc[["a", "b", "c"], f"land_{cat}"].astype(float).fillna(0).to_numpy()
        np.testing.assert_allclose(mine, theirs[f"land_{cat}"].to_numpy(), rtol=1e-9, atol=1e-12)


def test_a_target_half_outside_the_sources():
    # Both allocate by source area (half the total) and average over the covered part (the
    # source's value); urbanweave also reports the measured overlap the mean is taken over.
    src = frame([sq(0, 0, 100)], source_id=["s"], pop=[100.0], temp=[20.0])
    tgt = frame([sq(50, 0, 100)], target_id=["t"])
    ours = uw.aggregate(uw.match(src, tgt, "area_overlap"), None,
                        [uw.sum("pop"), uw.weighted_mean("temp", valid_measure_as="m2")])
    theirs = tobler_area.area_interpolate(src, tgt, extensive_variables=["pop"], intensive_variables=["temp"],
                                         allocate_total=False)
    assert ours["sum_pop"].iloc[0] == pytest.approx(theirs["pop"].iloc[0]) == pytest.approx(50.0)
    assert ours["weighted_mean_temp"].iloc[0] == pytest.approx(theirs["temp"].iloc[0], rel=1e-6) == pytest.approx(20.0)
    assert ours["m2"].iloc[0] == pytest.approx(5000.0)
