# Line Network — Open Source Build Guide

> **For the agent picking this up.** Read this whole file first, then `CLAUDE.md`, then the `PLAN.md` of whichever product you are touching. This guide sets the direction. Each `PLAN.md` holds the current state. When you finish a phase, tick it here and update that product's `PLAN.md`.

**Written:** 2026-10-05 · **Owner:** Ian Van Dusen (Ito Geospatial)

> **Progress 2026-10-05 (evening session).** Phases 0–3 are done except where marked, plus 6.1 (STAC + COGs) and 6.2 (launch draft). Snowline launch target: **2026-10-10**. Two blockers are Ian's: the Cloudflare R2 setup (`docs/cloudflare-setup.md`; the live map has served no tiles since the monorepo move) and the repo visibility decision (0.2). Findings worth knowing: the C1 switch is pixel-identical after the offset fix, and the SNOTEL check exposed bad Nov–Mar maps from the old per-tile pipeline. Snow is now `NDSI ≥ 0.4 or SCL = 11` (better in midwinter shadow, no new false snow), and the whole 2025–26 season was reprocessed: 39 listed maps, 82% station-day agreement with SNOTEL. An independent review agent followed the README from zero, and its 14 findings were fixed (see the commit "Fixes from an independent release review").

---

## 1. What we are making

The Line Network (`snow.line.itogeospatial.com`, `river.line.itogeospatial.com`, and later sky) becomes a **fully open-source** Montana outdoor-conditions project. It does not need to make money, but it should be good enough to be cited and forked. The quality bar is Taylor Geospatial's [S2 STAC GeoParquet explorer](https://research.taylorgeospatial.org/s2-stac-geoparquet/), which works like this:

- Static files and no API server. Anyone can reproduce the results with DuckDB and a URL.
- Every number on screen traces back to a source someone can open.
- Agent and human docs ship next to the data (`README.md` and `AGENTS.md`).
- It is calm, fast, and looks right on a phone.

**Data4 stays separate and private.** None of the Data4 code, data, layers, recorder work or Pro features go into this repo. Nothing from Data4 is copied here.

---

## 2. The imagery source: S2 STAC GeoParquet (required)

All Sentinel-2 scene discovery moves to the Taylor Geospatial / TGE Labs mirror of the Earth Search index on Source Cooperative. This replaces every `pystac_client.Client.open(...).search(...)` call against Element 84 and Planetary Computer.

**Important: the GeoParquet is the index, not the pixels.** Each row's `assets` column points to the same public Sentinel-2 COGs on AWS (`e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/...`). Snowline already reads those COGs today. The parquet replaces the slow, rate-limited STAC API search with a single SQL query, and it covers every year since 2015.

### Facts measured on 2026-10-05 (re-check them, don't trust them blindly)

| Thing | Value |
|---|---|
| Collection to use | `sentinel-2-c1-l2a`, ESA's Collection 1 reprocessing. The upstream AGENTS.md says to query this one first. |
| Year archive | `https://data.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/year=YYYY/items.parquet` (2026 is about 4.8 GB, but DuckDB fetches only the row groups it needs) |
| Current-year live files | Same folder: `live-MM.parquet`, plus `live.parquet` for the last 5 days. The list is in `year=YYYY/YYYY.json` → `assets`. **A query against `items.parquet` alone stops at roughly the last consolidation, which was 2026-09-16 when checked. Union the live files for anything recent.** |
| Glob access | `s3://us-west-2.opendata.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/year=*/*.parquet` (anonymous). DuckDB won't glob over https. |
| Tile column | `_tile`, e.g. `'12TVR'`, with no leading T. The data is sorted by tile, so tile filters are fast (about 7 s for a 2026 query from a cloud box). |
| Useful columns | `id`, `datetime`, `"eo:cloud_cover"`, `"s2:snow_ice_percentage"`, `"s2:nodata_pixel_percentage"`, `"s2:cloud_shadow_percentage"`, `"s2:water_percentage"`, `"s2:vegetation_percentage"`, `"proj:epsg"`, `geometry`, `thumbnail_url`, `assets` (a JSON string) |
| Asset keys | `red green blue nir nir08 nir09 rededge1-3 swir16 swir22 scl cloud snow visual thumbnail preview aot wvp coastal` + metadata. Use `json_extract_string(assets, '$.swir16.href')` |
| Monthly stats | `.../stats-c1/mgrs-monthly.parquet` with columns `mgrs_tile, year, month, scene_count, min_cloud_cover, median_cloud_cover, mean_cover, max_cover, best_item_id, best_item_date` |
| Update cadence | Refreshed daily at 03:42 UTC (last 5 days). Folded into monthly files on the 3rd of each month. |
| Licence | Code is Apache-2.0. Imagery falls under the Copernicus Sentinel terms (free, full and open; attribution required). |
| Docs to read before coding | `https://data.source.coop/tge-labs/s2-stac-geoparquet/AGENTS.md` and `.../sentinel-2-c1-l2a/AGENTS.md` (schema, expected NULLs, the `assets` contract) |

