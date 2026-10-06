# AGENTS.md: Line Network

Guidance for AI agents and automated clients working on this repository or
reading the data it publishes.

**One rule for edits to this file:** every claim is either quoted from a
source or measured, and the measurement carries its date. If you can't
point at where a fact came from, leave it out. A confident wrong column name
costs more than a missing one.

## What this is

Snowline is a daily snow-cover map of SW Montana. Sentinel-2 Collection 1
L2A imagery goes in, a snow/no-snow raster comes out, and every map
is checked against NRCS SNOTEL snow depth. RiverLine (`riverline/`) and
SkyLine (`skyline/`) share the repository and the Cloudflare deployment but
are separate products.

| Resource | Where |
|---|---|
| Live site | `https://line.itogeospatial.com/snow` |
| Scene index (input) | `https://data.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/` (its own guide: `.../sentinel-2-c1-l2a/AGENTS.md`) |
| Imagery (input) | `https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/...`, read through each scene's `assets` hrefs |
| Published metadata | `snowline/site/data/*.json` and `snowline/site/data_10m/*/snowline.json` in this repository, served under `/snow/data/` and `/snow/data_10m/` |
| Published tiles | `/snow/api/tile/{date}/{file}.webp` (from Cloudflare R2, key `tiles/{date}/{file}`) |

## Area

`lib/aoi.py` is the only definition. Snowline is bbox `(-112.2, 44.9, -109.0, 46.5)`
(west, south, east, north, EPSG:4326) and 12 MGRS tiles:
`12TUQ 12TUR 12TUS 12TVQ 12TVR 12TVS 12TWQ 12TWR 12TWS 12TXQ 12TXR 12TXS`.
These are every tile whose footprint intersects the bbox in the index
(measured 2026-10-05). `12TXQ` only clips the SE corner.

## Finding scenes (`lib/s2index.py`)

* Reads the year's file list from `year=YYYY/YYYY.json` → `assets`, skipping
  files with `table:row_count` 0. On 2026-10-05, 2026 was `items.parquet`
  (3,836,310 rows, to 2026-09-21) + `live-09.parquet` + `live-10.parquet`.
  **Querying `items.parquet` alone misses about the last two weeks.**
* Source Cooperative returned HTTP 403 to Python's default urllib
  User-Agent (2026-10-05). The module sends its own UA, and if the JSON
  can't be read it falls back to globbing `s3://us-west-2.opendata.source.coop/.../year=YYYY/*.parquet`.
* Filters on `_tile` (no leading `T`) and then `datetime`, the file's sort
  order. Tile-and-date queries took 3–20 s from a cloud VM (2026-10-05).
* Dedupes on `id` keeping the newest `s2:generation_time`, as the index's
  AGENTS.md says to when reading live files, then keeps **one scene per
  tile per UTC day**: lowest `s2:nodata_pixel_percentage`, then lowest
  `eo:cloud_cover`. Example: 12TVR on 2026-10-03 had
  `S2A_T12TVR_20261003T182811_L2A` (nodata 0.0) and
  `S2B_T12TVR_20261003T181250_L2A` (nodata 89.17). The first is kept.

## Pixels

* Collection 1 reflectance assets carry `raster:bands` `scale 0.0001,
  offset -0.1`, i.e. `DN = 10000·ρ + 1000`. `fetch_bands.py` removes the
  offset at download (`DN − 1000`, valid pixels clipped to ≥ 1, 0 kept as
  nodata). The cache then holds `10000·ρ`.
* Measured 2026-10-05 on 12TVR 2026-04-19: after that correction, the C1
  green, red, blue, swir16 and SCL windows are **identical pixel for
  pixel** to the older Earth Search `sentinel-2-l2a` COGs Snowline used
  before, and the processed snow-pixel count differs by 0.0%. Note that the
  old collection's metadata *also* advertised offset −0.1, but its pixels
  were already shifted. Don't apply an offset to `sentinel-2-l2a`.
* Snow: `NDSI = (green − swir16)/(green + swir16) ≥ 0.4` **or** SCL class
  11 (snow), excluding SCL classes 0, 3, 8, 9, 10. The SCL term was added
  on 2026-10-06 after the SNOTEL check. On 14 dates, point-sampling SCL at
  the stations raised agreement from 191/253 to 219/253 station-days,
  with no new false snow. Each map's `snowline.json` records its `method`. The grid is 0.0003° (3×2 chunks, `snow_r{row}c{col}.webp`).
* Until 2026-10-06 `fetch_bands.py` gave cached windows a transform that was
  off by up to half a source pixel (it used the fractional window while
  `read()` used the rounded one; found by an independent review). Maps
  processed before the fix are shifted by at most ~10 m, well inside one
  0.0003° output pixel.

## Published files

