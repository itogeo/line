"""
Build river_hierarchy.json — upstream attribution for MT USGS gauges.

For each gauge: snap it to a HydroSHEDS level-12 basin, walk NEXT_DOWN
upstream to collect all contributing basins, then find which SNOTEL
stations sit in those basins.  Groups gauges by parsed river name.

Usage (takes 2–5 min on the 160 MB shapefile):
  python riverline/scripts/build_hierarchy.py

Output:
  riverline/site/data/river_hierarchy.json
"""
import os
# Must be set before geopandas/pyproj import — fixes PROJ db path conflict
# between base conda PROJ and the geodata env's PROJ.
_PROJ_DATA = os.environ.get('GEODATA_PROJ_DIR', '')  # optional: a conda env's share/proj
if os.path.isdir(_PROJ_DATA):
    os.environ['PROJ_DATA'] = _PROJ_DATA
    os.environ['PROJ_LIB']  = _PROJ_DATA

import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]          # repos/line/
RAW  = ROOT / "riverline" / "raw"
DATA = ROOT / "riverline" / "site" / "data"
OUT  = DATA / "river_hierarchy.json"

# Expanded MT bbox — catches headwaters in WY/ID, AB
BBOX = (-118.0, 43.0, -103.0, 50.5)  # (minLon, minLat, maxLon, maxLat)


# ── River name parsing ──────────────────────────────────────────────────────

