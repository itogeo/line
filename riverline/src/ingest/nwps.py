"""NOAA NWPS (National Water Prediction Service) ingestion for RiverLine.

Two endpoints we use:
  - /gauges/{lid}                       — gauge metadata, flood thresholds, historic crests
  - /gauges/{lid}/stageflow/forecast    — current forecast time series (empty when not active)

We deliberately do NOT pull /stageflow/observed — it's redundant with USGS NWIS, which we
already ingest in src/ingest/usgs.py.

Storage contract:
  data/nwps/<lid>.json                  — static-ish metadata (flood thresholds, crests). Refresh weekly.
  data/forecast/<lid>.json              — current forecast snapshot. Overwritten every cron tick.

Pilot scope: ONE gauge — Gallatin Gateway, NWPS LID GLGM8 (USGS 06043500).

Run as a script for a smoke test:
  python -m src.ingest.nwps
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

NWPS_BASE = "https://api.water.noaa.gov/nwps/v1"
HEADERS = {"User-Agent": "RiverLine/0.1 (Ito Geospatial; itogeospatial.com)"}
DEFAULT_TIMEOUT = 30

# Pilot scope: Gateway only.
GATEWAY_LID = "GLGM8"
GATEWAY_USGS = "06043500"

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _get(path: str, retries: int = 3, backoff: float = 2.0) -> dict:
    url = f"{NWPS_BASE}/{path.lstrip('/')}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503, 504):
                time.sleep(backoff ** attempt)
                continue
            r.raise_for_status()
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(backoff ** attempt)
    raise RuntimeError(f"NWPS request failed after {retries} retries: {url}")


# ---------- Public functions ----------------------------------------------- #


def nwps_gauge_info(lid: str) -> dict:
    """Full gauge metadata: flood thresholds, historic crests, downstream/upstream topology, etc.

    Refresh cadence: weekly is plenty — flood thresholds and historic crests change rarely.
    """
    return _get(f"gauges/{lid}")


def nwps_forecast(lid: str) -> dict:
    """Current forecast time series for the gauge.

    Returns the raw response. When no forecast is active (e.g. winter on the Gallatin), the
    `data` array will be empty and `issuedTime` will be the zero value '0001-01-01T00:00:00Z'.
    Callers should treat both cases as valid — empty just means "no forecast right now."
    """
    return _get(f"gauges/{lid}/stageflow/forecast")


def is_forecast_active(forecast: dict) -> bool:
    """True if there's actual forecast data right now."""
    return bool(forecast.get("data")) and not forecast.get("issuedTime", "").startswith("0001")


# ---------- Persistence ---------------------------------------------------- #


def write_gauge_info(info: dict, lid: str) -> Path:
    out_dir = DATA_ROOT / "nwps"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{lid}.json"
    path.write_text(json.dumps(info, indent=2, default=str))
    return path


def write_forecast(forecast: dict, lid: str) -> Path:
    out_dir = DATA_ROOT / "forecast"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{lid}.json"
    path.write_text(json.dumps(forecast, indent=2, default=str))
    return path


# ---------- Smoke test ----------------------------------------------------- #


def main() -> None:
    print(f"NWPS smoke test for LID {GATEWAY_LID} ({GATEWAY_USGS})")
    print(f"Output → {DATA_ROOT}")
    print()

    # 1. Gauge metadata
    print(f"[1/2] Fetching gauge metadata for {GATEWAY_LID}...")
    info = nwps_gauge_info(GATEWAY_LID)
    info_path = write_gauge_info(info, GATEWAY_LID)
    print(f"      → wrote {info_path.relative_to(DATA_ROOT.parent)}")
    print(f"      Name: {info['name']}")
    print(f"      Coords: {info['latitude']:.4f}, {info['longitude']:.4f}")
    print(f"      USGS ID cross-check: {info['usgsId']} (expected {GATEWAY_USGS})")
    assert info["usgsId"] == GATEWAY_USGS, "USGS ID mismatch — wrong LID?"
    print(f"      RFC: {info['rfc']['abbreviation']} ({info['rfc']['name']})")
    print(f"      WFO: {info['wfo']['abbreviation']} ({info['wfo']['name']})")
    print(f"      Downstream LID: {info['downstreamLid'] or '(none)'}")
    print()
    print(f"      Flood thresholds (stage / flow):")
    for cat in ("action", "minor", "moderate", "major"):
        c = info["flood"]["categories"].get(cat, {})
        if c:
            print(f"        {cat:>9}: {c.get('stage')} ft / {c.get('flow')} cfs")
    print()
    crests = info["flood"]["crests"]["historic"]
    print(f"      Historic crests on record: {len(crests)} (top 5):")
    for c in crests[:5]:
        print(f"        {c['occurredTime'][:10]}  {c['stage']} ft  {c['flow']} cfs")
    print()
    print(f"      Forecast reliability: {info.get('forecastReliability', '(unstated)')[:80]}")
    print(f"      Currently in service: {info['inService']['enabled']}")
    print()

    # 2. Forecast (may be empty out of season)
    print(f"[2/2] Fetching current forecast for {GATEWAY_LID}...")
    forecast = nwps_forecast(GATEWAY_LID)
    fc_path = write_forecast(forecast, GATEWAY_LID)
    print(f"      → wrote {fc_path.relative_to(DATA_ROOT.parent)}")
    if is_forecast_active(forecast):
        data = forecast["data"]
        print(f"      ACTIVE forecast — issued {forecast['issuedTime']}")
        print(f"      {len(data)} forecast points spanning {data[0]['validTime']} → {data[-1]['validTime']}")
        print(f"      Primary: {forecast['primaryName']} ({forecast['primaryUnits']})")
        print(f"      Secondary: {forecast['secondaryName']} ({forecast['secondaryUnits']})")
        print(f"      First point: {data[0]}")
        print(f"      Last point:  {data[-1]}")
    else:
        print(f"      No active forecast right now (issuedTime={forecast.get('issuedTime')!r})")
        print(f"      This is normal outside the warm season — Gallatin runoff forecasts typically activate in late spring.")
        print(f"      Reliability note: {info.get('forecastReliability', '')[:120]}")
    print()
    print("✓ NWPS smoke test complete")


if __name__ == "__main__":
    main()
