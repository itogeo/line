# Snowline release loop

**End goal:** a super simple, open-source website that helps people plan ski
trips: where the snow is today, how much the stations measure, and how
that compares with normal. When a choice comes up, pick the simpler one.

A spec for an agent (or a person) working on Snowline in repeated passes
until it is ready for the public. Each pass is short. Every pass ends with
the site at least as healthy as it started, and with one line in
`docs/release-log.md`.

## Definition of done

Snowline is public-ready when all of these hold on the same day:

1. `python tools/release_check.py` prints **all PASS** against
   `https://line.itogeospatial.com` (pages, newest map and its tiles,
   latest view, lidar terrain, fresh pass list and SNOTEL, last season's
   SNOTEL archive, agreement file).
2. The last **3 scheduled runs** of `snowline-daily` and
   `snowline-process-imagery` on GitHub succeeded, and the newest map is
   no more than 10 days behind the newest clear pass (the check covers this).
3. No other workflow in the repo fails on schedule (today `riverline-ingest`
   runs every 30 min; it must pass or be switched to manual until RiverLine
   launches).
4. A person has looked at the map on a phone and a laptop, on the newest map
   and on 2026-02-10, and signed off in the log.
5. Ian has made the repo public and restricted the Mapbox token to
   `line.itogeospatial.com` (agents can't do these two).

## One pass

1. **Sync.** `git pull --rebase origin main` (the bot commits data daily).
   Never force-push, never rewrite history.
2. **Measure.** Run `python tools/release_check.py` on production. If
   GitHub access is available, list the last runs:
   `gh run list -R itogeo/line -L 20` and read the log of any failure
   (`gh run view <id> --log-failed`).
3. **Pick one thing:** the highest item in the backlog below that is not
   done, or the first FAIL from step 2 if it isn't in the backlog yet (add
   it). One item per pass.
4. **Fix it small.** Change the least code that fixes it. Python for
   pipeline/tooling; the front end stays plain HTML/JS; `_worker.js` stays JS.
5. **Prove it locally.** `python tools/dev_server.py` then
   `python tools/release_check.py --base http://localhost:8787`, plus the
   script's own `--help` and smoke test. For map changes, take a screenshot
   at `#date=2026-02-10` and of the newest map.
6. **Commit** with a message that says what a visitor will notice, ending
   with the attribution lines. Push (needs push access, below).
7. **Verify live** after Cloudflare redeploys (1–3 min): re-run
   `release_check.py`. If it got worse, revert the commit (a new commit,
   not a reset) and log why.
8. **Log** one line in `docs/release-log.md`:
   `YYYY-MM-DD HH:MM · item · result · release_check N/M`.

**Stop** when the definition of done holds, or after 3 passes in a row with
no progress (log what blocks it and who has to act).

## Access the loop needs

| Need | Status 2026-10-13 | How |
|---|---|---|
| Push to `itogeo/line` | **Missing**: agents' shells have no GitHub login | Ian: a fine-grained token (this repo only; Contents + Workflows: read/write; Actions: read) saved as `GITHUB_TOKEN` in `line/.env`. Scripts read it from `.env`; nobody prints it. Or Ian runs `push_snowline.command` after each pass. |
| Read Actions logs | Missing (same token covers it) | as above |
| Upload to R2 | OK (token in `.env`) | `sync_r2.py`; throttle to `--workers 3` for terrain (API limit ~1,200 requests / 5 min) |
| Cloudflare Pages settings | No (token lacks Pages) | Ian, in the dashboard |

## Guardrails

* Never print, cat, echo, commit or move `.env` or any token.
* Never run long pipelines or big downloads in the background on Ian's
  machine. Heavy processing runs in CI or a cloud container.
* Data4 never goes into this repository.
* Never delete R2 objects except the `tmp/` prefix. `prune_r2.py` must keep
  every snow map (`--keep-snow 0`).
* Every number on the site keeps a visible, linked source.

