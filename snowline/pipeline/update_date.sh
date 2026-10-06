#!/bin/bash
# Run the full snowline imagery pipeline for one date.
#
# Phase 1 (fetch_bands.py): downloads Sentinel-2 band windows from
#   the public Sentinel-2 C1 COGs (found via the S2 GeoParquet index) to
#   cache/{date}/{tile_id}/{band}.tif. Resumable — re-running
#   skips bands already on disk.
#
# Phase 2 (process_tiles.py): reads from the cache, computes NDSI, encodes
#   per-tile snow + truecolor WebPs to site/data_10m/{date}/.
#
# Usage:
#   bash pipeline/update_date.sh 2026-04-04
#   bash pipeline/update_date.sh 2026-04-04 --keep-cache  # don't delete cache
#   bash pipeline/update_date.sh 2026-04-04 --quality=88  # lower quality
#
# Recommended: run from a fresh shell so PROJ_LIB / venv are clean.
#   cd /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/snowline
#   source .venv/bin/activate
#   export PROJ_LIB="$(pwd)/.venv/lib/python3.9/site-packages/rasterio/proj_data"
#   bash pipeline/update_date.sh 2026-04-04

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: bash pipeline/update_date.sh YYYY-MM-DD [--keep-cache] [--quality=N]"
    exit 1
fi

DATE="$1"
shift || true

KEEP_CACHE=0
QUALITY=92
for arg in "$@"; do
    case "$arg" in
        --keep-cache) KEEP_CACHE=1 ;;
        --quality=*) QUALITY="${arg#--quality=}" ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

cd "$(dirname "$0")/.."

# Pick the venv python if it exists, else system python
if [[ -f .venv/bin/python ]]; then
    PYTHON=.venv/bin/python
    export PROJ_LIB="$(pwd)/.venv/lib/python3.9/site-packages/rasterio/proj_data"
else
    PYTHON=python3
fi

echo "═══════════════════════════════════════════════"
echo "  SNOWLINE PIPELINE — $DATE"
echo "═══════════════════════════════════════════════"
echo ""
echo "── Phase 1: fetch bands ──"
$PYTHON pipeline/fetch_bands.py --date="$DATE"

echo ""
echo "── Phase 2: process tiles ──"
$PYTHON pipeline/process_tiles.py --date="$DATE" --quality="$QUALITY"

# Upload WebPs to Cloudflare R2 (if credentials are set).
# Tiles are served via the CF Worker at /api/tile/{date}/{file}.
# Falls back to Pages static assets for dates not yet in R2.
if [[ -n "${CF_ACCOUNT_ID:-}" && -n "${CF_API_TOKEN:-}" ]]; then
    echo ""
    echo "── Upload tiles to R2 ──"
    UPLOAD_OK=1
    for f in site/data_10m/"$DATE"/*.webp; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        http_code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
            "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/r2/buckets/snowline-tiles/objects/tiles/${DATE}/${fname}" \
            -H "Authorization: Bearer ${CF_API_TOKEN}" \
            -H "Content-Type: image/webp" \
            --data-binary @"$f")
        if [[ "$http_code" != "200" ]]; then
            echo "  WARN: upload failed for $fname (HTTP $http_code)"
            UPLOAD_OK=0
        fi
    done
    if [[ $UPLOAD_OK -eq 1 ]]; then
        echo "    tiles/$DATE/* uploaded to R2"
    fi
else
    echo ""
    echo "── Skipping R2 upload (CF_ACCOUNT_ID / CF_API_TOKEN not set) ──"
fi

if [[ $KEEP_CACHE -eq 0 ]]; then
    echo ""
    echo "── Cleanup: removing cache/$DATE ──"
    rm -rf "cache/$DATE"
    echo "    cache/$DATE deleted"
else
    echo ""
    echo "── Keeping cache/$DATE (--keep-cache) ──"
fi

echo ""
echo "✓ Done. Site files in site/data_10m/$DATE/"
echo "  Next: git add site/data/snowline.json site/data_10m/dates.json site/data_10m/$DATE/snowline.json && git commit && git push"
