# Snow classifier: why 6–7k ft read snowier than 7–8k ft, and what to change

Ian, 2026-10-15: "Why does 6,000 to 7,000 ft have more snow than 7,000 to
8,000 ft?" Current classifier (process_tiles.py): snow if NDSI >= 0.4 or
Sen2Cor SCL = 11; SCL 0/3/8/9/10 dropped as cloud/no data; binary, ~20 m.

## What the data show (2026-10-13, measured 2026-10-15)

Open ground (< 30 % trees), share of clear pixels with snow:

| Region | 5–6k ft | 6–7k | 7–8k | 8–9k | 9k+ |
|---|---|---|---|---|---|
| NW (Bridgers, Belts) | 100 % | 96 % | 90 % | 97 % | – |
| NE (Crazies, Shields) | 95 % | 95 % | 96 % | 98 % | 100 % |
| SW (Madison, Gallatin, Tobacco Roots) | 29 % | 48 % | 66 % | 87 % | 96 % |
| SE (Absaroka, Beartooth) | 26 % | 65 % | 48 % | 38 % | 72 % |

1. **Mostly mixing regions.** The storm hit the north and east. 6–7k ft
   clear ground was mostly in the north (~730k of 1.1M px), 7–8k mostly in
   the south (~425k of 527k). The area-wide curve dips; no region but the
   SE does. 2025-12-15 and 2026-03-20 rise steadily with elevation.
2. **SE: heavy cloud, small biased sample.** At 6–8k ft in the SE, Sen2Cor
   flagged 70 % (tile 12TWQ) and 93 % (12TXQ) of open ground as cloud. The
   flags look mostly real (red reflectance 0.5–0.9); only ~6 % of
   cloud-flagged pixels look like snow (NDSI >= 0.4, B11 < 0.15). The clear
   holes left were mostly bare.
3. **Two SNOTEL misses, two different failures:**
   - Box Canyon (6,720 ft, 3 in): SCL "bare" but green 0.52 and B11 0.44,
     bright in both: thin cloud called bare ground. Counted as ground.
   - Monument Peak (8,740 ft, 4 in, 100 % trees): dark (green 0.07, B11
     0.04), NDSI 0.4–0.6 on 3 of 9 pixels: snow in shaded forest, lost to
     the 3x3 majority. Fisher Creek and Placer Basin (also forested) were
     detected correctly.

## Literature (research agent; verified items marked)

- Let It Snow / Theia (Gascoin et al. 2019, ESSD, verified): NDSI + red
  thresholds; a second, looser pass (NDSI ~0.15, low red, values
  unverified) applied using a DEM snowline found from cloud-free snow
  fraction by elevation band; "dark cloud" rescue for bright-looking cloud
  flags. 94 % accuracy vs 120 stations, best depth threshold 2 cm.
  AGPL-3.0. No Montana products.
- FSC = 0.5·tanh(2.65·NDSI − 1.42) + 0.5 (Gascoin et al. 2020, verified):
  our NDSI 0.4 cut ≈ 25 % snow fraction. FSC alone doesn't fix thin-snow
  misses; useful as a calibrated output.
- Sen2Cor is weak over bright surfaces (one benchmark: cloud precision
  18.6 %); on 2026-10-13 here it was not the main error.

## Plan

1. **Stats (cheap, no reprocessing).** Per-mountain-range profiles
   (done 2026-10-15 on the terrain page; Ian chose ranges over
   watersheds), and hide a band when under half its open ground was clear.
2. **Classifier v2 (needs a season reprocess; Ian triggers):**
   a. Bright-"bare" test: SCL 4/5/7 with green > ~0.35 and B11 > ~0.3 is
      cloud, not ground (Box Canyon case).
   b. LIS-style second pass above the snowline: looser NDSI with a red
      floor, forest/shade only (Monument Peak case). Watch false snow.
   c. Dark-cloud rescue for SCL 8/9 with high NDSI and low B11 (~6 % here).
   Thresholds tuned on station pixels (step 0 below); each change kept only if SNOTEL
   false negatives fall more than false positives rise, on 10+ dates,
   reported by elevation band, canopy and cloud.
3. **Don't:** lower NDSI everywhere, adopt SPIReS, or swap in an ML cloud
   model before the steps above are measured.