`snowline/site/data/scenes.json` (written by `build_sat_availability.py`): one row per tile per day, the last 400 days.
`columns` = `date, tile, id, cloud, snow, nodata, baseline, dir, extra`.
An asset URL is `dir + files[key]` for keys `thumbnail, visual, green,
swir16, scl`. If `dir` is null, the full URLs are in `extra`. `snow` is
ESA's `s2:snow_ice_percentage`, **not** Snowline's map.

`snowline/site/data/sat_availability.json`: one row per pass date. Fields:
`dt, s2n` (tiles imaged, excluding slivers with ≥95% nodata), `s2clr`
(tiles under 30% cloud **and** under 50% nodata), `s2cc` (mean cloud),
`snow_pct` (nodata-weighted mean of `s2:snow_ice_percentage`), `q`
(`excellent` ≥8 clear and mean cloud <20, `good` ≥4 clear, `partial` ≥2
clear, otherwise `cloudy`), `why` (plain English), `tiles`,
`clear_tiles`. The thresholds are in the file under `thresholds` and in
`classify()`.

`snowline/site/data_10m/{date}/snowline.json`: one per map. `scene_date,
snow_cover_pct` (of imaged pixels), `coverage_pct` (of the bbox),
`chunks[]` (`snow_file, truecolor_file, bounds, snow_pixels,
valid_pixels`), `scenes[]` (`id, tile, datetime, cloud, nodata,
baseline`), `ndsi_threshold`, `source`. Maps made before 2026-10-05 by
the older pipeline have `tiles[]` instead of `chunks[]` and no `scenes`.

`snowline/site/data_10m/dates.json`: `{"dates": [...], "latest": ...}`.
A date is listed only after its tiles reached R2 (enforced in CI by
`update_date.sh`), and only if the map covers at least 10% of the area.

`snowline/site/data_10m/{date}/snow_r{row}c{col}.tif`: single-band uint8
COGs, EPSG:4326, `0 ground, 1 snow, 2 cloud, 3 nodata`, nodata value
255. Written by `export_cogs.py` from the snow WebPs and served from R2 at
`/snow/api/tile/{date}/{file}` with HTTP Range support. Catalogued in the
static STAC at `/snow/stac/catalog.json` (only dates in `dates.json`).

`snowline/site/terrain/shade.json` and `/snow/api/terrain/shade/{z}/{x}/{y}.webp`
(R2 key `terrain/shade/...`): lidar terrain shading, 512 px web-mercator
tiles z8–13, black RGB with the shading in alpha (0 = flat or sunlit, up to
160 in shadow). Made by `build_lidar_terrain.py` from the USGS 3DEP 1 m DEM
(664 tiles over the AOI on 2026-10-06, read at the COGs' 4 m overview).
Shaded per source tile in UTM, with neighbours as margin, then reprojected,
because shading after reprojection showed aliasing stripes in testing. Where
surveys overlap, the most recently flown wins (year from the 3DEP project
name, e.g. `MT_Statewide_Phase5_D23` → 2023). Outside coverage the worker
answers 204.

`snowline/site/data/snow_timeline.json`: per tile, `[date, snow_pct,
cloud_pct]` for scenes with cloud ≤20 and nodata <50, from 2015 on.
Measured 2026-10-05: 3,139 scenes, of which 2015–2017 have 0 and 2022 has
18. The index's AGENTS.md says the C1 reprocessing hasn't reached those
years yet. That's a gap in the index, not a gap in the imagery.

`snowline/site/data/snotel_agreement.json`: per date, `evaluated, agree,
pct, snow_agree, bare_agree, miss, false_snow, cloud, stations[]`. A
station counts as snow at depth ≥2 in and as bare at 0. The map class is
the majority of snow vs. ground pixels in a 3×3 window. Cloud, nodata and
1 in are not counted.

## Measured quality

On 2025-11-30, the older per-tile pipeline's map agreed with 4 of 23
SNOTEL stations. The same date reprocessed with the current pipeline
agreed with 20 of 23 (87%), and snow cover went from 58.2% to 85.5% of
imaged pixels (2026-10-05). The 2025–26 season was reprocessed for that
reason, with the SCL snow term, on 2026-10-06. After that, 39 listed
maps (2025-10-06 to 2026-10-03) agree with SNOTEL on 530 of 643
station-days (82%). There are 87 misses and 26 false snow, and spring
maps do best. Most remaining misses are stations under forest canopy or in
midwinter shadow (see `snowline/site/methods.html`). Twelve passes that
imaged under 10% of the area were processed but aren't listed.

## Working in this repository

* Python for pipelines and tooling. Plain HTML/JS front end, no build step.
* Run a module's `__main__` smoke test on one tile and one date before
  anything bigger. Full dates read about 2 GB.
* Never print, commit or move a `.env` or a token. Tiles go to R2, not git.
* Don't put Data4 code or data here. It is a separate, private product.
* Every number on the site gets a visible, linked source line.
