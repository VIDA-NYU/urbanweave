"""The registry agrees with what runs: a valid and an invalid call for every operator."""

import json

import pytest

import urbanweave as uw
from urbanweave.errors import UnsupportedError

from .conftest import frame, ln, pt, sq

SAMPLES = {
    "Point": lambda: frame([pt(5, 5)]),
    "MultiPoint": lambda: frame([__import__("shapely").geometry.MultiPoint([pt(5, 5), pt(6, 6)])]),
    "LineString": lambda: frame([ln((1, 1), (9, 9))]),
    "Polygon": lambda: frame([sq(0, 0, 10)]),
}
REQUIRED = {"within_distance": {"distance": 50}, "gaussian": {"bandwidth": 10}}


def test_registry_is_json_and_lists_every_method_and_reduction():
    reg = uw.registry()
    json.dumps(reg)
    assert set(reg["matching"]) == set(uw.METHODS)
    assert {"count", "weighted_count", "sum", "density", "weighted_mean", "majority", "shares"} <= set(reg["aggregation"])
    assert reg["matching"]["nearest_segment"]["params"]["max_distance"]["unit"] == "m"
    assert reg["aggregation"]["custom"]["serializable"] is False


@pytest.mark.parametrize("method", sorted(uw.METHODS))
def test_each_method_runs_where_the_registry_says_and_refuses_elsewhere(method):
    entry = uw.registry()["matching"][method]
    params = REQUIRED.get(method, {})
    for s_type, make_s in SAMPLES.items():
        for t_type, make_t in SAMPLES.items():
            if t_type == "MultiPoint":
                continue
            reasons = uw.registry_problems = __import__("urbanweave.registry", fromlist=["problems"]).problems(
                s_type, t_type, method)
            ok = not reasons
            assert ok == (s_type in entry["sources"] and t_type in entry["targets"]
                          and not (method == "contain" and s_type == "MultiPoint"))
            if ok:
                uw.match(make_s(), make_t(), method, **params)
            else:
                with pytest.raises(UnsupportedError):
                    uw.match(make_s(), make_t(), method, **params)


def test_validate_names_the_reason():
    uw.validate("Point", "Polygon", "contain", "extensive", "sum")
    with pytest.raises(UnsupportedError, match="does not provide"):
        uw.validate("Polygon", "LineString", "polygon_to_lines", aggregation="sum")
    with pytest.raises(UnsupportedError, match="suit"):
        uw.validate("Point", "Polygon", "contain", "categorical", "sum")


def test_reductions_requiring_quantities_are_refused_by_methods_without_them():
    reg = uw.registry()
    for method, entry in reg["matching"].items():
        for name, red in reg["aggregation"].items():
            needs = [q for q in red.get("requires", []) if q != "density_denominator"]
            missing = [q for q in needs if q not in entry["match_quantities"]]
            problems = __import__("urbanweave.registry", fromlist=["problems"]).problems(
                entry["sources"][0], entry["targets"][0], method, aggregation=name)
            assert bool(missing) == any("does not provide" in p for p in problems)
