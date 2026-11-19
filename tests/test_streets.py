"""Street targets, split_lines, along_lines and reduce, with the street fixtures of PLAN.md."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("osmnx")
pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402
import urbanweave as uw  # noqa: E402
from urbanweave import streets  # noqa: E402
from urbanweave.errors import UnsupportedError  # noqa: E402

from .conftest import TOL, UTM18, X0, Y0, frame, ln, pt, sq  # noqa: E402

pytestmark = pytest.mark.osm
GRAPH = Path(__file__).parent / "fixtures" / "street_graph.graphml"


def test_physical_segments_merge_reciprocal_edges_and_keep_carriageways():
    s = streets.osm_streets(graphml=GRAPH)
    assert len(s) == 6 and len(streets.osm_streets(graphml=GRAPH, representation="directed")) == 8
    first = s.set_index("target_id").loc["1-2-0"]
    assert first["edges"] == "1-2-0;2-1-0" and first["length_m"] == pytest.approx(1000.0, **TOL)
    assert set(s.loc[s["name"] == "South Blvd", "target_id"]) == {"2-5-0", "5-2-0"}  # two carriageways
    assert "1-2-1" in set(s["target_id"])  # the parallel curved street
    inter = streets.osm_intersections(graphml=GRAPH)
    assert inter["target_id"].tolist() == [2] and inter["degree"].tolist() == [6]


def test_crashes_per_road_km_on_physical_streets():
    s = streets.osm_streets(graphml=GRAPH)
    straight = s[s["target_id"].isin(["1-2-0", "2-3-0"])]  # two 1 km physical streets
    crashes = frame([pt(100, 3), pt(300, -2), pt(600, 1), pt(900, 0)])  # four on First St, A–B
    m = uw.match(crashes, straight, "nearest_segment", max_distance=30)
    per_street = uw.aggregate(m, None, [uw.count(as_="crashes", fill_empty=0)])
    zone = frame([sq(-100, -100, 2200, 200)], target_id=["z"])
    out = uw.aggregate(uw.match(per_street, zone, "length_weighted", shared_boundary="lowest_target_id"), None,
                       [uw.density("crashes", as_="per_road_km", denominator="overlap_length")])
    assert out["per_road_km"].iloc[0] == pytest.approx(2.0, **TOL)  # 4 crashes / 2 road-km
    directed = streets.osm_streets(graphml=GRAPH, representation="directed")
    assert directed[directed["u"].isin([1, 2]) & directed["v"].isin([1, 2]) & (directed["key"] == 0)].shape[0] == 2


def test_split_lines_gives_stable_pieces_and_boundary_length_once():
    zones = frame([sq(0, 0, 100), sq(100, 0, 100)], target_id=["w", "e"])
    lines = frame([ln((50, 50), (150, 50)), ln((100, 10), (100, 90)), ln((10, 10), (20, 10))], target_id=["across", "edge", "inside"])
    pieces = streets.split_lines(lines, zones)
    got = pieces.set_index("piece_id")["length_m"].to_dict()
    assert got == pytest.approx({"across|w": 50.0, "across|e": 50.0, "edge|e": 80.0, "inside|w": 10.0}, **TOL)
    assert set(pieces.columns) >= {"piece_id", "line_id", "zone_id", "length_m"}
    independent = streets.split_lines(lines, zones, shared_boundary="independent")
    assert independent.set_index("piece_id")["length_m"].filter(like="edge").sum() == pytest.approx(160.0, **TOL)


def _heat_raster():
    # 10 m cells, one row of 14: nine cells at UTCI 10, one at 30, two nodata (NaN), then 20 and 20.
    row = np.array([[10.0] * 9 + [30.0] + [np.nan, np.nan] + [20.0, 20.0]])
    return uw.read_raster(np.ma.masked_invalid(row), transform=from_origin(X0, Y0 + 10, 10, 10), crs=UTM18)


def test_heat_along_streets_pooled_by_zone():
    r = _heat_raster()
    zones = frame([sq(0, 0, 120, 10), sq(120, 0, 20, 10), sq(100, -50, 20, 40)], target_id=["z1", "z2", "dark"])
    street = frame([ln((0, 5), (140, 5)), ln((105, -20), (115, -20))], target_id=["main", "nodata_street"])
    pieces = streets.split_lines(street, zones)
    heat = streets.along_lines(r, pieces, [uw.weighted_mean(1, as_="utci_mean", weighted_total_as="utci_m_sum",
                                                            valid_measure_as="valid_m")])
    p = heat.set_index("piece_id")
    assert p.loc["main|z1", "utci_mean"] == pytest.approx(12.0, **TOL)  # (90×10 + 10×30) / 100
    assert p.loc["main|z1", "valid_m"] == pytest.approx(100.0, **TOL)
    assert p.loc["main|z1", "valid_fraction"] == pytest.approx(100 / 120, **TOL)
    assert p.loc["main|z2", "utci_mean"] == pytest.approx(20.0, **TOL)  # only its own zone's cells
    out = streets.reduce(heat, by="zone_id", targets=zones,
                         reductions=[streets.ratio_of_sums("utci_m_sum", "valid_m", as_="utci_mean")]).set_index("target_id")
    assert out.loc["z1", "utci_mean"] == pytest.approx(12.0, **TOL)
    assert out.loc["z2", "utci_mean"] == pytest.approx(20.0, **TOL)
    assert pd.isna(out.loc["dark", "utci_mean"])  # outside the raster: zero valid length, missing mean


def test_a_line_on_a_cell_boundary_counts_once():
    r = uw.read_raster(np.array([[1.0, 2.0], [3.0, 4.0]]), transform=from_origin(X0, Y0 + 20, 10, 10), crs=UTM18)
    on_edge = frame([ln((10, 2), (10, 18))], target_id=["vertical"])  # on the boundary between columns 0 and 1
    out = streets.along_lines(r, on_edge, [uw.weighted_mean(1, as_="m", valid_measure_as="len")])
    assert out["len"].iloc[0] == pytest.approx(16.0, **TOL)  # not 32
    assert out["m"].iloc[0] == pytest.approx((8 * 2 + 8 * 4) / 16, **TOL)  # the east cells own the boundary


def test_along_lines_refusals():
    r = uw.read_raster(np.ones((2, 2)), transform=from_origin(-74, 40.8, 0.01, 0.01), crs=4326)
    with pytest.raises(UnsupportedError, match="projected"):
        streets.along_lines(r, frame([ln((0, 0), (1, 1))]), [uw.weighted_mean(1)])
