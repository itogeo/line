"""
Build major_basins.geojson, medium_basins.geojson, and mt_basins.geojson from
HydroSHEDS level-12.

Dissolves level-12 basins at two resolutions:
  major  → dissolve by MAIN_BAS    → ~5–10 major watersheds  → major_basins.geojson
  medium → dissolve by PFAF_ID[:8] → ~50–150 sub-basins      → medium_basins.geojson

Also builds mt_basins.geojson (replaces the WBD HUC8 file) — same as medium but with
upstream-topology property `next_pfaf8` derived from NEXT_DOWN field.  This powers
the map's "highlight upstream basins" feature.

Takes 5–15 minutes on the 160 MB shapefile.  Run once, commit outputs.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/build_basins.py

Input:
  riverline/raw/hybas_na_lev12_v1c.shp   (or .zip)

Output:
  riverline/site/data/major_basins.geojson
  riverline/site/data/medium_basins.geojson
  riverline/site/data/mt_basins.geojson   ← used by map for upstream highlight
"""
import os
import zipfile

# Must be set before geopandas/pyproj import — fixes PROJ db path conflict
_PROJ_DATA = "/Users/ianvandusen/anaconda3/envs/geodata/share/proj"
if os.path.isdir(_PROJ_DATA):
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA

import json
from collections import Counter
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]          # repos/line/
RAW  = ROOT / "riverline" / "raw"
DATA = ROOT / "riverline" / "site" / "data"

# Montana bbox — slightly inset to trim border noise
BBOX = (-116.5, 44.0, -103.5, 49.2)

# Simplification tolerances (degrees)
PRE_SIMPLIFY  = 0.025   # before dissolve — fast, reduces vertex count
POST_SIMPLIFY = 0.04    # after dissolve — smooths dissolved boundaries


def load_shp() -> gpd.GeoDataFrame:
    shp = RAW / "hybas_na_lev12_v1c.shp"
    if not shp.exists():
        zf = RAW / "hybas_na_lev12_v1c.zip"
        if not zf.exists():
            raise FileNotFoundError(
                f"HydroSHEDS zip not found: {zf}\n"
                "Download hybas_na_lev12_v1c.zip from hydrosheds.org → put in riverline/raw/"
            )
        print(f"Extracting {zf.name} …")
        with zipfile.ZipFile(zf) as z:
            z.extractall(RAW)
        print("  Done.")

    print("Loading HydroSHEDS level-12 within MT bbox …")
    gdf = gpd.read_file(shp, bbox=BBOX)
    print(f"  {len(gdf):,} basins loaded")
    return gdf


def dissolve_and_save(gdf: gpd.GeoDataFrame, by: str, out_path: Path, label: str) -> None:
    print(f"\nBuilding {label} ({by}) …")

    # Pre-simplify individual polygons before dissolve
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(PRE_SIMPLIFY, preserve_topology=True)

    dissolved = gdf[[by, "geometry"]].dissolve(by=by, as_index=False)
    print(f"  Dissolved → {len(dissolved)} polygons")

    # Post-simplify merged boundaries
    dissolved["geometry"] = dissolved.geometry.simplify(POST_SIMPLIFY, preserve_topology=True)

    # Drop any degenerate geometries
    dissolved = dissolved[dissolved.geometry.is_valid & ~dissolved.geometry.is_empty]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    dissolved.to_file(out_path, driver="GeoJSON")
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  Wrote {len(dissolved)} features → {out_path}  ({size_mb:.1f} MB)")


def build_topology(gdf: gpd.GeoDataFrame) -> dict:
    """Return {pfaf8: next_pfaf8} downstream map using NEXT_DOWN → HYBAS_ID lookup."""
    hybas_to_pfaf8 = dict(zip(gdf["HYBAS_ID"].astype(int), gdf["PFAF8"]))

    counts: dict = {}
    for _, row in gdf.iterrows():
        src = row["PFAF8"]
        next_id = int(row["NEXT_DOWN"])
        if next_id == 0:
            continue
        tgt = hybas_to_pfaf8.get(next_id)
        if tgt and tgt != src:
            if src not in counts:
                counts[src] = Counter()
            counts[src][tgt] += 1

    return {k: v.most_common(1)[0][0] for k, v in counts.items()}


def build_mt_basins(gdf: gpd.GeoDataFrame, out_path: Path) -> None:
    """
    Output mt_basins.geojson — medium-resolution basins (PFAF8) with upstream topology.

    Properties per feature:
      pfaf8      — 8-char Pfafstetter code used as basin ID
      next_pfaf8 — downstream basin's pfaf8 (for BFS upstream traversal in the map)
      areasqkm   — dissolved area computed from geometry
    """
    print("\nBuilding mt_basins (medium + topology) …")

    topo = build_topology(gdf)
    print(f"  Topology: {len(topo)} PFAF8 → downstream mappings")

    gdf_s = gdf.copy()
    gdf_s["geometry"] = gdf_s.geometry.simplify(PRE_SIMPLIFY, preserve_topology=True)

    dissolved = gdf_s[["PFAF8", "geometry"]].dissolve(by="PFAF8", as_index=False)
    dissolved["geometry"] = dissolved.geometry.simplify(POST_SIMPLIFY, preserve_topology=True)
    dissolved = dissolved[dissolved.geometry.is_valid & ~dissolved.geometry.is_empty]
    print(f"  Dissolved → {len(dissolved)} basins")

    dissolved["next_pfaf8"] = dissolved["PFAF8"].map(topo).fillna("")
    dissolved["areasqkm"]   = (dissolved.geometry.to_crs("EPSG:6933").area / 1e6).round(1)
    dissolved = dissolved.rename(columns={"PFAF8": "pfaf8"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    dissolved[["pfaf8", "next_pfaf8", "areasqkm", "geometry"]].to_file(out_path, driver="GeoJSON")
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  Wrote {len(dissolved)} features → {out_path}  ({size_mb:.1f} MB)")

    # Sample — show a few with topology
    sample = dissolved[dissolved["next_pfaf8"] != ""].head(5)
    for _, r in sample.iterrows():
        print(f"    {r['pfaf8']} → {r['next_pfaf8']}  ({r['areasqkm']:.0f} km²)")


def main():
    gdf = load_shp()

    # Ensure columns are present
    gdf["MAIN_BAS"] = gdf["MAIN_BAS"].astype(int)
    gdf["PFAF8"]    = gdf["PFAF_ID"].astype(str).str[:8]

    dissolve_and_save(gdf, "MAIN_BAS", DATA / "major_basins.geojson",  "major basins")
    dissolve_and_save(gdf, "PFAF8",    DATA / "medium_basins.geojson", "medium basins")
    build_mt_basins(gdf, DATA / "mt_basins.geojson")

    print("\nDone.")


if __name__ == "__main__":
    main()
