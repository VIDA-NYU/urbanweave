"""Prepare the inputs of the taxi-over-time notebook: monthly zone counts and Manhattan's streets.

    python examples/nyc_taxi/prepare_series.py --zone-months ~/data/tlc_yellow_2016_on \\
        --out examples/nyc_taxi/data

Writes, into --out (next to what ``prepare.py`` writes; the notebook also needs its taxi zones and
2013 pickup samples):

- ``zone_counts_monthly.csv``: yellow-taxi pickups per taxi zone (``PULocationID``) for every
  ``yellow_tripdata_YYYY-MM.parquet`` in --zone-months (2016-01 to 2025-12 here: 120 months, about
  900 million trips). Each file holds a few trips stamped in other months or years (meter clock
  errors); a trip counts in its file's month only if its pickup time falls in that month, and the
  others are dropped and counted.
- ``manhattan_drive.graphml``: Manhattan's drivable street network from OpenStreetMap (OSMnx), saved
  once so that the notebook runs offline and on the same streets every time.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import duckdb


def zone_counts(con, files: list[Path]):
    parts = []
    for f in files:
        month = re.search(r"(\d{4}-\d{2})", f.name).group(1)
        parts.append(f"""
            SELECT '{month}' AS month, PULocationID AS LocationID,
                   count(*) FILTER (WHERE strftime(tpep_pickup_datetime, '%Y-%m') = '{month}') AS trips,
                   count(*) FILTER (WHERE strftime(tpep_pickup_datetime, '%Y-%m') <> '{month}'
                                    OR tpep_pickup_datetime IS NULL) AS dropped
            FROM '{f}' GROUP BY PULocationID""")
    return con.sql(" UNION ALL ".join(parts) + " ORDER BY month, LocationID")


def streets(out: Path, place: str) -> Path:
    path = out / "manhattan_drive.graphml"
    if not path.exists():
        import osmnx as ox
        ox.save_graphml(ox.graph_from_place(place, network_type="drive"), path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zone-months", type=Path, required=True, help="folder with yellow_tripdata_YYYY-MM.parquet")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--place", default="Manhattan, New York, USA", help="OSM place whose streets to fetch")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    files = sorted(args.zone_months.glob("yellow_tripdata_*.parquet"))
    if not files:
        raise SystemExit(f"No yellow_tripdata_YYYY-MM.parquet in {args.zone_months}")
    con = duckdb.connect()
    target = args.out / "zone_counts_monthly.csv"
    zone_counts(con, files).write_csv(str(target))
    kept, dropped, months = con.execute(
        f"SELECT sum(trips), sum(dropped), count(DISTINCT month) FROM '{target}'").fetchone()
    print(f"{target.name}: {months} months, {kept:,} trips kept, {dropped:,} stamped outside their file's month dropped")
    print("streets:", streets(args.out, args.place))


if __name__ == "__main__":
    main()
