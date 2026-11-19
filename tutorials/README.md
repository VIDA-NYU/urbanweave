# urbanweave tutorials

Eight short notebooks that walk through the package on **Riverton**, a synthetic town of 3 km × 2 km
(`tutorial_data.py`), so they run offline in a few seconds each. Every map is a static SVG drawn by
`svgmap.py`, so the notebooks render the same on GitHub, in JupyterLab and in VS Code, in light and
dark themes, and hovering a feature shows its ID and values. Schematic figures (`diagrams.py`), in the
style of the [Autark tutorial](https://github.com/ctsilva/autark-tutorial)'s drawings, show the data
models and what each operation does; orange is always the source and blue the target, and the
numbers in them (fractions, lengths, weights) are computed by urbanweave from the drawn shapes.

| Notebook | What it shows |
|---|---|
| [0. Data and concepts](00_data_and_concepts.ipynb) | Coordinates, vector geometries, rasters and nodata, H3 cells, street graphs, match → aggregate, value kinds; each drawn schematically, then shown in Riverton's data. |
| [1. First steps](01_first_steps.ipynb) | Crashes from a lat/lon table onto H3 cells, then onto districts; reading a report; the registry. |
| [2. Matching methods](02_matching_methods.ipynb) | `contain`, `centroid` vs `representative_point`, `area_overlap`, `largest_overlap`, `nearest` with a distance limit, `within_distance` (split or replicated), the Gaussian kernel. |
| [3. Aggregation and reports](03_aggregation_and_reports.ipynb) | Extensive, intensive and categorical values, and where the terms come from; declared kinds; zero versus missing; `where`; shares and majority; partial coverage; exact integer sums. |
| [4. H3 as a bridge](04_h3_as_a_bridge.ipynb) | A grid as the meeting point: grid to polygons, to points (cell lookup) and to lines (length in each cell); grids from cell IDs. |
| [5. Rasters and zonal statistics](05_rasters_and_zonal_statistics.ipynb) | Heat and land cover by district; exact coverage versus cell centres on small zones; nodata and zones off the raster. |
| [6. Streets](06_streets.ipynb) | Physical segments and intersections from an OSMnx graph; crashes per road-km; heat along streets pooled by district. |
| [7. Plans and replay](07_plans_and_replay.ipynb) | A JSON recipe: preflight, a run with a cache and manifest, replay, and what happens when an input changes. |

## Running them

```bash
uv pip install --python .venv -e '.[raster,osm,tutorials]' jupyterlab
.venv/bin/jupyter lab tutorials/
```

The notebooks are saved with their outputs. After changing the package, refresh those outputs from
the current code with

```bash
.venv/bin/python tools/run_tutorials.py            # all, or name prefixes: 03 05
.venv/bin/python tools/run_tutorials.py --check    # run without saving (CI does this)
```

## The figures

`diagrams.py` has one function per concept, each returning a figure that a notebook shows inline:
`coordinates`, `geometry_types`, `raster_anatomy`, `h3_support`, `street_graph`,
`match_and_aggregate`, `value_kinds`, `contain`, `centroid_and_representative_point`,
`area_overlap`, `nearest_and_within_distance`, `gaussian`, `grid_to_targets`, `zonal_rules`,
`along_lines_and_split` and `plan_flow`.

## The maps

`svgmap.Map` collects layers and renders one self-contained SVG:

```python
from svgmap import Map
(Map("Crashes per H3 cell")
 .fill(grid, "crashes", legend="crashes per cell")   # polygons by a column
 .outline(districts, label="name")                   # outlines with labels
 .dots(crashes, radius=1.5)                          # points
 .lines(streets, "crashes")                          # lines by a column
 .raster(heat, legend="UTCI (°C)")                   # a raster band
 .links(match_result))                               # source -> target pairs of a match
```

Magnitudes use one blue ramp in up to seven classes. Categories use at most three colors, and
further categories fold into "other"; `order=` pins a category to a color. Missing values are
hatched and named in the legend, so they never look like a measured zero. It is a teaching aid
kept beside the notebooks, not part of the urbanweave package.
