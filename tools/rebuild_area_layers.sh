#!/bin/bash
# Rebuild Snowline's AOI-derived static layers after an AOI change
# (lib/aoi.py). Run on Ian's Mac, never in CI. Safe to re-run.
#
# Layers, in order:
#   terrain     USGS 3DEP 1 m lidar shading -> R2 terrain/ (+ site/terrain/shade.json)
#               list -> fetch -> shade -> tiles (into a staging folder), then
#               the R2 upload, which asks for RUN first
#   historical  MODIS snow frequency, 2001-2025 -> site/data/historical/
#   forest      ESA WorldCover 2021 tree mask -> site/data/forest_mask.*
#   normals     SNOTEL 20-year medians -> site/data/snotel_normals.json
#
# How it stays safe:
#   - Every layer builds into snowline/cache/rebuild/ first (gitignored).
#   - Nothing in site/ changes until that layer's build and check pass.
#   - R2 is written only by the terrain upload, after you type RUN.
#   - Each layer leaves a marker in snowline/cache/rebuild/.done/ when done.
#     Re-running skips finished layers. Underlying scripts resume too
#     (fetch/shade skip cached files, historical skips periods already built).
#   - Git: the script does not commit. Review `git status`, then commit the
#     changed site/ files yourself (site/terrain/shade.json, site/data/...).
#
# Usage (from anywhere):
#   bash /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/tools/rebuild_area_layers.sh
#   bash .../rebuild_area_layers.sh --redo=historical    # rebuild one layer again
#   bash .../rebuild_area_layers.sh --only=forest        # run one layer
#
# Estimates (from the code and the old run, NOT timed; the list step's
# printed 1 m total is the real number for the terrain download):
#   Downloads: terrain ~5-10 GB of 4 m overview reads (~4% of the 1 m data,
#     ~700 tiles); historical ~1-2 GB of MODIS windows; forest ~0.5 GB.
#   Disk: snowline/cache/lidar ~10 GB while building; free ~15 GB first.
#   Time: terrain 2-3 h (fetch and shade dominate, tiles ~30 min);
#     historical 1-2 h (55 periods x 25 years); forest and normals ~15 min each.
#     Whole run 3-5 h. The R2 upload of ~4,800 terrain files (~400 MB) is 10-20 min.
#   Old baseline (for the checks): 4,860 terrain tiles, 406 MB, 3,575 at z13.
#   R2 writes: ~4,800 PUTs in the terrain upload. Storage +~0.4 GB. No egress.
#
# Needs CF_ACCOUNT_ID and CF_API_TOKEN in line/.env (read, never printed).

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    sed -n '2,40p' "$0"; exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY=/Users/ianvandusen/anaconda3/envs/geodata/bin/python
[[ -x "$PY" ]] || { echo "Python not found: $PY (see CLAUDE.md, Mac environment)"; exit 1; }

STAGE="$ROOT/snowline/cache/rebuild"
MARK="$STAGE/.done"
mkdir -p "$MARK"

ONLY=""
REDO=""
for arg in "$@"; do
    case "$arg" in
        --only=*) ONLY="${arg#--only=}" ;;
        --redo=*) REDO="${arg#--redo=}"; rm -f "$MARK/${REDO}" ;;
        *) echo "unknown arg: $arg"; exit 1 ;;
    esac
done

# Load CF credentials from line/.env without printing them.
if [[ -f "$ROOT/.env" ]]; then
    set -a; . "$ROOT/.env" >/dev/null 2>&1 || true; set +a
fi
if [[ -n "${CF_ACCOUNT_ID:-}" && -n "${CF_API_TOKEN:-}" ]]; then
    echo "Cloudflare credentials: present (from .env, not printed)"
else
    echo "Cloudflare credentials: MISSING in line/.env. The terrain upload will not run."
fi

step() { echo ""; echo "══ $1 ══"; echo "   started $(date '+%H:%M:%S')"; STEP_T0=$(date +%s); }
done_step() { echo "   done in $(( ($(date +%s) - STEP_T0) / 60 )) min"; touch "$MARK/$1"; }
wanted() { [[ -z "$ONLY" || "$ONLY" == "$1" ]] && [[ ! -f "$MARK/$1" ]]; }

BBOX_JSON='[-112.6, 44.55, -109.6, 46.35]'

# ── terrain ────────────────────────────────────────────────────────────────
if wanted terrain; then
    step "terrain 1/4: list (USGS tile index)"
    $PY snowline/pipeline/build_lidar_terrain.py list

    step "terrain 2/4: fetch 4 m overviews (resumable)"
    $PY snowline/pipeline/build_lidar_terrain.py fetch --workers=6

    step "terrain 3/4: shade (resumable)"
    $PY snowline/pipeline/build_lidar_terrain.py shade --workers=2

    step "terrain 4/4: tiles z8-z13 into staging"
    $PY snowline/pipeline/build_lidar_terrain.py tiles --out="$STAGE/terrain/shade"

    echo ""
    echo "── terrain check ──"
    $PY - "$STAGE/terrain" "$ROOT/snowline/site/terrain/shade" "$BBOX_JSON" <<'PYEOF'
import json, sys
from pathlib import Path
stage, site_shade, bbox = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
meta = json.load(open(stage / "shade.json"))
assert [round(x, 4) for x in meta["bounds"]] == [round(x, 4) for x in bbox], f"bounds {meta['bounds']}"
new13 = len(list((stage / "shade" / "13").rglob("*.webp")))
old13 = len(list((site_shade / "13").rglob("*.webp"))) if site_shade.exists() else 0
for z in range(8, 13):
    n = len(list((stage / "shade" / str(z)).rglob("*.webp")))
    assert n > 0, f"no z{z} tiles"
