# Snowline release log

One line per pass of `docs/release-loop.md`: date · item · result · release_check on production.

2026-10-13 21:00 · diagnose daily failures · GitHub still runs the pre-October pipeline (local commits never pushed); production newest map 2026-05-06, 27 maps; local 64 maps to 2026-10-03 · 7/17 prod, 15/17 local (only the two freshness checks, which CI refreshes)
2026-10-14 04:16 · items 1-4 · pushed 13 local commits; prune_r2 R2-list crash fixed (killed every Process Imagery run); SNOTEL season file restored; riverline-ingest passes; CF token reads R2, write unconfirmed until tonight's run · 16/17 (sat_availability freshness, refreshed by tomorrow's daily)
2026-10-14 04:14 · item 6 · snowline-daily now runs release_check.py as its last step (one retry after redeploy); first real test 11:00 UTC · 16/17
2026-10-14 04:21 · item 7 (part) · phone nav + opacity sliders no longer push the page to 491 px; live at 375 px on newest and 2026-02-10. Still open: layers panel open by default covers map, compass over panel, feedback pill over sheet text, timeline month labels collide · 16/17
2026-10-14 04:27 · item 7 (part) · layers panel starts closed on phones (tap Layers to open); live, map and compass clear · 16/17
2026-10-14 04:33 · item 7 (part) · Feedback button moved under the legend on phones, no longer covers the sheet text; live · 16/17
2026-10-14 04:38 · item 7 (part) · timeline shows every other month on phones (labels no longer collide); live · 16/17
2026-10-14 04:45 · item 7 (part) · desktop: sliders fit, compass lower right, layers panel clear of zoom/fullscreen; live · 16/17
