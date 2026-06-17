"""NRCS SNOTEL ingestion for RiverLine.

Pulls daily SWE / snow depth / precip / air temp from the SNOTEL stations that drain to
the Gallatin Gateway gauge (upper Gallatin HUC8 10020008).

Endpoint: AWDB REST v1 — https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1

Storage contract:
  data/snotel/<triplet>.json    — latest readings per station, all elements

Pilot scope: 4 upper-Gallatin SNOTEL stations feeding the Gateway gauge (06043500).
Brackett Creek (in the Bridgers / lower Gallatin) is intentionally excluded — it drains
to the East Gallatin downstream of Gateway, not upstream.

Run as a script for a smoke test:
  python -m src.ingest.snotel
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
HEADERS = {"User-Agent": "RiverLine/0.1 (Ito Geospatial; itogeospatial.com)", "Accept": "application/json"}
DEFAULT_TIMEOUT = 30

# Pilot scope: SNOTEL stations in upper Gallatin (HUC 10020008) that drain to Gateway.
# Verified live 2026-04-07 via /stations?networkCds=SNTL&hucs=10020008
GATEWAY_SNOTEL_STATIONS = [
    {"triplet": "385:MT:SNTL", "name": "Carrot Basin",   "elevation_ft": 9200},
    {"triplet": "578:MT:SNTL", "name": "Lick Creek",     "elevation_ft": 6880},
    {"triplet": "590:MT:SNTL", "name": "Lone Mountain",  "elevation_ft": 8820},
    {"triplet": "754:MT:SNTL", "name": "Shower Falls",   "elevation_ft": 8060},
]

# What we measure at each station.
# WTEQ = snow water equivalent (in)
# SNWD = snow depth (in)
# PREC = accumulated precipitation since Oct 1 (in)
# TOBS = observed air temperature (°F)
ELEMENTS = ("WTEQ", "SNWD", "PREC", "TOBS")

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _get(path: str, params: dict, retries: int = 3, backoff: float = 2.0) -> list | dict:
    url = f"{AWDB_BASE}/{path.lstrip('/')}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503, 504):
                time.sleep(backoff ** attempt)
                continue
            r.raise_for_status()
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(backoff ** attempt)
    raise RuntimeError(f"AWDB request failed after {retries} retries: {url}")


def snotel_current(
    station_triplets: list[str],
    elements: tuple[str, ...] = ELEMENTS,
    days_back: int = 7,
) -> dict[str, dict]:
    """Pull the most recent reading for each (station, element) over the last N days.

    Returns {triplet: {element_code: {value, date, unit}, ...}}.

    We ask for a small window (last N days) and take the most recent non-null value per
    element. This handles transient telemetry gaps gracefully — if today's reading is
    missing, we fall back to yesterday's instead of returning null.
    """
    end = datetime.utcnow().date()
    start = end - timedelta(days=days_back)
    params = {
        "stationTriplets": ",".join(station_triplets),
        "elements": ",".join(elements),
        "duration": "DAILY",
        "beginDate": start.isoformat(),
        "endDate": end.isoformat(),
        "periodRef": "END",
    }
    raw = _get("data", params)
    out: dict[str, dict] = {t: {"triplet": t} for t in station_triplets}
    for entry in raw:
        triplet = entry["stationTriplet"]
        for elem_block in entry.get("data", []):
            elem = elem_block["stationElement"]
            code = elem["elementCode"]
            unit = elem["storedUnitCode"]
            # Take the most recent non-null value
            values = [v for v in elem_block.get("values", []) if v.get("value") is not None]
            if not values:
                continue
            latest = values[-1]
            out[triplet][code] = {
                "value": float(latest["value"]),
                "unit": unit,
                "date": latest["date"],
            }
    return out


# ---------- Normals (long-term daily-of-year medians) --------------------- #


NORMALS_DEFAULT_START_YEAR = 1991  # 30-year climate normal window: 1991 → present
NORMALS_CACHE_DIR = DATA_ROOT / "snotel" / "normals"


def _fetch_wteq_range(triplet: str, begin: str, end: str) -> list[dict]:
    """Pull daily WTEQ for one station over [begin, end]. Returns list of {date, value}."""
    raw = _get(
        "data",
        {
            "stationTriplets": triplet,
            "elements": "WTEQ",
            "duration": "DAILY",
            "beginDate": begin,
            "endDate": end,
            "periodRef": "END",
        },
    )
    if not raw:
        return []
    out: list[dict] = []
    for entry in raw:
        for elem_block in entry.get("data", []):
            for v in elem_block.get("values", []):
                if v.get("value") is not None:
                    out.append({"date": v["date"], "value": float(v["value"])})
    return out


def snotel_normals(
    triplet: str,
    start_year: int = NORMALS_DEFAULT_START_YEAR,
    end_year: int | None = None,
    force_refresh: bool = False,
):
    """Compute daily SWE normals (median by day-of-year) for one SNOTEL station.

    Fetches daily WTEQ from AWDB over [start_year, end_year], groups by day-of-year
    (1-366), and takes the median. Cached to ``data/snotel/normals/<triplet>.parquet``
    so repeated pipeline runs don't refetch.

    Returns a pandas DataFrame with columns: doy, swe_in_median, swe_in_p25,
    swe_in_p75, n_years.
    """
    import pandas as pd  # local import: module still imports without pandas

    if end_year is None:
        end_year = datetime.utcnow().year - 1  # exclude current incomplete year

    NORMALS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = triplet.replace(":", "_")
    cache_path = NORMALS_CACHE_DIR / f"{safe}.parquet"

    if cache_path.exists() and not force_refresh:
        try:
            import pyarrow.parquet as pq  # noqa: F401
            table = pd.read_parquet(cache_path)
            # Cheap staleness check: cache is considered valid for the configured window
            # if it covers the requested [start_year, end_year]. We stash the window in
            # a sidecar JSON because pandas doesn't persist DataFrame.attrs to parquet.
            meta_path = cache_path.with_suffix(".json")
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                if meta.get("start_year") == start_year and meta.get("end_year") == end_year:
                    return table
        except Exception:
            pass  # corrupt cache — refetch below

    # AWDB happily returns multi-decade ranges in a single call (~5s, <500KB for 30y).
    rows = _fetch_wteq_range(triplet, f"{start_year}-01-01", f"{end_year}-12-31")
    if not rows:
        raise RuntimeError(f"No SWE history returned for {triplet}")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["doy"] = df["date"].dt.dayofyear
    df["year"] = df["date"].dt.year

    grouped = df.groupby("doy")["value"]
    normals = pd.DataFrame({
        "doy": sorted(df["doy"].unique()),
    }).set_index("doy")
    normals["swe_in_median"] = grouped.median()
    normals["swe_in_p25"] = grouped.quantile(0.25)
    normals["swe_in_p75"] = grouped.quantile(0.75)
    normals["n_years"] = grouped.nunique()
    normals = normals.reset_index()

    normals.to_parquet(cache_path, index=False)
    cache_path.with_suffix(".json").write_text(json.dumps({
        "triplet": triplet,
        "start_year": start_year,
        "end_year": end_year,
        "n_doy_rows": len(normals),
    }, indent=2))
    return normals


def snotel_pct_of_normal(triplet: str, current_swe_in: float | None, as_of: datetime | None = None) -> float | None:
    """Return current SWE as a percentage of the long-term daily median for today's DOY.

    Returns None if the normal is zero (summer-dry days divide-by-zero) or if the
    normals table has no entry for this DOY.
    """
    if current_swe_in is None:
        return None
    normals = snotel_normals(triplet)
    if as_of is None:
        as_of = datetime.utcnow()
    doy = as_of.timetuple().tm_yday
    row = normals[normals["doy"] == doy]
    if row.empty:
        return None
    median = float(row["swe_in_median"].iloc[0])
    if median <= 0:
        return None
    return round(100.0 * current_swe_in / median, 1)


# ---------- Persistence ---------------------------------------------------- #


def write_station_json(station_data: dict, triplet: str) -> Path:
    out_dir = DATA_ROOT / "snotel"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Triplets contain ':' which is fine on macOS but ugly — use a safe filename
    safe = triplet.replace(":", "_")
    path = out_dir / f"{safe}.json"
    path.write_text(json.dumps(station_data, indent=2, default=str))
    return path


# ---------- Smoke test ----------------------------------------------------- #


def main() -> None:
    print("SNOTEL smoke test — upper Gallatin (drains to Gateway 06043500)")
    print(f"Output → {DATA_ROOT}")
    print()

    triplets = [s["triplet"] for s in GATEWAY_SNOTEL_STATIONS]
    print(f"[1/1] Fetching {len(triplets)} stations × {len(ELEMENTS)} elements in one batched call...")
    print()

    snapshot = snotel_current(triplets)

    # Pretty-print + persist
    swe_values = []
    for station in GATEWAY_SNOTEL_STATIONS:
        triplet = station["triplet"]
        data = snapshot.get(triplet, {})
        path = write_station_json({**station, "elements": data}, triplet)

        wteq = data.get("WTEQ", {})
        snwd = data.get("SNWD", {})
        prec = data.get("PREC", {})
        tobs = data.get("TOBS", {})

        print(f"  {station['name']:<14} ({station['elevation_ft']} ft, {triplet})")
        if wteq:
            print(f"    SWE:        {wteq['value']:>5.1f} in   ({wteq['date']})")
            swe_values.append(wteq["value"])
        if snwd:
            print(f"    Snow depth: {snwd['value']:>5.1f} in   ({snwd['date']})")
        if prec:
            print(f"    Precip YTD: {prec['value']:>5.1f} in   (water year accumulation)")
        if tobs:
            print(f"    Air temp:   {tobs['value']:>5.1f} °F  ({tobs['date']})")
        print(f"    → wrote {path.relative_to(DATA_ROOT.parent)}")
        print()

    if swe_values:
        avg = sum(swe_values) / len(swe_values)
        print(f"  Basin average SWE (mean of {len(swe_values)} stations): {avg:.1f} inches")

    print()
    print("✓ SNOTEL smoke test complete")


if __name__ == "__main__":
    main()
