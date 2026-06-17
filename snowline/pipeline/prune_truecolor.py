#!/usr/bin/env python3
"""
Keep truecolor RGB imagery only on the most recent N dates.

Why: truecolor WebPs are ~95 MB per date (vs ~6 MB for snow tiles). Without
pruning, the repo grows ~3 GB/month. Snow tiles stay forever — they're
small. Truecolor is the user's most-loved feature so we keep it for the
last KEEP_RECENT dates and delete the rest.

When a date's truecolor is deleted, we also strip the truecolor_file
field from each tile in that date's snowline.json. The frontend's
'View Satellite Imagery' button uses the presence of truecolor_file
to decide whether to enable itself, so this update makes the button
disable itself automatically on pruned dates.

Idempotent — running it twice is harmless. Safe to wire into process_imagery.yml
after each new date is processed.

Usage:
    python pipeline/prune_truecolor.py             # default keep last 10
    python pipeline/prune_truecolor.py --keep 5    # keep last 5
"""
import argparse
import json
from pathlib import Path

DATA_10M = Path(__file__).parent.parent / "site" / "data_10m"


def log(msg):
    print(f"[prune] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=10,
                        help="Number of most-recent dates to keep truecolor for")
    args = parser.parse_args()

    # All processed date folders, newest first
    date_dirs = sorted(
        [d for d in DATA_10M.iterdir()
         if d.is_dir() and len(d.name) == 10 and d.name[0:4].isdigit()],
        reverse=True,
    )
    if not date_dirs:
        log("No date folders found.")
        return

    keep = set(d.name for d in date_dirs[:args.keep])
    prune = [d for d in date_dirs[args.keep:]]
    log(f"Total dates: {len(date_dirs)}. Keeping truecolor on newest {len(keep)}: {sorted(keep)}")
    log(f"Pruning truecolor from {len(prune)} older dates.")

    total_deleted_files = 0
    total_freed_bytes = 0
    for d in prune:
        tc_files = list(d.glob("truecolor_*.webp"))
        if not tc_files:
            continue

        freed_here = sum(f.stat().st_size for f in tc_files)
        for f in tc_files:
            f.unlink()
        total_deleted_files += len(tc_files)
        total_freed_bytes += freed_here

        # Strip truecolor_file field from snowline.json so the frontend
        # disables the View Satellite Imagery button for this date.
        meta_path = d / "snowline.json"
        if meta_path.exists():
            try:
                meta = json.load(open(meta_path))
                if "tiles" in meta:
                    for t in meta["tiles"]:
                        t.pop("truecolor_file", None)   # legacy single-string schema
                        t.pop("truecolor_files", None)  # new list schema
                    with open(meta_path, "w") as f:
                        json.dump(meta, f)
            except Exception as e:
                log(f"  WARN: failed to update {meta_path}: {e}")

        log(f"  {d.name}: deleted {len(tc_files)} files ({freed_here // 1024 // 1024} MB)")

    if total_deleted_files == 0:
        log("Nothing to prune.")
    else:
        log(f"Done. Deleted {total_deleted_files} files, freed {total_freed_bytes // 1024 // 1024} MB.")


if __name__ == "__main__":
    main()
