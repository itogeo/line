"""Areas of interest for the Line Network — the one place bboxes and
Sentinel-2 tile lists live. Every pipeline imports from here.

    python -m lib.aoi      # prints each AOI
"""

from __future__ import annotations

from dataclasses import dataclass


def pad_bbox(bbox: tuple[float, float, float, float], margin: float) -> list[float]:
    """Grow a (west, south, east, north) box by `margin` degrees on every side."""
    w, s, e, n = bbox
    return [round(w - margin, 4), round(s - margin, 4), round(e + margin, 4), round(n + margin, 4)]


@dataclass(frozen=True)
class AOI:
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)
    tiles: tuple[str, ...]                    # MGRS tile ids, `_tile` form (no leading T)

    @property
    def bbox_list(self) -> list[float]:
        return list(self.bbox)


# SW Montana: Bozeman, Tobacco Roots, Madisons, Gallatins, Absarokas to
# Yellowstone's north edge, Cooke City, east to Red Lodge and the Beartooth
# front. Changed 2026-10-14 (Ian approved); east edge -109.6 -> -109.0 on
# 2026-10-16 (Ian: don't cut the Beartooths off). The X column reaches
# -108.24..-108.33, so the wider box needs no new tiles.
# Old box (through 2026-10-13): (-112.2, 44.9, -109.0, 46.5), same 12 tiles.
# All 12 tiles are needed for the new box. The W column ends at -109.82
# (12TWQ), -109.58 (12TWR) and -109.56 (12TWS), so the east edge at -109.6
# runs into the X column in every row (12TXQ, 12TXR, 12TXS). Checked
# 2026-10-14 against the UTM grid and cache/*/meta.json footprints. Dropping
# the X column would leave a ~0.13 deg wide strip unimaged on the east side.
SNOWLINE = AOI(
    name="snowline",
    bbox=(-112.6, 44.55, -109.0, 46.35),
    tiles=(
        "12TUQ", "12TUR", "12TUS",
        "12TVQ", "12TVR", "12TVS",
        "12TWQ", "12TWR", "12TWS",
        "12TXQ", "12TXR", "12TXS",
    ),
)

# Upper Gallatin reach for RiverLine's future S2 water layer.
RIVERLINE = AOI(
    name="riverline",
    bbox=(-111.35, 45.2, -110.95, 45.7),
    tiles=("12TVR", "12TVQ"),
)

ALL = {a.name: a for a in (SNOWLINE, RIVERLINE)}

# Snowline's season: Oct 1 to May 31 (Ian, 2026-10-16). Passes from June 1 to
# Sept 30 are not processed, listed or stored.
SEASON_START_MONTH, SEASON_END_MONTH = 10, 5


def in_season(date_str: str) -> bool:
    """True for YYYY-MM-DD dates from Oct 1 to May 31."""
    m = int(date_str[5:7])
    return m >= SEASON_START_MONTH or m <= SEASON_END_MONTH


if __name__ == "__main__":
    for a in ALL.values():
        print(f"{a.name}: bbox={a.bbox_list} tiles={len(a.tiles)} {' '.join(a.tiles)}")
