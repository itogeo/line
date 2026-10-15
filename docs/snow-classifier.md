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

1. **Stats (cheap, no reprocessing).** Per-watershed profiles (USGS WBD
   HUC8, public domain) instead of one area-wide curve, and hide a band
   when under half its open ground was clear. Fixes what the page shows.
2. **Classifier v2 (needs a season reprocess; Ian triggers):**
   a. Bright-"bare" test: SCL 4/5/7 with green > ~0.35 and B11 > ~0.3 is
      cloud, not ground (Box Canyon case).
   b. LIS-style second pass above the snowline: looser NDSI with a red
      floor, forest/shade only (Monument Peak case). Watch false snow.
   c. Dark-cloud rescue for SCL 8/9 with high NDSI and low B11 (~6 % here).
   Thresholds tuned on cached bands; each change kept only if SNOTEL
   false negatives fall more than false positives rise, on 10+ dates,
   reported by elevation band, canopy and cloud.
3. **Don't:** lower NDSI everywhere, adopt SPIReS, or swap in an ML cloud
   model before the steps above are measured.
