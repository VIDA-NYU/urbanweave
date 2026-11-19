"""Matching methods: quantities, thresholds, ties and reports."""

import geopandas as gpd
import numpy as np
import pytest

import urbanweave as uw
from urbanweave.errors import InputError, UnsupportedError

from .conftest import TOL, UTM18, frame, ln, pt, sq


def test_nearest_threshold_is_inclusive_and_in_metres():
    tgt = frame([pt(0, 0)], target_id=["n"])
    src = frame([pt(30, 0), pt(30.001, 0)], source_id=["at", "past"])
    m = uw.match(src, tgt, "nearest", max_distance=30)
    assert m.pairs["source_id"].tolist() == ["at"]
    assert m.report["sources"]["unmatched"]["beyond_max_distance"]["sample"] == ["past"]


def test_nearest_measures_in_metres_not_degrees():
    # Two targets 1 km east and 1 km north of a point at 40.7° N: in degrees the east one looks nearer.
    import pyproj

    t = pyproj.Transformer.from_crs(UTM18, 4326, always_xy=True)
    lon, lat = t.transform(585_000, 4_506_000)
    e_lon, e_lat = t.transform(585_000 + 1_000, 4_506_000)
    n_lon, n_lat = t.transform(585_000, 4_506_000 + 990)
    from shapely.geometry import Point

    tgt = gpd.GeoDataFrame({"target_id": ["east", "north"]}, geometry=[Point(e_lon, e_lat), Point(n_lon, n_lat)], crs=4326)
    src = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs=4326)
    m = uw.match(src, tgt, "nearest")
    assert m.pairs["target_id"].tolist() == ["north"]
    assert m.pairs["distance_m"].iloc[0] == pytest.approx(990, rel=1e-3)


def test_nearest_segment_and_node_accept_only_their_targets():
    streets = frame([ln((0, 0), (100, 0)), ln((0, 50), (100, 50))], target_id=["s1", "s2"])
    m = uw.match(frame([pt(10, 20)]), streets, "nearest_segment", max_distance=25)
    assert m.pairs["target_id"].tolist() == ["s1"] and m.pairs["distance_m"].iloc[0] == pytest.approx(20, **TOL)
    with pytest.raises(UnsupportedError):
        uw.match(frame([pt(0, 0)]), frame([sq(0, 0, 1)]), "nearest_segment")
    with pytest.raises(UnsupportedError):
        uw.match(frame([pt(0, 0)]), streets, "nearest_node")


def test_within_distance_split_replicate_and_k():
    tgt = frame([pt(0, 0), pt(10, 0), pt(40, 0)], target_id=["a", "b", "c"])
    src = frame([pt(4, 0)], source_id=["s"], v=[12.0])
    split = uw.match(src, tgt, "within_distance", distance=20)
    assert split.pairs["target_id"].tolist() == ["a", "b"]
    assert split.pairs["allocation_fraction"].tolist() == pytest.approx([0.5, 0.5], **TOL)
    rep = uw.match(src, tgt, "within_distance", distance=20, split=False)
    out = uw.aggregate(rep, None, [uw.sum("v")])
    assert out["sum_v"].tolist()[:2] == pytest.approx([12.0, 12.0], **TOL)
    assert uw.report_of(out)["aggregate"][0]["extensive"]["replicated"] == pytest.approx(12.0, **TOL)
    nearest_one = uw.match(src, tgt, "within_distance", distance=20, k=1, split=False)
    assert nearest_one.pairs["target_id"].tolist() == ["a"]  # 4 m away, nearer than b at 6 m
    first = uw.aggregate(uw.match(frame([pt(4, 0), pt(9, 0)], name=["p", "q"]), tgt, "within_distance",
                                  distance=20, split=False), None, [uw.first("name"), uw.join("name")])
    assert first.set_index("target_id").loc["b", "first_name"] == "q"  # nearest first
    assert first.set_index("target_id").loc["a", "join_name"] == "p, q"


