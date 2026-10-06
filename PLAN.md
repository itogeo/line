# ItoGeo Line Network — Draft Plan

> **Workflow note.** This file is the **load-me-first** index for the entire Line Network. Read it at the start of any Claude session that touches `repos/line/`. It points to each project's own `PLAN.md` for detail. Update it when project status changes — keep it short, this is an index, not a plan in itself.

**Last updated:** 2026-10-05. Snowline now finds scenes in the S2 STAC GeoParquet index; see `AGENTS.md` and `GUIDE.md`.

---

## What is the Line Network?

A family of four sibling websites under the ItoGeo umbrella, each focused on a different layer of Montana's outdoor environment. Shared design language: free public government data, surfaced through fast static sites on Cloudflare Pages, automated by GitHub Actions cron jobs. **Storage is evolving:** Snowline imagery and RiverLine data are migrating to Cloudflare R2/KV/D1 (object store + edge DB) — the "repo as database" pattern still applies to small JSON metadata but not to bulk tiles or time-series data.

| Project | Domain | Status | Plan |
|---------|--------|--------|------|
| **Snowline** | Snow cover + depth (SW Montana) | **Live** at [line.itogeospatial.com/snow](https://line.itogeospatial.com/snow). Open-source launch 2026-10-10 | [snowline/PLAN.md](./snowline/PLAN.md) |
| **RiverLine** | River discharge + forecasts | **Active** — Phase 0 complete, Phase 1 next | [riverline/PLAN.md](./riverline/PLAN.md) |
| **SkyLine** | Weather for the outdoor community | Future / scaffolded | [skyline/](./skyline/) — README only, no plan yet |
| **DataLine** | (TBD — empty directory) | Future | [dataline/](./dataline/) — empty |

---

## Monorepo structure (2026-06-17)

Both sites now live in a single `itogeo/line` GitHub repo + one CF Pages project.

- **CF Pages root**: repo root (no `site/` subdirectory — output dir = blank)
- **Unified worker**: `_worker.js` at repo root routes by hostname
  - `snow.*` → rewrites to `/snowline/site/` prefix via `env.ASSETS`
  - `river.*` → rewrites to `/riverline/site/` prefix via `env.ASSETS`
- **Domains**: `snow.line.itogeospatial.com` + `river.line.itogeospatial.com`
- **DNS**: single wildcard CNAME `*.line.itogeospatial.com` → `<pages-project>.pages.dev`
- **GitHub workflows**: `.github/workflows/snowline-daily.yml`, `snowline-process-imagery.yml`, `riverline-ingest.yml`
- **CF bindings on `line` project**: R2 `SNOWLINE_BUCKET`, KV `RIVERLINE_KV`, D1 `RIVERLINE_DB`
- **One GitHub Secret**: `CF_API_TOKEN` on `itogeo/line`

Python pipeline scripts need zero changes — all use `Path(__file__)` to locate `snowline/site/`.

---

## Project status (one paragraph each)

### Snowline ✅ Scaffold complete — awaiting `itogeo/line` push + CF Pages setup
Static assets at `snowline/site/`. Pipeline at `snowline/pipeline/`. Worker route: `snow.*` → `/snowline/site/`. R2 tile serving via `SNOWLINE_BUCKET`. **User needs**: push to `itogeo/line` → create CF Pages `line` project (root = blank) → add R2/KV/D1 bindings → add custom domains → add wildcard DNS → add `CF_API_TOKEN` secret → archive `itogeo/snowline`. See [snowline/PLAN.md](./snowline/PLAN.md).

### RiverLine 🔜 Scaffold complete — awaiting `itogeo/line` push + CF Pages setup
Static site at `riverline/site/`. Ingest pipeline at `riverline/src/ingest/`. Worker routes: `river.*` → `/riverline/site/`, `/api/current` → KV, `/api/chart` → D1. **User needs**: same CF Pages setup as Snowline (shared project) + archive `itogeo/riverline`. See [riverline/PLAN.md](./riverline/PLAN.md).

### SkyLine 💤 Future
Weather product for Montana's outdoor community. Scaffolded only — README + empty `docs/` directory. No plan written yet. Likely scope: aggregate NWS forecasts + RAWS / MesoWest stations + Mountain Forecast-style alpine weather + air quality. Will reuse the same Cloudflare Pages + GH Actions pattern. Pick this up after RiverLine Phase 2.

### DataLine 💤 Future
Empty directory. Purpose not yet defined. Best guess: a public-facing data catalog or API gateway that exposes the underlying datasets the other three Line projects use, so other developers can build on the same pipeline. Revisit when there's a real reason to start it.

---

## Cross-cutting patterns (apply to every Line project)

These are the conventions that make adding the next Line project mechanical. New projects should adopt all of them by default unless there's a specific reason not to.

1. **Hosting:** Cloudflare Pages, custom subdomain under `itogeospatial.com`.
2. **Automation:** GitHub Actions cron job runs the data pipeline, commits fresh data files to the repo, CF Pages auto-deploys on push. No external schedulers, no servers.
3. **Storage:** Small JSON metadata stays in repo. Bulk tiles → CF R2 (Snowline). Time-series data → CF KV (current) + CF D1 (history) (RiverLine). Parquet + DuckDB retained for pipeline analytics.
4. **Frontend:** 100% static HTML/JS. API layer via CF Worker (`_worker.js`) for R2/KV/D1 reads. Mapbox GL JS for maps.
5. **Data philosophy:** Surface government data better than the agencies do. We don't generate new data; we aggregate, contextualize, and design.
6. **Draft plan files:** Every project keeps a `PLAN.md` at its root. This network-level `PLAN.md` is the index. Both are updated at the end of every working session and read at the start of the next one — they exist to save context tokens by avoiding repeated codebase exploration.

---

## Session log

- **2026-06-17** — Monorepo scaffold complete. Unified `_worker.js` at repo root, three workflow files in `.github/workflows/`. CF Pages root = repo root. Worker routes by hostname to `snowline/site/` and `riverline/site/`. Pending: user creates `itogeo/line` repo, pushes, configures CF Pages `line` project with bindings + custom domains, archives old repos.
- **2026-04-22** — Snowline webcam page shipped. MDT posId bug fixed, GPS coords corrected, timestamps + mobile CSS added. Golf cams removed.
- **2026-04-07** — Network-level plan file created. RiverLine vision crystallized, Phase 0 complete. Snowline live and stable. SkyLine and DataLine remain dormant.
