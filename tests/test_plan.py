"""Plans: preflight, the two worked examples, manifests, replay and its refusals."""

import json
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("osmnx")
import urbanweave as uw  # noqa: E402
from urbanweave import plan as plan_module  # noqa: E402
from urbanweave.errors import PlanError  # noqa: E402
from urbanweave.inputs import SUPPORT_ATTR  # noqa: E402
from urbanweave.plan import Plan, frame_from_snapshot, frame_snapshot, replay  # noqa: E402

from .conftest import UTM18, X0, Y0, frame, pt, sq  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def examples(tmp_path):
    """A private copy of the examples, so tests can change inputs in place."""
    dest = tmp_path / "examples"
    shutil.copytree(EXAMPLES, dest, ignore=shutil.ignore_patterns("*.py"))
    return dest


def _simple_plan(**extra):
    spec = {"version": 1, "targets": {"cells": {"kind": "zones", "path": "zones.geojson"}},
            "steps": [{"id": "counts", "source": "points", "match": {"method": "contain", "target": "cells"},
                       "aggregate": [{"method": "count", "as": "n", "fill_empty": 0}]}]}
    spec.update(extra)
    return spec


@pytest.fixture
def simple(tmp_path):
    zones = frame([sq(0, 0, 10), sq(10, 0, 10)], target_id=["a", "b"])
    zones.to_file(tmp_path / "zones.geojson", driver="GeoJSON")
    points = frame([pt(1, 1), pt(2, 2), pt(15, 5)], v=[1.0, 2.0, 3.0])
    return tmp_path, points


# -- preflight ----------------------------------------------------------------------------------


def test_preflight_names_each_problem():
    bad = {"version": 2, "targets": {"t": {"kind": "zones", "path": "x"}},
           "steps": [{"id": "a", "source": "@b", "match": {"method": "contain", "target": "t"}, "aggregate": [{"method": "count"}]},
                     {"id": "b", "source": "s", "match": {"method": "teleport", "target": "t"}, "aggregate": [{"method": "count"}]},
                     {"id": "b", "source": "s", "match": {"method": "nearest", "target": "nowhere", "radius": 3},
                      "aggregate": [{"method": "count", "as": "x"}, {"method": "sum", "column": "v", "as": "x"}]}]}
    with pytest.raises(PlanError) as err:
        Plan(bad).validate()
    msg = str(err.value)
    for expected in ("version must be 1", "@b is not an earlier step", "unknown matching method 'teleport'",
                     "id repeats", "unknown target 'nowhere'", "does not take radius", "output names repeat: x"):
        assert expected in msg, expected


def test_preflight_checks_declared_value_kinds_and_units():
    spec = _simple_plan(sources={"points": {"columns": {"temp": {"kind": "intensive", "units": "degC"}}}})
    spec["steps"][0]["aggregate"] = [{"method": "sum", "column": "temp"}]
    with pytest.raises(PlanError, match="does not suit intensive"):
        Plan(spec).validate()
    heat = json.loads((EXAMPLES / "heat_exposure.json").read_text())
    heat["steps"][2]["reduce"]["aggregate"][0]["units"] = "K"
    with pytest.raises(PlanError, match="incompatible units"):
        Plan(heat).validate()
    Plan(json.loads((EXAMPLES / "heat_exposure.json").read_text())).validate()  # degC*m / m = degC


def test_a_target_used_by_two_steps_and_a_step_reading_a_target(simple):
    folder, points = simple
    spec = _simple_plan()
    spec["steps"].append({"id": "again", "source": "points", "match": {"method": "nearest", "target": "cells"},
                          "aggregate": [{"method": "sum", "column": "v", "as": "v"}]})
    spec["steps"].append({"id": "zone_size", "source": {"target": "cells"}, "match": {"method": "area_overlap", "target": "cells"},
                          "aggregate": [{"method": "weighted_count", "as": "w"}]})
    run = Plan(spec, base_dir=folder).run({"points": points})
    assert run["counts"]["n"].tolist() == [2, 1] and run["again"]["v"].tolist() == [3.0, 3.0]
    assert run["zone_size"]["w"].tolist() == pytest.approx([1.0, 1.0])


# -- the worked examples ------------------------------------------------------------------------


def test_crash_example_from_its_json(examples, tmp_path):
    plan = Plan.from_json(examples / "crash_density.json")
    run = plan.run({"crashes": "data/crashes.geojson"}, cache=tmp_path / "cache")
    streets = run["street_crashes"].set_index("target_id")
    assert streets["crashes"].sum() == 5  # one crash is 200 m from every street
    assert uw.report_of(run["street_crashes"])["match"]["sources"]["unmatched"]["beyond_max_distance"]["count"] == 1
    out = run.result.set_index("target_id")
    # Denominators computed directly: every eligible street counts, including those without crashes.
    west_km = (1000 + 1077.0329614 + 500.0999900) / 1000  # First St, Curve Ave, South Blvd (west carriageway)
    east_km = (1000 + 500 + 500.0999900) / 1000  # B–C, North St (on the boundary: lowest zone ID), South Blvd
    assert out.loc["west", "crashes_per_road_km"] == pytest.approx(4 / west_km, rel=1e-7)
    assert out.loc["east", "crashes_per_road_km"] == pytest.approx(1 / east_km, rel=1e-7)
    assert out.loc["west", "injured"] == 4 and out.loc["east", "injured"] == 3


