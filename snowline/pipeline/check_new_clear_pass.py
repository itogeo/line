"""Detect the most recent clear satellite pass that has no processed tiles yet.

Reads snowline/site/data/sat_availability.json, looks for rows with q='good' or
q='excellent', checks whether snowline/site/data_10m/<date>/snowline.json exists.

Prints the date string (YYYY-MM-DD) to stdout if a new clear pass is found.
Prints nothing if all clear passes already have tiles or no clear passes exist.

Used by snowline-daily.yml to decide whether to dispatch snowline-process-imagery.yml.
"""

from __future__ import annotations

if __name__ == "__main__":
    # --help before the heavy imports below (and before anything runs).
    import argparse
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()


import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AVAIL_JSON = REPO / "snowline/site/data/sat_availability.json"
TILES_DIR = REPO / "snowline/site/data_10m"


def main() -> None:
    if not AVAIL_JSON.exists():
        return

    data = json.loads(AVAIL_JSON.read_text())
    rows = data.get("rows", [])

    # Sort newest first
    rows = sorted(rows, key=lambda r: r.get("dt", ""), reverse=True)

    for row in rows:
        if row.get("q") not in ("good", "excellent"):
            continue
        dt = row.get("dt", "")
        if not dt:
            continue
        tile_file = TILES_DIR / dt / "snowline.json"
        if not tile_file.exists():
            print(dt)
            return


if __name__ == "__main__":
    main()
