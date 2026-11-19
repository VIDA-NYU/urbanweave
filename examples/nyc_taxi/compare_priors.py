"""Which prior recovers taxi pickups best? July 2013 rebuilt from its zone counts under each prior.

    python examples/nyc_taxi/compare_priors.py [--data examples/nyc_taxi/data] [--resolution 10]

Ground truth: the July 2013 pickup sample, counted per H3 cell. Each method sees only July's pickups
per taxi zone and spreads them over the cells with :func:`urbanweave.dasymetric`; the estimate is
then compared with the truth, citywide and in Manhattan (CRIF's study area).

Priors:

- *areal*: no prior; each zone's total spread by area.
- *hotels*, *businesses*, *common places*: the CRIF draft's points of interest, alone and combined.
  Hotels are weighted by units (one row per hotel unit, tax year 2021, the earliest published);
  businesses are deduplicated by name, as in CRIF.
- *CRIF weights*: the three POI layers with min-max normalization and CRIF's weighting rule
  (Pearson correlation of each layer with fine-grained pickups, normalized to sum to 1), with the
  correlations measured on **January** 2013, not on the July test month.
- *historical*: January 2013 pickups (six months before the test).
- *blend α*: historical with weight α, POI layers (CRIF weights) sharing 1 − α. Reported for several α
  as a sensitivity table, not tuned on July.

Metrics per cell: share of trips in the wrong cell (½ Σ|truth − estimate| / Σ truth), Pearson
correlation, error in the busiest 1% of cells, and the CRIF draft's MAE, RMSE and R².
Writes ``results/priors_comparison_res<R>.csv`` and ``.md`` next to this script.
"""

from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

import urbanweave as uw

HERE = Path(__file__).parent
NYC_BOX = (-74.30, 40.45, -73.65, 40.95)  # the box prepare.py keeps trips in


