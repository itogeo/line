# Snowline — Plan

> Read this at the start of any Snowline session. Update end-of-session.

**Last updated:** 2026-06-17

---

## Status: Live at [snowline.itogeospatial.com](https://snowline.itogeospatial.com)

Automated daily pipeline: Sentinel-2 NDSI → snow cover map → SNOTEL comparison. Deployed on Cloudflare Pages with GitHub Actions.

---

## What's been built

### Core map (`site/index.html`)
- Mapbox GL JS snow cover raster + SNOTEL gauge dots
- Date picker cycling through available scenes
- Partial coverage handled gracefully in UI

### Webcam page (`site/webcam.html`)
Full-featured webcam dashboard:
- **Mapbox GL JS** map with viewshed fan icons (bearing-rotated, anchor bottom)
- **14 MDT RWIS cameras** via `/api/mdtcam` worker proxy (posId pattern: `564{station*10+cam}`)
- **Non-MDT cams**: NPS Yellowstone (img/proxy), ipcamlive embeds, KBZK streams
- **Timestamp system**: `stampLoad(i)` / `stampErr(i)` update `.cam-ts` spans on load/error; green flash for fresh images
- **Auto-refresh**: 2-min cycle for img cams, timestamp reset on each refresh
- **Mobile CSS**: breakpoints at 620/480/380px; single-col at 380px, count/refresh pill hidden at 480px
- **`_worker.js`** edge worker: `/api/camproxy` (CORS image proxy), `/api/mdtcam` (MDT RWIS latest image), `/api/snotel`, `/api/feedback`

### MDT camera posId pattern
`564{stationIndex * 10 + cameraIndex}` — e.g. Three Forks station 12 cam 0 = `564120`

---

## Architecture: Imagery in CF R2 (not git)

As of 2026-06-17, WebP tiles are stored in Cloudflare R2, not committed to git.
Git repo only commits: `site/data/snowline.json`, `site/data_10m/dates.json`, `site/data_10m/{date}/snowline.json`.

### Tile pipeline
```
pipeline/update_date.sh → process_tiles.py → WebPs in site/data_10m/{date}/ →
  curl PUT to CF R2 bucket "snowline-tiles" at key "tiles/{date}/{filename}.webp"
  (guarded: only runs when CF_ACCOUNT_ID + CF_R2_TOKEN env vars are set)
```

### Tile serving
`site/_worker.js` handles `GET /api/tile/{date}/{filename}.webp`:
1. Look up R2 key `tiles/{date}/{filename}.webp` via `env.SNOWLINE_BUCKET.get(key)`
2. If found → return `image/webp` with `Cache-Control: max-age=86400`
3. If not found (old date still in git) → rewrite to `/data_10m/{date}/{file}` and serve from Pages static assets

### Frontend URL
Tile references in `site/index.html` use `/api/tile/{date}/snow_r0c0.webp` (not `/data_10m/`).
JSON metadata (`dates.json`, per-date `snowline.json`) still fetched from `/data_10m/` — served from Pages static assets.

### Pruning
`pipeline/prune_r2.py` (replaces old `prune_truecolor.py`):
- Lists R2 objects, groups by date and type (snow vs truecolor)
- Deletes snow tiles beyond 30 dates, truecolor beyond 10 dates
- Strips `truecolor_file`/`truecolor_files` from local `site/data_10m/{date}/snowline.json` for pruned dates

### One-time CF setup required (not yet done by user as of 2026-06-17)
1. CF dashboard → R2 → Create bucket `snowline-tiles`
2. CF Pages → snowline project → Settings → Bindings → add R2 binding `SNOWLINE_BUCKET`
3. GitHub repo → Settings → Secrets → add `CF_ACCOUNT_ID`, `CF_R2_TOKEN`

---

## Open / deferred

- **R2 one-time setup**: Bucket + binding + secrets above still needed before first R2 upload.
- **Livingston city cams**: No embeddable URLs found. American Bank cam page is JS-rendered. No KBZK feed for Livingston. May need ipcamlive search or another source.
- **HLS coverage upgrade**: Replace S2 with NASA HLS for 90%+ daily coverage — DEFERRED, not urgent. See memory.
- **Iteris CDN**: `mt.cdn.iteris-atis.com/rwis_images/{posId}-00-01.jpg` serves MDT cam images directly (no CORS needed for `<img>`). Could switch `mdt` type to direct `img` to reduce worker hops — not implemented.

---

## Session log

- **2026-06-17** — Imagery migrated from git to CF R2. Added `prune_r2.py`, updated `update_date.sh` with R2 upload loop, updated `_worker.js` with `/api/tile/` route + Pages fallback, updated `index.html` tile URLs. One-time CF setup (bucket + binding + secrets) still needed from user.
- **2026-04-22** — Webcam page fully built. MDT posId bug fixed (10x off). Timestamps added. Mobile CSS. Golf cams (Cottonwood Hills, Valley View) removed — went offline. MDT GPS coords corrected to road-precise positions. All pushed and live.
- **2026-04-07** — Network plan created, Snowline noted as live and stable.
