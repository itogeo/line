# RiverLine — Draft Plan

> **Workflow note.** This file is the persistent draft plan for the RiverLine project. It is read at the start of every Claude session so context doesn't have to be re-discovered, and updated at the end of every working session. Keep it accurate; treat it as the single source of truth for "what is RiverLine and where are we." Network-level companion: [`../PLAN.md`](../PLAN.md).

**Last updated:** 2026-06-17
**Status:** **CF-first reboot complete (code side).** All five new files written: `scripts/migrate_to_d1.py`, `src/ingest/push_cf.py`, `.github/workflows/ingest.yml` (no more git data commits), `site/_worker.js` (KV + D1 edge API), `site/index.html` (Daily Water Briefing frontend). **Pending user actions**: create KV namespace `riverline-kv` + D1 database `riverline-db` + run migration + add 4 GitHub secrets + create CF Pages project with bindings.

---

## Vision

RiverLine is the one-stop river dashboard for Montana — a sleek, fast, modern site that aggregates every relevant piece of public hydrological data into a single experience. We do **not** create new data; we surface government data better than the agencies do themselves.

**Reference point we're outclassing.** [levels.wkcc.org/?P=Montana.html](https://levels.wkcc.org/?P=Montana.html) is the current incumbent for Montana river info — a static HTML table of ~100 gauges showing CFS / height / temperature / change-arrow. No map, no forecasts, no snowpack context, no reservoir releases, no alerts, no history graphs, no mobile design. We want everything that page has, plus the future (forecasts), plus context (snowpack, reservoirs, weather), plus a UI people actually want to use.

**Strategy: complement NOAA, don't compete.** NOAA's National Water Prediction Service already publishes forecasts. We embed/surface them — we don't try to beat them on prediction quality. Our edge is **aggregation + UX + Montana focus**, not better hydrology.

**Pilot scope.** **One gauge: USGS 06043500 Gallatin River near Gallatin Gateway, NWPS forecast point GLGM8.** Not "the Gallatin basin" — one gauge. Get every data source flowing for that one site, polish the UI for it, deploy it, *then* expand to other Gallatin gauges, then other basins, then statewide. Resist scope creep aggressively. Locked in 2026-04-07.

---

## Decisions (locked in 2026-04-07)

1. **Audience:** All three (anglers, boaters, general public) equally in v1. No audience gets cut.
2. **Forecast horizon:** Everything NWPS publishes — short (0-72h), medium (10-day), and long-range where available. UI surfaces all of them with clear horizon labels.
3. **Hosting:** Cloudflare Pages for the static site + GitHub Actions cron for the ingest job. Action runs the pipeline on a schedule, commits the fresh `current.json` and updated parquet files to the repo, CF Pages auto-deploys. Zero servers, zero hosting cost. Same pattern as Snowline.
4. **Storage:** Flat files (parquet history + JSON current snapshot) with **DuckDB** as the query layer when SQL is needed. DuckDB reads parquet directly, runs in-process, has a WASM build for client-side analytics later. No DB to host. Graduate to Postgres only if a future feature genuinely demands a server.

---

## Data Sources

### Tier 1 — Core Streamflow (must-have for v1)

| # | Source | What it gives us | API | Gallatin sites |
|---|--------|------------------|-----|----------------|
| 1 | **USGS NWIS Instantaneous Values** | Latest discharge (CFS), gage height (ft), water temp. **Snapshot only** — fetched every cron tick into `current.json`, never persisted to history (we don't need 15-min depth because we don't train models) | `waterservices.usgs.gov/nwis/iv/` | **5 active Gallatin gauges** (verified 2026-04-07 via site service): 06043120 above Deer Creek nr Big Sky, **06043500 nr Gallatin Gateway** (canonical), 06048650 E Gallatin ab Water Reclamation nr Bozeman, 06050000 Hyalite Creek at Hyalite Reservoir, 06052500 at Logan. No active IV on W Fork or Taylor Fork. Note: not every gauge has water temp (Gateway has discharge + gage height only). |
| 2 | **USGS NWIS Daily Values** | Daily mean discharge — **the only history we keep**. Full period of record on first pull, then one new row per gauge per day. Powers history charts and percentile bands. | `waterservices.usgs.gov/nwis/dv/` | Same sites |
| 3 | **USGS NWIS Site Service** | Gauge metadata: lat/lon, drainage area, datum | `waterservices.usgs.gov/nwis/site/` | All MT gauges (one-time pull) |
| 4 | **USGS Statistics Service** | Daily P10/P25/P50/P75/P90 by day-of-year — powers the "is this flow normal?" chart | `waterservices.usgs.gov/nwis/stat/` | Gallatin sites |

