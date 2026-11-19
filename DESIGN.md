# urbanweave: design

Claudio Silva, with Claude. November 2026. This document describes urbanweave 0.1 as built: why it
exists, what it does, and the rules it follows. The sequence of work and its release gates are in
[PLAN.md](PLAN.md); where each item stands is in [STATUS.md](STATUS.md).

## 1. Summary

urbanweave is a Python package for **spatial integration**: moving data from the shape it was
collected in (crash points, census tracts, a heat raster, an H3 grid) onto the places an urban
analysis asks about (districts, streets, intersections, grid cells), with explicit measurement,
explicit handling of missing values, and a report of what each step did.

Every operation has the same two parts:

```python
import urbanweave as uw

m = uw.match(crashes, cells, "contain")            # who goes where, with what quantities
grid = uw.aggregate(m, None, [uw.count(as_="crashes", fill_empty=0), uw.sum("persons_injured")])
uw.report_of(grid)                                 # matched, unmatched by cause, totals moved, CRS used
```

`match` pairs sources with targets and measures what the pairing needs: a share of the source, an
overlap area or length, a distance, a sampling weight. `aggregate` reduces the pairs to one row per
target. Results can be the sources of the next step (points → H3 cells → districts), raster
statistics and street conversions follow the same rules, and a sequence of steps can be saved as a
JSON plan and replayed from pinned inputs.

## 2. History

**Origins in UrbanTrace.** urbanweave began as the integration operators of UrbanTrace, a web tool
for combining NYC datasets on an H3 grid and then onto zones. Those operators (allocation such as
`BinaryContainment`, `ProportionalAreaWeighted`, `GaussianKernel`; aggregation such as
`SumAggregation`, `DensityAggregation`; and a separate family of zoning operators for the second
stage) lived inside UrbanTrace's backend. They assumed the H3 grid, expected fixed column names, and
could not be installed or used from a notebook or another tool. Which operator suited which geometry
was written in three places: the backend's constraints, the front end's node, and the copilot's
fallback rules.

