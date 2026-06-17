"""NWS api.weather.gov ingestion for RiverLine.

Pulls the local weather forecast for the lat/lon of a river gauge. The /forecast endpoint
returns ~14 periods (7 days × day/night), and /forecast/hourly returns ~156 hourly periods.

Two-step pattern (NWS quirk):
  1. GET /points/{lat},{lon}  → returns the gridpoint forecast URL for that location
  2. GET that forecast URL    → returns the actual periods

The points response is essentially static for any given lat/lon and can be cached forever.

Storage contract:
  data/weather/<gauge_key>.json     — the forecast (14 day/night periods, ~7 days)

Pilot scope: ONE gauge — Gateway (45.4972, -111.2708).

Run as a script for a smoke test:
  python -m src.ingest.nws
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

NWS_BASE = "https://api.weather.gov"
HEADERS = {
    "User-Agent": "RiverLine/0.1 (Ito Geospatial; itogeospatial.com)",
    "Accept": "application/geo+json",
}
DEFAULT_TIMEOUT = 30

# Pilot: Gateway gauge lat/lon (from NWPS metadata for GLGM8)
GATEWAY_LAT = 45.4972
GATEWAY_LON = -111.2708
GATEWAY_KEY = "GLGM8"

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _get(url: str, retries: int = 3, backoff: float = 2.0) -> dict:
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
    raise RuntimeError(f"NWS request failed after {retries} retries: {url}")


def nws_forecast(lat: float, lon: float, hourly: bool = False) -> dict:
    """Forecast for a lat/lon.

    Returns the trimmed forecast dict (periods + metadata), not the raw GeoJSON wrapper.
    Set hourly=True to get the hourly forecast (~156 periods, 6.5 days) instead of the
    day/night forecast (~14 periods).
    """
    points_url = f"{NWS_BASE}/points/{lat},{lon}"
    points = _get(points_url)
    props = points["properties"]
    forecast_url = props["forecastHourly"] if hourly else props["forecast"]
    forecast = _get(forecast_url)
    return {
        "lat": lat,
        "lon": lon,
        "wfo": props.get("gridId"),
        "grid": (props.get("gridX"), props.get("gridY")),
        "forecast_url": forecast_url,
        "generated_at": forecast["properties"].get("generatedAt"),
        "updated": forecast["properties"].get("updated"),
        "periods": forecast["properties"].get("periods", []),
    }


# ---------- Persistence ---------------------------------------------------- #


def write_forecast_json(forecast: dict, gauge_key: str) -> Path:
    out_dir = DATA_ROOT / "weather"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{gauge_key}.json"
    path.write_text(json.dumps(forecast, indent=2, default=str))
    return path


# ---------- Smoke test ----------------------------------------------------- #


def main() -> None:
    print(f"NWS weather smoke test for Gateway ({GATEWAY_LAT}, {GATEWAY_LON})")
    print(f"Output → {DATA_ROOT}")
    print()

    print("[1/1] Fetching point forecast (day/night periods)...")
    forecast = nws_forecast(GATEWAY_LAT, GATEWAY_LON)
    path = write_forecast_json(forecast, GATEWAY_KEY)
    print(f"      → wrote {path.relative_to(DATA_ROOT.parent)}")
    print(f"      WFO: {forecast['wfo']}, grid {forecast['grid']}")
    print(f"      {len(forecast['periods'])} periods")
    print()
    print("      Forecast summary:")
    for p in forecast["periods"][:8]:  # show first 4 days (8 day/night periods)
        pop = p.get("probabilityOfPrecipitation") or {}
        pop_val = pop.get("value")
        pop_str = f"{pop_val}%" if pop_val is not None else "—"
        print(
            f"        {p['name']:<14} "
            f"{p['temperature']:>3}°{p['temperatureUnit']}  "
            f"PoP {pop_str:>4}  "
            f"{p['windDirection']:<3} {p['windSpeed']:<14}  "
            f"{p['shortForecast']}"
        )
    print()
    print("✓ NWS smoke test complete")


if __name__ == "__main__":
    main()