### Reference query (Python + DuckDB)

```python
import duckdb
BASE = "https://data.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/year=2026"
FILES = [f"{BASE}/items.parquet", f"{BASE}/live-09.parquet", f"{BASE}/live-10.parquet", f"{BASE}/live.parquet"]
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET TimeZone='UTC';")
rows = con.execute("""
  SELECT id, datetime, "eo:cloud_cover" AS cloud, "s2:snow_ice_percentage" AS snow,
         json_extract_string(assets,'$.green.href')  AS green,
         json_extract_string(assets,'$.swir16.href') AS swir16,
         json_extract_string(assets,'$.scl.href')    AS scl
  FROM read_parquet(?, union_by_name=true)
  WHERE _tile IN ('12TVR','12TUR','12TVQ','12TUQ','12TWR','12TWQ')
    AND datetime >= now() - INTERVAL 10 DAY
  ORDER BY datetime DESC
""", [FILES]).fetchall()
```

Build the list of live files from `year=YYYY/YYYY.json` instead of hard-coding the months.

### Pitfalls you must handle

1. **Collection 1 reflectance offset.** `sentinel-2-l2a` (the old collection snowline uses now) and `-c1-` scale DN differently. Processing baseline 04.00+ applies a −1000 offset. NDSI is a ratio, so an uncorrected offset moves the snow line. Read `raster:bands` scale/offset from each asset (or follow the c1 AGENTS.md), apply it, and check one known date against the current output before switching over (see acceptance test S2).
2. **Duplicate passes.** The same tile and date can appear twice (two datatakes or baselines, e.g. S2A and S2B on 2026-09-13). Dedupe by tile and date, keeping the lowest `"s2:nodata_pixel_percentage"` and then the lowest cloud.
3. **Item IDs changed format.** The c1 format is `S2B_T12TVR_20260916T182452_L2A`, not `S2C_12TUQ_20260404_0_L2A`. Fix `parse_tile_id()` and anything else that parses IDs. Prefer the `_tile` column over parsing.
4. **Don't download the 4.8 GB file.** Always query it remotely with a `_tile` and `datetime` filter. In CI, cache the small per-AOI result (`snowline/site/data/scenes.parquet`) and diff against it.

### Can this source *all* of our data?

No, only the satellite-derived layers:

| Layer | S2 GeoParquet? | Source |
|---|---|---|
| Snow cover (Snowline) | **Yes**, primary | S2 green + swir16 + SCL |
| Scene availability / "next clear pass" | **Yes**, replaces `build_sat_availability.py` | parquet metadata only |
| Historical snow per tile, 2015→ | **Yes**, a new freebie | `s2:snow_ice_percentage` per scene, no pixel downloads |
| River width / ice / turbidity (RiverLine) | **Yes**, a later layer | S2 water mask (SCL=6, NDWI) |
| Burn scars, green-up (SkyLine/DataLine later) | Yes | NBR / NDVI |
| Landsat / HLS gap-filling | No | Keep Planetary Computer or drop it. Optional. |
| SNOTEL, USGS gauges, NWPS forecasts, weather, webcams | **No** | Their own APIs (unchanged) |
| MODIS 25-year history (`build_historical.py`) | No | Leave it as is |

---

## 3. House rules (from CLAUDE.md, plus these)

