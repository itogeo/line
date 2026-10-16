#!/bin/bash
# Rebuild Snowline's AOI-derived static layers after an AOI change
# (lib/aoi.py). Run on Ian's Mac, never in CI. Safe to re-run.
#
# Layers, in order (terrain shading is no longer built: since 2026-10-16 the
# map draws it in the browser from Mapbox's elevation tiles):
#   historical  MODIS snow frequency, 2001-2025 -> site/data/historical/
#   forest      ESA WorldCover 2021 tree mask -> site/data/forest_mask.*
#   normals     SNOTEL 20-year medians -> site/data/snotel_normals.json
#
# How it stays safe:
#   - Every layer builds into snowline/cache/rebuild/ first (gitignored).
#   - Nothing in site/ changes until that layer's build and check pass.
#   - Nothing is written to R2.
#   - Each layer leaves a marker in snowline/cache/rebuild/.done/ when done.
#     Re-running skips finished layers. Underlying scripts resume too
#     (fetch/shade skip cached files, historical skips periods already built).
#   - Git: the script does not commit. Review `git status`, then commit the
#     changed site/ files yourself (site/data/...).
#
# Usage (from anywhere):
#   bash /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/tools/rebuild_area_layers.sh
#   bash .../rebuild_area_layers.sh --redo=historical    # rebuild one layer again
#   bash .../rebuild_area_layers.sh --only=forest        # run one layer
#
# Estimates (from the code, NOT timed): historical ~1-2 GB of MODIS reads,
# 1-2 h (55 periods x 25 years); forest ~0.5 GB and normals, ~15 min each.

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

step() { echo ""; echo "══ $1 ══"; echo "   started $(date '+%H:%M:%S')"; STEP_T0=$(date +%s); }
done_step() { echo "   done in $(( ($(date +%s) - STEP_T0) / 60 )) min"; touch "$MARK/$1"; }
wanted() { [[ -z "$ONLY" || "$ONLY" == "$1" ]] && [[ ! -f "$MARK/$1" ]]; }

BBOX_JSON='[-112.6, 44.55, -109.6, 46.35]'

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

echo ""
echo "══ Finished $(date '+%H:%M:%S') ══"
echo "Next: review git status, then commit the changed site/ files"
echo "(data/historical, data/forest_mask.*, data/snotel_normals.json) and update the docs."
echo "After the commit deploys: python tools/release_check.py"
