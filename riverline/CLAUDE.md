# RiverLine — Montana River Conditions Dashboard

## What this is
River conditions dashboard aggregating USGS flow, NOAA forecasts, SNOTEL snowpack, and FWP fishing data. Gallatin River pilot first, then expand.

## SCOPE LOCK — read this first
**Gateway-only until end-to-end is complete.**
- USGS gauge: `06043500` (Gallatin at Logan)
- NOAA forecast point: `GLGM8`
- Do NOT add state-wide discovery, other gauges, or generalized fetchers until the full Gallatin pipeline works and displays correctly.

## Structure
- `src/` — Python modules (not notebooks)
- `data/` — downloaded data (ignored)
- `site/` — frontend
- `notebooks/` — exploratory only

## Data sources
- USGS NWIS: flow/stage for 06043500
- NOAA NWPS: forecast for GLGM8
- SNOTEL: snowpack context
- FWP: fishing regulations (future)

## Hard constraints
- Modules in `src/`, not notebooks
- Never background-run data fetches — hand off to user
- No state-wide or multi-gauge generalization until Gallatin is end-to-end
