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
| Dasymetric, January 2013 as the prior | 5.1% | 0.995 | 6.7% |
| Areal weighting (spread by area) | 35.8% | 0.736 | 48.3% |

The notebook is saved with its outputs, so it reads without the data.

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
```

`prepare.py` downloads TLC's taxi zones, samples 2 million pickups from January and from July 2013,
and counts pickups per zone for July 2016, 2019 and 2021 (`--months` picks others).