### Tier 2 — Forecasts

| # | Source | What it gives us | API |
|---|--------|------------------|-----|
| 5 | **NOAA NWPS** | Official short, medium, long-range river forecasts at AHPS points | `api.water.noaa.gov/nwps/v1/gauges/{lid}` |
| 6 | **NOAA National Water Model** *(stretch)* | Continuous gridded forecasts on every NHD reach — fills gaps where there's no AHPS point | NWM via NOMADS / AWS Open Data |
| 7 | **NWS NDFD / api.weather.gov** | Local precip + temperature forecasts above each gauge | `api.weather.gov/points/{lat,lon}/forecast` |

### Tier 3 — Watershed Context (the "all in one place" advantage)

| # | Source | What it gives us | API |
|---|--------|------------------|-----|
| 8 | **NRCS SNOTEL (AWDB REST)** | SWE, snow depth, soil moisture, precip at upper-basin stations | `wcc.sc.egov.usda.gov/awdbRestApi/services/v1/` — Gallatin: Lone Mountain (590), Shower Falls (737), Carrot Basin (366), Brackett Creek (357) |
| 9 | **NOHRSC SNODAS** *(stretch)* | Daily 1km gridded SWE for whole basin | NSIDC FTP / NOHRSC web service |
| 10 | **USBR Hydromet** | Reservoir releases & storage. N/A for free-flowing Gallatin; activates with Madison/Missouri/Flathead rollout | `usbr.gov/pn/hydromet/`, `usbr.gov/gp/hydromet/` |
| 11 | **MT FWP Hoot Owl / Closures** | Fishing-restriction status — angler-critical | Scrape `fwp.mt.gov/aboutfwp/news/hoot-owl-restrictions` (no public API) |

### Tier 4 — Nice-to-have / future

| # | Source | What it gives us |
|---|--------|------------------|
| 12 | **USGS Water Quality (WQX)** | Turbidity, sediment — relevant during runoff |
| 13 | **MesoWest / Synoptic** | Dense weather station network beyond NWS METARs |
| 14 | **EPA ECHO / NPDES** | Discharge permits — water quality storytelling |
| 15 | **Snowline (sibling)** | Reuse the HLS snow-cover-fraction layer from `repos/line/snowline/` as a basemap |

---

## Implementation Phases

### Phase 0 — Persistent draft plans ✅

- [x] Approved master plan
- [x] [`repos/line/riverline/PLAN.md`](./PLAN.md) (this file)
- [x] [`repos/line/PLAN.md`](../PLAN.md) (network-level index)

### Phase 1+2 — Build `src/ingest/` modules directly

**Workflow shift (2026-04-07):** notebooks 02–05 are cancelled. After notebook 01 proved the USGS API patterns, every remaining source is built as a production Python module under [src/ingest/](src/ingest/) with a `if __name__ == "__main__":` smoke test that pulls a real sample and prints/saves a summary. Same code = exploration tool + production cron job.

**Status of the historical notebook:**
- [x] `notebooks/01_usgs_nwis_gallatin.ipynb` ✅ — Historical artifact of first USGS exploration. 5 Gallatin gauges discovered, 96-yr DV history pulled (33k rows), 366 DOY stats, current snapshot, percentile-envelope plot rendered. Findings cell has the full report. **Will not be updated or extended; functions get lifted into `src/ingest/usgs.py` next.**

