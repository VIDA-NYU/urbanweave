# Urbanweave implementation plan

The first release extracts the local vector and H3 operators used by UrbanTrace into an installable Python
package. The first raster release adds zonal statistics for Curio’s UHVI and Weather nodes. Street analysis
and reusable JSON plans follow once the core numerical contract has been tested in both applications. The
[design document](DESIGN.md) describes the public behavior and longer-term
scope.

## Status (2026-11-19)

Milestones 0, 1, 3.1 and 4 are implemented in this repository, and every acceptance fixture has a test (130
in the regular suite, plus the Milan comparison under `-m slow`); benchmarks still run on synthetic
stand-ins for the NYC data. The steps of milestones 2, 3.2 and 4.2 that change UrbanTrace or Curio are
marked **in the consumer**: urbanweave provides what they call, but neither repository has been modified.
Milestone 5 has not started. The first prerelease, 0.1.0a1, is released from
[VIDA-NYU/urbanweave](https://github.com/VIDA-NYU/urbanweave), maintained by the OSCUR team.
[STATUS.md](STATUS.md) maps each item to its code and tests.

## Sequence and release gates

| Milestone | Depends on | Deliverable and gate |
|---|---|---|
| 0. Baselines and contracts | | Freeze representative UrbanTrace outputs, confirm the consumer dependency ranges, and write the hand-calculated fixtures. |
| 1. Vector and H3 core | 0 | Build and install the package in a clean environment. Pass the core numerical fixtures and all three H3-to-zone paths. |
| 2. UrbanTrace cutover | 1 | Pass old/new comparisons for the available corpus cases and consumer API tests. Release the first version once discrepancies have named explanations and rollback has been exercised. |
| 3. Curio zonal statistics | 1 | Pass independent exact-coverage tests and preserve UHVI and Weather outputs in explicit center mode. Enable each Curio adapter after its own dataflow checks. |
| 4. Saved plans and street workflows | 1 for plans, 3 for the heat workflow | Verify replay on pinned artifacts and execute both revised examples on local fixtures. Expose each workflow after its acceptance tests pass. |
| 5. Additional grids and conversions | Relevant earlier milestones | Evaluate each new capability with accuracy and memory fixtures before adding it to the registry. |

Build the Curio raster slice independently of UrbanTrace’s cutover once the core match and reducer
interfaces are stable. Roll out consumer changes from their own repositories after the package prerelease is
available. Keep library releases independent of consumer deployment schedules.

## 0. Capture baselines and agree on the contract

- [x] Record the UrbanTrace and Curio revisions used for comparisons. Build an inventory from UrbanTrace’s
      121-dataset catalog. For each dataset, record the local asset, CRS, geometry types, representative
      columns and valid operator cases. Record missing assets and unsupported cases so the regression report
      shows the actual coverage of the inventory.
      *Done:* revisions in `tests/legacy/*/REVISION`; inventory and comparison by
      `tools/urbantrace_corpus.py`, results in `reports/urbantrace_corpus.md`: 121 datasets, 319 cases
      compared, 15 refused with the reason (corrupt or mislabelled coordinates), 38 skipped for size.
- [x] Run UrbanTrace’s current kernel tests and capture old outputs for representative point, line, polygon and
      multipart inputs. Include grid-only, polygon zoning, point zoning, line zoning, zone values displayed on
      the grid, and multivariate `grid`, `zones` and `both` responses. Capture IDs, CRS, column types, row
      membership, nulls and numerical outputs. Use small fixture extracts in regular CI and run the larger
      comparison separately.
      *Done:* kernel tests ported (`tests/test_kernel_port.py`); legacy operators run beside urbanweave in
      `tests/test_legacy_urbantrace.py` for grid-only, polygon, point and line zoning and zone values painted
      back on the grid. The multivariate response shape lives in UrbanTrace's HTTP layer.
- [x] Inventory the request and response paths in UrbanTrace’s `backend/main.py` and
      `backend/integration_engine.py`, including `/api/operators` and the operator recommendation endpoint.
      Note legacy combinations with no direct numerical equivalent. In particular, classify H3-to-point as
      sampling and H3-to-line as a length-based overlay. Check which legacy zoning reducers use
      target-normalized weights, especially extensive reducers. Decide which behaviors require an explicitly
      named compatibility path and which numerical corrections change outputs.
      *Done:* classifications and named changes in `urbanweave.compat.urbantrace.CHANGES`; legacy `SumZoning`
      on line zones kept as `target_normalized_sum`; `BinaryContainment` on MultiPoints refused with the
      reason.
- [x] Confirm the minimum Python and dependency versions that work in the consumer environments. Use both the
      lowest supported combination and a current supported combination in CI. Park unrelated dependency
      upgrades until there is a demonstrated requirement.
      *Done:* Python 3.11 with NumPy 1.26, pandas 2.2, Shapely 2.0.4, pyproj 3.6, GeoPandas 1.0, h3 4.1,
      rasterio 1.4.0, exactextract 0.2.0 and OSMnx 2.0.0 passes, as does Python 3.13 with current releases;
      both in `.github/workflows/ci.yml` with a core-only job.
- [x] Write the analytical fixtures in the acceptance matrix below. Agree on area, length and distance
      tolerances for calculated results. For simple projected fixtures use absolute and relative tolerances of
      `1e-9` where the areas, lengths and expected results are well scaled. Use exact equality for IDs, unit
      integers and report counts. Record looser tolerances for measured reprojection fixtures along with the
      CRS and reason.
      *Done:* 1e-9 for projected fixtures; 1e-5 for allocation flags after reprojection; 1e-7 where
      exactextract's single-precision fractions are summed; 2e-3 for EPSG:3857-vs-UTM comparisons with legacy.

## 1. Implement the vector and H3 core

### 1.1 Package and input types

- [x] Create `pyproject.toml` and a `src/urbanweave/` layout. Use GeoPandas, Shapely, pyproj, pandas, NumPy and
      H3 for the core. Provide `raster`, `osm` and development extras as those capabilities land. Verify wheel
      and source installs and that importing the base package works with neither the raster nor the OSM extras
      present.
      *Done:* a clean wheel install imports with no extras (CI `package` job).
- [x] Keep the responsibilities of `targets`, `matching`, `aggregation`, `registry` and `reports` separate.
      Start with ordinary DataFrames and GeoDataFrames at entry points and a defined match schema. Avoid
      committing the public API to how the package stores an indexed or batched intermediate.
- [x] Validate CRS, geometry family, unique non-null IDs and requested columns before joining. Allow
      caller-supplied IDs via explicit parameters. Generate IDs by a documented rule for supported inputs with
      no ID column, then preserve them through filtering and joins. Reject duplicate IDs and missing CRS at the
      input boundary. Report empty or invalid source geometry as excluded, and reject invalid target geometry
      before constructing a support. Define each multipart operator’s unit of observation and port parity
      fixtures before enabling it.
      *Done:* sources with coordinates outside a geographic CRS's range are also excluded by cause, and a
      layer with every coordinate out of range is refused as a mislabelled CRS (found by the corpus run).
- [x] For H3, keep hex cell IDs and resolution as the primary representation. Materialize one boundary per cell
      when needed for overlay or output. Expose center-based extent selection to reproduce UrbanTrace’s existing
      grid build. Test candidate completeness separately from extent selection. A point that indexes to a cell
      outside the chosen support is an unmatched source.

### 1.2 Matching and measurement

- [x] Implement `match` with `contain`, `representative_point`, `centroid` and `nearest` first. Use an interior
      point on polygons for `representative_point` and the geometric centroid for `centroid`. Test shared
      edges, vertices and tied distance results against stable target IDs. Check exact distance thresholds in
      meters and exclude zero-measure contacts from area and length overlays.
      *Done:* with `nearest_segment`, `nearest_node`, `within_distance`, `largest_overlap` and `sample` as well.
- [x] Implement `area_overlap` and `length_weighted` with a spatial index and vectorized intersections. Emit
      `overlap_measure` and `allocation_fraction` from the same measured geometry and CRS. Verify multi-target,
      partial coverage and overlapping cases. Expose a single measurement configuration per step. Accept a
      suitable explicit projected CRS or resolve a local UTM CRS from the study area, and reuse that resolution
      across chunks. Reject unsupported large or polar extents, unsuitable distance/area CRS choices, and
      antimeridian crossings until a measurement strategy exists for them.
      *Done:* topology runs in the targets' CRS and measurement in one projected CRS per step.
- [x] Add the Gaussian kernel with bandwidth in meters and source normalization. Use `outside="drop"` for the
      core default and request `outside="nearest"` explicitly in the UrbanTrace adapter. Preserve UrbanTrace’s
      centroid-distance kernel for grid targets, including its cutoff rule. Report fallback matches and check
      that explicit `max_distance`, where applicable, is honored.
- [x] Complete the zoning paths. H3 to polygons uses centroid or area overlap. H3 to points uses cell lookup and
      may copy one cell value to several points. H3 to lines measures the length of each line inside each cell
      for intensive reductions. Test line segments coincident with a cell boundary to avoid duplicating length
      when the operation assumes a partition. Keep any legacy target-normalized extensive result in the
      compatibility path with its original units and behavior documented.

### 1.3 Aggregation, registry and reports

- [x] Implement `count`, `weighted_count`, `sum`, target-size `density`, `mean`, `weighted_mean`, `min`, `max`
      and `majority`, followed by `shares` for area-overlay validation. `count` returns the number of eligible
      matches. `weighted_count` sums their allocation fractions. Reuse match geometry for multiple reducer
      requests. Multiply by source allocation fractions for totals and by actual overlap area or length for
      spatial means and category results. Use unit or explicitly declared kernel/sampling coefficients for
      their supported operations. Reject unsupported method and value-kind combinations early.
      *Done:* with `median`, `weighted_median`, `first`, `last`, `join` and `custom` as well.
- [x] Derive every output from eligible, valid inputs. Return a row for each resolved target in target order.
      Preserve genuine zeros and distinguish no eligible match from no valid measurement. Apply `fill_empty=0`
      only when requested for `count`, `weighted_count` or `sum` and there are no eligible matches. Keep
      unit-weight integer sums exact through a range check and represent missing integer output with a
      nullable type. Reject duplicate output aliases and make category ordering and tie behavior deterministic.
- [x] Generate the versioned registry from the same definitions used by method dispatch and validation. Include
      input supports, required match quantities, parameter defaults, allowed value kinds, result units and
      conditional conservation. Test registry parity with actual execution on a valid and invalid call for each
      operator. Add unavailable optional operations only when their dependencies and implementations are
      present.
- [x] Make reports composable across matching and aggregation. Include resolved measurement,
      eligible/matched/excluded counts, partial allocation, fallback counts, and per-column reductions or
      exclusions. For extensive values distinguish input, allocated, unallocated and replicated amounts where
      defined. For independent overlaps report pairwise allocated contribution and flag geographical coverage as
      unavailable when the union has not been measured. Aggregate counts and keep a bounded sample of IDs by
      default. Opt into a separate full-ID artifact for larger diagnostics.

### Exit checklist

- [x] Run points → H3 → zones from a clean core install using the public API, registry and structured reports.
      Verify polygon, point and line zoning.
- [x] Pass the core fixtures and the ported kernel tests.
- [x] Shuffle the input rows with stable IDs and verify the same matching decisions and floating reductions
      within tolerance.

## 2. Migrate UrbanTrace

- [x] Introduce an adapter around the existing integration engine paths. Map legacy operator IDs and column
      conventions (`cell_id`, `zone_id`, `gamma`, `aggregated_value`, `allocated_val`) at the application
      boundary. Map `BinaryCentroidContainment` and polygon `CentroidZoning` to the geometric centroid path.
      Record the centroid calculation CRS in compatibility tests. Keep explicit defaults for H3 extent,
      Gaussian fallback and sampling. Preserve the contract of the zone-to-grid display path, including
      which zoning mapping decisions are reused when painting values back onto H3 cells.
      *Done:* `urbanweave.compat.urbantrace.run` with legacy IDs, column names, wire units and basis. Wiring
      it into `integration_engine.py` is **in the consumer**.
- [x] Run the old and new paths against the same captured inputs. Compare ID sets, geometry, row presence,
      response shape, nullness, units, reports and values. Review density deltas from both the metric
      projection change and any conversion from legacy per-m² output to per-km². Keep legacy wire units where
      clients expect them until both sides migrate. Record expected deltas for weights, boundary assignments,
      invalid values and empty targets. Ensure server and UI represent missing values without treating them as
      measured zeros.
      *Done:* in the tests and over the catalog; every difference is named (UTM measurement, invalid sources
      excluded, nearest ties, H3 index lookup). Server and UI handling of missing values is **in the
      consumer**.
- [ ] Change `/api/operators` to project the package registry into the payload the frontend currently consumes.
      Make the backend validation, `frontend/src/components/canvas/nodes/IntegrationNode.jsx` and copilot
      fallbacks read the generated constraints. Test legacy saved IDs, invalid geometry errors, output-mode
      selection and the recommendation path using fixtures with no live LLM dependency.
      **In the consumer.** urbanweave provides `operators_payload()` and `geometry_constraints()`, generated
      from the registry.
- [ ] Pin the package prerelease in UrbanTrace, exercise the new path alongside the existing one, and record
      the operator mapping and fallback switch. Make the package path the default only after the compatibility
      review passes. Verify the previous pinned path in a rollback smoke test.
      **In the consumer.** The prerelease is 0.1.0a1, published from VIDA-NYU/urbanweave by
      `.github/workflows/release.yml` when its tag is pushed.

### Exit checklist

- [x] Publish counts of available, exercised and skipped cases and a reason for each accepted difference.
      Resolve all unexplained regressions in supported workflows.
      *Done:* `reports/urbantrace_corpus.md`: 0 unexplained, 0 errors.
- [ ] Reproduce build artifacts and consumer dependency pins from recorded revisions.
      **In the consumer.** The legacy code's revisions are recorded; the consumers' pins depend on the prerelease.

## 3. Implement north-up zonal statistics and migrate Curio

### 3.1 Raster input and reducers

- [x] Add `read_raster` and `zonal_stats` under the `raster` extra. Accept a Rasterio dataset or local file and an
      in-memory band with an explicit affine transform, CRS and validity mask. Treat band selection,
      nodata/mask, scale, offset, value kind and units as per-band metadata. Define ownership of opened datasets
      so caller-owned readers stay usable and library-opened readers close when finished.
- [x] Support north-up grids with known linear units for `cell_coverage` and north-up projected or geographic
      grids for unweighted `cell_center`. Reject rotated or skewed transforms and requests for exact geographic
      area in this milestone. Distinguish a fraction in grid coordinates from a planar area. Record the raster
      CRS and measurement basis, convert native linear units to meters for area results, and use a suitable
      projected grid for area claims. A geographic or unsuitable analysis grid needs explicit resampling or a
      later measurement engine for physical area.
- [x] Use exactextract for `cell_coverage` and a windowed Rasterio mask for `cell_center`. Project zones into
      the raster CRS for coverage. Keep geometric coverage separate from band validity. For exact coverage
      return the portion inside the raster footprint and the portion with valid values, both relative to the
      full zone’s planar area. In center mode report valid and selected center counts within the raster. Explain
      the denominator and distinguish no intersection, no selected centers, and selected cells with no valid
      values.
- [x] Deliver zonal extensive sum, `count` and `weighted_count` of valid cells, intensive mean and weighted
      mean, min/max and categorical shares. With exact coverage, `count` returns the number of matched cells
      and `weighted_count` sums the coverage fractions. Merge totals, valid measures and category
      accumulators across windows before computing ratios. Exact median and arbitrary Python reducers require a
      separate storage or resource policy. Use the core match and report schema with windowed raster cells.
- [x] Measure read windows, total cells read, runtime and peak memory on a local tiled GeoTIFF. Repeat with
      disjoint zones, overlapping zones and a zone spanning many windows. Require equivalent results across
      window sizes and bounded memory for streaming reducers. Record a baseline before setting performance
      thresholds for future releases.
      *Done:* `tools/benchmark.py raster`: 8,000 × 8,000 tiled GeoTIFF, 500 zones, 4.3 s and 0.54 GB peak (1.8
      GB before zones were batched); results are equal for any window size.

### 3.2 Curio adapters

- [ ] Migrate `zonal_mean` in `packages/ai.utk.uhvi@1/sources/uhvi_statistics.py`. Preserve the order-independent
      inputs, projected output geometry, `uhvi_mean`, `uhvi_zonal` metadata, and the current missing-CRS
      assumption in the node adapter. Select `cell_center` explicitly and compare empty and subcell polygons,
      masked cells, and the sample dataflow.
      **In the consumer.** The drop-in is `urbanweave.compat.curio.uhvi_zonal_mean`, equal to Curio's in
      either input order and on the Milan sample dataflow (0.9 s against minutes). Enabling it adds urbanweave
      to the libraries Curio's node code may import, which is the owner's decision.
- [ ] Migrate `utci_zonal_mean` in `packages/curio.weather@1/sources/weather_census.py`. Pass the in-memory UTCI
      array with its derived transform and mask. Select `cell_center`, preserve the `mean` and `gt_65` output
      and geometry, and test rectangular grids to catch width/height mistakes. Compare with the existing
      rasterstats output on the sample dataflow.
      **In the consumer.** The drop-in is `urbanweave.compat.curio.utci_zonal_mean`, equal to Curio's
      rasterstats output on a rescaled rectangular grid and the Milan sample dataflow.

### Exit checklist

- [x] Run both Curio adapters on their local sample dataflows and verify their documented output shapes.
      *Done:* from urbanweave's tests against Curio's sample data, read in place.
- [x] Pass the hand-calculated exact-mode fixtures independently of engine comparisons.
- [x] Verify that the first raster release advertises north-up support and gives clear errors for unsupported
      grids.

## 4. Implement reproducible plans and the street workflows

### 4.1 Plan format and replay

- [x] Implement `Plan.from_json` and `Plan.run` for the core operations first. Version the schema and define
      steps that pair `match` with `aggregate`. Use unique step IDs, named runtime sources, named targets and
      `@step_id` references. Permit
      `{"target": "name"}` in a source slot when the step reads target geometry. Preflight references,
      parameter types, known field names, duplicate aliases and input/output support compatibility. Validate
      bound columns, units and value kinds against the actual data before each affected step. Restrict
      serialized predicates to declared operators and typed operands.
- [x] Separate target request keys from artifacts. Cache immutable artifacts by fingerprint and store the
      resolution metadata that maps a request to the artifact. Materialize a local copy or an immutable
      versioned reference when a source must be available for replay. Fingerprint actual file content, file
      collections or a deterministic exported snapshot, including relevant band or part selections. Preserve
      artifacts when a newer resolution of a mutable request is cached.
- [x] Write a versioned run manifest with the evaluated arguments and defaults, source and target selectors and
      fingerprints, package and operator versions, relevant backend versions, CRS and coverage policy. Commit
      cache entries and manifests atomically. Replay verifies artifact fingerprints and compatible engine
      versions before computation. Report stale, changed, missing or unavailable artifacts by name and offer
      live resolution as a separate run mode.
- [x] Verify round trips from JSON to plan to manifest to replay. Test an unknown operator and version, forward
      reference, reuse of one target by two steps, incompatible unit, path content changed in place, and
      refresh of a live target whose request key is unchanged. Test the case in which an in-memory input needs
      to be supplied and verified again.

### 4.2 Street targets and examples

- [x] Add optional OSMnx builders backed by local saved graph extracts in tests. Distinguish physical segments
      used for exposure and length from directed edges used for network topology. Preserve graph edge keys and
      junction IDs. Test reciprocal edges, separate carriageways, parallel edges, eligible street length and an
      intersection derived from incident physical street count.
- [x] Implement `nearest_segment` matching, explicit per-overlap-length density, and deterministic handling of
      segments on a shared boundary between zones with disjoint interiors. Execute the crash example with every
      eligible segment present, including streets with no matches. The report records cutoff misses,
      denominator units and the approximation for splitting street-level counts at zone boundaries.
- [x] Implement `split_lines`, `along_lines`, and `reduce` with `ratio_of_sums`. Persist `zone_id` and a stable
      piece ID across sampling. Allocate line length coincident with a raster cell boundary once per target
      piece using a documented ownership rule. Return the weighted temperature total and valid length along
      with coverage. The final reduction uses component pairs with valid values and returns missing for zero
      total valid length.
- [x] Save both worked plans and their small input fixtures in the package’s examples or tests, and run the
      plans without OSM or other network access. Verify heat and crash denominators against direct
      calculations. Add an UrbanTrace plan import/export adapter after the saved-plan schema has passed the
      replay tests.
      *Done:* `examples/crash_density.json` and `examples/heat_exposure.json`. The UrbanTrace plan
      import/export adapter is **in the consumer**.

### Exit checklist

- [x] Execute both plans from their checked-in JSON and replay them with pinned fixtures.
- [x] Verify street IDs, spatial splits, units, observed lengths and missing values against the fixtures.
- [x] Verify that a changed local or remote artifact requires a new manifest or the original artifact for replay.

## 5. Extend after the first workflows

- [ ] Prioritize masked whole-grid statistics and migrate `raster_statistics` in
      `packages/curio.rasterization@1/sources/scout_rasters/raster_algebra.py`. Establish a resource policy for
      exact median and preserve band selection, masked conditions and the node’s one-row contract. Check a
      mask that excludes some valid values and a mask that excludes all cells.
- [ ] Add rasterization and then resampling. Define the overlap measure for projected, geographic, and rotated
      grids before enabling each combination. Test aligned and half-cell-shifted grids, clipped extents, nodata,
      and extensive mass balance. Keep categorical nearest/mode and intensive averaging choices explicit.
      Benchmark the write path independently of zonal extraction.
- [ ] Evaluate A5 and cross-resolution DGGS transfers with geometric versus index roll-up fixtures. Treat
      logical hierarchy and spatial overlap as separate operations with separate guarantees. Add the other
      targets, interpolation, routing, additional raster formats and grid preparation as concrete consumer uses
      justify them.

## Acceptance fixtures

- [x] **Unequal areas.** Cover two polygons, 100 m² at 10°C and 900 m² at 20°C, with one target. Both allocation
      fractions are 1, the weighted temperature is 19°C, and differently labeled areas have category shares of
      10% and 90%.
- [x] **One source with a total of 100.** A complete partition conserves 100. Disjoint targets covering 30% and
      50% receive 30 and 50 with 20 unallocated. Two independent targets each covering 80% receive 80 each. The
      pairwise weights alone leave union coverage undetermined.
- [x] **Shared boundary and nearest ties.** A boundary point and an equidistant point each yield one match,
      selected by stable target ID. A line on the boundary contributes length once under the partition rule.
- [x] **Centroid and representative point.** Use a concave polygon with its centroid outside its footprint.
      Match to separate target polygons containing the geometric centroid and the interior point to verify the
      two method IDs select different targets.
- [x] **Gaussian cutoff.** A point outside every candidate radius is unmatched by default. UrbanTrace’s
      explicit nearest fallback attributes it once and increments the fallback count.
- [x] **Valid zeros, invalid values and overflow.** A real zero stays zero. The optional empty fill responds
      only to no eligible matches. An all-missing field stays missing. A unit-weight sum over the output
      integer range reports overflow.
- [x] **One quarter of a valid cell with value 8.** Exact coverage gives intensive mean 8, extensive sum 2,
      `count=1` and `weighted_count=0.25`. A center rule selects no cells if the quarter excludes the center.
- [x] **One valid cell and one nodata cell, both 1 m².** Geometric coverage is 100% and valid area coverage is
      50%. Only the valid cell contributes to the mean and sum. A second band with a different mask gets its
      own coverage.
- [x] **Partly outside the raster.** Geometric coverage uses the full target area denominator. A zone wholly
      outside has zero coverage and a missing value. A rotated grid triggers the unsupported-grid error.
- [x] **Four crashes on one of two 1 km physical streets in the same zone.** With complete event coverage and
      no clipping, the density is 2 crashes per road-km. A reciprocal edge representing the same street adds
      no length.
- [x] **A zone with 90 observed street meters at UTCI 10, 10 at UTCI 30, and 20 unobserved meters.** The pooled
      mean is 12, with 100 of 120 m observed. A piece on the other side of the neighborhood boundary
      contributes only to its own zone. A zone with zero valid length has a missing mean.

### Test suite and benchmarks

- [x] Run analytical, schema and adapter tests in CI. Add generated partition tests for conservation and test
      that inputs remain unmodified.
      *Done:* generated tests in `tests/test_properties.py` (Hypothesis).
- [x] Compare vector results against Tobler with source-area allocation for extensive values, equivalent
      missing-value handling, and the same denominator for shares. Test the raster adapter against
      exactextract alongside independent hand-calculated fixtures.
      *Done:* `tests/test_tobler.py` (Tobler's `allocate_total=False` is urbanweave's source-area allocation;
      its intensive results are single precision). Raster results are compared with exactextract and
      rasterstats.
- [ ] Run large benchmarks separately from the regular suite. For the NYC crash and land-cover runs, record
      dataset and CRS, engine versions, hardware, candidate counts, windows or bytes read, wall time, peak
      memory and result checks. Use the measurements to prioritize further optimization.
      *Partly done:* `tools/benchmark.py` records these fields on synthetic stand-ins: 500,000 points onto H3
      resolution 9 over NYC match in 0.85 s. The real NYC crash and land-cover datasets are still to be wired
      in.
