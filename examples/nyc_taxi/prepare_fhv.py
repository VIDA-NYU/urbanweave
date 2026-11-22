"""Prepare ride-hail (Uber, Lyft, Via, Juno) pickups per taxi zone and month, 2016-2025, from TLC.

    python examples/nyc_taxi/prepare_fhv.py --fhvhv ~/data/tlc_fhvhv \\
        --fhv ~/data/tlc_fhv --out examples/nyc_taxi/data

TLC publishes for-hire-vehicle (FHV) trip records by zone, never with coordinates. Download them once
from the TLC trip record page (https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page):

- ``fhvhv_tripdata_YYYY-MM.parquet`` (high-volume FHV, February 2019 on, about 500 MB a month) into
  --fhvhv;
- ``fhv_tripdata_YYYY-MM.parquet`` (all FHV bases, here January 2016 to January 2019) into --fhv.

Writes, into --out:

- ``fhv_zone_counts_monthly.csv``: ``month, company, LocationID, trips``. ``LocationID`` is empty for
  trips whose record has no pickup zone (Juno before 2019).
  - From February 2019, the high-volume records name the company: ``HV0003`` Uber, ``HV0005`` Lyft,
    ``HV0004`` Via, ``HV0002`` Juno.
  - Before that, the FHV records name only the dispatching base. Each base is given the company it
    carries most trips for in the 2019+ records (stray records under another company are reported), plus Uber's base B02598
    ("Hinter"), which closed before 2019 and is named as Uber's in the 2014 FOIL release. Black-car and
    livery bases, which mostly report no zone, are left out.
  A trip counts in its file's month only if its pickup time falls in that month.
- ``tlc_monthly_report.csv``: TLC's monthly industry indicators (trips per day by license class),
  for checking the totals.

DuckDB reads only the three columns it needs from each file: about a minute for all of them.
"""

from __future__ import annotations

import argparse
import re
import ssl
import urllib.request
from pathlib import Path

import duckdb

REPORT = "https://www.nyc.gov/assets/tlc/downloads/csv/data_reports_monthly.csv"
COMPANY = {"HV0003": "Uber", "HV0005": "Lyft", "HV0004": "Via", "HV0002": "Juno"}
EXTRA_BASES = {"B02598": "HV0003"}  # Uber's "Hinter" base, closed before 2019


def _month(f: Path) -> str:
    return re.search(r"(\d{4}-\d{2})", f.name).group(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fhvhv", type=Path, required=True, help="folder with fhvhv_tripdata_YYYY-MM.parquet")
    ap.add_argument("--fhv", type=Path, required=True, help="folder with fhv_tripdata_YYYY-MM.parquet")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--first", default="2016-01")
    ap.add_argument("--last", default="2025-12")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    hv = sorted(f for f in args.fhvhv.glob("fhvhv_tripdata_*.parquet") if "2019-02" <= _month(f) <= args.last)
    old = sorted(f for f in args.fhv.glob("fhv_tripdata_*.parquet") if args.first <= _month(f) < "2019-02")
    if not hv or not old:
        raise SystemExit("No fhvhv_tripdata_*.parquet or fhv_tripdata_*.parquet files found in the folders given.")
    con = duckdb.connect()
    case = "CASE " + " ".join(f"WHEN lic = '{k}' THEN '{v}'" for k, v in COMPANY.items()) + " END"

    # Base -> license, from every 2019+ month: each base goes to the company it carries most trips for
    # (a base's trips under another company are a handful of stray records, reported here).
    con.sql(f"""CREATE TABLE base_lic AS SELECT upper(trim(dispatching_base_num)) AS base, hvfhs_license_num AS lic,
                count(*) AS n FROM read_parquet({[str(f) for f in hv]}) GROUP BY 1, 2""")
    stray = con.sql("""SELECT base, lic, n FROM base_lic QUALIFY row_number() OVER (PARTITION BY base ORDER BY n DESC) > 1""").fetchall()
    if stray:
        print("bases with stray records under another company (base, license, trips):", stray)
    con.sql("""CREATE TABLE bases AS SELECT base, lic FROM base_lic
               QUALIFY row_number() OVER (PARTITION BY base ORDER BY n DESC) = 1""")
    for b, lic in EXTRA_BASES.items():
        con.execute("INSERT INTO bases SELECT ?, ? WHERE ? NOT IN (SELECT base FROM bases)", [b, lic, b])
    print("bases:", con.sql("SELECT lic, count(*) FROM bases GROUP BY 1 ORDER BY 1").fetchall())

    parts = []
    for f in old:
        m = _month(f)
        parts.append(f"""
            SELECT '{m}' AS month, {case} AS company, CAST(t.PUlocationID AS INTEGER) AS LocationID, count(*) AS trips
            FROM (SELECT upper(trim(dispatching_base_num)) AS base, PUlocationID, pickup_datetime FROM '{f}') t
                 JOIN bases USING (base)
            WHERE strftime(t.pickup_datetime, '%Y-%m') = '{m}' GROUP BY ALL""")
    for f in hv:
        m = _month(f)
        parts.append(f"""
            SELECT '{m}' AS month, {case} AS company, CAST(PULocationID AS INTEGER) AS LocationID, count(*) AS trips
            FROM (SELECT hvfhs_license_num AS lic, PULocationID, pickup_datetime FROM '{f}')
            WHERE strftime(pickup_datetime, '%Y-%m') = '{m}' GROUP BY ALL""")
    target = args.out / "fhv_zone_counts_monthly.csv"
    con.sql(" UNION ALL ".join(parts) + " ORDER BY month, company, LocationID").write_csv(str(target))
    print(target.name, con.sql(f"""SELECT company, sum(trips), sum(trips) FILTER (WHERE LocationID IS NULL) AS no_zone
                                   FROM '{target}' GROUP BY 1 ORDER BY 2 DESC""").fetchall())

    report = args.out / "tlc_monthly_report.csv"
    if not report.exists():
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(REPORT, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            report.write_bytes(r.read())
    print(report.name, "ready")


if __name__ == "__main__":
    main()
