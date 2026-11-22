# Line Network plan (index)

One repository, one Cloudflare Pages project, several products. This page only
says what exists and where each product's plan is.

**Last checked against the code:** 2026-11-21.

| Product | Path | State | Plan |
|---|---|---|---|
| Snowline | `snowline/` | Live at [line.itogeospatial.com/snow](https://line.itogeospatial.com/snow), runs daily | [snowline/PLAN.md](./snowline/PLAN.md) |
| RiverLine | `riverline/` | In progress. `riverline-ingest.yml` runs every 30 minutes | [riverline/PLAN.md](./riverline/PLAN.md) |
| SkyLine | `skyline/` | Notes only, no code | none yet |

## Shared pieces

- `_worker.js` (repository root): the Cloudflare edge worker for every product.
  It routes `/snow` to `snowline/site/` and `/river` to `riverline/site/`,
  serves Snowline tiles and wind from R2, proxies webcams, and redirects the old
  `snow.line.itogeospatial.com` and `river.line.itogeospatial.com` hosts.
- `_shared/`: front-end code used by more than one product (`freshness.js`).
- `lib/`: shared Python (`aoi.py`, `s2index.py`).
- `tools/`: `dev_server.py` (local preview), `release_check.py` (checks the
  deployed site), maintainer scripts.
- `.github/workflows/`: `snowline-daily.yml`, `snowline-process-imagery.yml`,
  `snowline-wind.yml`, `riverline-ingest.yml`.
- Cloudflare bindings on the Pages project: R2 `SNOWLINE_BUCKET`, KV
  `RIVERLINE_KV`, D1 `RIVERLINE_DB`. One GitHub secret: `CF_API_TOKEN`.

## Conventions

1. Static HTML and JS, no build step. Cloudflare Pages deploys `main` on push.
2. Scheduled work runs in GitHub Actions. Small JSON is committed to the repo;
   tiles and time series go to Cloudflare (R2, KV, D1).
3. Free public data, with a visible source line for everything shown.
4. Each product keeps a `PLAN.md` that states its current state and open work.