**Modules built (Gateway pilot):**
- [x] `src/ingest/usgs.py` ✅ — `nwis_sites()`, `nwis_dv()`, `nwis_stats()`, `nwis_iv_snapshot()`. Pulls all 5 Gallatin gauges (built before scope was narrowed to Gateway only — harmless extra data). Writes `data/sites.json` + `data/history/*.parquet` (104k rows total, back to 1900) + `data/stats/*.parquet` + `data/current_usgs.json`. **1.1 MB total footprint.**
- [x] `src/ingest/nwps.py` ✅ — `nwps_gauge_info(lid)`, `nwps_forecast(lid)`. Gateway-focused (`GLGM8`). Pulls flood thresholds (action 4846 / minor 6886 / moderate 9726 / major 11200 cfs), **79 historic crests** (1943→2024), downstream LID (LOGM8 = Logan), forecast reliability note. Writes `data/nwps/GLGM8.json` + `data/forecast/GLGM8.json`. Forecast empty in April (pre-runoff) — module handles that gracefully via `is_forecast_active()`.
- [x] `src/ingest/snotel.py` ✅ — `snotel_current(triplets)`. **Found 4 real upper-Gallatin SNTL stations** via HUC 10020008 query (verified live, not from memory): Carrot Basin (385, 9200 ft), Lick Creek (578, 6880 ft), Lone Mountain (590, 8820 ft), Shower Falls (754, 8060 ft). **Brackett Creek excluded** — it's in the Bridgers, drains to East Gallatin downstream of Gateway, doesn't feed it. Writes `data/snotel/<triplet>.json`. Current basin avg SWE: **15.7 in**.
- [x] `src/ingest/nws.py` ✅ — `nws_forecast(lat, lon)`. Two-step pattern (`/points/{lat,lon}` → `/gridpoints/.../forecast`). Returns 14 day/night periods. WFO is **TFX (Great Falls)** — same as the river forecast WFO. Writes `data/weather/GLGM8.json`.
- [x] `src/ingest/pipeline.py` ✅ — Orchestrator. Produces canonical **`data/current.json` (~9 KB)** containing: gauge metadata, current observed (CFS / stage / temp), flood thresholds, flood-category determination, forecast (when active), basin SWE summary + per-station snowpack, 4-day weather strip, top-10 historic crests. **This is the file the frontend reads.** Schema_version: 1.
- [x] `.github/workflows/ingest.yml` ✅ — GH Actions cron, every 30 min, runs `python -m src.ingest.pipeline`, commits any data changes back to the repo. CF Pages auto-deploys on push.
- [ ] `src/query/duckdb_helpers.py` — deferred until the frontend needs SQL queries against history. The current.json has everything for v1.

### Phase 2 — Ingestion service *(now folded into Phase 1+2 above)*

Original outline kept here for reference:

```
src/ingest/
├── usgs.py          # nwis_iv(), nwis_dv(), nwis_sites(), nwis_stats()
├── nwps.py          # nwps_forecast(lid)
├── snotel.py        # snotel_swe(station_triplet)
├── nws.py           # nws_forecast(lat, lon)
├── pipeline.py      # orchestrates all four, writes data/current.json + data/history/<site>.parquet
└── cache.py         # disk + in-memory caching (USGS rate-limits aggressively)

src/query/
└── duckdb_helpers.py  # flow_percentiles(), basin_swe(), etc. — reads parquet via DuckDB
```

Outputs go to:
- `data/current.json` — overwritten every run; latest IV reading per gauge + latest forecast + latest SNOTEL/weather context. Frontend reads directly.
- `data/history/<site_id>.parquet` — daily mean values only, append-only (one row per day per gauge). No instantaneous data.
- `data/stats/<site_id>.parquet` — pre-computed P10/P50/P90 by day-of-year. Refreshed annually, otherwise static.

GitHub Actions workflow at `.github/workflows/ingest.yml` runs the pipeline on a cron (start at 15-min cadence to match USGS IV; back off to hourly if rate-limited), commits any changed data files. **The repo is the database.**

### Phase 3 — Frontend ([site/](site/))

