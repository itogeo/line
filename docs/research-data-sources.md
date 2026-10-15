# Snowline: what to add next (research, 2026-10-14)

Question from Ian: how to show snow across elevations when SNOTEL sits only in
the mountains; what open scientific data or models would add value; what
public / community layers (Nordic trails etc.) could go on the map. Avalanche
products are out of scope by decision.

## Measured facts (2026-10-14)

- SNOTEL in the mapped area: 32 SNTL stations, 6,310–9,420 ft, median 7,820 ft.
  None below 6,000 ft. (From live `data/snotel_season.json`.)
- Montana Mesonet: 22 stations in the area, 4,040–7,350 ft. The HydroMet ones
  report `snow_depth` through an open API with no key:
  `https://mesonet.climate.umt.edu/api/v2/latest/?type=json&elements=snow_depth&stations=acebozem,...`
  At 04:00 UTC 2026-10-15 Bozeman read 2.0″, Dillon 0.2″, the rest 0. The
  stations list is `.../api/v2/stations/?type=json`. Licence not stated on the
  site: ask before redistributing (contact on climate.umt.edu/mesonet).
- The Sentinel-2 snow map already covers every elevation at ~24 m. The only
  missing piece for elevation bands is a DEM on the snow grid. The pipeline
  has 3DEP lidar only in the local cache (`build_lidar_terrain.py`), so the
  daily job needs its own small DEM (Copernicus GLO-30 or 3DEP 1/3″, made once,
  stored in R2).
- OpenStreetMap Nordic trail coverage (`piste:type=nordic`) could not be
  checked: three Overpass servers timed out. Query to rerun:
  `way["piste:type"="nordic"](44.55,-112.6,46.35,-109.6);out tags center;`

## Recommended, in order

| # | Add | Why | Source / terms | Effort |
|---|---|---|---|---|
| 1 | **Snow by elevation**: % snow per 100 m band, per range, north vs south slopes; the snowline elevation (50 % snow) each pass; SNOTEL and Mesonet readings plotted at their elevations on the same chart | Answers "where does snow start today?" from our own data. Shows SNOTEL's high-elevation bias instead of hiding it. It is the product's name. | Our S2 snow classes + GLO-30 (free COG on AWS) or 3DEP | DEM once; ~1 small JSON per date; one chart |
| 2 | **Valley snow depth points** (Mesonet HydroMet) | HydroMet stations sit at 4,060–5,270 ft, where SNOTEL has nothing (the 5,300–6,300 ft gap stays satellite-only). Independent of SNODAS, so it can check it. | Open API, no key; ask UM for terms | A few lines in `snowline-daily` |
| 3 | **NWS winter alerts + snowfall forecast** | What's coming in the next 1–3 days | api.weather.gov, US Government data, User-Agent required. NBM 2.5 km grids on AWS (`noaa-nbm-grib2-pds`) for a map layer | Alerts: low. Gridded forecast: medium |
| 4 | **SNODAS modelled depth / SWE** (1 km, daily) | The only continuous estimate between and below stations | NSIDC G02158, HTTPS, citation only | Medium. Label as modelled 1 km; weak on ridges and steep aspects. It assimilates station data, so judge it against Mesonet, not SNOTEL. |
| 5 | **Nordic trails** | Lines from OSM if coverage is good; grooming status only by asking operators | OSM (ODbL, attribution). No grooming feed exists for BSF, Crosscut, Rendezvous, Lone Mountain | Geometry: low if OSM has it. Grooming: emails first |
| 6 | **Public land + FS rental cabins** | Where you can legally go; cabins as points linking to recreation.gov | MSL / BLM surface management (open); RIDB API (free key, CC-BY, no live availability) | Low, static |

## Checked and not worth it now

- Running our own snow model (SnowModel, iSnobal): needs forcing, calibration and compute; SNODAS is already a calibrated model run.
- National Water Model snow: redundant with SNODAS, heavier to read.
- UA SWE 4 km: ends 2023-09-30; history comparison only.
- Sentinel-1 snow depth / wet snow: research datasets, no operational feed.
- MODIS / VIIRS daily snow, Landsat / HLS: coarser or duplicate our S2 layer.
- ERA5-Land, Daymet, PRISM: too coarse or too late for a daily map.
- Synoptic / MesoWest: paid tiers and terms; Mesonet + NRCS cover it.
- CoCoRaHS: sparse volunteer points.
- Ski area snow reports, MDT 511, plow tracking, Yellowstone road status: no open feed; link out instead of scraping.
- Snowmobile grooming (FWP, clubs) and Custer Gallatin over-snow routes: no GIS feed found (OSVUM only as PDF/Avenza); would need a request to the forest's GIS office.

## Emails that would unlock the rest (Ian's call)

Montana Climate Office (Mesonet terms); Bridger Ski Foundation, Crosscut,
Rendezvous Ski Trails (trail GeoJSON + a daily grooming file); Custer Gallatin
GIS (over-snow routes).

## Sources

nsidc.org/data/g02158 · nsidc.org/data/nsidc-0719 · nsidc.org/data/modscgdrf_nrt ·
docs.opendata.aws/noaa-hrrr-pds · github.com/blaylockbk/Herbie ·
climate.umt.edu/mesonet · weather.gov/documentation/services-web-api ·
data.fs.usda.gov/geodata/edw · catalog.data.gov/dataset/recreation-information-database-ridb-58364 ·
bridgerskifoundation.org/trails · nps.gov/yell/planyourvisit/parkroads.htm
