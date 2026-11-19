# urbanweave: a package for spatial integration

Status: draft for discussion (2026-11-19). Author: Claudio Silva, with Claude.
Name: `urbanweave` (`pip install urbanweave`, `import urbanweave as uw`): it weaves data from many
sources, vector and grid, onto the places urban analysis asks about.

## Summary

UrbanTrace's integration operators (allocation, aggregation, zoning) move into a small, installable
Python package with a functional core:

```
match(sources, targets, method)  ->  matches with allocation fractions, overlap measures, or sampling weights
aggregate(matches, values, method)  ->  one value per target per requested statistic
```

Sources and targets are vector data or grids. A vector target is any geometry table: zones,
administrative areas, street segments, intersections, sidewalks, crosswalks, or points of interest.
A grid is a tessellation whose cells' geometry follows from their address: a raster (cells on
an affine grid in one CRS, such as a heat, shade, land cover or population surface) or a
global grid such as H3, which is raster data with hexagonal cells and cell ids instead of rows and
columns. Conversions go both ways: vector to grid (rasterize, density surfaces, distance surfaces),
grid to vector (zonal statistics, sampling at points and along lines, polygonize), and grid to grid
(resampling between rasters, H3 resolutions, or a raster and H3). Steps chain
(sources → grid → zones, sources → streets → neighborhoods, or raster → tracts → neighborhoods), and
a whole plan serializes to JSON. One registry describes every operator (accepted supports, value
kinds, weighting basis, and conditions for preserving totals) for UrbanTrace's interface, validation,
and copilot. A run records the resolved inputs and versions needed to reproduce its results.

The package also takes over what UrbanMapper enabled (urban layers from OpenStreetMap, nearest-street
and nearest-intersection matching, geocoding, count and summary statistics, shareable pipelines),
since UrbanMapper is no longer maintained. Section 9 lists every UrbanMapper capability and where it
lands.

## 1. Why

- **Reuse**: the operators live in `urbantrace/backend/operators/`, are not installable, assume the H3
  grid, and expect fixed column names (`source_id`, `cell_id`, `source_value`, `gamma`, `area`) with
  inconsistent output names (`aggregated_value`, `allocated_val`). Notebooks, other tools, and the
  Auctus pipeline cannot use them.
- **One source of truth**: which operator fits which geometry is written in three places today
  (`GEOMETRY_CONSTRAINTS` in `backend/main.py`, a list in `IntegrationNode.jsx`, and the copilot's
  fallback rules in `main.py`).
- **Correctness**: a review found a Gaussian kernel that measured distances in degrees (fixed in
  UrbanTrace on 2026-11-19, with tests), densities computed from Web Mercator areas, which are about 1.74x too
  large at NYC's latitude, so densities come out about 1.74x too small, missing values turned into zeros, points on a cell boundary counted
  twice, and aggregators that modify their input. A package with a small, tested core fixes these
  once.
- **New targets**: UrbanTrace cannot integrate onto streets or intersections, and its zones come
  only from NYC catalog files. UrbanMapper could do both, for points only and nearest matching only.
- **Raster data**: much urban data is raster: heat and UTCI surfaces, shade, land cover, satellite
  imagery and the segmentation and shadow models that run on it, population grids, elevation.
  Neither UrbanTrace nor UrbanMapper reads rasters. Curio has separate zonal statistics implementations
  for UHVI and Weather, each with its own input and output conventions. Rasterization also computes
  whole-raster or masked statistics, and SCOUT adds building rasterization and mosaics. The package can
  share the statistics and value-kind rules across these workflows.

## 2. Scope

In scope:

- Targets ("supports"): building them (grids, OSM layers, raster grids, files) and caching them.
- Matching points, lines, polygons and raster cells to vector or raster targets, with match
  quantities such as overlap area, distance or allocation fractions.
- Aggregation of weighted values, by kind of value.
- Conversions between vector and raster in both directions, and between raster grids (section 6b).
- Preparing a grid for integration, on its own grid: masking, nodata, reclassifying, cell-wise
  arithmetic, aligning and stacking bands (section 6b).
- Chaining steps, and plans serialized to JSON.
- Input helpers: points from coordinate columns, geocoding addresses, clipping to a target's extent.
- An operator registry with metadata.
- Reports of what each step did (matched, dropped, totals before and after).

Out of scope:

