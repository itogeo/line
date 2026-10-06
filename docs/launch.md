# Launch note (draft for Ian to post)

Two versions: a short post (LinkedIn, Bluesky, a Slack) and a longer one
for a blog or newsletter. Edit freely; the numbers were measured on
2026-10-05 and are linked to where they came from.

---

## Short

**Snowline is now free and open source.**

It's a daily snow-cover map of SW Montana, from the Bridgers to the Beartooths, built from free Sentinel-2 satellite imagery and checked against SNOTEL ground stations.

What's new:
• Every map lists the exact satellite scenes it came from, and one click opens the original files.
• Every number can be reproduced on a laptop with one DuckDB query, with no API key.
• Each map is scored against SNOTEL snow depth (85% agreement across 64 maps so far) so you can see how far to trust it.
• Snow history back to 2018 for every 110 km tile, drawn without downloading a single pixel.

Map: https://line.itogeospatial.com/snow
Code (Apache-2.0): https://github.com/itogeo/line

Built on the S2 STAC GeoParquet index from @Taylor Geospatial / TGE Labs, Element 84's Earth Search, and ESA Copernicus data. Thank you for making the hard part open.

---

## Long

### Snowline goes open source

Every fall the same question comes up in Bozeman: *where's the snow?* SNOTEL tells you about one clearing at a time. Webcams show one view. Satellites see everything, but turning raw Sentinel-2 imagery into a usable map takes more work than anyone wants on a Tuesday morning.

Snowline does that work. Every clear day it finds the new Sentinel-2 scenes over SW Montana, computes a snow index on the 10–20 m bands, masks clouds, and publishes a map. One pass never sees the whole area, so the default "latest view" shows every pixel's most recent clear look from the last 10 days, laid over 1 m lidar terrain shading. It has run since fall 2025, and today the whole thing (code, data and method) is public under Apache-2.0.

**What makes it different from another pretty map**

1. **Every pixel traces to a file you can open.** Each map lists the Sentinel-2 scene ids it used. The Data page has a row per scene with its thumbnail, cloud cover, ESA's own snow percentage, and a link to the Cloud-Optimized GeoTIFF on AWS.
2. **Reproduce it in one query.** Snowline doesn't call a search API. It queries the [S2 STAC GeoParquet index](https://research.taylorgeospatial.org/s2-stac-geoparquet/), a static, Parquet-formatted copy of every Sentinel-2 scene since 2015, published by Taylor Geospatial / TGE Labs on Source Cooperative. A "reproduce" button on every row copies the DuckDB query. Paste it into a laptop and you get the same scenes in seconds.
3. **It grades itself.** Every map is compared with snow depth at the SNOTEL stations under it. Across all 64 maps so far it agrees on 85% of station-days. The comparison also exposed problems in the old winter maps, so I fixed the method and reprocessed the whole season. The Methods page explains where satellites struggle (forest canopy, midwinter terrain shadow, thin snow) instead of hiding it.
4. **History for free.** ESA's scene classifier records a snow percentage for every scene. From the index alone, Snowline charts snow cover per tile back to 2018, with no pixel downloads.

**What it isn't.** It's not an avalanche forecast and it doesn't measure depth. Read the [GNFAC](https://www.mtavalanche.com/) before going into avalanche terrain.

**Thanks** to Taylor Geospatial and TGE Labs for the GeoParquet index and its agent-friendly documentation, Element 84 for Earth Search and for hosting the COGs, ESA and the Copernicus programme for the imagery, and NRCS for SNOTEL.

Map: https://line.itogeospatial.com/snow · Code: https://github.com/itogeo/line · Issues and pull requests welcome.

— Ian Van Dusen, Ito Geospatial