def test_area_overlap_ignores_touching_targets():
    src = frame([sq(0, 0, 10)])
    tgt = frame([sq(0, 0, 10), sq(10, 0, 10), sq(0, 10, 10)], target_id=["same", "east", "north"])
    m = uw.match(src, tgt, "area_overlap")
    assert m.pairs["target_id"].tolist() == ["same"]
    assert m.pairs["overlap_measure"].iloc[0] == pytest.approx(100.0, **TOL)


def test_largest_overlap_and_its_ties():
    tgt = frame([sq(0, 0, 10), sq(10, 0, 10)], target_id=["b", "a"])
    src = frame([sq(2, 0, 10), sq(5, 0, 10)], source_id=["mostly_b_at_8", "tie"])
    m = uw.match(src, tgt, "largest_overlap").pairs.set_index("source_id")
    assert m.loc["mostly_b_at_8", "target_id"] == "b"
    assert m.loc["tie", "target_id"] == "a"  # equal overlap: the lowest target ID
    assert m.loc["mostly_b_at_8", "overlap_measure"] == pytest.approx(80.0, **TOL)


def test_polygon_to_lines_and_a_line_on_the_cell_boundary():
    cells = frame([sq(0, 0, 100), sq(100, 0, 100)], source_id=["c1", "c2"], heat=[30.0, 20.0])
    streets = frame([ln((50, 50), (150, 50)), ln((100, 0), (100, 100))], target_id=["across", "boundary"])
    m = uw.match(cells, streets, "polygon_to_lines")
    out = uw.aggregate(m, None, [uw.weighted_mean("heat")]).set_index("target_id")
    assert out.loc["across", "weighted_mean_heat"] == pytest.approx(25.0, **TOL)
    assert m.pairs.query("target_id == 'boundary'")["overlap_measure"].sum() == pytest.approx(200.0, **TOL)
    once = uw.match(cells, streets, "polygon_to_lines", shared_boundary="lowest_source_id")
    b = once.pairs.query("target_id == 'boundary'")
    assert b["source_id"].tolist() == ["c1"] and b["overlap_measure"].sum() == pytest.approx(100.0, **TOL)
    with pytest.raises(UnsupportedError):  # sampling does not allocate, so a sum is refused
        uw.aggregate(m, None, [uw.sum("heat")])


def test_sample_copies_one_cell_to_several_points():
    cells = frame([sq(0, 0, 100), sq(100, 0, 100)], source_id=["c1", "c2"], v=[1.0, 2.0])
    stations = frame([pt(10, 10), pt(20, 20), pt(100, 50), pt(500, 500)], target_id=["p1", "p2", "edge", "away"])
    m = uw.match(cells, stations, "sample")
    out = uw.aggregate(m, None, [uw.first("v")]).set_index("target_id")
    assert out["first_v"].tolist()[:3] == [1.0, 1.0, 1.0]  # the edge point takes the lowest source ID
    assert out.loc["away", "first_v"] is None
    assert m.report["notes"]["targets_without_source"] == 1


def test_exclusions_and_input_errors():
    tgt = frame([sq(0, 0, 10)])
    src = frame([pt(1, 1), None, pt(2, 2)], source_id=["ok", "null", "ok2"])
    m = uw.match(src, tgt, "contain")
    assert m.report["sources"]["excluded"]["null_geometry"]["sample"] == ["null"]
    with pytest.raises(InputError, match="no CRS"):
        uw.match(gpd.GeoDataFrame(geometry=[pt(0, 0)]), tgt, "contain")
    with pytest.raises(InputError, match="not unique"):
        uw.match(frame([pt(0, 0), pt(1, 1)], source_id=[1, 1]), tgt, "contain")
    bowtie = frame([__import__("shapely").geometry.Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])])
    with pytest.raises(InputError, match="valid"):
        uw.match(frame([pt(0, 0)]), bowtie, "contain")
    with pytest.raises(UnsupportedError, match="does not accept source geometry LineString"):
        uw.match(frame([ln((0, 0), (1, 1))]), tgt, "contain")
    with pytest.raises(InputError, match="does not take"):
        uw.match(frame([pt(0, 0)]), tgt, "contain", bandwidth=3)
    with pytest.raises(InputError, match="needs bandwidth"):
        uw.match(frame([pt(0, 0)]), tgt, "gaussian")
    with pytest.raises(UnsupportedError, match="Unknown"):
        uw.match(frame([pt(0, 0)]), tgt, "telepathy")


