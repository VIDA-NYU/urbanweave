# NYC taxi pickups: from zone counts back to city blocks

Until 2015, NYC's Taxi and Limousine Commission published every yellow-taxi trip with its pickup and
drop-off coordinates; the records published for 2016 onward give only one of 263 taxi zones. This
example recovers a fine-grained estimate for the later years by **dasymetric disaggregation**: the
2013 coordinates show where, inside each zone, taxis pick people up, and each later zone total is
spread the same way. With urbanweave it is four `match`/`aggregate` calls.

[`nyc_taxi_dasymetric.ipynb`](nyc_taxi_dasymetric.ipynb) builds the method, tests it on July 2013
(rebuilt from its zone counts and compared with its true locations), and applies it to July 2016,
2019 and 2021. Rebuilding July 2013 per H3 cell (resolution 10, about a city block):

| | Trips in the wrong cell | Correlation with the truth | Error in the busiest 1% of cells |
|---|---|---|---|
| Dasymetric, January 2013 as the prior | 5.1% | 0.995 | 6.8% |
| Areal weighting (spread by area) | 35.8% | 0.736 | 48.3% |

The notebook is saved with its outputs, so it reads without the data.

## Ten years, down to the streets

[`nyc_taxi_over_time.ipynb`](nyc_taxi_over_time.ipynb) spreads every month from January 2016 to
December 2025 (120 months, 655 million trips) with one prior: January and July 2013 pooled, 4 million
pickups. `uw.dasymetric(..., total=[...months])` places all 120 months in one call (about 20 s), since
the matching is shared. It then shares each Manhattan cell's estimate among the OSM street segments
crossing it, in proportion to the 2013 pickups snapped to each segment (`nearest_segment`, 40 m).
Tested on July 2013, per street segment:

| | Trips on the wrong segment | Correlation with the truth |
|---|---|---|
| Cells from zone totals, streets by the 2013 prior | 5.7% | 0.988 |
| Cells from zone totals, streets by length | 23.3% | 0.857 |
| True cells, streets by length | 22.8% | 0.865 |

Sharing a cell by street length is wrong by a quarter even when the cells are exact: taxis stop on the
avenues, not evenly along every street. The notebook has monthly series citywide and by borough
(COVID-19, the 2019 congestion surcharge, the 2025 congestion pricing), a map of Manhattan for every
year, maps of each zone's change in share, pickups per 100 m of street per day in 2025, and each
avenue's trajectory. A last section adds Uber, Lyft, Via and Juno from TLC's for-hire-vehicle records
(`prepare_fhv.py`) to ask where yellow's trips went: in Manhattan and at the airports the apps replaced
yellow cabs nearly trip for trip, while elsewhere they grew a market yellow never served; COVID-19 then
halved yellow's share again, and 2025 is the first year it rose. Within a zone the placement stays 2013's, so change over time is real only at the
zone level; the notebook says so where it matters. It writes
`results/pickups_by_borough_monthly.csv`, `results/streets_pickups_per_100m_day.csv`,
`results/yellow_and_apps_monthly.csv` and `results/yellow_share_by_area_monthly.csv`, plus the full
cell × month and segment × year estimates into `data/` (`estimates_h3r10_monthly.parquet`,
`estimates_streets_yearly.parquet`).

`compare_priors.py` repeats the July 2013 test with `uw.dasymetric` and other priors: the points of
interest of the CRIF draft (hotels, businesses, common places), alone, combined with CRIF's weighting
rule (fitted on January), and blended with the historical prior, at H3 resolutions 8 to 10. Results
are in `results/priors_comparison_res<R>.md`.

## Running it

The data is not in the repository. You need:

- the 2013 yellow-taxi trip data with coordinates (the FOIL release: `trip_data_1.csv` …
  `trip_data_12.csv`, from [Chris Whong's FOIL request](https://chriswhong.com/open-data/foil_nyc_taxi/)
  or the NYC TLC trip record archive);
- TLC's yellow-taxi Parquet files for the later months
  ([TLC trip record data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)), named
  `yellow_tripdata_YYYY-MM.parquet`.

```bash
uv pip install --python .venv -e '.[raster,osm,tutorials,examples]'
.venv/bin/python examples/nyc_taxi/prepare.py \
    --foil2013 /path/to/FOIL2013/Tripdata_2013 \
    --zone-months /path/to/tlc_yellow_2016_on \
    --out examples/nyc_taxi/data                       # about 10 s with DuckDB; 52 MB
.venv/bin/jupyter lab examples/nyc_taxi/nyc_taxi_dasymetric.ipynb   # about a minute to run

# The ten-year notebook also needs every month's zone counts and Manhattan's streets (OSM):
.venv/bin/python examples/nyc_taxi/prepare_series.py \
    --zone-months /path/to/tlc_yellow_2016_on --out examples/nyc_taxi/data   # about 20 s, plus the OSM download
# Its ride-hail section also needs TLC's for-hire-vehicle files (fhvhv_tripdata_2019-02 on, about
# 40 GB; fhv_tripdata_2016-01 to 2019-01, about 5 GB), downloaded once from the TLC trip record page:
.venv/bin/python examples/nyc_taxi/prepare_fhv.py \
    --fhvhv /path/to/tlc_fhvhv --fhv /path/to/tlc_fhv --out examples/nyc_taxi/data
.venv/bin/jupyter lab examples/nyc_taxi/nyc_taxi_over_time.ipynb    # about a minute to run
```

`prepare.py` downloads TLC's taxi zones, samples 2 million pickups from January and from July 2013,
and counts pickups per zone for July 2016, 2019 and 2021 (`--months` picks others).
