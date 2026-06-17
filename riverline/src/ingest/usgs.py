"""USGS NWIS ingestion for RiverLine.

Four endpoints we use:
  - Site Service       — discover gauges + metadata (lat/lon, drain area, elevation)
  - Daily Values (DV)  — historical daily mean discharge; the only history we persist
  - Statistics Service — day-of-year percentiles (P10/P25/P50/P75/P90); reference data
  - Instantaneous (IV) — latest CFS / gage height / water temp; snapshot only

Storage contract:
  data/sites.json                      — list of {site_no, name, lat, lon, ...}
  data/history/<site_no>.parquet       — daily mean discharge, append-only
  data/stats/<site_no>.parquet         — day-of-year percentiles (refresh annually)
  data/current/<site_no>.json          — latest IV snapshot (one file per gauge)

Run as a script for a smoke test against the Gallatin basin:
  python -m src.ingest.usgs
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

NWIS_BASE = "https://waterservices.usgs.gov/nwis"
HEADERS = {"User-Agent": "RiverLine/0.1 (Ito Geospatial; itogeospatial.com)"}
DEFAULT_TIMEOUT = 60

# Gallatin pilot scope: Upper + Lower Gallatin HUC8s
GALLATIN_HUCS = ["10020008", "10020009"]

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


# ---------- HTTP helper ---------------------------------------------------- #


def _get(path: str, params: dict, retries: int = 3, backoff: float = 2.0) -> requests.Response:
    """GET with simple exponential backoff. USGS rate-limits aggressively under load."""
    url = f"{NWIS_BASE}/{path.lstrip('/')}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return r
            # 503 / 429 → back off and retry
            if r.status_code in (429, 503):
                time.sleep(backoff ** attempt)
                continue
            r.raise_for_status()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(backoff ** attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"USGS request failed after {retries} retries: {url}")


def _parse_rdb(text: str) -> pd.DataFrame:
    """USGS RDB format = '#' comments, then header line, then type line, then tab-separated rows."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if len(lines) < 3:
        return pd.DataFrame()
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[2:] if ln.strip()]
    return pd.DataFrame(rows, columns=header)


# ---------- Site service --------------------------------------------------- #