## Backlog (highest first)

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Push the 10+ local commits (`push_snowline.command`). Until then GitHub runs the old pipeline, which hasn't made a map since 2026-05-06 and fails daily. | Ian (one double-click) | done 2026-10-13 (9311ff7) |
| 2 | Watch the first nightly `snowline-process-imagery` on the new code; fix whatever fails. | loop | done 2026-10-14: run 38603376451 mapped Oct 4-13 (two bugs fixed: prune R2 list, read loop dropped last date) |
| 3 | `riverline-ingest` (every 30 min): find out if it fails; if yes, fix or set it to `workflow_dispatch` only until RiverLine launches. | loop | done 2026-10-13: passes on schedule |
| 4 | Confirm GitHub secret `CF_API_TOKEN` can write R2 (the nightly upload step fails otherwise; `update_date.sh` then unlists the date). | Ian / loop | done 2026-10-14: 70 tiles uploaded, 0 failed |
| 5 | Delete `tmp/line.bundle` from R2. | loop | done 2026-10-13 |
| 6 | Run `release_check.py` in `snowline-daily` after the commit step, so a broken site fails CI the same morning. | loop | done 2026-10-14 (step 5, one retry after redeploy) |
| 7 | Phone layout pass: panel, legend, timeline, SNOTEL popups at 375 px. | loop + Ian sign-off | loop done 2026-10-14 (all 4 pages 375 px wide; layers closed on phones; feedback, timeline, desktop controls fixed); waits for Ian's phone + laptop sign-off |
| 8 | First snow of 2026–27: compare the first snowy map with SNOTEL and webcams; note results on the Methods page. | loop | waits for snow |
| 9 | Restrict the Mapbox token; make the repo public; roll the Cloudflare token. | Ian | open |
| 10 | Cloudflare Web Analytics (no cookies) so we know if people use it. | Ian | optional |
| 11 | **Trim the left panel** (Sam, issue #1: "too much data, dial it in"). Front and centre: date, the three view buttons, Imagery/Snow, next passes, one SNOTEL line. Everything else (change callout, ground check, coverage bars, range list, season chart) into collapsible sections, closed by default. Biggest single win; matches Ian's own reviews. | loop | done 2026-10-14: buttons, next passes and range depths up front; coverage+change, season chart, source+ground check in closed sections (remembered per browser) |
| 12 | **Where am I when zoomed in** (Sam). Put basemap roads, rivers and place labels above the snow/imagery layers, and show peak names from z10. Cheap; check it on the satellite basemap too. | loop | done 2026-10-14: roads, rivers, boundaries and place names drawn above snow and imagery |
| 13 | **Wider panel with dropdowns** (Sam). Do with item 11: 340 → ~400 px on desktop, sections as dropdowns. Phones keep the bottom sheet. | loop | done 2026-10-14: panel 360 → 400 px |
| 14 | **Plan a trip 2–4 weeks out** (Sam: "historical imagery"). A "Same week last year" jump to the nearest map ±3 days one year earlier (last season's snow maps are kept), next to the SNOTEL red dashed line that already shows last season. Imagery for past seasons is not kept, so snow maps only. | loop | done 2026-10-14: 'Same week last year' button (nearest map within 5 days) |
| 15 | **Topo hybrid** (Sam, unsure himself). Contour lines from z11 on the topo basemap only. Low priority; skip if item 12 solves orientation. | loop | later |
| 16 | **Most recent imagery easier to reach** (Sam). Done 2026-10-14: map opens on 'Most recent pass'; three fixed jump buttons. Revisit after item 11. | loop | done |
| 17 | **New AOI** (Ian 2026-10-14): Bozeman, Tobacco Roots, Rubies, all of the Madisons, the Gallatins and Absarokas south toward Yellowstone, the Crazies, Cooke City; drop the Columbus/Nye edge. Proposal [-112.6, 44.55, -109.6, 46.35] with 12 tiles: 9 is not enough, the X column stays (2026-10-14 check, see lib/aoi.py). Touches lib/aoi.py, 6 hard-coded copies in index.html, lidar terrain (rebuild, Ian runs), historical + forest mask (rebuild), SNOTEL bboxes, this season's maps (reprocess so the composite lines up). | Ian decides box, then loop | waits for Ian |

## UX pass: make the map make sense to a first-time visitor (2026-10-14)

Audit of the live site as a stranger would see it. Worked top to bottom, one
item per commit, each checked on desktop and a 390 px phone.

| # | Problem a visitor hits | Fix | Status |
|---|---|---|---|
| U1 | No answer to "how much snow is there?" until you read bars and charts. | One plain headline under the date: "Snow on 58% of what the satellite saw · stations average 3″, up 3″ this week". | done |
| U2 | Jargon: LIVE (the imagery is a day old), AOI, S2 Imagery, Satellite pass, Lidar terrain, Historical, SNOTEL unexplained. | Plain names: "Newest" / "N days ago", "of the area seen", "Satellite photo", "Strip edge", "Terrain shading", "How often it's snowy (2000–25)", "Snow stations (SNOTEL)". | done |
| U3 | On "Most recent pass" half the map is bare basemap; it reads as "no snow" instead of "not photographed that day". | Shade and label the part the pass missed: "Not photographed Oct 13 · try Most recent composite". | done |
| U4 | Legend misses what the map shows: hatching (no data), station dot colours (red = least snow, blue = most today), webcams. | Complete legend, one line each. | open |
| U5 | Desktop layers panel is open over the map with 10 toggles + a draw button; Sam: "too much". | Collapsed to a "Layers" button by default (as on phones); everyday layers first, the rest under "More". | open |
| U6 | Nothing tells a new visitor they can click a spot or a station. | One-time dismissible tip: what blue/grey mean, "click anywhere for that spot's snow history", "click a dot for a station". | open |
| U7 | Header takes 4 lines (wordmark, title, region, updated) before the date. | One line: "Snow Cover · SW Montana", updated time beside the date. | done |
| U8 | Timeline: tiny dots, "2026-27" unexplained, no hint it's clickable. | Label "Season 2026–27 · click a dot for that day's map"; bigger dots; legend for dot colours. | open |
| U9 | View buttons are four cramped uppercase mono labels. | Two clear tabs (Most recent pass / Most recent composite) + two text links (Same week last year · Last full day), sentence case. | open |
| U10 | Data and Webcams pages: same audit (headers, jargon, phone). | Pass after U1–U9. | open |
| U11 | Most recent composite still draws the pink single-pass edge over the dated regions; two competing outlines. | Hide the strip edge in composite view (the regions already show each pass). | done |


Ready in code, **not yet live**. Checked against NRCS on 2026-10-06:
station depths match (Lick Creek 16″, Albro Lake 41″, Shower Falls 54″ on
2026-02-10). The map and Data page now load the season file for the date on
screen, and "% of normal" is computed on that date from the same stations
(2026-02-10: 77%; the live site still shows the old "12%" until item 1).
`snotel_season_2025.json` (last season) ships with item 1;
`build_snotel_season.py` keeps the current season fresh every morning.
"% of normal" is hidden until the 20-year medians average 3″, so it stays
quiet in early October.