## Step 0: station test bench (built 2026-10-15)

`snowline/pipeline/build_station_pixels.py` reads, for every processed
date, a 5x5 window of 20 m pixels (blue, green, red, NIR, B11, SCL, Sen2Cor
cloud and snow probability) at each SNOTEL and Mesonet station, from the
same L2A scenes the map used, with that day's measured depth. Windowed
reads only, nothing saved but the result (~10 KB per date). About 50 s per
date; this season by default (8 dates on 2026-10-15, about 2 min).

`snowline/pipeline/classifier_eval.py` scores each candidate rule against
the stations in seconds, split by tree cover and elevation. Rules live in
that file as small functions; the winner moves into `process_tiles.py`.

First date (2026-10-13, 21 labelled stations): v1 called 13 of them,
missing snow at Box Canyon and Monument Peak and calling snow at Big Timber
SE (bare). Three snow stations (Porcupine, Shower Falls and White Mill)
were Sen2Cor cloud, so the dark-cloud rescue never triggered:
their B11 was 0.2-0.6, which is real cloud or snow under cloud, not dark
cloud. The loose forest rule added two false snows. One date is not
evidence; judge on the full run.

## Result: last season + this one (measured 2026-10-16)

1,398 station-days with a truth label over 61 dates (2025-10-03 to 2026-10-13),
40 SNOTEL and Mesonet stations; `classifier_eval.py`.

| rule | accuracy (called) | missed snow | false snow | called cloud |
|---|---|---|---|---|
| v1 (map today) | 83 % | 143 | 21 | 439 |
| dark_cloud_rescue | 83 % | 142 | 22 | 415 |
| loose_forest (NDSI 0.2 + red) | 86 % | 112 | 27 | 416 |
| forest_dark_gated | 91 % | 57 | 31 | 415 |

v1's main error is snow under forest called ground: those pixels are dark
(red ~0.06), NDSI ~0.07, but B11 stays low (~0.05) where bare forest floor
reads ~0.11. `forest_dark_gated`: on forest pixels within 300 m below the
day's open-ground snow line or above, ground with NDSI >= -0.1 and
B11 <= 0.10 is snow. Thresholds hold on both alternate-date halves
(missed 23/34, false 16/15). Without the snow-line gate: missed 47, false 37.
The 9 added false snows are all October dates (Oct 2025 x8, Oct 13 2026 x1),
where a station clearing at 0 in can sit in lightly snowed forest.

Next: implement in process_tiles.py as classifier v2 (two passes per date:
v1, then the snow line from open ground, then the forest rule using the
terrain grid's elevation and tree cover), check a few dates by eye, then a
season reprocess (Ian triggers).

## Published methods scored (2026-10-16)

Research brief: simple, open, per-pixel Sentinel-2 methods for snow under
forest. No published Sentinel-2 method was found validated in Rockies conifer
forest; no ready-made 20 m Sentinel-2 snow product covers Montana (HR-S&I is
European, Theia covers the Alps/Pyrenees and a few other sites; USGS Landsat
Level-3 fSCA at 30 m does cover the western US). Same 1,398 station-days:

| method | acc | missed | false | notes |
|---|---|---|---|---|
| v1 (map today) | 83 % | 143 | 21 | |
| LIS two-pass (Gascoin et al. 2019, ESSD 11:493) | 79 % | 193 | 16 | red > 0.20 in pass 1 drops dark snow; built for open ground |
| LIS + Klein NDSI-NDVI forest rule (MOD10) | 79 % | 193 | 16 | its NDSI floor (~0.16 at NDVI 0.5) is above our misses (~0.07) |
| v1 + NDFSI >= 0.39, forest above snow line | 90 % | 66 | 28 | Wang et al. 2015; S2 thresholds ISPRS 2022; threshold not tuned here |
| v1 + forest_dark_gated (ours, tuned) | 91 % | 57 | 31 | |

NDFSI = (NIR - B11) / (NIR + B11) is the one published forest snow index, and
with its published threshold it gets most of what our tuned rule gets
(missed 66 vs 57). Recommended v2: v1 + dark-cloud rescue + NDFSI >= 0.39 on
forest pixels above the day's snow line. The bench used B08 for B8A; use B8A
(20 m) in production. LIS's code is AGPL-3.0; the rules here are written from
the papers, no code copied.
