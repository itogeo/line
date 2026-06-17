# Snowline — Daily Snow Cover Map

## What this is
Automated daily pipeline that pulls satellite imagery, maps snow cover, and compares against SNOTEL ground truth. Deployed as a static map site.

## Structure
- `pipeline/` — processing steps driven by `daily.yml`
- `site/` — map frontend
- `cache/` — sat imagery cache (large, ignored — never read)

## Pipeline flow
`daily.yml` orchestrates: sat_availability → cloud masking → snow classification → SNOTEL comparison

## Key decisions
- **HLS over Sentinel-2**: strategy to get 90%+ daily coverage — DEFERRED, no longer urgent. Don't implement unless asked.
- Partial coverage is expected and handled in UI — not a bug.

## Hard constraints
- Never background-run the pipeline — hand off to user
- `cache/` and pipeline outputs are ignored — don't try to read them
