# Snowline

**[snowline.itogeospatial.com](https://snowline.itogeospatial.com)**

Near-real-time snow cover map and depth tracker for SW Montana. Combines Sentinel-2 satellite imagery with SNOTEL ground measurements to provide a comprehensive view of snow conditions across the Gallatin, Bridger, Madison, Tobacco Root, Gravelly, Crazy, Absaroka, Beartooth, and Yellowstone ranges.

## Features

- **Snow classification** from Sentinel-2 NDSI at 10m resolution
- **26+ historical dates** spanning the 2025-2026 winter season
- **SNOTEL depth charts** with 20-year median comparison (Oct–May)
- **9 mountain ranges** with interactive depth dashboards
- **Live webcams** from Bridger Bowl and Yellowstone NP
- **3D terrain**, basemap switcher, cursor elevation
- **Data catalog** with full satellite availability and SNOTEL station data
- **Automated** — GitHub Actions updates every 3 days

## Architecture

```
pipeline/
  run.py              # Sentinel-2 NDSI pipeline (multi-tile mosaicking)
  run_hls.py           # HLS (Harmonized Landsat-Sentinel) pipeline
  build_snotel_normals.py  # Pre-compute 20-year SNOTEL medians
  build_forest_mask.py     # ESA WorldCover forest canopy mask
  build_historical.py      # MODIS 25-year snow frequency
  backfill.sh              # Batch process historical dates
  build_index.sh           # Rebuild dates.json index

site/
  index.html           # Main map application
  metadata.html        # Data catalog (SNOTEL charts + satellite table)
  _worker.js           # Cloudflare Worker (webcam proxy, feedback)
  data/                # Pipeline outputs (committed to git)

.github/workflows/
  update.yml           # Automated pipeline (every 3 days)
  backfill.yml         # Historical data population
  update-hls.yml       # HLS pipeline
  build-assets.yml     # Static assets (forest mask, SNOTEL normals)
  historical.yml       # MODIS historical snow frequency
```

## Data Sources

| Source | Resolution | Coverage | Access |
|--------|-----------|----------|--------|
| Sentinel-2 L2A | 10m | 5-day revisit | [Planetary Computer](https://planetarycomputer.microsoft.com/) (free) |
| Landsat C2 L2 | 30m | 8-day revisit | Planetary Computer (free) |
| HLS v2.0 | 30m | 2-3 day combined | Planetary Computer (free) |
| Copernicus DEM GLO-30 | 30m | Global | Planetary Computer (free) |
| SNOTEL | Point | Daily | [NRCS AWDB API](https://wcc.sc.egov.usda.gov/awdbRestApi/) (free) |
| ESA WorldCover | 10m | Global | Planetary Computer (free) |
| MODIS MOD10A1 | 500m | Daily since 2000 | Planetary Computer (free) |
| Basemap + Terrain | — | Global | [Mapbox](https://www.mapbox.com/) |

## Deploy

The site is hosted on [Cloudflare Pages](https://pages.cloudflare.com/):
- Build command: *(none)*
- Output directory: `site`
- Connect to this GitHub repo for auto-deploy on push

### Environment Variables (Cloudflare Pages)
- `GH_FEEDBACK_TOKEN` — Fine-grained GitHub PAT with `issues:write` on this repo (for feedback form)

### GitHub Settings
- **Actions > Workflow permissions**: Read and write

## Study Area

SW Montana: Bridger Range to Red Lodge, Gallatin Valley to Yellowstone.
- Expanded AOI: `-112.2, 44.9, -109.0, 46.5`
- 12 Sentinel-2 tiles for full coverage
- 32 SNOTEL stations across 9 mountain ranges
- Season: October 1 – May 31

## License

MIT — [Ito Geospatial](https://itogeospatial.com)
