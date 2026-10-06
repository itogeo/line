# Snowline pipeline

Everything that fetches, computes or builds data for the Snowline site.
Run commands from the repository root. Every script has `--help` and runs
on its own.

## The common commands

```bash
# Make the snow map for one date: find scenes, fetch bands, NDSI, WebPs, upload to R2
bash snowline/pipeline/update_date.sh 2026-10-03

# What CI does every morning (metadata only; no pixels)
python snowline/pipeline/build_sat_availability.py
python snowline/pipeline/build_snotel_season.py
python snowline/pipeline/build_snow_timeline.py       # Mondays in CI

# After new maps: compare them with SNOTEL
python snowline/pipeline/build_snotel_agreement.py --date=2026-10-03
```

## Data flow

```
S2 STAC GeoParquet index (Source Cooperative)   ← lib/s2index.py, one DuckDB query
        │  scene ids + COG hrefs, one scene per tile per day
        ▼
fetch_bands.py      range-reads green/red/blue/swir16/SCL windows from the
        │           public Sentinel-2 C1 COGs on AWS, removes the C1 +1000 DN
        ▼           offset → cache/{date}/T{tile}/{band}.tif + meta.json
process_tiles.py    reprojects to a 0.0003° grid, NDSI ≥ 0.4, SCL cloud mask
        │           → site/data_10m/{date}/snow_r*c*.webp, truecolor_r*c*.webp,
        ▼             snowline.json (with the scene list), dates.json
sync_r2.py          uploads the WebPs to R2 bucket snowline-tiles
        │           (in CI the date is unlisted again if this fails)
        ▼
build_snotel_agreement.py   map class vs SNOTEL depth at each station
```

## Scripts

| Script | Cadence | What it does |
|---|---|---|
| `fetch_bands.py` | per map | Phase 1. Resumable: cached bands are skipped. `--tiles=12TVR` for a quick test. |
| `process_tiles.py` | per map | Phase 2. CPU only, re-runnable. |
| `update_date.sh` | per map | Runs both phases and the R2 upload, then deletes the cache (`--keep-cache` to keep it). |
| `sync_r2.py` | per map / backfill | Uploads any local tiles missing from R2. `--check` only lists them. Needs `CF_ACCOUNT_ID` and `CF_API_TOKEN`. |
| `prune_r2.py` | per run | Deletes old true-colour tiles from R2 (keeps 10 dates). Snow tiles are kept forever (`--keep-snow 0`). |
| `build_sat_availability.py` | daily | Every S2 pass over the AOI from the index → `sat_availability.json` + `scenes.json`. |
| `check_new_clear_pass.py` | daily | Prints the newest good/excellent pass without a map, so CI can trigger processing. |
| `build_snotel_season.py` | daily | Current-season SNOTEL depth and SWE → `snotel_season.json`. |
| `build_snow_timeline.py` | weekly | `s2:snow_ice_percentage` per tile since 2015 → `snow_timeline.json`. Metadata only. |
| `build_snotel_agreement.py` | after maps | Satellite vs SNOTEL → `snotel_agreement.json`. |
| `diagnose_tile.py` | debugging | Prints every bound and offset for one date and tile. |
| `build_snotel_normals.py` | yearly | 20-year SNOTEL medians → `snotel_normals.json`. |
| `build_forest_mask.py` | yearly | ESA WorldCover tree cover → `forest_mask.webp`. Needs `requirements-assets.txt`. |
| `build_historical.py` | yearly | 25-year MODIS snow frequency by day of year. Needs `requirements-assets.txt`. |
| `fetch_fs_roads.py` | rarely | USFS roads with seasonal restrictions. |

## Requirements

`requirements.txt` is what CI installs: duckdb, numpy, rasterio, Pillow,
requests, pytz. `requirements-assets.txt` adds pystac-client and
planetary-computer for the two yearly asset builds that read from Microsoft
Planetary Computer.

## History

Until October 2026 scenes were found through the Element 84 Earth Search
STAC API (`sentinel-2-l2a`), with HLS and Landsat from Planetary Computer
for the pass table. The switch to the GeoParquet index and Collection 1
was checked pixel for pixel. See `AGENTS.md` at the repository root. Maps
made before 2026-10-05 by an older per-tile pipeline were reprocessed after
the SNOTEL check showed they missed most snow in Nov–Mar.
