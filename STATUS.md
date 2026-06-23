# Line Network — Status Review
*Last updated: 2026-06-22*

---

## Snowline — snow.line.itogeospatial.com

### What works today
- **Site loads** — Cold Light design is live. Map renders, UI is clean.
- **Satellite availability calendar** — `sat_availability.json` updates every morning via `snowline-daily.yml` (cron 11am UTC / 5am MT). Current through 2026-06-01. Users can see exactly which dates had satellite passes and why they were cloudy/clear.
- **SNOTEL season history** — `snotel_season.json` refreshes daily with the full current-season SWE + snow depth record for all 4 upper-Gallatin stations (Carrot Basin, Lick Creek, Lone Mountain, Shower Falls). Kept current.
- **Tile coverage through May 6, 2026** — 25 processed dates from Oct 2025 through May 2026, all in R2. The map scrubber works for those dates; users can browse the whole season.
- **SNOTEL normals** — `snotel_normals.json` exists (30-yr median baseline).
- **Webcam proxies** — NPS, MDT cameras wired in. CORS proxied via `_worker.js`.
- **Feedback** — POST to `/api/feedback` → GitHub issue. Working.

### What's broken / missing
- **No tiles since May 6** — It's now mid-June. `snowline-process-imagery.yml` is manual-trigger only. The last 6 weeks have no tile data. This is expected behavior (someone has to run imagery processing), but it means the "today" view is perpetually stale.
- **`snowline/site/data/snotel.json` is stale** — This file (the non-season snapshot, used by the main map's SNOTEL panel) was last written in April. The daily job updates `snotel_season.json` but not this legacy `snotel.json`. The SNOTEL panel on the map shows April values.
- **Snow season is ending** — SW Montana is past peak snowpack (it was gone by early May). The site's utility window is Oct–May. For the rest of June through September, there's nothing to show. This isn't a bug; it's a product question (see "hard questions" below).

### What a user sees right now
Map loads. Can scrub through Oct 2025 – May 6, 2026. SNOTEL panel shows April data (stale by ~10 weeks). Availability calendar is current. Overall: functional for historical browsing, not useful as a "live today" product until October.

### Blockers to a polished daily site
1. **Automate imagery processing** — today it's a manual run. For a daily site, the process-imagery workflow should run automatically when a clear satellite pass is detected (trigger off `sat_availability.json` updates, or run nightly and skip if no clear pass).
2. **Fix `snotel.json` staleness** — either merge it into `snotel_season.json` or have the daily job regenerate it.
3. **Off-season experience** — Jun–Sep, there's no snow. Options: (a) show the last known snow extent frozen with a "season complete" banner, (b) redirect attention to the watershed context data (SWE history, annual peak dates), (c) go dormant with a "back in October" message. There's no product decision here yet.
4. **Process missing June tiles** — there may be a few clear passes in late May / early June. Run `snowline-process-imagery.yml` manually to catch up.

---

## RiverLine — river.line.itogeospatial.com

### What works today
- **Site loads** — Deep Current design is live. Page renders correctly.
- **Pipeline runs locally** — `python -m src.ingest.pipeline` produces a valid `data/current.json` (1280 CFS at Gallatin Gateway as of 2026-06-17, schema_version 2). All 4 data sources are wired: USGS IV/DV, NWPS forecast, SNOTEL snowpack, NWS weather strip.
- **Backend code is complete** — `push_cf.py` can push to KV and D1. The D1 migration script (`scripts/migrate_to_d1.py`) can generate SQL from existing parquet history. All ingest modules work.
- **CF infrastructure exists** — KV namespace (`30fc2c20314c4e98bad40e12e7632167`) and D1 database (`1792601d-cf3f-4647-a739-8ac06e80f5a0`) are created. Worker routes `/api/current` → KV and `/api/chart` → D1.

### What's broken / missing
- **KV is empty → hero shows nothing** — `GET /api/current` returns `503 No data yet`. The pipeline has never pushed to KV because the GitHub Action was failing (and then was disabled). The Deep Current hero — the big 80px CFS number — never populates.
- **D1 has no tables → chart is blank** — The migration SQL has never been run. D1 returns errors on `/api/chart`. The 90-day history chart and the P10–P90 percentile bands are empty.
- **GitHub Action is disabled** — `riverline-ingest.yml` was disabled after it failed 48×/day. Root cause: `CF_API_TOKEN` secret was never added to `itogeo/line` repo. Fix is a single command (user action required — see below).

### What a user sees right now
Page loads with the Deep Current design. Hero area shows loading state that never resolves. Charts blank. Weather strip and snowpack section also empty (they pull from the same `current.json` KV lookup). The site looks correct but has no data.

### Blockers to a polished daily site (in order)

**Step 1 — Unblock the pipeline (user action, ~10 min):**
```bash
gh secret set CF_API_TOKEN --repo itogeo/line
# Paste the token value (it's in riverline/.env as CF_API_TOKEN=...)
```
Then re-enable the action:
```bash
gh workflow enable riverline-ingest.yml --repo itogeo/line
```

**Step 2 — Seed D1 with historical data (user runs locally, ~5 min):**
```bash
cd repos/line/riverline
python scripts/migrate_to_d1.py          # generates migration.sql from parquets
wrangler d1 execute riverline-db --file migration.sql --remote
```
This seeds 96 years of Gallatin Gateway daily flow + DOY percentile bands. The P10–P90 chart will populate immediately.

**Step 3 — Push first KV record (user runs locally, ~1 min):**
```bash
cd repos/line/riverline
python -m src.ingest.pipeline            # generates current.json
python -m src.ingest.push_cf             # pushes to KV + D1
```

After Step 3, the site will show real live data. After that, the GitHub Action runs every 30 min and keeps it current.

**Step 4 — Product / UX gaps to address before "anyone can visit":**
- **No graceful empty state** — if KV is empty or the pipeline fails, the hero just spins. Should show last-known value with a "last updated N hours ago" timestamp.
- **Trend arrow** — the hero currently shows CFS but no trend. Pipeline has `discharge_cfs` but the push flow doesn't compute rise/fall. One-line fix (compare current to previous KV value before overwriting).
- **No mobile layout** — charts and the hero strip are readable on desktop but the audience cards and weather strip need a responsive pass.
- **Forecast panel** — `current.json` contains the NWPS forecast (active as of June — it's peak runoff season). The frontend doesn't render it yet. A 10-day stage forecast graph would be high-value for floaters and anglers.
- **NWPS flood badge** — pipeline pulls flood thresholds (action/minor/moderate/major CFS). Not displayed anywhere in the UI yet. Should color the hero number when approaching action stage.
- **Hoot-owl fishing restrictions** — noted as future in the plan but high value for the angling audience. FWP posts closures on their website; no public API.

---

## Shared infrastructure state

| Component | Status |
|-----------|--------|
| `itogeo/line` GitHub repo | Active, main branch |
| CF Pages `line` project | Live — both domains routing correctly |
| `snow.line.itogeospatial.com` | Returns 200, site loads |
| `river.line.itogeospatial.com` | Returns 200, site loads (but no data) |
| R2 `snowline-tiles` | 25 dates of tiles, through 2026-05-06 |
| KV `riverline-kv` | Empty — never seeded |
| D1 `riverline-db` | Created — schema not yet applied |
| `snowline-daily.yml` | Running daily, succeeding |
| `snowline-process-imagery.yml` | Manual trigger only — last run May 6 |
| `riverline-ingest.yml` | Disabled — needs CF_API_TOKEN secret |
| Old `itogeo/snowline` workflows | Disabled |
| Old `itogeo/riverline` workflows | Disabled |
| `itogeo/site-unseen` workflows | Disabled |

---

## Hard questions to answer before calling these "public daily sites"

### For both sites
- **Who is the daily user?** What do they check every morning, and why would they open this instead of wunderground, NOAA, or the USGS gauges page? The design assumes the answer but we haven't validated it.
- **How do we handle pipeline failures?** Right now a failed GitHub Action = stale data with no user-visible indication. We need a "data last updated" timestamp prominently displayed so users know if something's wrong.

### Snowline specifically
- **What's the off-season product?** June–September the site has nothing to show. Do we turn it into a "last season recap" dashboard? Redirect to SWE historical trends? Or just put up a "back in October" page? The current UX just shows stale tiles with no explanation.
- **Is manual imagery processing sustainable?** Someone has to trigger `snowline-process-imagery.yml` for every new tile date. Is that you once a week? Or do we automate it (trigger when sat_availability detects a clear pass)?

### RiverLine specifically
- **Is Gallatin Gateway the right pilot gauge?** It's a scientifically good choice (long record, key upper-basin point), but Gallatin at Bozeman or the Madison near Ennis might be higher-traffic for the angling/floating audiences we're targeting.
- **What's the right update cadence?** 30 min matches USGS IV publishing rate. But NWPS forecasts only update twice daily, SNOTEL hourly, weather 12h. Could simplify to hourly runs without losing meaningful freshness.
- **What's next after the pipeline is running?** The roadmap after step 1–3 above is: (a) render the NWPS forecast, (b) add the flood badge, (c) mobile pass, (d) add a second gauge to prove the pattern generalizes.

---

## Priority order to get both sites to "anyone can use this"

1. **RiverLine: add CF_API_TOKEN + run D1 migration** (user action, one afternoon) → site shows live data
2. **RiverLine: forecast panel** (1–2 hr dev) → the most useful new feature; data is already in current.json
3. **Snowline: run imagery processing** (user triggers workflow) → tiles up to date
4. **Snowline: fix snotel.json staleness** (1 hr dev) → accurate snowpack panel
5. **Both: data-freshness timestamp** (1 hr dev each) → users know when data is from
6. **RiverLine: mobile pass** (2 hr dev) → makes it shareable
7. **Snowline: off-season plan** → product decision, then implement
8. **RiverLine: second gauge** → proves it's a platform, not a one-off