**What a review found.** Reading the operators closely turned up errors that a shared, tested core
would fix once: a Gaussian kernel that measured distance in degrees, densities computed from Web
Mercator areas (about 1.74 times too large at NYC's latitude, so densities came out too small),
missing values turned into zeros, points on a cell boundary counted twice, and aggregators that
modified their inputs.

**The neighbours.** Two related projects had pieces of the same problem. UrbanMapper (VIDA-NYU)
could put points onto OpenStreetMap streets and intersections, but only by nearest matching and only
for points, and it was no longer maintained. Curio, the dataflow framework, had raster zonal
statistics in two packages (UHVI by cell centres, Weather through rasterstats), each with its own
conventions, and no shared rules with the vector side.

**Design decisions.** The design was worked out in a short series of discussions before any code
was written:

- *Raster and vector, with conversions between them.* Much urban data is raster (heat, shade, land
  cover, population, imagery), so the package had to handle both, and move values between them in
  both directions.
- *H3 is a raster.* An H3 grid is a regular grid of cells whose geometry follows from their
  address; it differs from an array raster in having hexagonal cells with names instead of rows and
  columns. Treating it as a grid lets one set of rules cover rasters, H3 and their conversions.
- *What other tools do.* RustGIS (a GIS in Rust with many of these operations as separate tools)
  contributed names and habits: largest-overlap joins, distance-limited joins, the merge rules of a
  spatial join (an empty result for no match but a count of zero), and the reports of what an
  operation lost. Where its tools disagreed with each other, for example a point on a shared edge
  counted in both polygons, urbanweave picked one rule and applied it everywhere.
- *A rule for scope.* An operation belongs in urbanweave when it moves values between supports, or
  prepares a grid for that move (masking, reclassifying, aligning). Analysis of a single raster on
  its own grid (terrain, hydrology, filters, classification) is done well by other libraries and is
  left to them. The point of the package is the derived data that integration produces for urban
  analysis: values on streets, zones and grids.
- *The name.* urbanweave weaves data from many sources onto the places urban analysis asks about.
  tobler (PySAL), the closest existing library, does areal interpolation between polygons;
  urbanweave covers points, lines, rasters, H3 and streets as well, adds reports and replayable
  plans, and is compared against tobler where they overlap.

**Implementation.** The package was then built in milestones (section 9): the vector and H3 core,
a compatibility layer that runs UrbanTrace's operator names on it, raster zonal statistics with
drop-in replacements for Curio's two zonal means, street targets and conversions, and JSON plans
with manifests and replay. UrbanTrace and Curio were not modified: their code was copied into the
tests at recorded revisions and run beside urbanweave. Over UrbanTrace's catalog of 121 datasets,
every difference between the old operators and urbanweave has a named cause (section 8). Eight
tutorial notebooks with schematic figures and maps introduce the package on a synthetic town.

## 3. Goals

- **Correct by construction.** Distances, lengths and areas are measured in metres in a projected
  CRS, never in degrees. Missing stays missing and an observed zero stays zero. A boundary point is
  counted once. Inputs are never modified. Integer totals stay exact.
- **Honest about what happened.** Every step reports what it matched, what it left out and why,
  and how totals moved, so a surprising number can be explained from the report alone.
- **One description of the operators.** A registry, generated from the code that runs the
  operators, tells interfaces, validators and assistants what each operator accepts and produces.
- **Reproducible.** A plan is plain JSON; a run records its inputs by content hash, its arguments
  and its engine versions, and can be replayed from those inputs, refusing if any has changed.
- **Small and installable.** The core needs NumPy, pandas, Shapely, pyproj, GeoPandas and h3;
  rasters (`rasterio`, `exactextract`) and streets (`osmnx`) are optional extras.

Not goals: visualization (Autark and the applications draw), LLM features (an assistant reads the
registry), dataset discovery (Auctus), single-raster analysis (section 2), and running models on
imagery (they produce rasters urbanweave then reads).

## 4. Concepts

**Sources and targets.** A source is a GeoDataFrame of features with values, or a raster with one
or more bands. A target is a GeoDataFrame of places, or an H3 support. Every feature has a stable,
unique, non-null ID, taken from an explicit column, else `source_id`/`target_id`, else (for
sources) a `target_id` column left by a previous step, else the index. A result keeps its targets'
IDs, so it can be the next step's source.

**Grids.** A grid is a tessellation whose cell geometry follows from the cell's address. An *array
grid* (a raster) addresses cells by row and column through an affine transform in one CRS. A
*global grid* such as H3 addresses cells by ID at a resolution. urbanweave keeps H3 data as cell
IDs and builds cell polygons only when an overlay needs them; points are matched to H3 cells by
index lookup, not geometry. A grid built over an extent keeps the cells whose centres fall inside
it (UrbanTrace's rule), so a point in a cell left out is reported as outside the support.

**Match quantities.** A match is a table of `(source_id, target_id)` pairs with the quantities the
method provides:

| Quantity | Meaning | Used by |
|---|---|---|
| `allocation_fraction` | the share of the source assigned to this target | `sum`, `weighted_count`, `density` |
| `overlap_measure` | overlap area (m²) or length (m) | `weighted_mean`, `shares`, `majority`, per-length density |
| `sample_weight` | a coefficient for copying a value to a target | `weighted_mean` of sampled values |
| `distance_m` | the distance between the pair | ordering (`first`, `last`) |

**Assignment.** How a method distributes a source decides whether totals are conserved:
*exclusive* (each source to at most one target), *independent* (each target receives its own overlap,
so overlapping targets can together receive more than the source), *normalized* (a source split
among its candidates so its fractions sum to 1), *replicated* (a source given whole to several
targets) and *sampling* (a target copies a source's value). The registry and each report name the
assignment.

**Value kinds.** *Extensive* values (people, crashes) split with space and are summed; *intensive*
values (temperature, median income) are averaged by overlap; *categorical* values (land use) become
shares or a majority. Declaring a column's kind lets urbanweave refuse a reduction that does not fit,
such as summing median incomes.

**Measurement.** Each step measures in one projected CRS: the one given, or a local UTM zone
resolved from the study area and reported. Topology (containment, intersections, shared boundaries)
is evaluated in the targets' own CRS, so reprojection cannot move a point across a boundary. Study
areas that are polar, cross the antimeridian or are wider than 12° of longitude are refused with
the reason, since one UTM zone cannot measure them accurately.

## 5. What is built

**Matching** (`uw.match`):

| Method | Sources → targets | What it does | Replaces in UrbanTrace |
|---|---|---|---|
| `contain` | points → polygons, H3 | the polygon containing the point; ties to the lowest target ID | `BinaryContainment` |
| `centroid` | any → polygons | the polygon containing the geometric centroid | `BinaryCentroidContainment`, `CentroidZoning` |
| `representative_point` | polygons, lines → polygons | the polygon containing a point guaranteed inside the source | |
| `nearest` | points → any | the nearest target, within an optional, inclusive `max_distance` | `NearestAssignment` |
| `nearest_segment`, `nearest_node` | points → lines, points | nearest street segment or intersection | UrbanMapper's nearest street and intersection |
| `within_distance` | points, lines → any | every target within `distance`, split equally or replicated, optionally the `k` nearest | |
| `area_overlap` | polygons → polygons | overlap area and share of the source | `ProportionalAreaWeighted`, `AreaWeightedZoning` |
| `length_weighted` | lines → polygons | overlap length and share; a line on a shared boundary can count once | `ProportionalLengthWeighted` |
| `largest_overlap` | polygons, lines → polygons | the whole source to the target it overlaps most | |
| `polygon_to_lines` | polygons, H3 → lines | the length of each line inside each source | `LengthWeightedZoning` |
| `gaussian` | points, lines → any | weights exp(−d²/2σ²) normalized per source, kept while at least 1% of the peak (about 3σ); points beyond are dropped, or sent to the nearest target when asked, and reported | `GaussianKernel` |
| `sample` | polygons, H3 → points | each point copies the value of the cell or polygon containing it | `CentroidZoning` with point zones |

**Aggregation** (`uw.aggregate`): `count`, `weighted_count`, `sum`, `density` (per km² of target,
per km, per node, or per km of matched source lines), `mean`, `weighted_mean` (which can also return
its numerator and denominator for pooling later), `median`, `weighted_median`, `min`, `max`,
`majority`, `shares`, `first`, `last`, `join`, and `custom` (a Python function, flagged as not
serializable). A `where` condition filters the matched rows.

**Rasters** (`[raster]` extra): `read_raster` reads a file, an open dataset, or an array with its
transform, CRS and mask, with per-band nodata, scale, offset, units and value kind.
`zonal_stats(raster, zones, reductions, method=...)` summarizes cells under each zone with exact
coverage fractions (`cell_coverage`, through exactextract) or whole cells whose centres are inside
(`cell_center`, the rule of GDAL, rasterstats and Curio). It returns each zone's geometric coverage
and its valid coverage per band. Rasters must be north-up; exact area weighting on a geographic
grid is refused rather than approximated. Reading is windowed, accumulators merge across windows,
and zones are processed in batches so memory stays bounded.

**Streets** (`[osm]` extra): `osm_streets` and `osm_intersections` build targets from a saved
GraphML graph or, live, from OpenStreetMap. *Physical segments* merge the two directed edges of a
two-way street, so its length counts once, while the two carriageways of a divided road stay
separate; *intersections* are nodes where three or more physical segments meet. `split_lines` cuts
lines at zone boundaries into pieces with stable IDs (`line|zone`). `along_lines` averages raster
values along each line by the length inside each cell, and `reduce` with `ratio_of_sums` pools the
pieces per zone (Σ value × metres / Σ valid metres).

**Plans** (`uw.Plan`): a versioned JSON recipe of named sources, target specifications (`h3`,
`zones`, `file`, `osm_streets`, `osm_intersections`, `raster_file`) and steps (match + aggregate,
a conversion, or a reduce), where `@step` refers to an earlier step's output. `validate` checks the
whole plan before it runs: versions, references, methods and parameters, reductions, output names,
declared kinds and units. `run` stores every input as an artifact named by the SHA-256 of its
content (or of a deterministic snapshot of an in-memory frame), records which artifact each target
request resolved to, and writes a manifest atomically. `replay` reruns a manifest from its
artifacts, with the raster band settings and H3 support metadata they were recorded with, after
verifying fingerprints and engine versions; it names every artifact that changed or is missing.

**Registry and reports.** `uw.registry()` is one JSON document describing every installed operator:
accepted geometries and supports, parameters with types, defaults and units, quantities, assignment,
conservation conditions and the operators it replaces. Tests check that it agrees with execution
for every method and geometry. Reports compose across steps and keep a bounded sample of IDs per
cause.

**Compatibility.** `urbanweave.compat.urbantrace.run` accepts UrbanTrace's operator names, column
conventions, wire units (density per m²) and weighting basis, and lists each deliberate difference in
`CHANGES`; `operators_payload()` produces its `/api/operators` response from the registry.
`urbanweave.compat.curio` has drop-in replacements for the UHVI and Weather zonal means.

## 6. Rules

- **Boundaries and ties.** A point on a shared boundary, and an equidistant nearest neighbour, go to
  the lowest target ID. With `shared_boundary="lowest_target_id"`, a line on the boundary between
  zones is counted once. In a raster, a cell owns its west and north edges, so a line on a cell
  edge is counted once.
- **Missing values.** A target with no match gets a missing result; `fill_empty=0` turns that into
  zero only for `count`, `weighted_count` and `sum`. Missing values are left out of means rather
  than counted as zero, and reported per column. A zero or missing denominator gives a missing
  density.
- **Integers.** Integer columns stay integers for `min`, `max` and unit-weight `sum`; a sum that
  would overflow 64 bits is reported, not wrapped.
- **Inputs.** Missing CRS, duplicate or null IDs, and invalid target geometry are refused before
  matching. Null, empty and invalid source geometries, and coordinates outside the range of a
  geographic CRS, are excluded and reported by cause; a layer whose coordinates are all out of range
  is refused as a probably mislabelled CRS.
- **Tolerances.** Allocation fractions are checked against 1 with a tolerance of 1e-6, which covers
  the cut points of an overlay after reprojection.
- **Order.** Results follow target order; shuffling the input rows changes nothing.

## 7. Relation to other tools

| Tool | Relation |
|---|---|
| UrbanTrace | origin of the operators; the compatibility layer is what its backend would call |
| Curio | its UHVI and Weather zonal means have drop-in replacements; whether node code may import urbanweave is its owner's decision |
| UrbanMapper | its street, intersection and nearest-feature capabilities are covered; geocoding and admin-area targets are on the roadmap |
| RustGIS | source of several method names and of the reporting habits (section 2) |
| tobler | the closest library for areal interpolation; results agree on shared cases (with `allocate_total=False`) |
| exactextract | the engine of exact raster coverage |
| rasterstats | the reference for the cell-centre rule |
| OSMnx, h3 | build street graphs and H3 cells |

## 8. Validation

- **Analytical fixtures.** Each rule above has a hand-calculated test: unequal areas averaging to
  19°C, a partition conserving a total, a quarter of a raster cell giving `count=1` and
  `weighted_count=0.25`, four crashes on 2 km of street giving 2 per road-km, a pooled street mean
  of 12°C with 100 of 120 m observed. Tolerances are 1e-9 for projected fixtures.
- **Property tests** (Hypothesis): conservation over random partitions, each covered point matched
  once, invariance to row order.
- **Against the old code.** UrbanTrace's and Curio's code, copied into the tests at recorded
  revisions, runs beside urbanweave. Over UrbanTrace's 121-dataset catalog, 319 operator cases were
  compared and every difference was named: UTM instead of Web Mercator measurement, invalid sources
  excluded, nearest ties, the H3 index lookup. Fifteen cases are refused, with the reason, on three
  datasets with corrupt or mislabelled coordinates, where the old code crashed or ran on nonsense.
  On Curio's Milan sample, the replacements match its outputs, in 0.9 s where the old UHVI code took
  minutes.
- **Against other libraries.** tobler for area-weighted results, exactextract and rasterstats for
  raster statistics.
- **Versions.** CI runs the current releases, the lowest supported versions (Python 3.11, GeoPandas
  1.0, Shapely 2.0.4, rasterio 1.4, exactextract 0.2, OSMnx 2.0), and the core without extras.
- **Benchmarks** (synthetic stand-ins): 500,000 points onto 7,434 H3 cells in 0.85 s; land-cover
  shares for 500 zones on an 8,000 × 8,000 raster in 4.3 s at 0.54 GB peak memory.

## 9. Roadmap

Built: the vector and H3 core, zonal statistics, street workflows, plans, the registry, the
compatibility layers and the tutorials. Steps that change UrbanTrace or Curio themselves (switching
UrbanTrace's backend and interface to the registry, enabling the Curio replacements, importing and
exporting plans in UrbanTrace) belong to those projects.

Next, as uses appear:

- **Grid conversions:** `rasterize` (vector → raster or H3, aggregated by value kind),
  `resample_to` (raster ↔ raster ↔ H3, conserving extensive totals), `density_surface` and
  `distance_surface`, `interpolate` (IDW, kriging; intensive values only), `polygonize`,
  `cells_to_vector`, `mosaic` and `clip`.
- **Grid preparation:** `mask`, `set_nodata`, `reclassify`, cell-wise `calculate`, `align` and
  `stack`, each declaring the value kind of its output; then whole-grid statistics for Curio's
  Rasterization package.
- **Targets:** A5 (equal-area cells), `admin_areas` and `osm_features` from OpenStreetMap,
  sidewalks and crosswalks from Tile2Net output, and `line_overlap` for routes onto streets.
- **Inputs:** geocoding addresses, clipping to a target's extent.
- **Measurement:** distances and areas on the ellipsoid for extents a UTM zone cannot cover;
  network distance along streets.

## 10. Open questions

- **Home:** VIDA-NYU or OSCUR, and claiming the name on PyPI before announcing.
- **H3 coverage:** keep centre-based selection, or also offer a covering that includes every cell
  touching the extent.
- **Density normalizations:** per km and per node are the defaults on lines and points; are others
  needed (per lane-km, per capita)?
- **tobler's other methods:** reuse its dasymetric and pycnophylactic interpolation, or implement
  them with urbanweave's reports and chaining.
- **Raster stack:** rioxarray and dask for multi-band, time-stacked or lazy rasters; Zarr outputs.
- **Time:** temporal binning (per hour, per month) as another kind of step.
