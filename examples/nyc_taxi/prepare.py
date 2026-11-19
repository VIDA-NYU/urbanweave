"""Prepare the inputs of the NYC taxi dasymetric example from the TLC trip records.

    python examples/nyc_taxi/prepare.py --foil2013 ~/data/FOIL2013/Tripdata_2013 \\
        --zone-months ~/data/tlc_yellow_2016_on --out examples/nyc_taxi/data

Writes, into --out:

- ``taxi_zones/``: TLC's 263 taxi zones (downloaded once from TLC's public site).
- ``pickups_2013-01.parquet`` and ``pickups_2013-07.parquet``: pickup coordinates (longitude,
  latitude) of a reproducible random sample of yellow-taxi trips from the 2013 FOIL trip data,
  keeping only coordinates inside a box around NYC (records at (0, 0) and other bad GPS fixes go).
- ``zone_counts.csv``: yellow-taxi pickups per taxi zone (``PULocationID``) for each month of the
  TLC Parquet files given (2016 onwards, when trip records carry zones instead of coordinates).
- ``poi/``: the point-of-interest priors of the CRIF draft, from NYC Open Data: ``hotels.csv``
  (Hotels Properties Citywide, ``tjus-cn27``: one row per hotel unit per tax year),
  ``businesses.csv`` (``d8ic-tk4f``) and ``commonplace.csv`` (CommonPlace, ``t95h-5fsr``).

DuckDB reads the large files (about 15 million trips a month) in seconds; the notebook then needs
only these small files.
"""

from __future__ import annotations

import argparse
import io
import re
import ssl
import urllib.request
import zipfile
from pathlib import Path

import duckdb

ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip"
POI = {  # NYC Open Data (Socrata) dataset IDs
    "hotels.csv": "tjus-cn27",
    "businesses.csv": "d8ic-tk4f",
    "commonplace.csv": "t95h-5fsr",
}
NYC_BOX = (-74.30, 40.45, -73.65, 40.95)  # lon/lat bounds that contain the five boroughs


def _open(url: str, timeout: int):
    """urlopen with certifi's certificates when available (some Python builds lack system ones)."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    return urllib.request.urlopen(url, timeout=timeout, context=ctx)


def zones(out: Path) -> Path:
    target = out / "taxi_zones"
    if not list(target.glob("**/taxi_zones.shp")):
        with _open(ZONES_URL, 60) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(target)
    return next(target.glob("**/taxi_zones.shp"))


def poi(out: Path) -> None:
    folder = out / "poi"
    folder.mkdir(exist_ok=True)
    for name, ident in POI.items():
        path = folder / name
        if not path.exists():
            url = f"https://data.cityofnewyork.us/resource/{ident}.csv?$limit=500000"
            with _open(url, 120) as r:
                path.write_bytes(r.read())
        print(f"poi/{name}:", sum(1 for _ in path.open()) - 1, "rows")


def pickups(con, csv: Path, n: int, seed: int) -> "duckdb.DuckDBPyRelation":
    x0, y0, x1, y1 = NYC_BOX
    return con.sql(f"""
        SELECT lon, lat FROM (
            SELECT pickup_longitude AS lon, pickup_latitude AS lat
            FROM read_csv('{csv}', header = true, normalize_names = true)
            WHERE pickup_longitude BETWEEN {x0} AND {x1} AND pickup_latitude BETWEEN {y0} AND {y1}
        ) USING SAMPLE reservoir({n} ROWS) REPEATABLE ({seed})""")


def zone_counts(con, files: list[Path]) -> "duckdb.DuckDBPyRelation":
    parts = []
    for f in files:
        month = re.search(r"(\d{4}-\d{2})", f.name).group(1)
        parts.append(f"SELECT '{month}' AS month, PULocationID AS LocationID, count(*) AS trips "
                     f"FROM '{f}' GROUP BY PULocationID")
    return con.sql(" UNION ALL ".join(parts) + " ORDER BY month, LocationID")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--foil2013", type=Path, required=True, help="folder with trip_data_<month>.csv (2013)")
    ap.add_argument("--zone-months", type=Path, required=True, help="folder with yellow_tripdata_YYYY-MM.parquet")
    ap.add_argument("--months", nargs="*", default=["2016-07", "2019-07", "2021-07"],
                    help="months whose zone counts to extract (default: July 2016, 2019, 2021)")
    ap.add_argument("--sample", type=int, default=2_000_000, help="pickups sampled per 2013 month")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    print("zones:", zones(args.out))
    poi(args.out)
    for month in (1, 7):
        rel = pickups(con, args.foil2013 / f"trip_data_{month}.csv", args.sample, seed=month)
        path = args.out / f"pickups_2013-{month:02d}.parquet"
        rel.write_parquet(str(path))
        print(path.name, con.execute(f"SELECT count(*) FROM '{path}'").fetchall()[0][0], "pickups")
    files = [args.zone_months / f"yellow_tripdata_{m}.parquet" for m in args.months]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"Missing: {', '.join(missing)}")
    zone_counts(con, files).write_csv(str(args.out / "zone_counts.csv"))
    print("zone_counts.csv:", con.execute(f"SELECT month, sum(trips) FROM '{args.out / 'zone_counts.csv'}' "
                                          "GROUP BY month ORDER BY month").fetchall())


if __name__ == "__main__":
    main()