def test_heat_example_against_a_direct_calculation(examples, tmp_path):
    run = Plan.from_json(examples / "heat_exposure.json").run({"utci": "data/utci.tif"}, cache=tmp_path / "cache")
    pieces = run["piece_heat"].set_index("piece_id")
    # First St A–B runs east along y = 0 from x 0 to 1000: 100 cells of 10 m, 5 of them nodata (x 400–450).
    xc = np.arange(0, 1000, 10) + 5.0
    valid = ~((xc >= 400) & (xc < 450))
    utci = 25 + 11 * (xc + 100) / 2200
    assert pieces.loc["1-2-0|west", "valid_street_m"] == pytest.approx(950.0)
    assert pieces.loc["1-2-0|west", "utci_mean"] == pytest.approx(utci[valid].mean(), rel=1e-6)
    out = run.result.set_index("target_id")
    west = pieces[pieces["zone_id"] == "west"]
    expected = (west["utci_m_sum"].astype(float).sum()) / west["valid_street_m"].astype(float).sum()
    assert out.loc["west", "utci_mean"] == pytest.approx(expected, rel=1e-12)
    assert out.loc["east", "utci_mean"] > out.loc["west", "utci_mean"]  # UTCI rises to the east


# -- manifests and replay -----------------------------------------------------------------------


def test_run_manifest_and_replay_round_trip(examples, tmp_path):
    cache = tmp_path / "cache"
    plan = Plan.from_json(examples / "heat_exposure.json")
    first = plan.run({"utci": "data/utci.tif"}, cache=cache, manifest_path=tmp_path / "run.json")
    manifest = json.loads((tmp_path / "run.json").read_text())
    assert manifest["manifest_version"] == 1 and manifest["engines"]["urbanweave"] == uw.__version__
    assert set(manifest["targets"]) == {"streets", "nbhd"} and manifest["sources"]["utci"]["snapshotted"]
    assert manifest["steps"][1]["params"] == {"coverage_as": "valid_fraction"}
    again = replay(tmp_path / "run.json", cache=cache)
    pd.testing.assert_frame_equal(first.result.drop(columns="geometry"), again.result.drop(columns="geometry"))
    # Replay does not read the original files: delete them.
    shutil.rmtree(examples / "data")
    third = replay(tmp_path / "run.json", cache=cache)
    pd.testing.assert_frame_equal(first.result.drop(columns="geometry"), third.result.drop(columns="geometry"))


@pytest.mark.parametrize("legacy_snapshot", [False, True])
def test_replay_keeps_h3_boundary_assignments(tmp_path, monkeypatch, legacy_snapshot):
    extent = [-74.00, 40.70, -73.96, 40.74]
    spec = _simple_plan(targets={"cells": {"kind": "h3", "extent": extent, "resolution": 9}})
    # A vertex shared by several cells, where H3 lookup and polygon coverage can choose different IDs.
    xy = uw.targets.cell_polygon("892a100d063ffff").exterior.coords[0]
    points = frame([Point(xy)], crs=4326)

    def snapshot_without_support(data):
        data = data.copy()
        data.attrs.pop(SUPPORT_ATTR, None)
        return frame_snapshot(data)

    with monkeypatch.context() as patch:
        if legacy_snapshot:
            patch.setattr(plan_module, "frame_snapshot", snapshot_without_support)
        run = Plan(spec).run({"points": points}, cache=tmp_path)
    again = replay(run.manifest, cache=tmp_path)

    assert run.reports["counts"]["match"]["notes"]["lookup"] == "h3_index"
    assert again.reports["counts"]["match"]["notes"]["lookup"] == "h3_index"
    pd.testing.assert_series_equal(again.result["n"], run.result["n"])
    if not legacy_snapshot:
        assert again.result.attrs[SUPPORT_ATTR] == run.result.attrs[SUPPORT_ATTR]


