"""The tutorials' SVG renderer and synthetic town, and (marked slow) every tutorial notebook run end to end."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

TUTORIALS = Path(__file__).resolve().parents[1] / "tutorials"
sys.path.insert(0, str(TUTORIALS))

pytest.importorskip("rasterio")
pytest.importorskip("osmnx")
import tutorial_data as td  # noqa: E402
from svgmap import Map  # noqa: E402

import urbanweave as uw  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"


def _parse(m: Map):
    return ET.fromstring(m.to_svg())


def test_the_town_is_deterministic_and_partitions_cleanly():
    a, b = td.tracts(), td.tracts()
    assert a.drop(columns="geometry").equals(b.drop(columns="geometry"))
    for zones in (td.districts(), a):
        assert zones.area.sum() == pytest.approx(td.TOWN.area, rel=1e-9)
        assert zones.union_all().symmetric_difference(td.TOWN).area < 1e-3
    assert (a["population"] == 0).sum() == 1 and a["median_income"].isna().sum() == 2
    assert len(td.crashes()) == len(td.crashes_table()) == 600


def test_sequential_fill_has_classes_tooltips_and_a_hatched_missing_value():
    zones = td.districts().assign(v=[1.0, 2.0, np.nan, 4.0, 5.0])
    root = _parse(Map("t").fill(zones, "v", legend="value", tooltip=["name"]))
    paths = [p for p in root.iter(f"{SVG}path") if "feature" in (p.get("class") or "")]
    assert len(paths) == 5
    styles = [p.get("style") for p in paths]
    assert sum("url(#uw-hatch)" in s for s in styles) == 1  # the missing value, not a color
    assert all(p.find(f"{SVG}title") is not None for p in paths)
    assert "Old Town" in "".join(p.find(f"{SVG}title").text for p in paths)
    assert "missing" in "".join(t.text or "" for t in root.iter(f"{SVG}text"))


def test_categories_fold_past_three_and_follow_the_given_order():
    zones = td.districts().assign(kind=["a", "b", "c", "d", "e"])
    root = _parse(Map().fill(zones, "kind", order=["c", "a", "b"]))
    texts = [t.text for t in root.iter(f"{SVG}text")]
    assert texts[-4:] == ["c", "a", "b", "other (2)"]
    style_of = {p.find(f"{SVG}title").text.split("kind: ")[1]: p.get("style") for p in root.iter(f"{SVG}path")
                if p.find(f"{SVG}title") is not None}
    assert "var(--c0)" in style_of["c"] and "var(--c1)" in style_of["a"]
    assert "#898781" in style_of["d"] and "#898781" in style_of["e"]  # folded into "other"


def test_numbers_stored_as_objects_are_still_numbers():
    zones = td.districts().assign(v=np.array([1, 2, 3, 4, 5], dtype=object))
    m = Map().fill(zones, "v")
    assert m._legends[0].kind == "sequential"


def test_raster_layer_embeds_light_and_dark_images_and_a_geographic_map_reprojects():
    heat = td.heat()
    root = _parse(Map().raster(heat, legend="UTCI"))
    images = list(root.iter(f"{SVG}image"))
    assert {i.get("class") for i in images} == {"light-only", "dark-only"}
    assert all(i.get("href").startswith("data:image/png;base64,") for i in images)
    cells = uw.targets.h3_cells(td.crashes().to_crs(4326), 8)
    m = Map().fill(cells)
    m.to_svg()
    assert m._crs.is_projected  # EPSG:4326 cells drawn in a local UTM zone


def test_links_draw_one_segment_per_pair():
    m = uw.match(td.tracts(), td.districts(), "area_overlap", target_id="district_id")
    root = _parse(Map().links(m, width="allocation_fraction"))
    assert len([ln for ln in root.iter(f"{SVG}line") if ln.get("stroke") == "var(--link)"]) == len(m.pairs)


@pytest.mark.slow
@pytest.mark.parametrize("notebook", sorted(p.name for p in TUTORIALS.glob("[0-9]*.ipynb")))
def test_notebook_runs(notebook):
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    sys.path.insert(0, str(TUTORIALS.parent / "tools"))
    import run_tutorials

    run_tutorials.run(TUTORIALS / notebook, save=False)