def in_nyc(points: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    """Points inside the NYC box; a few records carry coordinates far away (0, 0 or swapped)."""
    x0, y0, x1, y1 = NYC_BOX
    keep = points.geometry.x.between(x0, x1) & points.geometry.y.between(y0, y1)
    print(f"  {name}: {len(points):,} points, {int((~keep).sum())} outside NYC dropped")
    return points[keep].reset_index(drop=True)


def load(data: Path, resolution: int):
    zones = gpd.read_file(next((data / "taxi_zones").glob("**/taxi_zones.shp")))[["LocationID", "zone", "borough", "geometry"]]
    zones = zones.rename(columns={"LocationID": "target_id"})
    cells = uw.targets.h3_cells(zones, resolution, cover="geometry")
    jan = uw.points_from_columns(pd.read_parquet(data / "pickups_2013-01.parquet"), lat="lat", lon="lon")
    jul = uw.points_from_columns(pd.read_parquet(data / "pickups_2013-07.parquet"), lat="lat", lon="lon")

    hotels = pd.read_csv(data / "poi" / "hotels.csv")
    year = int(hotels["taxyear"].min())
    hotels = hotels[hotels["taxyear"] == year].assign(units=1)
    hotels = uw.points_from_columns(hotels, lat="latitude", lon="longitude")
    shops = pd.read_csv(data / "poi" / "businesses.csv").drop_duplicates("business_name")
    shops = uw.points_from_columns(shops, lat="latitude", lon="longitude")
    places = pd.read_csv(data / "poi" / "commonplace.csv")
    places = gpd.GeoDataFrame(places.drop(columns="the_geom"), geometry=gpd.GeoSeries.from_wkt(places["the_geom"]), crs=4326)
    places = places[places.geometry.notna()].reset_index(drop=True)
    pois = {"hotels": in_nyc(hotels, "hotels"), "businesses": in_nyc(shops, "businesses"),
            "common places": in_nyc(places, "common places")}
    return zones, cells, jan, jul, pois, year


def per_cell(points, cells):
    return uw.aggregate(uw.match(points, cells, "contain"), None,
                        [uw.count(as_="n", fill_empty=0)]).set_index("target_id")["n"].astype(float)


def metrics(truth: pd.Series, est: pd.Series) -> dict:
    t = truth.astype(float)
    e = est.reindex(t.index).fillna(0.0).astype(float)
    busy = t >= t.quantile(0.99)
    d = t - e
    return {
        "wrong cell": (d.abs().sum() / t.sum()) / 2,
        "correlation": float(np.corrcoef(t, e)[0, 1]),
        "busiest 1% error": d[busy].abs().sum() / t[busy].sum(),
        "MAE": d.abs().mean(),
        "RMSE": float(np.sqrt((d ** 2).mean())),
        "R2": 1 - (d ** 2).sum() / ((t - t.mean()) ** 2).sum(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=HERE / "data")
    ap.add_argument("--resolution", type=int, default=10)
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore", category=UserWarning)

    t0 = time.time()
    zones, cells, jan, jul, pois, hotel_year = load(args.data, args.resolution)
    july_zones = uw.aggregate(uw.match(jul, zones, "contain"), None, [uw.count(as_="trips", fill_empty=0)])
    truth = per_cell(jul, cells)
    in_mn = uw.match(cells, zones[zones["borough"] == "Manhattan"], "centroid").pairs["source_id"].unique()

    # CRIF's weighting rule, measured on January (not on the July test month).
    jan_cells = per_cell(jan, cells)
    corr = {k: max(float(np.corrcoef(jan_cells, per_cell(v, cells).reindex(jan_cells.index).fillna(0))[0, 1]), 0.0)
            for k, v in pois.items()}
    crif_w = {k: v / sum(corr.values()) for k, v in corr.items()}
    print(f"loaded in {time.time() - t0:.0f} s; {len(cells):,} cells; CRIF weights from January:",
          {k: round(v, 2) for k, v in crif_w.items()}, f"(hotels: tax year {hotel_year})")

    hotels = (pois["hotels"], "units")
    poi_layers = {"hotels": hotels, "businesses": pois["businesses"], "common places": pois["common places"]}
    methods = {
        "areal (no prior)": None,
        "hotels": ({"hotels": hotels}, None, "share"),
        "businesses": ({"businesses": pois["businesses"]}, None, "share"),
        "common places": ({"common places": pois["common places"]}, None, "share"),
        "POIs, equal weights": (poi_layers, None, "share"),
        "POIs, CRIF weights (min-max)": (poi_layers, crif_w, "minmax"),
        "historical (Jan 2013)": ({"historical": jan}, None, "share"),
    }
    for a in (0.5, 0.75, 0.9):
        w = {"historical": a, **{k: (1 - a) * v for k, v in crif_w.items()}}
        methods[f"blend, α = {a:g}"] = ({"historical": jan, **poi_layers}, w, "share")

    rows = []
    for name, spec in methods.items():
        t = time.time()
        if spec is None:
            est = uw.aggregate(uw.match(july_zones, cells, "area_overlap"), None, [uw.sum("trips", as_="est", fill_empty=0)])
        else:
            layers, weights, norm = spec
            est = uw.dasymetric(july_zones, cells, layers, total="trips", weights=weights, normalize=norm, as_="est")
        e = est.set_index("target_id")["est"]
        secs = time.time() - t
        for area, idx in (("NYC", truth.index), ("Manhattan", pd.Index(in_mn))):
            rows.append({"method": name, "area": area, **metrics(truth.reindex(idx).fillna(0), e.reindex(idx)),
                         "seconds": secs})
        print(f"{name:32s} wrong cell NYC {rows[-2]['wrong cell']:.1%}  Manhattan {rows[-1]['wrong cell']:.1%}  ({secs:.1f} s)")

    out = pd.DataFrame(rows)
    res = HERE / "results"
    res.mkdir(exist_ok=True)
    stem = f"priors_comparison_res{args.resolution}"
    out.to_csv(res / f"{stem}.csv", index=False)
    fmt = out.copy()
    for c in ("wrong cell", "busiest 1% error"):
        fmt[c] = fmt[c].map("{:.1%}".format)
    for c in ("correlation", "R2"):
        fmt[c] = fmt[c].map("{:.3f}".format)
    for c in ("MAE", "RMSE"):
        fmt[c] = fmt[c].map("{:.1f}".format)
    fmt["seconds"] = fmt["seconds"].map("{:.1f}".format)
    header = (f"July 2013 pickups (2M-trip sample) rebuilt per H3 resolution-{args.resolution} cell from their taxi-zone "
              f"counts. CRIF weights from January 2013: " + ", ".join(f"{k} {v:.2f}" for k, v in crif_w.items()) +
              f". Hotels: tax year {hotel_year}, weighted by units.\n\n")
    (res / f"{stem}.md").write_text(header + fmt.to_markdown(index=False) + "\n")
    print(f"done in {time.time() - t0:.0f} s -> {res / (stem + '.md')}")


if __name__ == "__main__":
    main()