def extract_river_name(station_name: str) -> str:
    """'Gallatin River at Logan, MT' → 'Gallatin River'"""
    # Split on location indicators
    base = re.split(r'\s+(?:at|near|above|below|ab|nr|bl)\s+', station_name,
                    maxsplit=1, flags=re.IGNORECASE)[0]
    base = base.rstrip(',').strip()
    # Normalize common USGS abbreviations
    base = re.sub(r'\bCr\b',  'Creek',  base)
    base = re.sub(r'\bR\b',   'River',  base)
    base = re.sub(r'\bFk\b',  'Fork',   base)
    base = re.sub(r'\bBr\b',  'Branch', base)
    base = re.sub(r'\bTr\b',  'Tributary', base)
    return base


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # 1. Extract HydroSHEDS if needed
    shp = RAW / "hybas_na_lev12_v1c.shp"
    if not shp.exists():
        zf = RAW / "hybas_na_lev12_v1c.zip"
        if not zf.exists():
            raise FileNotFoundError(
                f"HydroSHEDS zip not found: {zf}\n"
                "Download hybas_na_lev12_v1c.zip from hydrosheds.org and put it in riverline/raw/"
            )
        print(f"Extracting {zf.name} …")
        with zipfile.ZipFile(zf) as z:
            z.extractall(RAW)
        print("  Done.")

    # 2. Load basins clipped to expanded MT bbox
    print(f"Loading HydroSHEDS level 12 (bbox filter) …")
    basins = gpd.read_file(shp, bbox=BBOX)
    basins = basins[['HYBAS_ID', 'NEXT_DOWN', 'geometry']].copy()
    basins['HYBAS_ID']  = basins['HYBAS_ID'].astype(int)
    basins['NEXT_DOWN'] = basins['NEXT_DOWN'].astype(int)
    print(f"  {len(basins):,} basins in expanded MT bbox")

    # 3. Build upstream adjacency graph
    #    upstream_of[B] = list of basin IDs that drain directly into B
    upstream_of: dict[int, list[int]] = defaultdict(list)
    for hid, nd in zip(basins['HYBAS_ID'], basins['NEXT_DOWN']):
        if nd != 0:
            upstream_of[int(nd)].append(int(hid))

    def upstream_basins(start: int) -> set[int]:
        """All basin IDs that eventually drain through `start` (inclusive)."""
        seen: set[int] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(upstream_of.get(node, []))
        return seen

    # 4. Load gauge + station data
    usgs_fc   = json.loads((DATA / "usgs_gauges.json").read_text())
    snotel_fc = json.loads((DATA / "snotel_stations.json").read_text())

    usgs_gdf = gpd.GeoDataFrame(
        [{'id': f['properties']['id'], 'name': f['properties']['name']}
         for f in usgs_fc['features']],
        geometry=[Point(f['geometry']['coordinates']) for f in usgs_fc['features']],
        crs='EPSG:4326',
    )
    snotel_gdf = gpd.GeoDataFrame(
        [{'triplet':      f['properties']['triplet'],
          'name':         f['properties']['name'],
          'elevation_ft': f['properties'].get('elevation_ft')}
         for f in snotel_fc['features']],
        geometry=[Point(f['geometry']['coordinates']) for f in snotel_fc['features']],
        crs='EPSG:4326',
    )

    # 5. Spatial join: point → basin
    print("Spatial join: USGS gauges → basins …")
    usgs_j = gpd.sjoin(usgs_gdf, basins[['HYBAS_ID', 'geometry']], how='left', predicate='within')
    print("Spatial join: SNOTEL stations → basins …")
    snotel_j = gpd.sjoin(snotel_gdf, basins[['HYBAS_ID', 'geometry']], how='left', predicate='within')

    # triplet → HYBAS_ID
    snotel_basin: dict[str, int] = {}
    for _, row in snotel_j.iterrows():
        if not pd.isna(row.get('HYBAS_ID')):
            snotel_basin[row['triplet']] = int(row['HYBAS_ID'])

    print(f"  {len(snotel_basin)}/{len(snotel_gdf)} SNOTEL stations matched to a basin")

    # 6. Upstream attribution per gauge
    print("Computing upstream SNOTEL per gauge …")
    rivers: dict[str, list] = defaultdict(list)
    matched = 0
    for _, row in usgs_j.iterrows():
        gauge_id   = row['id']
        gauge_name = row['name']
        river_name = extract_river_name(gauge_name)

        # Coordinates from original GDF
        pt = usgs_gdf.loc[usgs_gdf['id'] == gauge_id, 'geometry'].iloc[0]

        if pd.isna(row.get('HYBAS_ID')):
            print(f"  ⚠  {gauge_name} — outside HydroSHEDS coverage")
            rivers[river_name].append({
                'id': gauge_id, 'name': gauge_name,
                'coords': [round(pt.x, 5), round(pt.y, 5)],
                'source': 'usgs', 'upstream_snotel': [],
            })
            continue

        gauge_basin = int(row['HYBAS_ID'])
        up          = upstream_basins(gauge_basin)
        upstream_snotel = [t for t, b in snotel_basin.items() if b in up]
        matched += 1

        rivers[river_name].append({
            'id':              gauge_id,
            'name':            gauge_name,
            'coords':          [round(pt.x, 5), round(pt.y, 5)],
            'source':          'usgs',
            'hybas_id':        gauge_basin,
            'upstream_snotel': upstream_snotel,
        })

    print(f"  {matched}/{len(usgs_gdf)} gauges matched; "
          f"{sum(len(r['upstream_snotel']) for rs in rivers.values() for r in rs)} total upstream links")

    # 7. Sort rivers alphabetically; sort gauges W→E (upstream→downstream)
    river_list = []
    for rname, gauges in sorted(rivers.items()):
        gauges_sorted = sorted(gauges, key=lambda g: g['coords'][0])
        river_list.append({'name': rname, 'gauges': gauges_sorted})

    # 8. SNOTEL lookup table
    snotel_lookup: dict[str, dict] = {}
    for f in snotel_fc['features']:
        p = f['properties']
        snotel_lookup[p['triplet']] = {
            'name':         p['name'],
            'elevation_ft': p.get('elevation_ft'),
            'coords':       [round(c, 5) for c in f['geometry']['coordinates']],
        }

    out = {'rivers': river_list, 'snotel': snotel_lookup}
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(',', ':')))
    print(f"\nWrote {len(river_list)} rivers → {OUT}  ({OUT.stat().st_size:,} bytes)")

    # Quick sanity check
    sample = next(iter(rivers.values()), [])
    if sample:
        g = sample[0]
        print(f"\nSample: {g['name']}")
        print(f"  Upstream SNOTEL ({len(g['upstream_snotel'])}): {g['upstream_snotel'][:5]}")


if __name__ == '__main__':
    main()
