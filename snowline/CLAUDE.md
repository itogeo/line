# Snowline — Daily Snow Cover Map

Notes for AI coding sessions. Current state and open work: [PLAN.md](PLAN.md).

## What this is
An automated pipeline that reads Sentinel-2 imagery, maps snow cover and checks it
against SNOTEL. Deployed as a static map site.

## Structure
- `pipeline/` — processing scripts; see `pipeline/README.md`
- `site/` — the static site (`index.html` map, `range.html`, `terrain.html`,
  `metadata.html`, `methods.html`, `webcam.html`)
- `cache/` — imagery cache (large, git-ignored — never read)
- Outside this folder: `_worker.js` (edge worker), `lib/` (area, scene search),
  `tools/` (local preview, release check), `.github/workflows/`

## Pipeline flow
- `snowline-daily.yml`: pass list, SNOTEL, Mesonet snow depth; then triggers imagery.
- `snowline-process-imagery.yml`: `update_date.sh` (fetch bands → classify → COGs →
  R2), SNOTEL agreement, composites, terrain and range stats, STAC.
- `snowline-wind.yml`: wind grid and station wind to R2.

## Key decisions
- Free and open source. No trip-planning features.
- Use a free hosted source before building or hosting a layer ourselves.
- HLS instead of Sentinel-2 alone: deferred, not planned. Don't implement unless asked.
- Partial coverage is expected and handled in the UI — not a bug.

## Hard constraints
- Never background-run the pipeline on a laptop session — hand off to the person.
- Tiles (`*.webp`, `*.tif`) and `cache/` are git-ignored. The JSON outputs under
  `site/data/` and `site/data_10m/` are committed by CI: read them to debug, but
  don't edit or commit them by hand.