def nwis_sites(hucs: Iterable[str], parameter_cd: str = "00060") -> pd.DataFrame:
    """Active streamflow gauges in the given HUCs that have IV telemetry.

    Returns expanded metadata (drain_area_va, alt_va, county, state, etc.).
    """
    params = {
        "format": "rdb",
        "huc": ",".join(hucs),
        "parameterCd": parameter_cd,
        "siteStatus": "active",
        "siteType": "ST",
        "hasDataTypeCd": "iv",
        "siteOutput": "expanded",
    }
    r = _get("site/", params)
    df = _parse_rdb(r.text)
    for c in ("dec_lat_va", "dec_long_va", "alt_va", "drain_area_va"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------- Daily values --------------------------------------------------- #


def nwis_dv(
    site_no: str,
    parameter_cd: str = "00060",
    start: str = "1900-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Daily mean values for one site. Returns columns: date, discharge_cfs."""
    if end is None:
        end = datetime.utcnow().strftime("%Y-%m-%d")
    params = {
        "format": "json",
        "sites": site_no,
        "startDT": start,
        "endDT": end,
        "parameterCd": parameter_cd,
        "statCd": "00003",  # daily mean
    }
    js = _get("dv/", params).json()
    series = js.get("value", {}).get("timeSeries", [])
    if not series:
        return pd.DataFrame(columns=["date", "discharge_cfs"])
    values = series[0]["values"][0]["value"]
    if not values:
        return pd.DataFrame(columns=["date", "discharge_cfs"])
    df = pd.DataFrame(values)
    df["date"] = pd.to_datetime(df["dateTime"]).dt.tz_localize(None).dt.normalize()
    df["discharge_cfs"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["date", "discharge_cfs"]].dropna().reset_index(drop=True)


# ---------- Statistics service --------------------------------------------- #


def nwis_stats(site_no: str, parameter_cd: str = "00060") -> pd.DataFrame:
    """Day-of-year statistics over the full period of record."""
    params = {
        "format": "rdb",
        "sites": site_no,
        "statReportType": "daily",
        "statTypeCd": "p10,p25,p50,p75,p90,mean",
        "parameterCd": parameter_cd,
    }
    df = _parse_rdb(_get("stat/", params).text)
    for c in ("month_nu", "day_nu", "p10_va", "p25_va", "p50_va", "p75_va", "p90_va", "mean_va"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------- Instantaneous snapshot ----------------------------------------- #


# Friendly names + units for the parameters we care about
PARAMETER_LABELS = {
    "00060": ("discharge_cfs", "cfs"),
    "00065": ("gage_height_ft", "ft"),
    "00010": ("water_temp_c", "C"),
    "00011": ("water_temp_f", "F"),
}


def nwis_iv_snapshot(
    site_nos: list[str],
    parameter_cds: tuple[str, ...] = ("00060", "00065", "00010", "00011"),
) -> dict[str, dict]:
    """Latest IV reading per site. Returns {site_no: {field: {value, timestamp}, ...}}.

    Handles per-gauge variability — not every site reports every parameter.
    Note 00010 (C) and 00011 (F) for water temp are mutually exclusive at most gauges,
    so we ask for both and let the gauge tell us which it has.
    """
    params = {
        "format": "json",
        "sites": ",".join(site_nos),
        "parameterCd": ",".join(parameter_cds),
        "siteStatus": "active",
    }
    js = _get("iv/", params).json()
    out: dict[str, dict] = {s: {"site_no": s} for s in site_nos}
    for ts in js.get("value", {}).get("timeSeries", []):
        site_no = ts["sourceInfo"]["siteCode"][0]["value"]
        var_code = ts["variable"]["variableCode"][0]["value"]
        label_unit = PARAMETER_LABELS.get(var_code)
        if not label_unit:
            continue
        label, unit = label_unit
        values = ts["values"][0]["value"]
        if not values:
            continue
        latest = values[-1]
        if latest["value"] in ("", "-999999"):
            continue
        out.setdefault(site_no, {"site_no": site_no})[label] = {
            "value": float(latest["value"]),
            "unit": unit,
            "timestamp": latest["dateTime"],
            "parameter_cd": var_code,
        }
    return out


# ---------- Persistence helpers -------------------------------------------- #


def write_sites_json(sites_df: pd.DataFrame, out_path: Path) -> None:
    cols = ["site_no", "station_nm", "dec_lat_va", "dec_long_va", "huc_cd", "drain_area_va", "alt_va"]
    keep = [c for c in cols if c in sites_df.columns]
    records = sites_df[keep].rename(
        columns={
            "site_no": "site_no",
            "station_nm": "name",
            "dec_lat_va": "lat",
            "dec_long_va": "lon",
            "huc_cd": "huc",
            "drain_area_va": "drain_area_sqmi",
            "alt_va": "elevation_ft",
        }
    ).to_dict(orient="records")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2))


def write_history_parquet(dv_df: pd.DataFrame, site_no: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{site_no}.parquet"
    dv_df.to_parquet(path, index=False)
    return path


def write_stats_parquet(stats_df: pd.DataFrame, site_no: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{site_no}.parquet"
    stats_df.to_parquet(path, index=False)
    return path


# ---------- Smoke test (also the production backfill) --------------------- #


def main() -> None:
    print(f"USGS NWIS smoke test → {DATA_ROOT}")
    print()

    # 1. Site discovery
    print("[1/4] Discovering Gallatin gauges...")
    sites = nwis_sites(GALLATIN_HUCS)
    print(f"      Found {len(sites)} active streamflow gauges")
    site_nos: list[str] = sites["site_no"].tolist()
    write_sites_json(sites, DATA_ROOT / "sites.json")
    print(f"      → wrote data/sites.json")
    for _, row in sites.iterrows():
        print(f"        {row['site_no']}  {row['station_nm']}")
    print()

    # 2. Daily values backfill
    print(f"[2/4] Backfilling daily values for {len(site_nos)} gauges...")
    history_dir = DATA_ROOT / "history"
    for site_no in site_nos:
        dv = nwis_dv(site_no)
        path = write_history_parquet(dv, site_no, history_dir)
        if not dv.empty:
            print(
                f"      {site_no}: {len(dv):>6,} rows  "
                f"{dv['date'].min().date()} → {dv['date'].max().date()}  "
                f"→ {path.relative_to(DATA_ROOT.parent)}"
            )
        else:
            print(f"      {site_no}: (no DV available)")
    print()

    # 3. Statistics service
    print(f"[3/4] Pulling day-of-year stats for {len(site_nos)} gauges...")
    stats_dir = DATA_ROOT / "stats"
    for site_no in site_nos:
        stats = nwis_stats(site_no)
        path = write_stats_parquet(stats, site_no, stats_dir)
        print(f"      {site_no}: {len(stats):>3} DOY rows  → {path.relative_to(DATA_ROOT.parent)}")
    print()

    # 4. Current IV snapshot
    print(f"[4/4] Pulling current IV snapshot for all {len(site_nos)} gauges (one batched call)...")
    snapshot = nwis_iv_snapshot(site_nos)
    snap_path = DATA_ROOT / "current_usgs.json"
    snap_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"      → wrote data/current_usgs.json")
    for site_no in site_nos:
        s = snapshot.get(site_no, {})
        fields = {k: v["value"] for k, v in s.items() if isinstance(v, dict)}
        if fields:
            print(f"      {site_no}: {fields}")
        else:
            print(f"      {site_no}: (no current readings)")
    print()
    print("✓ USGS smoke test complete")


if __name__ == "__main__":
    main()
