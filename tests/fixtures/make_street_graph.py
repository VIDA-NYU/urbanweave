"""Builds tests/fixtures/street_graph.graphml: a tiny OSMnx-style street graph in UTM 18N.

    python tests/fixtures/make_street_graph.py

Nodes (x, y offsets from 500 000, 4 500 000 m): A(0,0) B(1000,0) C(2000,0) D(1000,500) E(1000,-500).
- A–B, OSM way 1, two-way: two reciprocal edges that are one physical segment.
- A–B, OSM way 6, a second, curved street between the same nodes (a parallel edge).
- B–C, OSM way 2, two-way.
- B→D, OSM way 3, one-way.
- B→E and E→B, OSM ways 4 and 5: separate carriageways, two physical segments.
B has 6 incident physical segments; A, C, D and E have fewer than 3.
"""

from pathlib import Path

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

X0, Y0 = 500_000.0, 4_500_000.0
P = {"A": (0, 0), "B": (1000, 0), "C": (2000, 0), "D": (1000, 500), "E": (1000, -500)}
ID = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}


def xy(n):
    return (X0 + P[n][0], Y0 + P[n][1])


def build() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph(crs="EPSG:32618")
    for n, i in ID.items():
        x, y = xy(n)
        G.add_node(i, x=x, y=y, street_count=0)

    def edge(a, b, key, osmid, name, oneway, geom=None, highway="residential"):
        g = geom or LineString([xy(a), xy(b)])
        G.add_edge(ID[a], ID[b], key=key, osmid=osmid, name=name, highway=highway, oneway=oneway,
                   reversed=False, length=g.length, geometry=g)

    edge("A", "B", 0, 1, "First St", False)
    edge("B", "A", 0, 1, "First St", False, LineString([xy("B"), xy("A")]))
    curve = LineString([xy("A"), (X0 + 500, Y0 + 200), xy("B")])
    edge("A", "B", 1, 6, "Curve Ave", True, curve)
    edge("B", "C", 0, 2, "First St", False)
    edge("C", "B", 0, 2, "First St", False, LineString([xy("C"), xy("B")]))
    edge("B", "D", 0, 3, "North St", True)
    edge("B", "E", 0, 4, "South Blvd", True, LineString([xy("B"), (X0 + 1005, Y0 - 250), xy("E")]))
    edge("E", "B", 0, 5, "South Blvd", True, LineString([xy("E"), (X0 + 995, Y0 - 250), xy("B")]))
    return G


if __name__ == "__main__":
    out = Path(__file__).with_name("street_graph.graphml")
    ox.save_graphml(build(), out)
    print(out)