def test_explicit_ids_and_the_index_rule():
    tgt = frame([sq(0, 0, 10)], name=["zone A"])
    src = frame([pt(1, 1)])
    src.index = ["row-7"]
    m = uw.match(src, tgt, "contain", target_id="name")
    assert m.pairs.iloc[0].to_dict() | {} == {"source_id": "row-7", "target_id": "zone A",
                                               "allocation_fraction": 1.0, "sample_weight": 1.0}


def test_inputs_are_not_modified():
    src = frame([sq(0, 0, 10), sq(5, 5, 10)], v=[1.0, 2.0])
    tgt = frame([sq(0, 0, 8), sq(8, 0, 8)])
    before_s, before_t = src.copy(deep=True), tgt.copy(deep=True)
    for method in ("area_overlap", "centroid", "largest_overlap"):
        uw.aggregate(uw.match(src, tgt, method), None, [uw.weighted_mean("v"), uw.count()])
    assert src.equals(before_s) and tgt.equals(before_t)
    assert list(src.columns) == list(before_s.columns)


def test_measurement_resolution_and_refusals():
    tgt = frame([sq(0, 0, 10)])
    m = uw.match(frame([pt(1, 1)]), tgt, "contain")
    assert m.report["measurement"]["crs"] == "EPSG:32618" and m.report["measurement"]["resolved"] == "utm"
    m = uw.match(frame([pt(1, 1)]), tgt, "contain", crs="EPSG:2263")  # NY State Plane, US feet
    assert m.report["measurement"]["unit_to_m"] == pytest.approx(0.3048006096, rel=1e-9)
    with pytest.raises(UnsupportedError, match="not projected"):
        uw.match(frame([pt(1, 1)]), tgt, "contain", crs=4326)
    from shapely.geometry import Point, box

    polar = gpd.GeoDataFrame(geometry=[Point(10, 86)], crs=4326)
    with pytest.raises(UnsupportedError, match="UTM"):
        uw.match(polar, gpd.GeoDataFrame(geometry=[box(9, 85, 11, 87)], crs=4326), "contain")
    wide = gpd.GeoDataFrame(geometry=[box(-100, 30, -80, 40)], crs=4326)
    with pytest.raises(UnsupportedError, match="spans"):
        uw.match(gpd.GeoDataFrame(geometry=[Point(-90, 35)], crs=4326), wide, "contain")
    across = gpd.GeoDataFrame(geometry=[Point(179.9, 0), Point(-179.9, 0)], crs=4326)
    with pytest.raises(UnsupportedError, match="antimeridian"):
        uw.match(across, gpd.GeoDataFrame(geometry=[box(179, -1, 180, 1)], crs=4326), "nearest")


def test_density_in_square_kilometres_and_per_overlap_length():
    zones = frame([sq(0, 0, 1000), sq(1000, 0, 2000, 1000)], target_id=["one_km2", "two_km2"])
    pts = frame([pt(10, 10), pt(20, 20), pt(1500, 500)], one=[1, 1, 1])
    out = uw.aggregate(uw.match(pts, zones, "contain"), None, [uw.density("one", as_="per_km2")])
    assert out["per_km2"].tolist() == pytest.approx([2.0, 0.5], **TOL)
    # Four crashes on one of two 1 km streets in one zone: 2 crashes per road-km (PLAN.md fixture).
    streets = frame([ln((0, 100), (1000, 100)), ln((0, 600), (1000, 600))], target_id=["s1", "s2"])
    crashes = frame([pt(100, 101), pt(300, 99), pt(500, 100), pt(900, 102)])
    per_street = uw.aggregate(uw.match(crashes, streets, "nearest_segment", max_distance=30), None,
                              [uw.count(as_="crashes", fill_empty=0)])
    zone = frame([sq(0, 0, 1000)], target_id=["z"])
    out = uw.aggregate(uw.match(per_street, zone, "length_weighted", shared_boundary="lowest_target_id"), None,
                       [uw.density("crashes", as_="per_road_km", denominator="overlap_length")])
    assert out["per_road_km"].iloc[0] == pytest.approx(2.0, **TOL)
