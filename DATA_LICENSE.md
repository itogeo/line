# Data licence and attribution

The **code** in this repository is licensed under [Apache-2.0](LICENSE).

The **data** the Line Network shows comes from public sources, each under its
own terms. Derived products we publish (Snowline snow masks, `scenes.json`,
`snow_timeline.json`, `sat_availability.json`) inherit the attribution
requirements of their inputs. If you reuse them, keep the credits below.

| Source | Used for | Terms | Attribution |
|---|---|---|---|
| **Copernicus Sentinel-2** (ESA), Collection 1 L2A COGs hosted by Element 84 on AWS | Snow cover, true colour, scene table | [Copernicus Sentinel data terms](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) — free, full and open, attribution required | "Contains modified Copernicus Sentinel data [year]" |
| **S2 STAC GeoParquet** index (Taylor Geospatial / TGE Labs, on Source Cooperative) | Finding scenes; scene metadata incl. `s2:snow_ice_percentage` | Code Apache-2.0; metadata mirrors Earth Search | Credit "Taylor Geospatial / TGE Labs, s2-stac-geoparquet" and link https://research.taylorgeospatial.org/s2-stac-geoparquet/ |
| **Earth Search** STAC (Element 84) | Upstream of the index | Open | Credit "Element 84 Earth Search" |
| **NRCS SNOTEL** (USDA) | Snow depth, SWE, normals | US Government work, public domain | Credit "USDA NRCS SNOTEL" |
| **USGS** water data | RiverLine gauges | Public domain | Credit "USGS" |
| **NOAA / NWS** (NWPS, forecasts) | RiverLine forecasts, weather | Public domain | Credit "NOAA / NWS" |
| **MODIS MOD10A1** (NASA, via Microsoft Planetary Computer) | 25-year snow frequency layer | NASA EOSDIS data policy, no restrictions | Credit "NASA MODIS" |
| **ESA WorldCover 2021** (via Microsoft Planetary Computer) | Forest mask | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium" |
| **USFS** roads | Map overlay | Public domain | Credit "USDA Forest Service" |
| **Webcam images** (MDT, NPS, resorts, others) | Webcam page | Owned by each operator | Linked and proxied for display only. **Not redistributed and not covered by this repository's licences.** Follow each owner's terms. |
| **Mapbox** basemap and terrain | Map background | [Mapbox terms of service](https://www.mapbox.com/legal/tos) | Shown on the map. If you fork, use your own token. |

Nothing in this repository makes these sources' data proprietary. Where a
term above is stricter than Apache-2.0, the stricter term wins for that data.
