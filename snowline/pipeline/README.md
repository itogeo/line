# Snowline Pipeline

Everything that fetches, computes, or builds data for the snowline website
lives in this directory. The pipeline has two cadences:

- **Daily cron** — fast metadata refresh, runs in CI every morning at 11 UTC
- **Manual / on-demand** — slow imagery processing + one-shot static asset
  builds. Run locally or via manual GitHub Actions dispatch.

## TL;DR — most common commands

```bash
# Process Sentinel-2 imagery for one date (the everyday command)
bash pipeline/update_date.sh 2026-04-06

# Refresh the satellite availability table + SNOTEL season history
# (this is what daily.yml does in CI; only run locally if CI is broken)
python pipeline/build_sat_availability.py
python pipeline/build_snotel_season.py

# Refresh Forest Service roads (rare — they barely change)
python pipeline/fetch_fs_roads.py
```

After running anything locally, commit + push the resulting files in `site/`.

---

## Imagery pipeline (the slow, two-phase one)

Sentinel-2 imagery processing is split into two phases so it's resumable
when network drops mid-fetch and so re-encoding doesn't require re-downloading.

| File | Phase | What it does |
|---|---|---|
| `fetch_bands.py` | 1 | Downloads Sentinel-2 band windows from Element84 (us-west-2 S3) into `cache/{date}/{tile_id}/{band}.tif`. Resumable: re-running skips bands already on disk. Sequential by default — parallelism over residential connections caused TLS handshake failures. |
| `process_tiles.py` | 2 | Reads cached bands, computes NDSI, encodes per-tile snow + truecolor WebPs to `site/data_10m/{date}/`. Pure CPU, no network. Re-runnable for free. |
| `update_date.sh` | wrapper | `bash pipeline/update_date.sh YYYY-MM-DD` runs both phases + cleans up the cache on success. Pass `--keep-cache` to keep the band files. |
| `prune_truecolor.py` | maintenance | Keeps only the most recent 10 dates of truecolor RGB imagery; deletes older ones to keep the repo small. Snow tiles stay forever (they're tiny). Called by `process_imagery.yml` after each new date. |

The big center tiles (T12TVR, T12TWR) sometimes overshoot Cloudflare's 25 MiB
file size cap at quality=92 — `process_tiles.py` recursively splits them
into 2x2 sub-tiles (`truecolor_T12TVR_NW.webp`, `_NE`, `_SW`, `_SE`).
Frontend handles both single-tile and split-tile cases via the
`truecolor_files` list in `snowline.json`.

### Data flow

```
Element84 S3 (sentinel-cogs.s3.us-west-2)
        │
        │  fetch_bands.py
        ▼
cache/{date}/{tile_id}/{green,red,blue,swir16,scl}.tif    (gitignored)
        │
        │  process_tiles.py
        ▼
site/data_10m/{date}/snow_T*.webp + truecolor_T*.webp + snowline.json
        │
        │  git push → Cloudflare Pages
        ▼
snowline.itogeospatial.com
```

---

## Daily metadata refresh (the fast cron)

Runs every morning via `.github/workflows/daily.yml`. Two scripts, both ~1 min:

| File | What it does |
|---|---|
| `build_sat_availability.py` | Queries Element84 (native S2 + Landsat) and Microsoft Planetary Computer (HLS-S30 + HLS-L30). Writes `site/data/sat_availability.json` — the source of truth for "what passes exist". The metadata page reads it. |
| `build_snotel_season.py` | Pulls the full current-season SWE + snow depth history for every NRCS SNOTEL station in the AOI from the AWDB API. Writes `site/data/snotel_season.json`. The frontend's per-date SNOTEL display reads it. Has retry logic for the flaky NRCS endpoint. |

These never need imagery — pure metadata fetches. Daily.yml is fast and
reliable specifically because we removed imagery processing from it.

---

## One-shot static assets (run rarely)

These build pre-baked files that change rarely. Run manually via
`workflow_dispatch` in GitHub Actions or locally.

| File | What it produces | Cadence |
|---|---|---|
| `build_forest_mask.py` | `site/data/forest_mask.webp` — ESA WorldCover forest canopy. Used to dim snow detections in heavy forest. | Once per year (or when AOI changes) |
| `build_historical.py` | `site/data/historical/doy_*.webp` — 25-year MODIS snow frequency by day-of-year. | Once per year |
| `build_snotel_normals.py` | `site/data/snotel_normals.json` — 20-year median SWE per station per day-of-year. Used for "% of normal" comparisons. | Once per year |
| `fetch_fs_roads.py` | `site/data/fs_roads.geojson` — All USFS roads in the AOI with seasonal use restrictions, merged from EDW_RoadBasic + EDW_MVUM. | Whenever you want fresh road data (rare) |

Corresponding CI workflows: `build-assets.yml` and `historical.yml`.

---

## File reference

**Active pipelines:**
- `fetch_bands.py` — phase 1 of imagery
- `process_tiles.py` — phase 2 of imagery
- `update_date.sh` — runs both phases + cleanup
- `prune_truecolor.py` — keeps only last 10 dates of RGB

**Daily metadata:**
- `build_sat_availability.py`
- `build_snotel_season.py`

**One-shot static assets:**
- `build_forest_mask.py`
- `build_historical.py`
- `build_snotel_normals.py`
- `fetch_fs_roads.py`

**Other:**
- `requirements.txt` — Python dependencies (rasterio, pystac-client, planetary-computer, requests, Pillow, numpy)
- `README.md` — this file

---

## What used to be here (and why it's gone)

The previous architecture had a single `run_pertile.py` that did download +
NDSI + encode in one pass. It worked but:

- Network errors during a 15-minute run lost all the work
- Re-encoding to test a quality setting required re-downloading bands
- Resuming was impossible without keeping all the temporary state

Splitting into `fetch_bands.py` + `process_tiles.py` solved all three.

Also gone:

- `run.py`, `run_hls.py`, `run_tile.py` — old mosaic-style processors that
  produced one big WebP per date. Replaced by the per-tile output.
- `backfill.sh`, `backfill_10m.sh`, `backfill_16k.sh`, `backfill_local.sh`,
  `backfill_tiled.sh`, `fill_missing_tiles.sh`, `reprocess_gaps.sh` — all
  called the deleted run scripts. Per-tile pipeline doesn't need backfill
  loops since each date is processed independently and resumably.
- `fix_metadata.py` — utility used by the dead backfill scripts
- `build_index.sh` — `process_tiles.py` updates `data_10m/dates.json` directly now
- `backfill_snotel_history.py` — one-shot that already ran successfully
- `.github/workflows/update.yml` — old separate cron, merged into daily.yml
- `.github/workflows/backfill.yml`, `backfill-good.yml`, `update-hls.yml` —
  CI versions of the deleted shell/python scripts