def test_replay_keeps_overrides_for_each_raster_binding(tmp_path):
    path = tmp_path / "heat.tif"
    transform = rasterio.transform.from_origin(X0, Y0 + 1, 1, 1)
    with rasterio.open(path, "w", driver="GTiff", width=2, height=1, count=1, dtype="float32",
                       crs=UTM18, transform=transform) as dataset:
        dataset.write(np.array([[10.0, 30.0]], dtype="float32"), 1)
    frame([sq(0, 0, 2, 1)]).to_file(tmp_path / "zone.geojson")
    spec = {
        "version": 1,
        "targets": {"zone": {"kind": "zones", "path": "zone.geojson"}},
        "steps": [
            {"id": name, "source": name,
             "convert": {"method": "zonal_stats", "target": "zone",
                         "aggregate": [{"method": "mean", "column": 1, "as": "heat"}]}}
            for name in ("original", "masked")
        ],
    }
    cache = tmp_path / "cache"
    with uw.read_raster(path) as original, uw.read_raster(
        path, nodata=10, names=["temperature"], value_kind="intensive", units="degC"
    ) as masked:
        run = Plan(spec, base_dir=tmp_path).run({"original": original, "masked": masked}, cache=cache)
    path.unlink()
    legacy_manifest = json.loads(run.manifest_path.read_text())
    for record in legacy_manifest["sources"].values():
        del record["raster"]

    for manifest in (run.manifest_path, legacy_manifest):
        again = replay(manifest, cache=cache)
        assert again["original"]["heat"].tolist() == run["original"]["heat"].tolist() == [20.0]
        assert again["masked"]["heat"].tolist() == run["masked"]["heat"].tolist() == [30.0]
        assert again.reports["masked"]["raster"] == run.reports["masked"]["raster"]


def test_a_file_changed_in_place_needs_a_new_run(simple, tmp_path):
    folder, points = simple
    cache = tmp_path / "cache"
    plan = Plan(_simple_plan(), base_dir=folder)
    plan.run({"points": points}, cache=cache, manifest_path=tmp_path / "run1.json")
    # The zones file changes in place: same path, same request key.
    frame([sq(0, 0, 20)], target_id=["all"]).to_file(folder / "zones.geojson", driver="GeoJSON")
    second = plan.run({"points": points}, cache=cache, manifest_path=tmp_path / "run2.json")
    m1 = json.loads((tmp_path / "run1.json").read_text())
    m2 = json.loads((tmp_path / "run2.json").read_text())
    assert m1["targets"]["cells"]["request_key"] == m2["targets"]["cells"]["request_key"]
    assert m1["targets"]["cells"]["fingerprint"] != m2["targets"]["cells"]["fingerprint"]
    from urbanweave.plan import Cache

    history = Cache(cache).resolutions(m1["targets"]["cells"]["request_key"])
    assert [h["fingerprint"] for h in history] == [m1["targets"]["cells"]["fingerprint"], m2["targets"]["cells"]["fingerprint"]]
    assert second.result["n"].tolist() == [3]
    old = replay(tmp_path / "run1.json", cache=cache)  # the original artifact is preserved
    assert old.result["n"].tolist() == [2, 1]


def test_replay_names_changed_and_missing_artifacts(simple, tmp_path):
    folder, points = simple
    cache = tmp_path / "cache"
    Plan(_simple_plan(), base_dir=folder).run({"points": points}, cache=cache, manifest_path=tmp_path / "run.json")
    m = json.loads((tmp_path / "run.json").read_text())
    zone_artifact = cache / "artifacts" / m["targets"]["cells"]["fingerprint"] / "zones.geojson"
    zone_artifact.write_text(zone_artifact.read_text().replace('"a"', '"z"'))
    shutil.rmtree(cache / "artifacts" / m["sources"]["points"]["fingerprint"])
    with pytest.raises(PlanError) as err:
        replay(tmp_path / "run.json", cache=cache)
    assert "target 'cells'" in str(err.value) and "changed in the cache" in str(err.value)
    assert "source 'points'" in str(err.value) and "missing" in str(err.value)


def test_replay_checks_versions_and_the_manifest_version(simple, tmp_path):
    folder, points = simple
    run = Plan(_simple_plan(), base_dir=folder).run({"points": points}, cache=tmp_path / "c")
    m = dict(run.manifest)
    with pytest.raises(PlanError, match="incompatible"):
        replay(m | {"engines": m["engines"] | {"shapely": "1.8.5"}}, cache=tmp_path / "c")
    with pytest.raises(PlanError, match="manifest version"):
        replay(m | {"manifest_version": 99}, cache=tmp_path / "c")


def test_in_memory_sources_supplied_again_and_verified(simple, tmp_path):
    folder, points = simple
    cache = tmp_path / "cache"
    Plan(_simple_plan(), base_dir=folder).run({"points": points}, cache=cache, manifest_path=tmp_path / "run.json",
                                              snapshot=False)
    with pytest.raises(PlanError, match="supply it again"):
        replay(tmp_path / "run.json", cache=cache)
    assert replay(tmp_path / "run.json", cache=cache, sources={"points": points.copy()}).result["n"].tolist() == [2, 1]
    moved = points.copy()
    moved.loc[0, "v"] = 99.0
    with pytest.raises(PlanError, match="changed"):
        replay(tmp_path / "run.json", cache=cache, sources={"points": moved})


def test_frame_snapshots_are_deterministic_and_round_trip():
    f = frame([pt(1, 1), None], i=pd.array([1, None], dtype="Int64"), s=["x", None], f=[1.5, np.nan])
    a, b = frame_snapshot(f), frame_snapshot(f.copy())
    assert a == b
    back = frame_from_snapshot(a)
    assert frame_snapshot(back) == a
    assert str(back["i"].dtype) == "Int64" and back.crs == f.crs
