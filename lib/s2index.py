"""Sentinel-2 scene search on the Taylor Geospatial S2 STAC GeoParquet mirror.

One SQL query against static Parquet files on Source Cooperative replaces
every STAC API search the Line Network used to make. The Parquet is the
*index*; the pixels are the same public Sentinel-2 Collection 1 COGs on AWS
that each row's ``assets`` column points to.

    Index:  https://data.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/
    Docs:   https://data.source.coop/tge-labs/s2-stac-geoparquet/sentinel-2-c1-l2a/AGENTS.md
    Pixels: https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/...

Facts this module relies on (from the upstream AGENTS.md, checked 2026-10-05):

* A year is ``year=YYYY/items.parquet`` plus zero or more ``live-MM.parquet``
  files holding scenes added since the last fold. ``year=YYYY/YYYY.json``
  lists them under ``assets``. Query ``items.parquet`` alone and you miss
  the most recent weeks.
* Rows are sorted by ``(_tile, datetime)``, so a ``_tile`` filter followed by
  a ``datetime`` range reads one or two row groups per file.
* Between folds a reprocessed scene can sit in a live file *and* in
  ``items.parquet``. Dedupe on ``id`` keeping the newest
  ``s2:generation_time``.
* ``datetime`` is UTC. We set the DuckDB session to UTC.

On top of that, Snowline wants one scene per tile per day. The same tile can
be imaged twice on one date (two datatakes); :func:`scenes` keeps the one with
the least nodata, then the least cloud.

Usage::

    from lib import s2index
    rows = s2index.scenes(["12TVR"], "2026-09-01", "2026-10-05", max_cloud=40)
    href = s2index.asset_href(rows[0], "green")
    scale, offset = s2index.scale_offset(rows[0], "green")

Smoke test (needs network, takes ~10 s)::

    python -m lib.s2index
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable

ROOT = "https://data.source.coop/tge-labs/s2-stac-geoparquet"
COLLECTION = "sentinel-2-c1-l2a"
BASE = f"{ROOT}/{COLLECTION}"
STATS_URL = f"{ROOT}/stats-c1/mgrs-monthly.parquet"
S3_BASE = f"s3://us-west-2.opendata.source.coop/tge-labs/s2-stac-geoparquet/{COLLECTION}"
USER_AGENT = "line-network/1.0 (+https://github.com/itogeo)"
EXPLORER_URL = "https://research.taylorgeospatial.org/s2-stac-geoparquet/"

# Columns we pull for every scene. Quoted because of the colons.
_COLUMNS = """
    id,
    _tile                              AS tile,
    datetime,
    "eo:cloud_cover"                   AS cloud,
    "s2:snow_ice_percentage"           AS snow,
    "s2:nodata_pixel_percentage"       AS nodata,
    "s2:cloud_shadow_percentage"       AS shadow,
    "s2:water_percentage"              AS water,
    "s2:processing_baseline"           AS baseline,
    "s2:generation_time"               AS generation_time,
    platform,
    "proj:epsg"                        AS epsg,
    bbox,
    thumbnail_url                      AS thumbnail,
    assets