- **Python only** for pipelines and tooling. Front end stays static HTML/JS, and `_worker.js` stays JS (Cloudflare needs it).
- **Never run pipelines or large downloads in the background.** Write the code, run the `__main__` smoke test on one tile and one date, then hand Ian the exact command.
- **Never print, cat, echo or commit `.env`** or any token. `.env` is gitignored, so keep it that way. The old `CF_API_TOKEN` needs rolling (Ian's job). Don't paste tokens into workflows. Use GitHub secrets.
- Every new module lives under `src/` or `pipeline/` and has a `if __name__ == "__main__":` smoke test.
- Commits end with Ian's usual co-author trailer. Don't push without asking.
- Everything shown on screen gets a visible source line, linked.
- Don't touch Data4.

---

## 4. Phases and tasks

Work top to bottom. Each task has an acceptance test, and a task is done only when the test passes.

### Phase 0 — Make it safe to open (do this first)

- [x] **0.1 Secret scan.** *(gitleaks 8.21.2 over all 62 commits, 2026-10-05: 7 hits, all the Mapbox public `pk.` browser token in HTML. No `.env` ever committed. Restrict the token to the site's URLs in the Mapbox dashboard.)* Run `gitleaks detect --source . --log-opts="--all"` (or `trufflehog git file://.`) across the full history. Report anything it finds to Ian, but **don't print the values**.
      *Test:* zero findings, or a list of file:commit references Ian has acknowledged.
- [ ] **0.2 History decision.** *(Measured: reachable history is ~100 MB of blobs, mostly RiverLine geojson. The 1.9 GB is local `.git` garbage, not history. **Recommendation changed: make `itogeo/line` public as it is.** That keeps the Pages project, Actions and secrets working with no new setup. A fresh repo would need a new Pages project, bindings, domain move and secrets before Oct 10.)* `.git` is 1.9 GB (old WebPs). Recommend publishing as a **fresh public repo with one squashed initial commit** (`itogeo/line-network`, or rename), and keep the old repo private as an archive. Ian decides. Don't rewrite or force-push anything yourself.
- [x] **0.3 Licence files.** `LICENSE` is Apache-2.0 (code). `DATA_LICENSE.md` covers Copernicus Sentinel terms + attribution, USGS (public domain), NRCS SNOTEL (public domain), NOAA (public domain), and webcam images (owners' terms: link only, don't redistribute).
      *Test:* both files exist, and the README links them.
- [x] **0.4 Clean the tree.** Add `.DS_Store`, `.wrangler/`, `riverline/raw/`, `**/cache/` to `.gitignore`. Delete tracked junk only after confirming it is unused.
- [x] **0.5 Public docs.** *(README with Mermaid diagram, CONTRIBUTING, AGENTS. Screenshots in docs/img/.)* Top-level `README.md` is a one-screen pitch, has a screenshot per product, and includes "Reproduce it yourself" (a DuckDB snippet) plus an architecture diagram (Mermaid). `CONTRIBUTING.md` covers dev setup with `python -m venv`, `pip install -r`, and smoke tests. `AGENTS.md` is written in the Taylor style: every claim quoted or measured.

### Phase 1 — Shared S2 library

- [x] **1.1 `lib/s2index.py`** with these functions:
      - `live_files(year)`: reads `YYYY.json`
      - `scenes(tiles, start, end, max_cloud=None)`: returns a list of dicts, deduped as in pitfall 2
      - `asset_href(row, band)`
      - `scale_offset(row, band)`
      - `monthly_stats(tiles, year)`

      Uses only `duckdb`, and nothing else heavy.
      *Test:* `python -m lib.s2index` prints the latest 3 scenes for 12TVR with dates within the last 10 days, plus the October stats row.
- [x] **1.2 `lib/aoi.py`** is the single source of the AOI bbox and MGRS tile list for each product. Today `BBOX` is copied across snowline scripts.
      *Test:* `grep -rn "BBOX =" snowline/pipeline` only imports from `lib`.
- [x] **1.3** Add `duckdb` to `snowline/pipeline/requirements.txt`. Remove `pystac-client` only after Phase 2 passes. Keep `planetary-computer` only if Landsat/HLS stays.

### Phase 2 — Snowline onto the parquet

- [x] **2.1 `fetch_bands.py`.** *(Offset removed at download, so process_tiles is unchanged.)* Replace `find_scenes()` with `lib.s2index.scenes()`. Read `green`, `red`, `blue`, `swir16`, `scl` hrefs from `assets`. Apply the c1 scale/offset in `process_tiles.py` before computing NDSI.
- [x] **2.2 `build_sat_availability.py`.** S2 rows come from the parquet (metadata only, no pixels). Add `snow_pct` and `nodata_pct` per pass to `sat_availability.json` so the UI can say "62% snow, 3% cloud" before imagery is processed.
- [x] **2.3 `check_new_clear_pass.py`** uses the parquet. A pass qualifies when the AOI tiles' cloud ≤ threshold and nodata < 50%.
- [x] **2.4 Diagnose & retire.** *(Planetary Computer stays only for the yearly forest/MODIS builds: `requirements-assets.txt`.)* Update `diagnose_tile.py`. Remove the Element 84 API calls everywhere (`grep -rn earth-search` should return nothing except docs).
- [x] **2.5 New: `build_snow_timeline.py`.** For every AOI tile from 2015 to now, write `s2:snow_ice_percentage`, cloud and date to `site/data/snow_timeline.json`, using metadata only. This gives a decade of per-tile snow history without downloading any pixels. Show it on the data page as a small multiples chart.

**Tests:**

- **S1:** `python snowline/pipeline/fetch_bands.py --date=<a recent clear date>` downloads all bands for every AOI tile. Ian runs it, or you run it on one tile only.
- **S2 — PASSED 2026-10-05:** 12TVR 2026-04-19, 0 differing pixels in 5 bands, snow pixels 2,776,856 both ways. Reprocess one date already live (pick from `site/data_10m/dates.json`, e.g. a clear April 2026 date). The snow-pixel count is within ±2% of the current output for the same date. If it isn't, the offset handling is wrong. Stop and report.
- **S3 — needs a push:** Both workflows (`snowline-daily.yml`, `snowline-process-imagery.yml`) pass on `workflow_dispatch` with no Element 84 calls in the log.

### Phase 3 — Snowline polish (the "nice project" part)

- [x] **3.1 Data page.** A Taylor-style scene table (date · tile · cloud · snow % · thumbnail · "open COG") that you can filter by tile, cloud and year, read from the parquet results. Each row gets a "reproduce in DuckDB" copy button.
- [x] **3.2 Map.** *(Basemap left as is.)*
      - Muted basemap, so the snow layer is the brightest thing on screen.
      - The date scrubber shows clear and cloudy passes in different colours.
      - A "next expected pass" chip, computed from the 5-day revisit and the last pass per tile.
      - URL state in the hash (`#map=z/lat/lon&date=...&tile=...`) so views can be shared, like the Taylor URL.
- [x] **3.3 SNOTEL vs satellite.** *(`build_snotel_agreement.py` → panel line + Methods table.)* At each station, compare the depth reading with the snow/no-snow pixel value. Show an agreement score per date. This is the credibility feature.
- [ ] **3.4 Mobile + performance.** *(Phone layout checked in headless Chromium. Lighthouse not run on the live site yet.)* Lighthouse ≥ 90 on mobile. First paint under 2 s on 4G. No layout shift.
- [x] **3.5 Methods page.** *(No example images yet.)* NDSI threshold, SCL masks used, forest mask, known failure modes (cloud/snow confusion, terrain shadow, forest canopy), each with an example image. Written plainly.

### Phase 4 — RiverLine finish

RiverLine's code side is done. What's missing is infra and data (see `riverline/PLAN.md`).

- [ ] **4.1** Write `riverline/SETUP.md`: the exact Cloudflare clicks/commands for the KV `riverline-kv`, D1 `riverline-db`, `migration.sql` and the 4 secrets. **Ian performs them.** You never handle tokens.
- [ ] **4.2** Once Ian confirms, run `scripts/migrate_to_d1.py` dry-run mode, then hand off the real command. Re-enable `riverline-ingest.yml`.
      *Test:* `river.line.itogeospatial.com` shows the live CFS for USGS 06043500 that matches waterservices.usgs.gov within one ingest cycle.
- [ ] **4.3** Optional, later: a river-ice / width layer from the S2 water mask over the Gallatin reach, using `lib.s2index`.

### Phase 5 — SkyLine & DataLine (plan only)

- [ ] **5.1** Turn `skyline/docs/data-sources.md` into a `skyline/PLAN.md`: NWS gridpoint forecasts + HRRR (open on AWS), with S2 used only for post-storm snow extent. No code until Ian approves the plan.
- [ ] **5.2** DataLine is empty. Propose one paragraph: "the open data catalog for the network". It would be a STAC catalog (`catalog.json`) of everything Line publishes, so the network itself is Portolan/Source Cooperative-browsable, like the Taylor mirror. Plan only.

### Phase 6 — Ship

- [x] **6.1** *(Class COGs per map via `export_cogs.py`, static STAC at `/snow/stac/catalog.json`, served from R2 with Range support. No public bucket needed.)* Publish Line's own derived outputs (snow masks per date, `scenes.parquet`, `snow_timeline`) as **open data** with a `catalog.json`. They go on the existing public R2 bucket, or onto Source Cooperative if Ian wants (ask).
- [x] **6.2** Write the launch note: a `docs/launch.md` draft that credits Taylor Geospatial / TGE Labs, Element 84 and ESA Copernicus. Ian posts it.
- [ ] **6.3** Final check by a fresh agent that hasn't seen the work: clone the public repo, follow the README from zero, reproduce one snow map. Every failure becomes a fix.

---

## 5. Hand-off checklist (Ian)

- Roll `CF_API_TOKEN` and set the GitHub secrets (Phase 0 / 4.1).
- Decide: fresh public repo vs make `itogeo/line` public (0.2).
- Run the long commands the agent hands you: backfills and the D1 migration.
- Approve the SkyLine plan before any code is written.

## 6. Done looks like

Someone who has never heard of Ito Geospatial lands on snow.line.itogeospatial.com, sees today's snow line, clicks a pixel, sees the scene it came from, clicks "reproduce", and gets the same answer on their own laptop with DuckDB. The code is on GitHub under Apache-2.0.
