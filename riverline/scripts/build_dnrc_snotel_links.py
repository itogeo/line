"""
Build dnrc_snotel_links.json — maps each DNRC gauge to its upstream SNOTEL stations.

Strategy:
  1. Load mt_basins.geojson (PFAF8 polygons + next_pfaf8 topology)
  2. For each DNRC gauge, find its containing PFAF8 basin via point-in-polygon
  3. BFS upstream through next_pfaf8 topology to collect all upstream basins
  4. Find SNOTEL stations inside those upstream basins
  5. Compute distance, sort, emit top MAX_SNOTEL per gauge

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/build_dnrc_snotel_links.py

Requires mt_basins.geojson to be rebuilt first (build_basins.py).

Output:
  riverline/site/data/dnrc_snotel_links.json
  Format: {"<dnrc_uuid>": [{"triplet", "name", "elevation_ft", "dist_km"}, ...], ...}
"""
import os
import json
import math
from collections import defaultdict
from pathlib import Path

_PROJ_DATA = "/Users/ianvandusen/anaconda3/envs/geodata/share/proj"
if os.path.isdir(_PROJ_DATA):
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA

import geopandas as gpd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "riverline" / "site" / "data"

MAX_SNOTEL = 8  # max stations per gauge in output


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_reverse_topo(basins_gdf):
    """Return {pfaf8: [pfaf8 codes that drain INTO it]} for BFS upstream traversal."""
    rev = defaultdict(list)
    for _, row in basins_gdf.iterrows():
        p = str(row["pfaf8"])
        n = str(row.get("next_pfaf8", "") or "")
        if n:
            rev[n].append(p)
    return dict(rev)


def bfs_upstream(start, reverse_topo):
    visited = set()
    queue = [start]
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for parent in reverse_topo.get(cur, []):
            if parent not in visited:
                queue.append(parent)
    return visited


def main():
    basins_path = DATA / "mt_basins.geojson"
    if not basins_path.exists():
        raise FileNotFoundError(f"mt_basins.geojson not found — run build_basins.py first: {basins_path}")

    print("Loading mt_basins.geojson …")
    basins = gpd.read_file(basins_path)
    print(f"  {len(basins)} PFAF8 basins")

    with open(DATA / "dnrc_gauges.json") as f:
        dnrc_fc = json.load(f)
    with open(DATA / "snotel_stations.json") as f:
        snotel_fc = json.load(f)

    dnrc_feats = dnrc_fc["features"]
    snotel_feats = snotel_fc["features"]
    print(f"  {len(dnrc_feats)} DNRC gauges, {len(snotel_feats)} SNOTEL stations")

    # Build GeoDataFrames
    dnrc_gdf = gpd.GeoDataFrame(
        [{"dnrc_id": f["properties"]["id"],
          "geometry": Point(f["geometry"]["coordinates"])}
         for f in dnrc_feats],
        crs="EPSG:4326",
    )
    snotel_rows = []
    for f in snotel_feats:
        p = f["properties"]
        coords = f["geometry"]["coordinates"]
        snotel_rows.append({
            "triplet": p["triplet"],
            "name": p["name"],
            "elevation_ft": p.get("elevation_ft", 0),
            "lon": coords[0],
            "lat": coords[1],
            "geometry": Point(coords),
        })
    snotel_gdf = gpd.GeoDataFrame(snotel_rows, crs="EPSG:4326")

    print("Spatial join: DNRC → basins …")
    dnrc_joined = gpd.sjoin(dnrc_gdf, basins[["pfaf8", "geometry"]], how="left", predicate="within")

    print("Spatial join: SNOTEL → basins …")
    snotel_joined = gpd.sjoin(snotel_gdf, basins[["pfaf8", "geometry"]], how="left", predicate="within")
    snotel_by_pfaf8 = defaultdict(list)
    for _, row in snotel_joined.iterrows():
        p = row.get("pfaf8")
        if p and str(p) != "nan":
            snotel_by_pfaf8[str(p)].append(row)

    print("Building reverse topology …")
    rev_topo = build_reverse_topo(basins)

    print(f"Computing upstream SNOTEL for {len(dnrc_joined)} DNRC gauges …")
    links = {}
    matched = 0
    for _, row in dnrc_joined.iterrows():
        dnrc_id = row["dnrc_id"]
        start_pfaf8 = row.get("pfaf8")
        if not start_pfaf8 or str(start_pfaf8) == "nan":
            links[dnrc_id] = []
            continue

        upstream = bfs_upstream(str(start_pfaf8), rev_topo)

        # Collect SNOTEL stations in all upstream basins
        candidates = []
        seen_triplets = set()
        for p in upstream:
            for s_row in snotel_by_pfaf8.get(p, []):
                t = s_row["triplet"]
                if t not in seen_triplets:
                    seen_triplets.add(t)
                    candidates.append(s_row)

        # Sort by distance from DNRC gauge
        dnrc_lon, dnrc_lat = row.geometry.x, row.geometry.y
        for s in candidates:
            s["dist_km"] = haversine_km(dnrc_lon, dnrc_lat, float(s["lon"]), float(s["lat"]))
        candidates.sort(key=lambda s: s["dist_km"])

        links[dnrc_id] = [
            {
                "triplet": s["triplet"],
                "name": s["name"],
                "elevation_ft": int(s["elevation_ft"] or 0),
                "dist_km": round(s["dist_km"], 1),
            }
            for s in candidates[:MAX_SNOTEL]
        ]
        if candidates:
            matched += 1

    total_links = sum(len(v) for v in links.values())
    print(f"\n  {matched}/{len(links)} DNRC gauges have upstream SNOTEL")
    print(f"  {total_links} total links")

    # Sample
    sample = [(k, v) for k, v in links.items() if v][:5]
    for dnrc_id, stations in sample:
        names = [s["name"] for s in stations[:3]]
        print(f"  {dnrc_id[:8]}… → {', '.join(names)}")

    out = DATA / "dnrc_snotel_links.json"
    with open(out, "w") as f:
        json.dump(links, f, separators=(",", ":"))
    print(f"\nWrote → {out}  ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
