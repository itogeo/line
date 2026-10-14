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
#   bash snowline/pipeline/update_date.sh 2026-04-04
#   bash snowline/pipeline/update_date.sh 2026-04-04 --keep-cache  # don't delete cache
#   bash snowline/pipeline/update_date.sh 2026-04-04 --quality=88  # lower quality
#   bash snowline/pipeline/update_date.sh 2026-04-04 --max-cloud=100  # keep all-cloud tiles too
#
# Run from the repository root, with the requirements installed (CONTRIBUTING.md).

set -euo pipefail

usage() { echo "usage: bash snowline/pipeline/update_date.sh YYYY-MM-DD [--keep-cache] [--quality=N] [--max-cloud=N]"; }
if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
    usage; [[ $# -lt 1 ]] && exit 1 || exit 0
fi
if [[ ! "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    usage; exit 1
fi

DATE="$1"
shift || true

KEEP_CACHE=0
QUALITY=92
MAX_CLOUD=90
for arg in "$@"; do
    case "$arg" in
        --keep-cache) KEEP_CACHE=1 ;;
        --quality=*) QUALITY="${arg#--quality=}" ;;
        --max-cloud=*) MAX_CLOUD="${arg#--max-cloud=}" ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

cd "$(dirname "$0")/.."

# Use whatever python is active (a venv if one is activated). rasterio's
# wheels bring their own PROJ data, so no PROJ_LIB is needed.
PYTHON="${PYTHON:-python3}"

# In CI, any failure after process_tiles has listed the date must unlist it
# again, so the site never offers a date it can't draw.
unlist() {
    $PYTHON - "$DATE" <<'PYEOF'
import json, sys
p = "site/data_10m/dates.json"
d = json.load(open(p)); dates = [x for x in d.get("dates", []) if x != sys.argv[1]]
json.dump({"dates": dates, "latest": dates[-1] if dates else None}, open(p, "w"))
PYEOF
}
on_error() {
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "  Failed — removing $DATE from dates.json."
        unlist
    fi
}
trap on_error ERR

echo "═══════════════════════════════════════════════"
echo "  SNOWLINE PIPELINE — $DATE"
echo "═══════════════════════════════════════════════"
echo ""
echo "── Phase 1: fetch bands ──"
$PYTHON pipeline/fetch_bands.py --date="$DATE" --max-cloud="$MAX_CLOUD"

echo ""
echo "── Phase 2: process tiles ──"
$PYTHON pipeline/process_tiles.py --date="$DATE" --quality="$QUALITY"
$PYTHON pipeline/export_cogs.py --date="$DATE"

# Upload WebPs to Cloudflare R2. Tiles are not in git: the map reads them
# through the edge worker at /api/tile/{date}/{file} → R2 tiles/{date}/{file}.
# In CI a date whose tiles didn't reach R2 is taken back out of dates.json,
# so the site never lists a date it can't draw.
UPLOADED=0
if [[ -n "${CF_ACCOUNT_ID:-}" && -n "${CF_API_TOKEN:-}" ]]; then
    echo ""
    echo "── Upload tiles to R2 ──"
    if $PYTHON pipeline/sync_r2.py --date="$DATE"; then
        UPLOADED=1
    fi
else
    echo ""
    echo "── Skipping R2 upload (CF_ACCOUNT_ID / CF_API_TOKEN not set) ──"
fi
if [[ $UPLOADED -eq 0 ]]; then
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "  Tiles not in R2 — removing $DATE from dates.json so the site doesn't list an empty map."
        trap - ERR
        unlist
        exit 1
    else
        echo "  WARNING: $DATE is in dates.json but its tiles are only on this machine."
        echo "  Run: python snowline/pipeline/sync_r2.py --date=$DATE   (with CF_ACCOUNT_ID + CF_API_TOKEN set)"
    fi
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
echo "  Next: commit snowline/site/data_10m/dates.json and snowline/site/data_10m/$DATE/snowline.json"