assert new13 >= 0.9 * old13, f"z13 tiles {new13}, old {old13}: too few"
print(f"   ok: {meta['tile_count']} tiles, {meta['bytes']/1e6:.0f} MB, z13 {new13} (old {old13}), bounds {meta['bounds']}")
PYEOF
    # Install: local copy only (site/terrain/shade is git-ignored; shade.json is tracked).
    rm -rf "$ROOT/snowline/site/terrain/shade"
    cp -R "$STAGE/terrain/shade" "$ROOT/snowline/site/terrain/shade"
    cp "$STAGE/terrain/shade.json" "$ROOT/snowline/site/terrain/shade.json"
    echo "   installed into snowline/site/terrain (local; commit shade.json yourself)"
    done_step terrain
fi

# ── historical ─────────────────────────────────────────────────────────────
if wanted historical; then
    step "historical: MODIS snow frequency into staging (skips periods already built)"
    $PY snowline/pipeline/build_historical.py --out-dir="$STAGE/historical"
    echo ""
    echo "── historical check ──"
    $PY - "$STAGE/historical" "$BBOX_JSON" <<'PYEOF'
import json, sys
from pathlib import Path
d, bbox = Path(sys.argv[1]), json.loads(sys.argv[2])
meta = json.load(open(d / "historical.json"))
assert [meta["bounds"][k] for k in ("west", "south", "east", "north")] == bbox, meta["bounds"]
n = len(meta["periods"])
assert n >= 50, f"only {n} periods (expect 55)"
missing = [p["file"] for p in meta["periods"].values() if not (d / p["file"]).exists()]
assert not missing, f"missing files: {missing[:5]}"
print(f"   ok: {n} periods, bounds {meta['bounds']}")
PYEOF
    cp -R "$STAGE/historical/." "$ROOT/snowline/site/data/historical/"
    echo "   installed into snowline/site/data/historical"
    done_step historical
fi

# ── forest mask ────────────────────────────────────────────────────────────
if wanted forest; then
    step "forest: ESA WorldCover tree mask into staging"
    mkdir -p "$STAGE/forest"
    $PY snowline/pipeline/build_forest_mask.py --out-dir="$STAGE/forest"
    echo ""
    echo "── forest check ──"
    $PY - "$STAGE/forest" "$BBOX_JSON" <<'PYEOF'
import json, sys
from pathlib import Path
d, bbox = Path(sys.argv[1]), json.loads(sys.argv[2])
meta = json.load(open(d / "forest_mask.json"))
assert [meta["bounds"][k] for k in ("west", "south", "east", "north")] == bbox, meta["bounds"]
assert (d / "forest_mask.webp").stat().st_size > 0
print(f"   ok: forest {meta['forest_pct']}%, bounds {meta['bounds']}")
PYEOF
    cp "$STAGE/forest/forest_mask.webp" "$STAGE/forest/forest_mask.json" "$ROOT/snowline/site/data/"
    echo "   installed into snowline/site/data"
    done_step forest
fi

# ── SNOTEL normals ─────────────────────────────────────────────────────────
if wanted normals; then
    step "normals: SNOTEL 20-year medians into staging"
    mkdir -p "$STAGE/normals"
    $PY snowline/pipeline/build_snotel_normals.py --out="$STAGE/normals/snotel_normals.json"
    echo ""
    echo "── normals check ──"
    $PY - "$STAGE/normals/snotel_normals.json" "$ROOT/snowline/site/data/snotel_normals.json" <<'PYEOF'
import json, sys
from pathlib import Path
new = json.load(open(sys.argv[1]))
old_path = Path(sys.argv[2])
old_n = len(json.load(open(old_path)).get("stations", {})) if old_path.exists() else 0
n = len(new.get("stations", {}))
assert n >= old_n, f"{n} stations, old file had {old_n}"
print(f"   ok: {n} stations (old {old_n})")
PYEOF
    cp "$STAGE/normals/snotel_normals.json" "$ROOT/snowline/site/data/snotel_normals.json"
    echo "   installed into snowline/site/data"
    done_step normals
fi

# ── R2 upload: the only step that writes to Cloudflare ─────────────────────
if [[ -z "$ONLY" || "$ONLY" == "upload" ]] && [[ ! -f "$MARK/uploaded" ]] && [[ -f "$MARK/terrain" ]]; then
    N=$(find "$ROOT/snowline/site/terrain/shade" -name '*.webp' | wc -l | tr -d ' ')
    MB=$(du -sm "$ROOT/snowline/site/terrain/shade" | cut -f1)
    echo ""
    echo "══ R2 upload: terrain ══"
    echo "   $N terrain tiles (~${MB} MB) go to bucket snowline-tiles under terrain/."
    echo "   Existing keys are overwritten. Nothing else in R2 is touched."
    read -r -p "   Type RUN to upload, anything else to stop: " ANS || ANS=""
    if [[ "$ANS" == "RUN" ]]; then
        if [[ -z "${CF_ACCOUNT_ID:-}" || -z "${CF_API_TOKEN:-}" ]]; then
            echo "   Credentials missing in line/.env. Stopped."; exit 1
        fi
        STEP_T0=$(date +%s)
        $PY snowline/pipeline/sync_r2.py --terrain --overwrite
        $PY snowline/pipeline/sync_r2.py --terrain --check && echo "   check: no local terrain tile is missing from R2"
        done_step uploaded
    else
        echo "   Not uploaded. Re-run this script and type RUN to upload (the layers above stay done)."
    fi
fi

echo ""
echo "══ Finished $(date '+%H:%M:%S') ══"
echo "Next: review git status, then commit the changed site/ files (terrain/shade.json,"
echo "data/historical, data/forest_mask.*, data/snotel_normals.json) and update the docs."
echo "After the commit deploys: python tools/release_check.py"
