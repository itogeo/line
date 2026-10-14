# Snowline release log

One line per pass of `docs/release-loop.md`: date · item · result · release_check on production.

2026-10-13 21:00 · diagnose daily failures · GitHub still runs the pre-October pipeline (local commits never pushed); production newest map 2026-05-06, 27 maps; local 64 maps to 2026-10-03 · 7/17 prod, 15/17 local (only the two freshness checks, which CI refreshes)
2026-10-14 04:16 · items 1-4 · pushed 13 local commits; prune_r2 R2-list crash fixed (killed every Process Imagery run); SNOTEL season file restored; riverline-ingest passes; CF token reads R2, write unconfirmed until tonight's run · 16/17 (sat_availability freshness, refreshed by tomorrow's daily)