**v0 shipped 2026-04-07.** Single static `site/index.html` with Leaflet + Esri World Topo basemap. Renders 14 HUC10 sub-basins for the Gallatin colored by SWE %-of-normal in the NRCS map style, with centered % labels, stats card showing live Gateway flow, legend, and a placeholder badge. Basin polygons fetched from USGS WBD layer 5 once and cached at `site/data/gallatin_hucs.geojson` (730 KB). Clicking any polygon shows a popup with name + HUC10 code + %.

**Note on the library choice:** originally tried MapLibre GL JS to match Snowline's pattern, but its v4 GeoJSON worker silently fails to tile features in headless chromium (no errors, source.loaded()=true, querySourceFeatures returns 0). Tried inline data, swiftshader WebGL, longer waits, simpler test polygons — none rendered. Swapped to Leaflet which "just works" and is the right call for "show some polygons on a basemap" anyway. Snowline can stay on MapLibre — RiverLine will use Leaflet.

**Open work for Phase 3:**

- [ ] **Real SWE %-of-normal computation.** Currently mocked. Need a `src/ingest/snotel_normals.py` (lift Snowline's `build_snotel_normals.py` pattern) that pulls each station's full historical WTEQ, computes 30-yr (1991–2020) median by day-of-year, then the pipeline divides today's reading by today's median to get %. Per-polygon basin %s come from spatially aggregating the SNOTEL stations to their containing HUC10.
- [ ] **Per-gauge detail panel.** Click the Gateway gauge → opens a panel with: current CFS + arrow, day-of-year percentile chart (the one from notebook 01), 7-day NWS weather strip, basin SWE breakdown, NWPS flood thresholds + closest historic crests, hoot-owl status (when wired).
- [ ] **Forecast panel** for when NWPS issues a runoff forecast (currently empty in April pre-runoff). The pipeline already captures it; the UI just needs to render it.
- [ ] **Mobile responsiveness pass** beyond the basic media query already in the CSS.
- [ ] **Cloudflare Pages deploy.** Connect the repo, output dir = `site/`. The cron (`.github/workflows/ingest.yml`) commits data updates back to the repo, CF Pages auto-deploys on push.

When we get here, original frontend wishlist:
- Map view of gauges (Mapbox, consistent with mtpublic)
- Per-gauge detail page: current CFS + arrow, history, all NWPS forecast horizons, normal-range envelope, basin SWE widget, weather strip, hoot-owl status
- Cross-gauge comparison
- Mobile-first
- 100% static — every consumed asset is a file on the same CDN

### Phase 4 — Beyond Gallatin

Adding a new basin = config file (gauge IDs + SNOTEL station triplets + NWPS LIDs). No new code. Statewide rollout is then mechanical.

---

## Verification

- **End of Phase 1:** open `05_data_join.ipynb` and confirm the joined dataframe has, for the Gallatin Gateway gauge right now, a row containing: current CFS, height, temp, today's normal range (P25–P75), 7-day NWPS forecast, basin-average SWE, 5-day precip forecast — all from public APIs.
- **End of Phase 2:** `python -m ingest.pipeline` produces a fresh `current.json` and updated `history/*.parquet` for all Gallatin gauges in under 30 seconds. `.github/workflows/ingest.yml` runs cleanly on a cron.

---

## Reusables from sibling projects

- **Snowline ([../snowline/](../snowline/))** — already runs the exact deployment pattern we want (Cloudflare Pages + GH Actions cron + parquet/JSON outputs committed to repo). Lift the workflow YAML and the AWDB SNOTEL ingest code directly. The HLS snow-cover layer becomes a free basin-context basemap.
- **mtpublic webapp** — Mapbox GL JS patterns, ArcGIS REST tile sources, PMTiles protocol setup. All directly reusable when Phase 3 begins.

---

## Session log

- **2026-04-07** — Project vision clarified (complement NOAA, beat wkcc on UX, Gallatin pilot). All four open decisions resolved. Draft plans seeded.
- **2026-04-07** — Project venv (`.venv/` Python 3.9.6 + numpy 2 + pandas 2.3 + matplotlib 3.9 + pyarrow 21) and `requirements.txt` created. Anaconda env was unusable (numpy 1↔2 ABI breakage). Notebook 01 written, executed, debugged (added `siteOutput=expanded` to site service call), and verified end-to-end. Plot rendered correctly. Open items surfaced: P90 NaN for early-Jan in stats service, no temp sensor at Gateway, parameter 00010 vs 00011 question for other MT gauges. Storage strategy clarified: only DV persisted, IV is snapshot-only. Plan corrected — sites are Logan not Manhattan, no W Fork or Taylor Fork IV gauges exist.
- **2026-04-07** — **Workflow shift:** notebooks 02–05 cancelled. From here, every source is built directly as a `src/ingest/<source>.py` module with `__main__` smoke test. One codebase, runnable in production, no two-step rewrite. Phase 1 + Phase 2 collapsed.
- **2026-04-07** — **Scope narrowed to Gateway only.** User pushed back on "all 5 Gallatin gauges" — pilot is **one gauge** (USGS 06043500 / NWPS GLGM8). Get every data source flowing for it, polish UI, deploy, then expand.
- **2026-04-07** — **Phase 1+2 complete for Gateway.** All 4 ingestion modules (`usgs.py`, `nwps.py`, `snotel.py`, `nws.py`) + the orchestrator (`pipeline.py`) built and verified end-to-end. `data/current.json` (~9 KB) is now the canonical contract. GH Actions cron at `.github/workflows/ingest.yml` runs every 30 min and commits back to the repo. Surprises learned: NWPS state-wide query 504s (use direct LID lookup); Brackett Creek isn't in the Gallatin Gateway watershed (it's in the Bridgers); Gateway gauge has no temp sensor; NWPS forecast is empty in winter/early spring (reliability note explains this is normal); NWPS has 79 historic crests on file going back to 1943.
- **2026-04-07** — **Ready for Phase 3 (frontend).** Data side is done for the pilot gauge.
- **2026-04-07** — **Phase 3 v0 shipped.** Built `site/index.html` mimicking the NRCS SWE %-of-normal map but scoped to the Gallatin only. 14 HUC10 polygons fetched from USGS WBD layer 5 (`huc10 LIKE '10020008%'`), saved to `site/data/gallatin_hucs.geojson` (730 KB). Mocked SWE %s with seeded random values for visual placeholder; clearly badged. Live Gateway flow (557 cfs) wired in from `data/current.json`. **Library swap:** intended to use MapLibre GL JS but its v4 GeoJSON worker silently failed to tile features in headless chromium. Switched to Leaflet, which renders polygons reliably first try.
- **2026-06-17** — **CF-first reboot (Session B+C complete — code side).** Retired "repo as database" pattern for ingest data. New storage: CF KV (`gateway:current`) + CF D1 (`daily_flow`, `doy_stats`). New files: `scripts/migrate_to_d1.py` (generates `migration.sql` from parquets), `src/ingest/push_cf.py` (stdlib urllib only, KV PUT + D1 INSERT), `ingest.yml` updated (no git commit step — CF is now the source of truth), `site/_worker.js` (`/api/current` → KV, `/api/chart` → D1 90-day + 366 doy bands), `site/index.html` rebuilt as "Daily Water Briefing" (hero CFS + trend + level badge, 10-day stage forecast Chart.js, audience cards Float/Wade/Water, 90-day history + P10-P90 shaded band, 7-day weather strip, collapsible snowpack + crests). CF token accidentally exposed in chat — token was rolled immediately; current valid token in `riverline/.env`. **Pending user**: create KV + D1 in CF dashboard → run `wrangler d1 create riverline-db` → run migration → add 4 GitHub secrets (`CF_ACCOUNT_ID`, `CF_KV_NS_ID`, `CF_D1_DB_ID`, `CF_API_TOKEN`) → create CF Pages project connected to `itogeo/riverline`, add `RIVERLINE_KV` KV binding + `RIVERLINE_DB` D1 binding.
