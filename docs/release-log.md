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
2026-10-14 04:57 · item 7 (part) · Webcams and Data pages no longer scroll sideways on phones; all 4 pages 375 px live. Loop idle: items 2/4 wait for tonight's Process Imagery run (~19:48 UTC), 7 needs Ian's sign-off, 9 is Ian's · 16/17
2026-10-14 16:56 · item 2 · first run on new code: prune worked (54 truecolor deleted), but no map made: read loop dropped the last date (no trailing newline); fixed. Newest map 2026-10-03, clear passes 10-06/08/09/13 waiting · 17/17
2026-10-14 17:23 · items 2+4 · Ian's run 38603376451 mapped Oct 13/9/8/6/4 (70 tiles to R2, 0 failed); newest map 2026-10-13, 31.5% snow, latest view 98.1% seen; CF token writes R2 · 17/17
2026-10-14 19:33 · Ian review fixes · coverage shows the day's own pass (Oct 13: 53% seen, not 98%); webcams on main map with viewsheds + hover image (were hidden by a date bug); MDT cams removed (MDT blocks Cloudflare); click a spot for its snow history this season · 17/17
2026-10-14 20:06 · Ian review 2 · composite imagery stack + 'Most recent composite'/'Oct 13 pass only'; Imagery/Snow on-off buttons; spot popup lists 3 nearest SNOTEL (mi, depth); webcams 19 → 94 (MDT via 511 CDN, FAA via /api/faacam), popup shows all views at a station · 17/17
2026-10-14 20:29 · Ian review 3 · paired Imagery/Snow buttons; composite/pass/last-full-day row; pass strips + clickable predicted passes (footprints arrive with next daily run); plainer ground check; most-new-snow line; webcams green, smaller, grouped within 3 km, popup stays open · 17/17
2026-10-14 20:46 · Ian review 4 · Data > Scenes: satellite pass panel (recent strips white, next predicted yellow, map to Jackson; click a pass to list its scenes); footprint clip widened to 1.5° · 17/17
2026-10-14 21:18 · Ian review 5 · imagery was drawn over the snow layer (Snow button looked dead), now under it; map opens on newest single pass; composite shades + dates each pass's strip; Data opens on SNOTEL; next pass flies to globe with approximate orbit + swath · 17/17
2026-10-14 21:31 · Ian review 6 · fixed view jumps (Most recent pass / composite / last full day); stations grouped by named range (Absaroka 11, was 6); lighter region markers; spot dates; last season red dashed by default; Scenes query tools removed; pipeline now maps every pass incl. cloudy and keeps season imagery (backfill: -f since=2026-10-01) · release_check above
