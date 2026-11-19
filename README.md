# urbanweave

Spatial integration for urban analysis: weave data from many sources (points, lines, polygons,
rasters, H3 cells) onto the places urban analysis asks about (zones, streets, grids), with explicit
measurement, value kinds and reports of what each step did.

```python
import urbanweave as uw

crashes = uw.points_from_columns(df, lat="latitude", lon="longitude")
cells = uw.targets.h3_cells(crashes, 9)

m = uw.match(crashes, cells, "contain")                   # who goes where, with what quantities
grid = uw.aggregate(m, None, [uw.count(as_="crashes", fill_empty=0), uw.sum("persons_injured")])
uw.report_of(grid)                                        # matched, unmatched by cause, totals, CRS

zones = uw.aggregate(uw.match(grid, nta, "area_overlap"), None, [uw.sum("crashes")])
```

- **Matching** (`uw.match`): `contain`, `centroid`, `representative_point`, `nearest`,
  `nearest_segment`, `nearest_node`, `within_distance`, `area_overlap`, `length_weighted`,
  `largest_overlap`, `polygon_to_lines`, `gaussian`, `sample`. Each returns `(source_id, target_id)`
  pairs with allocation fractions, overlap areas or lengths in metres, sampling weights or distances.
- **Aggregation** (`uw.aggregate`): `count`, `weighted_count`, `sum`, `density`, `mean`,
  `weighted_mean`, `median`, `weighted_median`, `min`, `max`, `majority`, `shares`, `first`, `last`,
  `join`, `custom`. Missing stays missing; integer sums stay exact; value kinds are checked.
- **Rasters** (`pip install urbanweave[raster]`): `uw.read_raster`, `uw.zonal_stats` with exact
  coverage fractions (exactextract) or cell centers, per-band validity and coverage.
- **Streets** (`pip install urbanweave[osm]`): physical street segments and intersections from OSMnx
  graphs, `split_lines`, `along_lines` (raster values by length along lines), `reduce`.
- **Plans** (`uw.Plan`): versioned JSON recipes with preflight validation, run manifests, and replay
  from pinned, fingerprinted artifacts. See `examples/crash_density.json` and
  `examples/heat_exposure.json`.
- **Registry** (`uw.registry()`): one JSON description of every installed operator, generated from
  the code that runs them.
- **Compatibility**: `urbanweave.compat.urbantrace` runs UrbanTrace's operator names and column
  conventions on urbanweave; `urbanweave.compat.curio` has drop-in versions of Curio's UHVI and
  Weather zonal means.

The design is in [DESIGN-spatial-integration-package.md](DESIGN-spatial-integration-package.md),
the sequence and release gates in [PLAN.md](PLAN.md), and where each plan item stands in
[STATUS.md](STATUS.md).

## Development

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv -e '.[raster,osm,dev]'
.venv/bin/python -m pytest -q                 # the regular suite
.venv/bin/python -m pytest -q -m slow         # comparisons on Curio's Milan sample data (minutes)
.venv/bin/python tools/urbantrace_corpus.py   # inventory and old/new comparison on UrbanTrace's catalog
.venv/bin/python tools/benchmark.py points --n 2000000
```

Tests that compare with UrbanTrace and Curio run their code as copied into `tests/legacy/` at the
revisions recorded there; Curio's sample data is read in place from `CURIO_REPO` (default `../curio`).