"""


def log(msg: str) -> None:
    print(f"[s2index] {msg}", flush=True)


def norm_tile(tile: str) -> str:
    """'T12TVR' or '12tvr' -> '12TVR' (the ``_tile`` form, no leading T)."""
    t = tile.strip().upper()
    if len(t) == 6 and t.startswith("T"):
        t = t[1:]
    if len(t) != 5:
        raise ValueError(f"not an MGRS tile id: {tile!r}")
    return t


def _to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


@lru_cache(maxsize=1)
def _con():
    import duckdb

    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; SET TimeZone='UTC';")
    con.sql("SET s3_region='us-west-2'; SET s3_url_style='path';")
    return con


@lru_cache(maxsize=32)
def year_files(year: int) -> tuple[str, ...]:
    """Every non-empty Parquet file that makes up one year, as https URLs.

    Read from ``year=YYYY/YYYY.json`` so new ``live-MM`` files are picked up
    without a code change. If the JSON can't be read, globs the year through
    the anonymous S3 door instead. A year the index hasn't published yet
    (e.g. early January) returns no files rather than failing the query.
    """
    url = f"{BASE}/year={year}/{year}.json"
    try:
        # Source Cooperative answers 403 to urllib's default User-Agent.
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            item = json.load(r)
    except Exception as e:  # noqa: BLE001 - network, 404 for a future year
        if getattr(e, "code", None) == 404 and year >= datetime.now(timezone.utc).year:
            log(f"{year} is not in the index yet; skipping it")
            return ()
        # Fall back to listing the year through the anonymous S3 door, which
        # DuckDB can glob. Slower, but still finds the live files.
        log(f"could not read {url} ({type(e).__name__}); globbing the year instead")
        return (f"{S3_BASE}/year={year}/*.parquet",)
    out = []
    for asset in item.get("assets", {}).values():
        href = asset.get("href", "")
        if not href.endswith(".parquet"):
            continue
        if asset.get("table:row_count", 1) == 0:
            continue  # e.g. the old empty live.parquet
        out.append(f"{BASE}/year={year}/{href.lstrip('./')}")
    return tuple(sorted(out))


def live_files(year: int) -> list[str]:
    """Just the live (not yet folded) files for a year."""
    return [f for f in year_files(year) if "/live" in f]


def _query(tiles: list[str], start: date, end_excl: date, max_cloud) -> list[dict]:
    files: list[str] = []
    for y in range(start.year, (end_excl - timedelta(days=1)).year + 1):
        files.extend(year_files(y))
    if not files:
        return []
    placeholders = ",".join("?" for _ in tiles)
    cloud_sql = 'AND "eo:cloud_cover" <= ?' if max_cloud is not None else ""
    params: list = [files, *tiles, start.isoformat(), end_excl.isoformat()]
    if max_cloud is not None:
        params.append(float(max_cloud))
    sql = f"""
        SELECT {_COLUMNS}
        FROM read_parquet(?, union_by_name = true)
        WHERE _tile IN ({placeholders})
          AND datetime >= CAST(? AS TIMESTAMPTZ)
          AND datetime <  CAST(? AS TIMESTAMPTZ)
          {cloud_sql}
        QUALIFY row_number() OVER (
            PARTITION BY id ORDER BY "s2:generation_time" DESC NULLS LAST) = 1
    """
    cur = _con().execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def scenes(
    tiles: Iterable[str],
    start,
    end,
    max_cloud: float | None = None,
    dedupe_daily: bool = True,
) -> list[dict]:
    """Sentinel-2 C1 L2A scenes for ``tiles`` acquired from ``start`` to ``end``
    (both inclusive dates, UTC).

    Each row is a dict with ``id, tile, datetime, date, cloud, snow, nodata,
    shadow, water, baseline, platform, epsg, bbox, thumbnail, assets`` where
    ``assets`` is the parsed upstream STAC assets object. Sorted newest first.

    With ``dedupe_daily`` (the default) only one scene per tile per UTC day is
    kept: lowest ``nodata``, then lowest ``cloud``.
    """
    tiles = sorted({norm_tile(t) for t in tiles})
    start_d, end_d = _to_date(start), _to_date(end)
    rows = _query(tiles, start_d, end_d + timedelta(days=1), max_cloud)
    for r in rows:
        r["date"] = r["datetime"].astimezone(timezone.utc).date().isoformat()
        r["assets"] = json.loads(r["assets"]) if r["assets"] else {}
        for k in ("cloud", "snow", "nodata", "shadow", "water"):
            if r[k] is not None:
                r[k] = round(float(r[k]), 2)
    if dedupe_daily:
        best: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["tile"], r["date"])
            rank = (r["nodata"] if r["nodata"] is not None else 100,
                    r["cloud"] if r["cloud"] is not None else 100)
            cur = best.get(key)
            if cur is None or rank < cur[0]:
                best[key] = (rank, r)
        rows = [v[1] for v in best.values()]
    rows.sort(key=lambda r: (r["datetime"], r["tile"]), reverse=True)
    return rows


def footprints(tiles: Iterable[str], start, end) -> dict[str, list[bytes]]:
    """Data footprints (WKB polygons, lon/lat) of every scene over ``tiles``
    from ``start`` to ``end`` (inclusive UTC dates), grouped by UTC date.
    Needs DuckDB's built-in ST_AsWKB (1.5+); callers should treat it as
    optional."""
    tiles = sorted({norm_tile(t) for t in tiles})
    start_d, end_d = _to_date(start), _to_date(end)
    files: list[str] = []
    for y in range(start_d.year, end_d.year + 1):
        files.extend(year_files(y))
    if not files:
        return {}
    placeholders = ",".join("?" for _ in tiles)
    sql = f"""
        SELECT datetime, ST_AsWKB(geometry) AS wkb
        FROM read_parquet(?, union_by_name = true)
        WHERE _tile IN ({placeholders})
          AND datetime >= CAST(? AS TIMESTAMPTZ)
          AND datetime <  CAST(? AS TIMESTAMPTZ)
    """
    out: dict[str, list[bytes]] = {}
    params = [files, *tiles, start_d.isoformat(), (end_d + timedelta(days=1)).isoformat()]
    for dt, wkb in _con().execute(sql, params).fetchall():
        out.setdefault(dt.astimezone(timezone.utc).date().isoformat(), []).append(bytes(wkb))
    return out


def asset_href(row: dict, band: str) -> str:
    """The COG URL for ``band`` (an upstream asset key: green, swir16, scl,
    visual, thumbnail, ...). Never build these from a template."""
    try:
        return row["assets"][band]["href"]
    except KeyError as e:
        raise KeyError(f"{row.get('id')}: no asset {band!r}") from e


def scale_offset(row: dict, band: str) -> tuple[float, float]:
    """``(scale, offset)`` so that ``reflectance = DN * scale + offset``.

    Read from the asset's ``raster:bands``. Sentinel-2 L2A from processing
    baseline 04.00 on stores DN = 10000 * reflectance + 1000, which shows up
    here as ``(0.0001, -0.1)``. Classified rasters such as ``scl`` have no
    scale and return ``(1.0, 0.0)``.
    """
    rb = (row["assets"].get(band, {}).get("raster:bands") or [{}])[0]
    return float(rb.get("scale", 1.0)), float(rb.get("offset", 0.0))


def monthly_stats(tiles: Iterable[str], year: int) -> list[dict]:
    """Rows of ``stats-c1/mgrs-monthly.parquet`` for these tiles and year:
    scene_count, min/median cloud, best_item_id/date per month."""
    tiles = sorted({norm_tile(t) for t in tiles})
    placeholders = ",".join("?" for _ in tiles)
    cur = _con().execute(
        f"""SELECT * FROM read_parquet(?) WHERE mgrs_tile IN ({placeholders})
            AND year = ? ORDER BY mgrs_tile, month""",
        [STATS_URL, *tiles, int(year)],
    )
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def reproduce_sql(tiles: Iterable[str], day: str) -> str:
    """A copy-pasteable DuckDB query that finds the scenes Snowline used for
    ``day``. Shown on the site behind the "Reproduce" buttons."""
    tiles = sorted({norm_tile(t) for t in tiles})
    y = int(day[:4])
    tile_list = ", ".join(f"'{t}'" for t in tiles)
    return f"""INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET s3_url_style='path'; SET TimeZone='UTC';
