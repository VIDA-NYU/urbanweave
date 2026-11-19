# UrbanTrace corpus: inventory and old/new comparison

UrbanTrace revision `6606a0856a63b4c0682c9f940f3c6c7189f31ae8`; H3 resolution 8; datasets up to 15.0 MB, first 20000 features.

| | count |
|---|---|
| urbantrace_revision | 6606a0856a63b4c0682c9f940f3c6c7189f31ae8 |
| datasets | 121 |
| cases_compared | 319 |
| cases_skipped | 38 |
| cases_refused | 15 |
| cases_legacy_failed | 0 |
| cases_error | 0 |
| cases_unexplained | 0 |

## Unexplained or failed cases

None.

## Refused by urbanweave, with the reason

- nyc_bridge_strike_data / BinaryContainment / SumAggregation (legacy: H3FailedError: ): UnsupportedError: The study area spans 148.1° of longitude, wider than one UTM zone can measure accurately (12° at most). Pass an explicit projected CRS (crs=), equal-area when areas are compared.
- nyc_bridge_strike_data / BinaryContainment / DensityAggregation (legacy: H3FailedError: ): UnsupportedError: The study area spans 148.1° of longitude, wider than one UTM zone can measure accurately (12° at most). Pass an explicit projected CRS (crs=), equal-area when areas are compared.
- nyc_bridge_strike_data / BinaryCentroidContainment / SumAggregation (legacy: H3FailedError: ): UnsupportedError: The study area spans 148.1° of longitude, wider than one UTM zone can measure accurately (12° at most). Pass an explicit projected CRS (crs=), equal-area when areas are compared.
- nyc_bridge_strike_data / NearestAssignment / SumAggregation (legacy: H3FailedError: ): UnsupportedError: The study area spans 148.1° of longitude, wider than one UTM zone can measure accurately (12° at most). Pass an explicit projected CRS (crs=), equal-area when areas are compared.
- nyc_bridge_strike_data / GaussianKernel / SumAggregation (legacy: H3FailedError: ): UnsupportedError: The study area spans 148.1° of longitude, wider than one UTM zone can measure accurately (12° at most). Pass an explicit projected CRS (crs=), equal-area when areas are compared.
- raised_crosswalk_locations / BinaryContainment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.05256e+06, y up to 267137), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- raised_crosswalk_locations / BinaryContainment / DensityAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.05256e+06, y up to 267137), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- raised_crosswalk_locations / BinaryCentroidContainment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.05256e+06, y up to 267137), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- raised_crosswalk_locations / NearestAssignment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.05256e+06, y up to 267137), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- raised_crosswalk_locations / GaussianKernel / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.05256e+06, y up to 267137), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- street_closures_due_to_construction_activities_by_intersection / BinaryContainment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.0526e+06, y up to 267762), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- street_closures_due_to_construction_activities_by_intersection / BinaryContainment / DensityAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.0526e+06, y up to 267762), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- street_closures_due_to_construction_activities_by_intersection / BinaryCentroidContainment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.0526e+06, y up to 267762), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- street_closures_due_to_construction_activities_by_intersection / NearestAssignment / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.0526e+06, y up to 267762), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).
- street_closures_due_to_construction_activities_by_intersection / GaussianKernel / SumAggregation (legacy: ran): InputError: Every source has coordinates outside longitude -180..180 and latitude -90..90 (x up to 1.0526e+06, y up to 267762), yet the CRS EPSG:4326 is geographic: the CRS is probably mislabelled. Set the right one with GeoDataFrame.set_crs(..., allow_override=True).

## Failed in legacy only

None.

## Skipped

- above the size limit: 31
- extent above 60000 cells: 7

## Named differences

- h3_index_lookup: in 1 cases
- invalid_sources_excluded: in 18 cases
- nearest_ties_or_degrees: in 9 cases
- utm_measurement: in 80 cases
