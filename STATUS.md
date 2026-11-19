# Status against PLAN.md

As of 2026-11-19. UrbanTrace and Curio were only read: their code is copied into `tests/legacy/`
at the revisions recorded there, and nothing in either repository was changed. Steps that must
happen inside those repositories are marked **in the consumer**: urbanweave provides what they call.

Tests: 111 in the regular suite (`pytest -q`), plus the Milan comparison (`-m slow`). They pass on
Python 3.13 with current releases, and on Python 3.11 with the lowest versions pyproject.toml allows
(NumPy 1.26, pandas 2.2, Shapely 2.0.4, pyproj 3.6, GeoPandas 1.0, h3 4.1, rasterio 1.4.0,
exactextract 0.2.0, OSMnx 2.0.0). The wheel installs and imports with no extras.

## 0. Baselines and contracts

- [x] Revisions recorded: `tests/legacy/urbantrace/REVISION`, `tests/legacy/curio/REVISION`.
- [x] Inventory of UrbanTrace's catalog and old/new comparison: `tools/urbantrace_corpus.py`, results in
      `reports/urbantrace_corpus.md` : 121 datasets inventoried; 319
      operator cases compared with every difference named (UTM measurement, invalid sources excluded,
      nearest ties or degrees, H3 index lookup), 0 unexplained, 0 errors; 15 refused with the reason
      (3 datasets with corrupt or mislabelled coordinates, on which legacy crashed or ran on nonsense);
      38 skipped for size (over 15 MB, or extents over 60,000 resolution-8 cells), to run separately.
- [x] Old outputs captured by running the copied legacy operators in the tests (grid-only, polygon,
      point and line zoning, zone values painted back onto cells): `tests/test_legacy_urbantrace.py`.
      Multivariate `grid`/`zones`/`both` responses are composed of these paths; their HTTP shape lives
      in UrbanTrace and is **in the consumer**.
- [x] Legacy paths classified, with named changes (`urbanweave.compat.urbantrace.CHANGES`): H3-to-point
      is sampling, H3-to-line a length overlay; legacy `SumZoning` on line zones is target-normalized and
      kept as `target_normalized_sum`; `BinaryContainment` on MultiPoints has no equivalent (refused with
      the reason).
- [x] Minimum versions confirmed in CI (`.github/workflows/ci.yml`: current, lowest, core only).
- [x] Analytical fixtures with tolerances: 1e-9 for projected fixtures; 1e-6 for allocation flags
      after reprojection (documented in `matching.ALLOCATION_TOLERANCE`); 1e-7 where exactextract's
      single-precision coverage fractions are summed; 2e-3 for EPSG:3857-vs-UTM comparisons with legacy.

## 1. Vector and H3 core

- [x] 1.1 Package, `src/` layout, extras (`raster`, `osm`, `dev`); ID rule, CRS and geometry checks,
      excluded sources reported by cause, invalid targets refused; H3 kept as cell IDs with
      center-based extent selection; points outside the support unmatched.
- [x] 1.2 `contain`, `representative_point`, `centroid`, `nearest` (+ `nearest_segment`, `nearest_node`),
      `within_distance`, `area_overlap`, `length_weighted`, `largest_overlap`, `polygon_to_lines`,
      `gaussian`, `sample`. Topology in the targets' CRS, measurement in one projected CRS per step
      (explicit or local UTM; polar, antimeridian and over-wide extents refused).
- [x] 1.3 Reductions, value-kind and quantity checks, exact integer sums with overflow reports,
      registry generated from the dispatch tables (parity tested for every method and geometry),
      composable reports with bounded ID samples.
- [x] Exit: points → H3 → zones by polygon, point and line from the public API; ported kernel tests;
      shuffled rows give the same results.

## 2. UrbanTrace cutover — **in the consumer**

- [x] The adapter UrbanTrace would call: `urbanweave.compat.urbantrace.run` (legacy operator IDs and
      column names, legacy wire units, legacy basis), `operators_payload()` for `/api/operators`, and
      `geometry_constraints()` from the registry.
- [x] Old/new comparisons with named explanations (tests and the corpus tool).
- [ ] Switching `main.py`, `integration_engine.py`, `IntegrationNode.jsx` and the copilot fallbacks,
      pinning the prerelease, the fallback switch and the rollback smoke test: changes inside UrbanTrace.

## 3. Zonal statistics and Curio

- [x] 3.1 `read_raster` (file, dataset, or array with transform, CRS and mask; per-band nodata, scale,
      offset, value kind, units; ownership), `zonal_stats` with `cell_coverage` (exactextract) and
      `cell_center`; north-up only, geographic exact weighting refused; coverage and valid coverage per
      band; streaming accumulators merged across windows, equal results for any window size; zones
      batched so memory is bounded (`tools/benchmark.py raster`).
- [x] 3.2 Drop-in functions for the nodes: `urbanweave.compat.curio.uhvi_zonal_mean` and
      `utci_zonal_mean`, equal to Curio's on synthetic rasters and on the Milan sample dataflow
      (0.9 s against minutes for the legacy UHVI function on 6,085 polygons).
- [ ] Enabling them in Curio's UHVI and Weather packages: **in the consumer**, and an owner decision,
      since urbanweave would join the libraries Curio's node code may import.

## 4. Plans and street workflows

- [x] 4.1 `Plan.from_json`, preflight (version, IDs, forward and unknown references, targets, methods
      and parameters, reductions, duplicate names, declared value kinds and units), content-addressed
      cache with request-key resolutions, atomic manifests, `replay` verifying fingerprints and engine
      versions and naming every changed, missing or unavailable artifact; in-memory sources supplied
      again and verified.
- [x] 4.2 Physical street segments and intersections from GraphML (no network in tests), `nearest_segment`,
      per-overlap-length density, shared-boundary ownership, `split_lines`, `along_lines` with
      cell-boundary ownership, `reduce` with `ratio_of_sums`; both worked plans run from their JSON in
      `examples/` and are checked against direct calculations.
- [ ] UrbanTrace plan import/export: **in the consumer**.

## 5. Later

Not started, as PLAN.md gates them on consumer use: whole-grid statistics for Rasterization,
rasterization and resampling, A5, interpolation, other targets.

## Benchmarks (synthetic stand-ins, this machine)

- 500,000 points onto 7,434 H3 resolution-9 cells over NYC: match 0.85 s, aggregate 0.09 s.
- Land-cover shares, 8,000 × 8,000 1 m tiled GeoTIFF, 500 zones: 4.3 s, 0.54 GB peak resident memory
  (1.8 GB before zones were batched).
