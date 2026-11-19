"""Builds the small inputs of the example plans in examples/data/ (UTM zone 18N, metres).

    python examples/make_example_data.py

- street_graph.graphml: the street graph of tests/fixtures/make_street_graph.py.
- neighborhoods.geojson: "west" (x < 1000) and "east" (x >= 1000), split along North St, which lies
  on their shared boundary, so the boundary rule decides which zone counts its length.
- crashes.geojson: four crashes beside First St between A and B, one beside B–C, one 200 m from any
  street, with persons_injured.
- utci.tif: 10 m cells of UTCI rising west to east (25 °C at x = 0 to 36 °C at x = 2200), with a
  nodata strip 50 m wide at x 400–450.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

X0, Y0 = 500_000.0, 4_500_000.0
CRS = "EPSG:32618"
HERE = Path(__file__).parent / "data"


def main():
    HERE.mkdir(exist_ok=True)
    zones = gpd.GeoDataFrame({"target_id": ["west", "east"], "name": ["West Side", "East Side"]},
                             geometry=[box(X0 - 100, Y0 - 600, X0 + 1000, Y0 + 600), box(X0 + 1000, Y0 - 600, X0 + 2100, Y0 + 600)],
                             crs=CRS)
    zones.to_file(HERE / "neighborhoods.geojson", driver="GeoJSON")
    pts = [(100, 3), (300, -2), (600, 1), (900, 0), (1500, 4), (500, -200)]
    crashes = gpd.GeoDataFrame({"crash_id": [f"c{i}" for i in range(len(pts))], "persons_injured": [1, 0, 2, 1, 3, 1]},
                               geometry=[Point(X0 + x, Y0 + y) for x, y in pts], crs=CRS)
    crashes.to_file(HERE / "crashes.geojson", driver="GeoJSON")
    cell = 10.0
    west, north = X0 - 100, Y0 + 600
    cols, rows = int(2200 / cell), int(1200 / cell)
    xs = west + (np.arange(cols) + 0.5) * cell - X0
    utci = np.tile(25 + 11 * (xs + 100) / 2200, (rows, 1)).astype("float32")
    utci[:, (xs >= 400) & (xs < 450)] = -9999
    with rasterio.open(HERE / "utci.tif", "w", driver="GTiff", height=rows, width=cols, count=1, dtype="float32",
                       crs=CRS, transform=from_origin(west, north, cell, cell), nodata=-9999) as ds:
        ds.write(utci, 1)
        ds.set_band_description(1, "utci")
        ds.update_tags(1, units="degC")


if __name__ == "__main__":
    main()
    print(HERE)
