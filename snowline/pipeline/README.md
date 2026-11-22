# Snowline pipeline

Everything that fetches, computes or builds data for the Snowline site.
Run commands from the repository root. Every script runs on its own, and most
have `--help`.

## The common commands

```bash
# Make the snow map for one date: find scenes, fetch bands, NDSI, WebPs, upload to R2
bash snowline/pipeline/update_date.sh 2026-10-03

# What CI does every morning (metadata only; no pixels)
python snowline/pipeline/build_sat_availability.py
python snowline/pipeline/build_snotel_season.py
python snowline/pipeline/fetch_mesonet_snow.py
python snowline/pipeline/build_snow_timeline.py       # Mondays in CI

# After new maps: compare them with SNOTEL
python snowline/pipeline/build_snotel_agreement.py --date=2026-10-03
```

## Data flow

```
S2 STAC GeoParquet index (Source Cooperative)   ← lib/s2index.py, one DuckDB query
        │  scene ids + COG hrefs, one scene per tile per day
        ▼
fetch_bands.py      range-reads green/red/blue/swir16/nir08/SCL windows from the
        │           public Sentinel-2 C1 COGs on AWS, removes the C1 +1000 DN
        ▼           offset → cache/{date}/T{tile}/{band}.tif + meta.json
process_tiles.py    reprojects to a 0.0003° grid; snow = NDSI ≥ 0.4 or SCL 11,
        │           plus the v2 forest rule (NDFSI ≥ 0.39 above the day's snow
        │           line); SCL cloud mask
        │           → site/data_10m/{date}/snow_r*c*.webp, truecolor_r*c*.webp,
        ▼             snowline.json (with the scene list), dates.json
sync_r2.py          uploads the WebPs to R2 bucket snowline-tiles
        │           (in CI the date is unlisted again if this fails)
        ▼
build_snotel_agreement.py   map class vs SNOTEL depth at each station
```

After the maps, the imagery workflow also runs `build_composite.py` (recent and
latest views), `build_terrain_stats.py` (snow by elevation, aspect and range),
`build_stac.py` and `prune_r2.py`. The order is in
`.github/workflows/snowline-process-imagery.yml`.

## Scripts

| Script | Cadence | What it does |
|---|---|---|
| `fetch_bands.py` | per map | Phase 1. Resumable: cached bands are skipped. `--tiles=12TVR` for a quick test. |
| `process_tiles.py` | per map | Phase 2. CPU only, re-runnable. |
| `update_date.sh` | per map | Runs both phases, `export_cogs.py` and the R2 upload, then deletes the cache (`--keep-cache` to keep it). Exit code 3 means no usable scene. |
| `sync_r2.py` | per map / backfill | Uploads any local tiles missing from R2. `--check` only lists them. Needs `CF_ACCOUNT_ID` and `CF_API_TOKEN`. |
| `prune_r2.py` | per run | Deletes old true-colour tiles from R2. CI keeps the newest 10 dates and everything since the season start (`--keep-truecolor-since`). Snow tiles are kept forever (`--keep-snow 0`). |
| `build_sat_availability.py` | daily | Every S2 pass over the AOI from the index → `sat_availability.json` + `scenes.json`. |
| `check_new_clear_pass.py` | daily | Prints the newest good/excellent pass without a map, so the daily job can trigger processing early. The imagery workflow also runs on its own schedule. |
| `build_snotel_season.py` | daily | SNOTEL depth and SWE for the season → `snotel_season_{YEAR}.json` (+ `snotel_season.json` for the current one). `--season 2025` rebuilds an archive. |
| `build_snow_timeline.py` | weekly | `s2:snow_ice_percentage` per tile since 2015 → `snow_timeline.json`. Metadata only. |
| `build_snotel_agreement.py` | after maps | Satellite vs SNOTEL → `snotel_agreement.json`. |
| `build_composite.py` | per run | Latest view (newest clear look per pixel over the last 10 days) and recent view (newest look, cloud included) → `latest_r*c*` and `recent_r*c*` files + `latest` and `recent` in snowline.json. `--upload` in CI. |
| `build_terrain_stats.py` | per run | Snow by elevation band, aspect and range for each map → `terrain_stats.json`, `range_stats.json`. Reads `data/terrain_grid.npz`. |
| `build_terrain_grid.py` | when the area changes | Elevation, aspect, forest and range grid → `data/terrain_grid.npz`, `site/data/terrain_classes.webp`. Imported by `build_terrain_stats.py`. |
| `fetch_mesonet_snow.py` | daily | Valley snow depth from the Montana Mesonet → `mesonet_snow.json`. |
| `fetch_wind.py` | hourly | RTMA wind grid and station wind (Mesonet, SNOTEL, NWS) → R2 `wind/`. Needs `pygrib`, which `snowline-wind.yml` installs. |
| `file_feedback.py` | daily | Files feedback sent from the site as GitHub issues. |
| `build_station_pixels.py`, `classifier_eval.py` | by hand | The classifier bench behind `docs/snow-classifier.md`. |
| `export_cogs.py` | per map | Class COGs (0 ground, 1 snow, 2 cloud, 3 nodata) from the snow WebPs, for open data. |
| `build_stac.py` | per run | Static STAC catalog of every map → `site/stac/`. |
| `diagnose_tile.py` | debugging | Prints every bound and offset for one date and tile. |
| `build_snotel_normals.py` | yearly; daily with `--if-missing` | 20-year SNOTEL medians → `snotel_normals.json`. The daily job adds any new station. |
| `build_forest_mask.py` | yearly | ESA WorldCover tree cover → `forest_mask.webp`. Needs `requirements-assets.txt`. |
| `build_historical.py` | yearly | 25-year MODIS snow frequency by day of year. Needs `requirements-assets.txt`. |
| `build_lidar_terrain.py` | once / when USGS adds surveys | USGS 3DEP 1 m lidar → shaded terrain tiles (z8–13) in `site/terrain/shade/`. Steps: `list`, `fetch`, `shade`, `tiles`. Then `sync_r2.py --terrain`. |
| `fetch_fs_roads.py` | not in use | USFS roads with seasonal restrictions. The map's roads layer was removed; the script is kept in case it returns. |

## Requirements

`requirements.txt` is what the daily and imagery jobs install: duckdb, pytz,
numpy, rasterio, Pillow, requests, shapely. The wind job installs pygrib, numpy
and requests itself. `requirements-assets.txt` adds pystac-client and
planetary-computer for the two yearly asset builds that read from Microsoft
Planetary Computer.

## History

Until October 2026 scenes were found through the Element 84 Earth Search
STAC API (`sentinel-2-l2a`), with HLS and Landsat from Planetary Computer
for the pass table. The switch to the GeoParquet index and Collection 1
was checked pixel for pixel. See `AGENTS.md` at the repository root. Maps
made before 2026-10-05 by an older per-tile pipeline were reprocessed after
the SNOTEL check showed they missed most snow in Nov–Mar.
