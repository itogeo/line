"""Areas of interest for the Line Network — the one place bboxes and
Sentinel-2 tile lists live. Every pipeline imports from here.

    python -m lib.aoi      # prints each AOI
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AOI:
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)
    tiles: tuple[str, ...]                    # MGRS tile ids, `_tile` form (no leading T)

    @property
    def bbox_list(self) -> list[float]:
        return list(self.bbox)


# SW Montana: Bridger Range to Red Lodge, Gallatin Valley to Yellowstone.
# The 12 tiles are every MGRS tile whose footprint touches the bbox
# (measured against the S2 GeoParquet index on 2026-10-05). 12TXQ only
# clips the SE corner and is often absent from a pass.
SNOWLINE = AOI(
    name="snowline",
    bbox=(-112.2, 44.9, -109.0, 46.5),
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


if __name__ == "__main__":
    for a in ALL.values():
        print(f"{a.name}: bbox={a.bbox_list} tiles={len(a.tiles)} {' '.join(a.tiles)}")