-- Sentinel-2 scenes Snowline used for {day}
SELECT id, _tile, datetime, "eo:cloud_cover", "s2:snow_ice_percentage",
       json_extract_string(assets, '$.green.href')  AS green,
       json_extract_string(assets, '$.swir16.href') AS swir16,
       json_extract_string(assets, '$.scl.href')    AS scl
FROM read_parquet('s3://us-west-2.opendata.source.coop/tge-labs/s2-stac-geoparquet/{COLLECTION}/year={y}/*.parquet')
WHERE _tile IN ({tile_list})
  AND datetime >= '{day}' AND datetime < CAST('{day}' AS DATE) + 1
QUALIFY row_number() OVER (PARTITION BY id ORDER BY "s2:generation_time" DESC) = 1
ORDER BY _tile;"""


if __name__ == "__main__":
    import time

    t0 = time.time()
    today = datetime.now(timezone.utc).date()
    files = year_files(today.year)
    print(f"{today.year} files: {[f.rsplit('/', 1)[1] for f in files]}")
    rows = scenes(["T12TVR"], today - timedelta(days=10), today)
    print(f"latest scenes for 12TVR ({time.time() - t0:.1f}s):")
    for r in rows[:3]:
        so = scale_offset(r, "green")
        print(f"  {r['date']} {r['id']} cloud={r['cloud']} snow={r['snow']} "
              f"nodata={r['nodata']} green scale/offset={so}")
        print(f"    {asset_href(r, 'green')}")
    assert rows, "no scenes in the last 10 days — live files not being read?"
    assert rows[0]["date"] >= (today - timedelta(days=10)).isoformat()
    stats = monthly_stats(["12TVR"], today.year)
    if stats:
        last = stats[-1]
        print(f"monthly stats, latest row: month={last['month']} scenes={last['scene_count']} "
              f"median_cloud={last.get('median_cloud_cover')}")
    print(f"ok in {time.time() - t0:.1f}s")