- Visualization (Autark, UrbanTrace's front end).
- LLM features (UrbanTrace's copilot reads the registry; the package has no LLM code).
- Dataset discovery and catalogs (Auctus revamp, `auctus/DESIGN-revamp.md`).
- Analysis that derives new quantities from a raster on its own grid: terrain (slope, aspect,
  hillshade), hydrology, viewsheds, focal filters, image classification. numpy, xarray,
  xarray-spatial, Whitebox and Curio's nodes do these well, and the package does not replicate them.
  The rule: an operation belongs in the package when it moves values between supports, or prepares
  a grid for that move; the package's purpose is the derived data that integration produces for
  urban analysis (values on streets, zones, grids), not the analysis of a single raster.
- Running models on imagery (segmentation, shadows): those produce rasters the package then reads.

The first release extracts UrbanTrace's existing H3 and zone workflows and adds the registry and
reports. The first raster milestone delivers zonal statistics for UHVI and Weather. The rest of this
document describes where the package can grow. [PLAN.md](PLAN.md) defines the sequence and release gates.

## 3. Concepts

- **Source**: a GeoDataFrame of features with values (crash points, bike-route lines, census-tract
  polygons), or a raster with one or more bands (a UTCI surface, a land-cover map, a population grid).
- **Target**: a GeoDataFrame with a `target_id`, a geometry, and a `TargetSpec` saying how it was
  made, so it can be rebuilt and cached; or a raster grid (`GridSpec`: CRS, affine transform, shape),
  whose cells are the targets, each with a `target_id` given by its row and column.
- **Grid**: a tessellation whose cells' geometry follows from their address, so it is never stored.
  Two families:
  - *array grids* (rasters): cells addressed by row and column through an affine transform in one
    CRS. The `square_grid` of a UTM zone is one.
  - *global grids* (DGGS), addressed by a 64-bit cell id, with a hierarchy of resolutions: H3's
    hexagons, and A5's pentagons, whose cells all have the same area at a resolution, so counts per
    cell are comparable between regions at that resolution (S2 or geohash, later).

  H3 data is raster data in this sense: values attached to implied cells, regular neighbors, coarser
  and finer levels like a raster's overviews. It differs in what the code must handle: cells are
  hexagons (and 12 pentagons), not squares; there is no transform or dense array, so H3 data is kept
  sparse, as a table `(cell_id, values...)`, the shape a sparse raster takes; cells of one resolution
  are only roughly equal in area (they vary by about 2x across the globe, a few percent within a
    city), so areas are always computed, never assumed. Both H3 and A5 have logical hierarchies with
    approximate geometric containment. Use geometric overlap when moving values between resolutions
    by area. An index-based roll-up answers a different question. [H3 hierarchy](https://h3geo.org/docs/) ·
    [A5 spatial hierarchy](https://a5geo.org/blog/2026/10/14/a5-v1#spatial-hierarchy-functions)
  The package treats both families as grids: the same conversions apply (section 6b), and only the
  cell geometry and the way cells are found differ.
- **Raster**: an array grid plus bands, each band with a nodata value and a value kind. In memory, an
  array or windowed reader with its CRS and transform; on disk, GeoTIFF or Cloud-Optimized
  GeoTIFF. The first raster adapters use Rasterio. An `xarray.DataArray` with rioxarray metadata is a
  later adapter. A raster cell has a polygonal footprint. The regular-grid path works on windows of
  cells and only the explicit vector conversion returns a geometry per cell.
- **Match result**: a relation keyed by `(source_id, target_id)`, together with method metadata
  and a report. Sources and targets have stable unique IDs within their resolved supports. The
  relation carries the quantities the method can provide. Values are joined at aggregation.

  | Quantity | Meaning |
  |---|---|
  | `allocation_fraction` | The share of the source value assigned to this target. For a geometric transfer this is usually overlap divided by source area or length. Used by `sum` and `weighted_count`. |
  | `overlap_measure` | Area in m² or length in m under the declared measurement rule. Used by overlay means, quantiles and category shares. Source and target sizes are available from their supports where defined. |
  | `sample_weight` | A coefficient for a target-side sample, such as bilinear interpolation. Sampling can reuse a source across targets. |

  The registry specifies which quantities an operator produces and the basis each aggregation can
  use. A discrete assignment uses unit matches, and a kernel declares its own weighting basis.
  Fractional allocations and sampling coefficients are finite and in [0, 1]. Only conserving
  allocations constrain the sum of fractions per source. Windowed raster paths yield match batches
  internally or reduce equivalent statistics directly.
- **Value kinds** decide which aggregations make sense:
  - *extensive*: totals that split with space (counts, population, crashes): sum, density.
  - *intensive*: rates or averages that do not split (median income, temperature): weighted mean,
    median, min, max. The output describes the source values being summarized. Recovering a pooled
    rate requires its numerator and denominator, and a median of tract medians describes the tracts.
  - *categorical*: labels (zoning class, borough): majority, shares per category.
  The value kind also decides how a raster is resampled or rasterized: extensive values are summed
  (a population grid coarsened keeps its total), intensive values are averaged or interpolated,
  categorical values take the mode or the nearest cell. One rule serves vector and raster data.
- **Step**: a match followed by aggregation, a conversion, or a reduction. **Plan**: a sequence of steps,
  where a step's output (targets with values, or a raster) can be the next step's sources.

## 4. Targets

Every target can be described by a `TargetSpec` (plain JSON). The spec hash keys requests, and the
resolved target has a separate fingerprint based on the artifact and its build inputs. A live OSM
query or the same file path can resolve to a different artifact. Persist the resolved CRS, geometry or
grid definition, and ID rules with the artifact. Keep a raster's affine transform and native CRS.

| Kind | Geometry | Built from | Notes |
|---|---|---|---|
| `h3` | global grid cells | resolution + extent | UrbanTrace's current grid; kept as cell ids, polygons built only when asked |
| `a5` | global grid cells | resolution + extent | equal-area pentagons with hex-encoded IDs; a later target for comparisons across regions |
| `square_grid` | array grid cells | cell size in meters + extent | uniform square cells in projected coordinates; a convenience name for `raster_grid` |
| `zones` | polygons | a file or GeoDataFrame | NTAs, ZIP codes, tracts |
| `admin_areas` | polygons | place name (+ optional OSM `admin_level`) | OSM boundaries; neighborhoods, cities, states, countries; infers `admin_level`, which differs by country, and lets the user override it |
| `osm_streets` | lines | place, address, bbox, point + distance, polygon, or an OSM XML file; `network_type` (drive, walk, bike, all) | directed graph edges or physical street segments, with topology and the road attributes |
| `osm_intersections` | points | same as streets | nodes with at least three incident physical street segments by default (option: all nodes) |
| `osm_features` | any | place or bbox + OSM tags (`{"amenity": "hospital"}`) | points of interest, parks, buildings |
| `sidewalks`, `crosswalks` | lines, polygons | Tile2Net output files | Tile2Net runs separately; the package reads its output |
| `file` | any | GeoJSON, GeoParquet, Shapefile, Overture extracts | any custom layer |
| `raster_grid` | raster cells | CRS + resolution in meters + extent, or "like" an existing raster | aligned to the local UTM zone by default; `like=` reuses another raster's exact grid so outputs line up cell for cell |
| `raster_file` | raster cells | GeoTIFF / COG path or URL, optional band selection | reads only the windows a step needs |

OSM layers use OSMnx. Street and intersection targets keep the graph or enough topology for
network-aware matching later, including the graph edge key alongside `u` and `v`. Street-length
statistics use physical segments when requested, deduplicating opposite-direction representations
of the same segment while retaining distinct physical carriageways.

## 5. Matching methods

Names are stable identifiers used in plans, the registry, and UrbanTrace's interface.

| Method | Sources | Targets | Match quantities | Replaces |
|---|---|---|---|---|
| `contain` | points | polygons | 1 for a polygon covering the point; when several cover it, assign to the lowest `target_id` | `BinaryContainment` (which counted boundary points twice) |
| `representative_point` | polygons, lines | polygons | 1 for the polygon covering a representative point on the source geometry | point-on-surface assignment |
| `centroid` | points, polygons, lines | polygons | 1 for the polygon covering the source's geometric centroid; the centroid can fall outside the source | `BinaryCentroidContainment`; `CentroidZoning` with polygon targets |
| `nearest` | points | any | 1 for the nearest target, optionally only within `max_distance` meters | `NearestAssignment`; UrbanMapper's `sjoin_nearest` matching |
| `nearest_segment` | points | lines (streets, sidewalks) | 1 for the nearest segment within `max_distance` | UrbanMapper's nearest street (`ox.distance.nearest_edges`) and nearest sidewalk/crosswalk |
| `nearest_node` | points | points (intersections) | 1 for the nearest node within `max_distance` | UrbanMapper's nearest intersection (`ox.distance.nearest_nodes`) |
| `within_distance` | points, lines | any | split equally among targets within `distance` meters, or 1 for each (`split=False`, one-to-many, matches ordered nearest first, optionally only the `k` nearest) | new: "crashes within 50 m of each intersection"; the one-to-many form is RustGIS's "Within a distance" |
| `area_overlap` | polygons | polygons | overlap area and share of the source's area | `ProportionalAreaWeighted`; zoning `AreaWeightedZoning` |
| `largest_overlap` | polygons, lines | polygons | 1 for the target covering most of the source (by area, or by length for lines); ties go to the lowest `target_id` | new (RustGIS's "Largest overlap"): parcels to the one district they mostly fall in |
| `length_weighted` | lines | polygons | overlap length and share of the source's length | `ProportionalLengthWeighted` |
| `line_overlap` | lines | lines | source length within `tolerance` meters of the target segment and the corresponding source fraction | new: bike routes onto street segments |
| `polygon_to_lines` | polygons or H3 cells | lines | length of the target segment inside the source, used for intensive or categorical values | `LengthWeightedZoning`; zone attributes onto streets |
| `gaussian` | points, lines | any | Gaussian of the distance in meters (bandwidth σ), cut at about 3σ and normalized per source; `outside="drop"` by default, with an explicit, reported `outside="nearest"` fallback | `GaussianKernel` uses a nearest fallback in UrbanTrace |
| `cell_coverage` | raster | polygons | per-cell planar coverage fraction and overlap area on a supported projected grid | exact zonal statistics |
| `cell_center` | raster | polygons | unit match for each zone containing the cell center under its declared boundary rule | Curio's UHVI and Weather means |
| `sample` | raster or H3 | points | a unit match to the cell containing the point or per-target interpolation coefficients on array grids | `CentroidZoning` with point targets; raster sampling |
| `along_line` | raster | lines | length of the target line inside each cell | new: heat or shade along each street segment |
| `burn` | points, lines, polygons | raster | polygon and line overlaps and their source fractions; unit matches for points | Curio's `rasterize_buildings` (one case) |
| `resample` | raster | raster | overlap area and fraction of each source cell covered by each target cell | new |

With a raster on either side, the methods are the vector methods applied to cells: `cell_coverage`
is `area_overlap` with cells as sources, `burn` is `area_overlap`/`length_weighted`/`contain` with
cells as targets, and `resample` is `area_overlap` between two grids. They have their own names
because they are computed differently (per window, on arrays, without building cell polygons), and
because `zonal_stats` and `rasterize` name common workflows. Section 6b lists the conversions built on
them.

Rules for matching and reporting:

- **Independent overlap** is the default for area and length overlays. Each target receives its
  actual overlap. Fractions can sum above 1 across overlapping targets or below 1 when there are
  gaps. These totals conserve source values only with full, nonduplicated coverage. One-to-many
  matches can also replicate a source (`within_distance(split=False)`).
- **Exclusive assignment** assigns each eligible feature to at most one target. Shared-boundary
  and nearest-distance ties use the lowest stable target ID. A line lying on a shared boundary of
  disjoint polygon interiors can use `shared_boundary="lowest_target_id"` to count its length once.
  **Normalized assignment** (`split=True` or `gaussian`) divides each matched source among its
  candidate targets. The extensive totals match the eligible input totals. Explicit renormalization
  of partial geometric coverage, if offered later, must report that it redistributed the uncovered share.
- The first vector release uses local projected measurements. Accept an explicit suitable CRS or
  resolve a local UTM CRS once for the step, and report it. Use a suitable equal-area CRS for area
  comparisons that need that accuracy. Larger extents, the antimeridian, and polar regions need an
  explicit supported strategy. Later ellipsoidal modes declare which operations they support.
- Candidate pairs come from a spatial index or native grid lookup. Inputs are never modified.
- Reports give matched and unmatched counts, partial allocations, applied fallbacks, and losses
  by cause. Report geometry failures and per-field missing, invalid and overflowed values separately.
  For extensive aggregations include valid input, allocated and unallocated amounts where defined.
  For independent overlaps, report replicated contribution separately when measurable. The sum of
  pairwise fractions alone cannot establish uncovered area where targets overlap. Detailed IDs
  are optional for large runs, with aggregate counts and a bounded sample by default.
- Raster geometry matching is independent of band validity. Each band excludes its nodata cells
  at aggregation. Report per-band valid coverage, including the denominator and units, and
  distinguish no geometric coverage from coverage with no valid values. Reproject vector geometry
  into the raster CRS for coverage; any warp is an explicit resampling operation.

Network distance (along streets rather than straight-line) is a later extension; the street and
intersection targets keep what it needs.

## 6. Aggregation methods

| Method | Value kind | Result per target |
|---|---|---|
| `count` | any | integer number of eligible matches, optionally filtered with `where` |
| `weighted_count` | any | sum of eligible matches' allocation fractions, optionally filtered with `where`; the result can be fractional |
| `sum` | extensive | Σ allocation fraction × valid value |
| `density` | extensive | allocated sum divided by the target's size by default: per km² (polygons and cells), per km (lines), per node (points). With `denominator="overlap_length"`, divide by the kilometers of eligible source lines inside the target |
| `weighted_mean` | intensive | Σ basis × valid value / Σ basis over valid values. Overlays use the overlap measure, samples use sampling coefficients, and other methods declare their basis. When requested, emit the weighted total and its valid measure for downstream aggregation |
| `mean` | intensive | unweighted mean of matched values |
| `median`, `weighted_median` | intensive | median of matched values, using the operator's statistical basis for the weighted variant |
| `min`, `max` | intensive | extremes of matched values |
| `majority` | categorical | category with the largest total under the declared basis; overlays use overlap area or length |
| `shares` | categorical | one column per category with its share of the valid matched measure; report target coverage separately |
| `first`, `last` | any | first or last valid match in the operator's declared order, such as nearest first, with stable source ID as the final tie-break |
| `join` | any | the matched values as text, separated by `delimiter` (", " by default), in the declared order |
| `custom` | any | a Python function of the matched rows (not serializable to JSON; flagged as such) |

Empty targets and targets whose matches have no valid values get missing results by default.
`count`, `weighted_count` and `sum` can use `fill_empty=0` for targets with no eligible matches. An all-missing
measured field remains missing, and valid observed zero remains zero. Count filtered matches and
report geometry and value coverage separately. A zero or missing density denominator returns a missing
result. `overlap_length` uses all eligible source geometry regardless of its attribute values, so
use a layer representing the intended physical network when reporting per-road-km rates. An integer
column stays integer for `min`, `max`, and unit-weight `sum`. Check the sum's exact result against
the 64-bit output range and report overflow. UrbanTrace's `LengthWeightedAggregation` becomes
`weighted_mean` with the appropriate basis.

The same aggregations apply when the target is a raster grid; the result is then a raster (one band
per aggregation) instead of a table. `density` on a raster target is per km² of cell.

## 6b. Conversions between raster and vector

Conversions that transfer values use the same match quantities and aggregation rules. Grid and
geometry operations such as `clip`, `split_lines` and `polygonize` can also be steps in a plan.

The first `zonal_stats` release supports north-up rasters. `cell_coverage` computes exact planar
fractions in the raster CRS on supported projected grids with known linear units. Area-based
statistics use a suitable projected CRS, with the planar measurement basis recorded. Equal-area
projections are appropriate when ground-area comparisons matter. `cell_center` also supports
north-up geographic grids for unweighted cell summaries. Rotated transforms and exact geographic
area weighting need separate support. The first release reports unsupported combinations without
implicitly warping the raster. For Curio migrations, adapters select the legacy center-based rule.
[exactextract coverage modes](https://isciences.github.io/exactextract/operations.html#operation-arguments) ·
[Rasterio adapter](https://github.com/isciences/exactextract/blob/master/python/src/exactextract/raster.py#L190-L213)

| Conversion | From → to | Built on | Default aggregation by value kind | Notes |
|---|---|---|---|---|
| `rasterize` | vector → raster | `burn` | extensive: `sum`; intensive: `weighted_mean`; categorical: `majority`; optional `presence`, `count`, `weighted_count` or `coverage` | `all_touched` option for thin lines; replaces SCOUT's height rasters (`max` of a height attribute) |
| `density_surface` | points, lines → raster | `gaussian` with a raster target | `sum`, normalized per km² | kernel density in meters; the same kernel as `gaussian` |
| `distance_surface` | vector → raster | distance per cell | — | meters to the nearest feature (proximity: distance to the nearest park, street, transit stop) |
| `interpolate` | points → raster (or any grid, or polygons through their cells) | IDW (`power`, `neighbors`, `max_distance`) or ordinary kriging (variogram fitted or given) | intensive only | a surface from measurements at points: air-quality and noise sensors, weather stations, tree inventories; extensive values are refused (use `density_surface`); kriging also writes its variance as a second band |
| `zonal_stats` | raster → polygons | `cell_coverage` (default on supported projected grids) or `cell_center` | extensive: `sum`; intensive: `weighted_mean`; categorical: `shares` | `count` counts valid matched cells; `weighted_count` sums their coverage fractions in exact mode |
| `sample_points` | raster → points | `sample` | the cell's value (or bilinear) | a column per band |
| `along_lines` | raster → lines | `along_line` | intensive: `weighted_mean` (by valid length) | heat or shade exposure per street segment; optionally return the weighted total and the valid length in meters |
| `split_lines` | lines + zones → line pieces | line–polygon intersections | — | stable piece IDs, parent line and zone IDs; for neighborhoods with disjoint interiors, shared boundary length goes to the lowest zone ID |
| `polygonize` | raster → polygons | connected cells of one value | — | categorical rasters (land cover, segmentation masks) to regions; optional minimum area and simplification |
| `cells_to_vector` | raster → polygons or points | — | — | each valid cell as a square polygon or its center point, with its band values; makes a raster usable by any vector method, at the cost of size |
| `resample_to` | raster → raster | `resample` | extensive: `sum`; intensive: `average` (or `bilinear`); categorical: `mode` (or `nearest`) | onto a `raster_grid` target or `like=` another raster; reprojection included |
| `mosaic` | rasters → raster | — | first valid value, or `mean`/`max` where they overlap | tiles to one raster; replaces Curio's `mosaic_rasters` |
| `clip` | raster → raster | — | — | to a polygon's footprint or a target's extent |

Preparing a grid before it is integrated, on its own grid (no values move between supports):

| Step | What it does | Example |
|---|---|---|
| `mask` | keeps cells by value, by class, or inside or outside polygons; the rest become nodata | only land-cover class "tree canopy" before `zonal_stats` |
| `set_nodata` | declares or changes the nodata value, or treats a range as nodata | a sensor's -9999 or a satellite's cloud flags |
| `reclassify` | maps values or ranges to classes (continuous to categorical, or classes to classes) | UTCI into heat-stress categories before `shares` |
| `calculate` | a cell-wise expression over aligned bands (arithmetic, comparisons, conditions) | Kelvin to Celsius; NDVI from two bands; a per-cell density times cell area to get a count |
| `align` | puts several rasters on one grid (`resample_to` with `like=`), each by its value kind | a heat raster and a population raster before comparing them |
| `stack` | aligned rasters as bands of one raster, each band keeping its value kind | inputs of one `zonal_stats` step |

`calculate` is cell-wise only: no neighborhoods, no filters, no terrain (those are out of scope,
section 2). A step's output declares its value kind, since an expression can change it (density
times area turns intensive into extensive).

Since H3 is a grid too, the grid-to-grid conversions cover it directly:

| Conversion | From → to | How | Notes |
|---|---|---|---|
| `resample_to` | raster → H3 | coverage of each raster cell in each hexagon | replaces "zonal onto H3 polygons"; the value kind decides sum, mean or mode |
| `resample_to` | H3 → raster | coverage of each hexagon in each raster cell | for drawing H3 results with raster tools, or combining them with raster layers |
| `resample_to` | H3 res r → H3 res r' | geometric intersections between source and destination cells at their respective resolutions | extensive totals are conserved over a complete destination covering |
| `cells_to_vector` | H3 → polygons | `h3.cell_to_boundary` per cell | keep each cell ID and its values |
| `rasterize` | vector → H3 | `burn` with hexagons as cells | native point indexing, or candidate cells and exact overlap for area shares |
| `zonal_stats` | H3 → polygons | `cell_coverage` with hexagons as cells | the second stage of UrbanTrace (grid → zones) |

The sources → H3 → zones chain is then vector → grid → vector, the same shape as raster workflows
(rasterize, then zonal statistics). The two paths share overlap semantics and reducer tests.
Array grids use windowed raster algorithms, and H3 uses cell lookup and indexed geometry operations.

Each conversion's report states what it lost or assumed: cells with nodata, sources outside the grid,
the share of a polygon covered by valid cells, and for `rasterize` whether small features fell
between cell centers (`all_touched=False`).

## 7. Chaining and plans

UrbanTrace's two stages (sources → grid → zones) are the same operation applied twice: in the second
step, the grid cells, now carrying values, are the sources and the zones are the targets. Its separate
zoning operators (`CentroidZoning`, `AreaWeightedZoning`, `LengthWeightedZoning`, and the zoning
aggregators) become the general methods:

| UrbanTrace zoning | Package |
|---|---|
| `CentroidZoning` | `centroid` for polygon zones; `sample` for point zones |
| `AreaWeightedZoning` (share of the cell inside the zone) | `area_overlap`, with the cells as sources |
| `LengthWeightedZoning` (line zones) | `polygon_to_lines` with H3 cells as source and intersection length as the statistical basis |
| `SumZoning`, `WeightedMeanZoning`, `DensityZoning`, `MajorityZoning`, `MaxZoning`, `MinZoning` | `sum`, `weighted_mean`, `density`, `majority`, `max`, `min` |

A plan is a versioned JSON recipe. Each step has a unique `id` and can refer to an earlier
output by `@id`. That reference can supply a source or a target support. Named sources are bound
at runtime, and named target specs can be reused by several steps. A step that reads target
geometry as its source uses a `{"target": "name"}` source reference. Validate references, method
parameters and compatible fields, including value kinds and units, before executing each step.

The extended street workflow below estimates crash counts per road kilometer. It distributes
counts uniformly along each physical segment when the segment crosses a neighborhood boundary.
The denominator is the length of all eligible street segments in a neighborhood, including
streets without crash matches. The zero fill assumes the crash input covers that network for
the observation period. Use snapped event locations directly for a location-based boundary assignment.

```json
{
  "version": 1,
  "targets": {
    "streets": {"kind": "osm_streets", "place": "Brooklyn, New York, USA", "network_type": "drive", "representation": "physical"},
    "nbhd":    {"kind": "admin_areas", "place": "Brooklyn, New York, USA", "admin_level": "10"}
  },
  "steps": [
    {"id": "street_crashes", "source": "crashes",
     "match": {"method": "nearest_segment", "target": "streets", "max_distance": 30},
     "aggregate": [{"method": "count", "as": "crashes", "fill_empty": 0},
                   {"method": "sum", "column": "persons_injured", "as": "injured"}]},
    {"id": "neighborhood_crashes", "source": "@street_crashes",
     "match": {"method": "length_weighted", "target": "nbhd", "shared_boundary": "lowest_target_id"},
     "aggregate": [{"method": "density", "column": "crashes", "denominator": "overlap_length", "as": "crashes_per_road_km"}]}
  ]
}
```

To compute mean heat exposure per observed meter of street, split the streets at neighborhood
boundaries before sampling. Each piece carries the UTCI × valid length total and the valid length.
The neighborhood step groups pieces by zone and divides their summed totals by their summed valid
length. A neighborhood with zero valid length gets a missing mean. Summarizing whole streets before
splitting would lose the location of the heat and nodata within streets that cross a boundary.

```json
{
  "version": 1,
  "targets": {
    "streets": {"kind": "osm_streets", "place": "Brooklyn, New York, USA", "network_type": "walk", "representation": "physical"},
    "nbhd":    {"kind": "admin_areas", "place": "Brooklyn, New York, USA", "admin_level": "10"}
  },
  "steps": [
    {"id": "street_pieces", "source": {"target": "streets"},
     "convert": {"method": "split_lines", "target": "nbhd"}},
    {"id": "piece_heat", "source": "utci",
     "convert": {"method": "along_lines", "target": "@street_pieces",
                 "aggregate": [{"method": "weighted_mean", "as": "utci_mean",
                                "weighted_total_as": "utci_m_sum", "valid_measure_as": "valid_street_m"},
                               {"method": "max", "as": "utci_max"}]}},
    {"id": "neighborhood_heat", "source": "@piece_heat",
     "reduce": {"by": "zone_id", "target": "nbhd",
                "aggregate": [{"method": "ratio_of_sums", "numerator": "utci_m_sum",
                               "denominator": "valid_street_m", "as": "utci_mean"}]}}
  ]
}
```

Each `reduce` group joins to a stable target ID. Ratios use rows where both components are valid.
Runtime source bindings, target specs and the `@step_id` namespace have explicit resolution rules.
Live target resolution is available for exploratory runs. A replayable run saves the resolved
parameters, source and target artifact fingerprints and selectors, package and engine versions,
CRSs, and coverage and allocation policies in a versioned run manifest. Replay uses the pinned
artifacts and verifies their fingerprints. A mutable or in-memory input can be replayed after it
is snapshotted or supplied again and verified. A JSON plan validates against registered operators
and typed arguments; Python callbacks remain available in the Python API.

## 8. API sketch

```python
import urbanweave as uw

crashes = uw.points_from_columns(df, lat="latitude", lon="longitude")   # drops rows without coordinates
streets = uw.targets.osm_streets(place="Brooklyn, New York, USA", network_type="drive")

m = uw.match(crashes, streets, method="nearest_segment", max_distance=30)
streets_out = uw.aggregate(m, crashes, [uw.count(as_="crashes"), uw.sum("persons_injured", as_="injured")],
                           targets=streets)
m.report        # matched 48,912 of 50,103 crashes; 1,191 farther than 30 m from any segment

utci = uw.read_raster("utci.tif", value_kind="intensive")
tracts = uw.zonal_stats(utci, tracts_gdf, [uw.weighted_mean(as_="utci_mean"), uw.max(as_="utci_max")])
grid = uw.targets.raster_grid(resolution=100, like=None, extent=tracts_gdf)   # 100 m cells, local UTM
crash_density = uw.density_surface(crashes, grid, bandwidth=150)            # a raster
pop_100m = uw.resample_to(pop_raster, grid)                                 # extensive: summed, total kept

plan = uw.Plan.from_json("crash_density.json")
result = plan.run(sources={"crashes": crashes})
```

Lower level, for tools like UrbanTrace's backend: `uw.registry` (operator metadata as JSON),
`uw.validate(source_geometry, target_geometry, method, value_kind)`, and per-step reports.

## 9. What UrbanMapper enabled, and where it goes

UrbanMapper (VIDA-NYU, last release 0.1.5, November 2025) is not maintained. Every capability is
either taken over or deliberately left to another tool:

| UrbanMapper capability | Where it goes |
|---|---|
| Streets layer from OSMnx (from place, address, bbox, point, polygon, XML, file; network types) | package: `osm_streets` target |
| Intersections layer (OSMnx nodes) | package: `osm_intersections` target |
| Sidewalks and crosswalks (Tile2Net) | package: `sidewalks`, `crosswalks` targets read from Tile2Net output |
| OSM features by tags | package: `osm_features` target |
| Admin regions: neighborhoods, cities, states, countries, with `admin_level` inference and override | package: `admin_areas` target |
| Custom layer from a file, or from another layer; Overture data via a file | package: `file` target |
| Nearest-feature matching with a distance threshold (`sjoin_nearest`, `nearest_edges`, `nearest_nodes`) | package: `nearest`, `nearest_segment`, `nearest_node` with `max_distance` |
| Count aggregator, with a custom counting function | package: `count` with `where` (and `custom`) |
| Simple aggregator: mean, sum, median, min, max, or a custom function | package: same names, plus weighted variants |
| Several enrichments of one layer in one pipeline | package: a step takes a list of aggregations; a plan has several steps |
| Simple geo imputer (drop rows without coordinates) | package: `points_from_columns` |
| Address geo imputer (geocode addresses with OSM) | package: `geocode(df, address_column, geocoder=...)`, pluggable geocoder, cached, rate-limited for Nominatim |
| Bounding-box filter (keep data within the layer's extent) | package: `clip_to(target)` (extent or exact footprint) |
| Loaders: CSV, Parquet, Shapefile, DataFrame, file auto-detection | GeoPandas reads these; the package adds `points_from_columns` and GeoParquet helpers |
| Hugging Face loader (`oscur` datasets, streaming, row limits) | package helper `read_hf(repo_id, columns=, rows=)`; long term, Auctus catalog records and subset reads |
| Urban pipeline: build, validate, run, save, load, share | package: JSON `Plan` with validation and per-step reports (no pickles) |
| Static and interactive visualisers | Autark / UrbanTrace (out of scope) |
| JupyterGIS export | optional exporter later; not core |
| LLM pipeline generator (GPT-3.5/4/4o) and MCP server | UrbanTrace's copilot, using the registry; an MCP server could wrap plans later |
| Auctus search mixin (`auctus_search`) | Auctus revamp client (`auctus/DESIGN-revamp.md`) |
| Interactive table display, `preview()` helpers | dropped (notebook conveniences) |

UrbanMapper had no raster support. Curio's raster code that overlaps the package:

| Curio | Where it goes |
|---|---|
| UHVI `zonal_mean` (cell centers in polygons), Weather `utci_zonal_mean` (rasterstats) | `zonal_stats`; the nodes explicitly select their center-based rule during migration |
| Rasterization `raster_statistics` (whole raster or masked cells) | a later whole-grid reducer composed with `mask`, sharing the zonal aggregation rules |
| Rasterization `rasterize_buildings` (SCOUT's web-tile height rasters) | `rasterize` with `max` of a height attribute, onto a `raster_grid` |
| Rasterization `mosaic_rasters`, `mosaic_collection` | `mosaic` |
| Rasterization `raster_calculate` (cell-wise operations over rasters on one grid) | the package's `calculate`, `mask` and `reclassify`; the node can keep its interface and call them |
| Autark grammar `heatmap` (rows near each cell of a grid, in Mercator units) | `density_surface` or `rasterize` in meters; Autark keeps drawing it |

RustGIS (opengeos, a desktop and web GIS in Rust) has many of these operations as separate tools.
The package takes names and habits from it, and fixes where its tools differ from one another:

| RustGIS | In the package |
|---|---|
| Spatial Join's match modes: Intersects, Contains, Within, Have their center in, Largest overlap, Closest (with a distance), Within a distance | `contain`, `centroid` for centers, `largest_overlap`, `nearest` with `max_distance`, `within_distance` with `split=False` |
| Spatial Join's merge rules (first, last, sum, mean, min, max, count, join), exact integer sums, empty for no match but a count of 0 | the same aggregations and rules (section 6) |
| Tabulate Intersection's sum fields (totals shared out by area) | `area_overlap` + `sum`, also for lines and grids, plus `weighted_mean` for intensive values |
| Summarize Within (a point on a shared edge counts in both polygons) | `contain`, where it counts once |
| A5 Grid, Aggregate Points to A5 (points only) | `a5` target, any source |
| Kernel Density, IDW, ordinary kriging | `density_surface`, `interpolate` |
| `raster.rasterize` (polygons, cell centers, the last polygon wins) | `rasterize` for points, lines and polygons, with coverage fractions and aggregation by value kind |
| Zonal Statistics (mean of the cells whose centers are inside) | `zonal_stats` with exact coverage, any aggregation |
| `raster.project` (sample, average or mode of cells whose centers fall inside; palette rasters forced to nearest or mode) | `resample_to` by coverage, with `sum` so extensive totals are kept; the value kind picks the method |
| Distances on the WGS 84 ellipsoid; reports of shapes that held no cell center and values left out | `measure="ellipsoid"`; the loss reports of section 5 |

Python libraries that overlap urbanweave, and what it does with each:

| Library | What it does | urbanweave |
|---|---|---|
| **tobler** (PySAL) | Areal interpolation, including area-weighted, dasymetric, pycnophylactic and model-based methods | Comparison for compatible overlap aggregations (section 11). Core installation stays independent. Its dasymetric and pycnophylactic methods are candidates for later releases (section 14) |
| **exactextract** (C++ with Python bindings) | Exact fractions of regular raster cells covered by polygons, and zonal statistics from them | Engine for supported `cell_coverage` and `zonal_stats` operations. Test against independently calculated fixtures. Benchmark polygon rasterization separately |
| **rasterstats** | Zonal statistics and point queries, by cell center or `all_touched` | Replaced by `zonal_stats` (exact by default) and `sample_points`; Curio's Weather package uses it today |
| **rioxarray**, **xarray-spatial** | Raster I/O, reprojection and clipping on xarray; local, focal and terrain operations | rioxarray for raster I/O and windows; xarray-spatial's analysis stays outside urbanweave (section 2) |
| **h3**, **a5** | Cell ids, cell geometry, cells of a polygon | Used for the `h3` and `a5` targets |
| **OSMnx** | Street networks and OSM features | Used for the OSM targets (section 4) |

## 10. Operator registry

One JSON document, generated from the code, consumed by UrbanTrace's interface, its backend
validation, and its copilot:

```json
{
  "matching": {
    "nearest_segment": {
      "sources": ["Point", "MultiPoint"], "targets": ["LineString", "MultiLineString"],
      "params": {"max_distance": {"type": "number", "unit": "m", "default": null}},
      "match_quantities": ["allocation_fraction", "distance_m"],
      "conservation": {"scope": "eligible_sources", "excludes": ["beyond_max_distance", "no_target"]},
      "summary": "Each point goes to the nearest line segment (street, sidewalk)."
    }
  },
  "aggregation": {
    "count": {"summary": "Number of eligible matches."},
    "weighted_count": {"requires": ["allocation_fraction"], "summary": "Sum of eligible allocation fractions."},
    "density": {"value_kinds": ["extensive"], "requires": ["allocation_fraction", "density_denominator"],
                "summary": "Allocated total divided by the configured area, length, or node denominator."}
  }
}
```

Registry entries distinguish vector geometry, array rasters and global grids. Conversions list
their supported measurement modes and their default aggregation by value kind. Conservation is
conditional metadata for a method and its parameters. For overlays it depends on actual target
coverage; the step report gives the observed result. The registry exposes only installed and
implemented operators to clients.

## 11. Correctness and testing

- **Totals**: test disjoint full coverage, partial coverage and independently overlapping targets.
  Check extensive totals for the method's eligible inputs. Check partial and replicated contributions
  against hand-calculated examples and conservation over partitions with property tests.
- **Weights**: check fraction bounds and each operator's normalization axis. Two fully covered
  polygons of 100 m² at 10°C and 900 m² at 20°C must yield an area-weighted mean of 19°C.
- **Counts**: a valid raster cell covered by one quarter yields `count=1` and `weighted_count=0.25`.
  A unit-match operator gives the same numeric result for both counts.
- **Point selection**: use a concave polygon whose geometric centroid lies outside the source to
  distinguish `centroid` from `representative_point`.
- **Units**: distances, lengths, and areas checked against known shapes in metric CRSs at several
  latitudes.
- **Boundaries**: points on shared edges and vertices land in exactly one polygon.
- **Missing data**: verify true zero, empty targets, all-missing matches and mixed valid/missing
  matches separately. Compare valid coverage and denominator alongside the returned value.
- **Regression**: UrbanTrace's existing operators on the 121-dataset corpus, compared before and after
  with named explanations for changes to numerical rules or output semantics.
- **OSM layers**: tests use small saved extracts, not live downloads.
- **Raster totals**: `zonal_stats` with `sum` over polygons that tile a supported raster equals the valid
  raster sum. Later, test the same invariant for extensive rasterization and resampling over complete
  destination coverage. A round trip on aligned fixtures can recover original totals. Crossing cell
  boundaries redistributes values, so measure the redistribution on a known nonaligned fixture.
- **Raster edge cases**: test nodata and per-band validity, subcell polygons, independent overlapping
  zones, and targets outside the raster. Verify the first raster release rejects unsupported rotated
  transforms and geographic exact area weighting. Add half-cell offsets when resampling ships.
- **Interpolation**: IDW and kriging reproduce the sample values at the sample points (exact
  interpolators) and match a reference implementation (PyKrige) on a fixed dataset.
- **Measures**: `measure="ellipsoid"` against pyproj's geodesic distances and areas, and against UTM
  for small extents, where both must agree within a set tolerance.
- **Against tobler**: compare extensive totals with `allocate_total=False` and compatible missing
  data. Compare intensive means using overlap areas. Compare category areas first, then normalize
  each tool's outputs to the same denominator. Tobler's default categorical frequency uses the
  full target area. [Tobler API](https://pysal.org/tobler/stable/generated/tobler.area_weighted.area_interpolate.html)
- **Independent raster fixtures**: hand-calculate totals, means, category shares and valid coverage on
  small grids. Matched-mode exactextract checks verify the adapter. Compare UHVI and Weather on their
  sample dataflows before enabling their adapters, and test Rasterization with its whole-grid reducer.
- **Plans**: execute the crash and heat examples on local fixtures when their operators ship. Verify
  the denominators, referenced outputs and frozen inputs, and reject replay when an artifact changes.

## 12. Performance

- Spatial indexes for all candidate searches; vectorized distance and overlay computations.
- `area_overlap` and `length_weighted` use clipped intersections only for candidate pairs.
- Large sources: process in chunks; GeoParquet in and out.
- Rasters: windowed reads under a step's targets. Start with local tiled GeoTIFFs, then benchmark
  optional chunked arrays and Cloud-Optimized GeoTIFFs over HTTP range requests.
- Exactextract computes planar coverage fractions on supported north-up grids. Combine sums, valid
  measures and category totals across windows before deriving means or shares. Exact medians and
  arbitrary reducers need their own memory policy.
- Benchmarks: NYC collisions (about 2M points) onto streets and onto H3 resolution 9; a 1 m land-cover
  raster of NYC (about 10^9 cells) onto census tracts and onto street segments.

## 13. Moving UrbanTrace onto the package

1. Release the local vector/H3 core with `h3`, `zones`, the operators UrbanTrace needs, the registry
   and reports. Port the kernel tests and verify the H3 → polygon, point and line zoning paths.
2. Switch UrbanTrace's backend through an adapter in `integration_engine.py` and `main.py`.
   Generate the interface's operator options and copilot constraints from the same registry. Use
   baseline comparisons before enabling the package path by default.
3. Deliver `zonal_stats` on supported north-up rasters and migrate Curio's UHVI and Weather nodes using
   their center-based coverage rules. Reuse those reducers for Rasterization once the whole-grid
   and mask operations are ready.
4. Add saved JSON plans and pinned run manifests for the implemented workflows. Add physical street
   and intersection targets and the operators needed for the two example plans. Expose each plan
   capability when its fixtures pass.
5. Extend raster and global grid support based on validated use cases. Add general resampling,
   additional rasterization, interpolation and A5 in subsequent releases.

## 14. Open questions

- **Home**: whether urbanweave lives under VIDA-NYU or OSCUR. (The name is decided: `urbanweave`,
  free on PyPI on 2026-11-19; claim it before announcing.)
- **tobler's methods**: for later dasymetric and pycnophylactic methods, evaluate reuse of tobler
  against the requirements for reporting and chaining.
- **Network distance**: once street targets are in use, which routing semantics should supported
  methods use for mode, direction and unreachable targets?
- **Target size for density on lines and points**: per km and per node are defaults; are other
  normalizations needed (per lane-km, per capita)?
- **Geocoding**: which geocoder by default (Nominatim has strict rate limits), and whether results are
  cached across projects.
- **Raster stack**: the first raster milestone uses Rasterio and exactextract as optional
  dependencies. Evaluate rioxarray and dask for later multi-band, time-stacked or lazy workflows.
- **Raster outputs**: GeoTIFF/COG only, or also Zarr for large or time-stacked results?
- **Other global grids**: H3 ships first. Evaluate the Python A5 binding against coverage and
  neighbor fixtures when there is a use case for equal-area cells, then consider other global grids.
- **H3 coverage**: keep UrbanTrace's center-based extent selection explicit for replay; benchmark a
  covering that includes every intersecting cell before offering it. Exact overlays use the
  geometry of the cells in the chosen support.
- **Time**: the operators are spatial only; temporal binning (per hour, per month) could become
  another step kind.
