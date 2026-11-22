# Snowline plan

The current state of Snowline and the open work. Read this first; update it when
something here changes. Older history is in `git log` and `docs/release-log.md`.

**Last checked against the code:** 2026-11-21.

## What it is

A free, open-source daily snow-cover map of SW Montana, live at
[line.itogeospatial.com/snow](https://line.itogeospatial.com/snow). Sentinel-2
imagery in, a snow / ground / cloud map out, checked against SNOTEL every pass.

Direction (Ian): free and not for sale; no trip-planning features; use a free
hosted source before building or hosting a layer ourselves; not an avalanche
forecast.

## State on 2026-11-21

- All four workflows ran green for the previous four days. `tools/release_check.py`
  passed 17 of 17 against production.
- 90 maps listed (2025-10-03 to 2026-11-20), 33 of them this season.
- This season the map agrees with SNOTEL on 264 of 314 station checks (84%):
  40 missed snow, 10 false snow (summed from `site/data/snotel_agreement.json`).
- Wind: 73 stations in `stations_7d.json`.

## How it runs

| Workflow | Schedule (UTC) | Does | Writes |
|---|---|---|---|
| `snowline-daily.yml` | 11:00 | Pass list, SNOTEL season, Mesonet snow depth, snow timeline (Mondays), then triggers imagery, files site feedback as issues, runs `release_check.py` | Commits `snowline/site/data/` to `main` |
| `snowline-process-imagery.yml` | 13:00, and when the daily job triggers it | Every unprocessed pass over 10% of the area in the last 10 days: `update_date.sh` (fetch, classify, COGs, R2 upload), SNOTEL agreement, composites, terrain and range stats, STAC, R2 prune | Tiles to R2. Commits `data_10m/dates.json`, `data_10m/*/snowline.json`, `data/snotel_agreement.json`, `data/terrain_stats.json`, `data/range_stats.json`, `stac/` to `main` |
| `snowline-wind.yml` | hourly at :25 | `fetch_wind.py --upload`: RTMA wind grid and station wind | R2 `wind/` only, nothing in git |

GitHub starts scheduled jobs late. The daily commit usually lands 17:00 to 19:30
UTC, and the hourly wind job has been firing about every 5 hours.

Cloudflare Pages deploys `main` on every push, bot commits included. Tiles and
wind are read from R2 by `_worker.js` at the repository root and are not part
of the deploy.

- Season: Oct 1 to May 31 (`lib/aoi.py`). Off-season passes are not processed,
  listed or stored.
- Area: bbox `(-112.6, 44.55, -109.0, 46.35)`, 12 MGRS tiles (`lib/aoi.py`).
- Classifier: v2 in `process_tiles.py`. NDSI >= 0.4 or SCL 11, then a second
  pass adds forest pixels above the day's snow line with NDFSI >= 0.39. Bench
  and reasoning: `docs/snow-classifier.md`.
- R2 pruning: every snow map is kept; true colour is kept for this season
  (`prune_r2.py` flags in the imagery workflow).

## Site (`snowline/site/`)

| Page | What |
|---|---|
| `index.html` | The map. One large file (about 4,300 lines) with its script inline. Views: single pass (default), recent, latest. Loads `season.js`, `cams.js`, `wind.js`, `/snow/shared/freshness.js`. |
| `range.html` | One page per range: imagery beside snow, depth, wind and a trust panel. Ranges are the GNFAC forecast zones in `data/gnfac_zones.geojson`. |
| `terrain.html` | Snow by elevation band and aspect, from `data/terrain_classes.webp` and `terrain_stats.json`. |
| `metadata.html` | Data page: scenes, snow history, SNOTEL. Loads `season.js`, `data.js`. |
| `methods.html` | How the map is made and where it goes wrong. |
| `webcam.html` | Webcams (`cams.js`). |

Terrain shading on `main` is hosted lidar tiles: `index.html` `addLidarShade()`
loads `/snow/api/terrain/shade/{z}/{x}/{y}.webp` from R2, and
`release_check.py` requires them. The branch `agent/charcoal-theme` replaces
them with Mapbox hillshade and a charcoal frame. It has not been merged and is
a month behind `main`. Two files on `main` already describe the branch's state
as if it had shipped: the header of `tools/rebuild_area_layers.sh` and the last
line of `docs/release-log.md`.

## Open work

- **Phone crashes** (reported 2026-11-21; Mark is taking it). A code read of the
  likely causes is in `docs/phone-crash-notes.md`. Nothing there is measured on
  a device yet.
- **`agent/charcoal-theme`**: merge or drop (Ian). If it merges, remove the
  lidar route from `_worker.js`, the lidar checks in `release_check.py`,
  `sync_r2.py --terrain`, `build_lidar_terrain.py` and the README terrain row.
- **Wind cadence**: the hourly cron runs about every 5 hours. Undecided whether
  to move the trigger off GitHub.
- **Ridge wind stations** (Bridger, Lone Peak) are only on Synoptic, which needs
  a token. Not set up.
- **Map panel "Snow depth by range"** still groups SNOTEL by `season.js`
  `STATION_RANGE`, not by the GNFAC zones the range page uses.
- **Push retry**: both committing workflows retry the push three times and then
  report success even if all three failed (`snowline-daily.yml:82-87`,
  `snowline-process-imagery.yml:204-209`).
- **No tests and no checks on pull requests.** `tools/release_check.py` only
  checks the deployed site.
- **Forced reprocess since 2026-10-01** was requested on 2026-10-16 after the
  area and classifier changed. Not confirmed done.
- Failure-mode example images for `methods.html`: not done.
- Lighthouse on a real phone: not measured.
- HLS (Landsat + Sentinel-2) for more frequent coverage: deferred, not planned.

## Not in git

Tiles (`*.webp`, `*.tif`) live in R2 bucket `snowline-tiles`. The imagery cache
is `snowline/cache/`. Both are git-ignored. A fresh clone has metadata for every
map but no pixels; see CONTRIBUTING.md for the local preview.
