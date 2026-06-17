"""RiverLine ingestion pipeline.

Orchestrates all four data sources (USGS / NWPS / SNOTEL / NWS) and produces a single
canonical `data/current.json` keyed by gauge. This is the file the frontend reads on
every page load.

Also refreshes the per-gauge static files (history, stats, NWPS metadata, weather, SNOTEL).

Pilot scope: Gateway only (USGS 06043500 / NWPS GLGM8). When we expand, this is the only
file that grows — every other module is per-source and parameterized.

Run as a script (this is what the GH Actions cron will call):
  python -m src.ingest.pipeline
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import nwps, nws, snotel, usgs

# Pilot scope — single gauge.
GATEWAY = {
    "usgs_id": "06043500",
    "nwps_lid": "GLGM8",
    "lat": 45.4972,
    "lon": -111.2708,
    "name": "Gallatin River near Gallatin Gateway",
    "snotel_triplets": [s["triplet"] for s in snotel.GATEWAY_SNOTEL_STATIONS],
}

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def build_gateway_snapshot() -> dict:
    """Pull from all four sources and assemble the canonical current.json payload."""
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Building Gateway snapshot...")

    # 1. USGS — current IV reading + verify history files exist
    print("  → USGS IV snapshot")
    iv = usgs.nwis_iv_snapshot([GATEWAY["usgs_id"]])
    iv_data = iv.get(GATEWAY["usgs_id"], {})

    # 2. NWPS — gauge metadata (rich) + current forecast
    print("  → NWPS gauge info + forecast")
    nwps_info = nwps.nwps_gauge_info(GATEWAY["nwps_lid"])
    nwps_fc = nwps.nwps_forecast(GATEWAY["nwps_lid"])
    nwps.write_gauge_info(nwps_info, GATEWAY["nwps_lid"])
    nwps.write_forecast(nwps_fc, GATEWAY["nwps_lid"])

    # 3. SNOTEL — current SWE + %-of-normal for the 4 upstream stations
    print("  → SNOTEL upper Gallatin")
    snotel_data = snotel.snotel_current(GATEWAY["snotel_triplets"])
    swe_values = []
    pct_values = []
    snotel_summary = []
    for station in snotel.GATEWAY_SNOTEL_STATIONS:
        triplet = station["triplet"]
        elements = snotel_data.get(triplet, {})
        snotel.write_station_json({**station, "elements": elements}, triplet)
        wteq = elements.get("WTEQ", {})
        swe_in = wteq.get("value") if wteq else None
        if swe_in is not None:
            swe_values.append(swe_in)

        # Long-term median for today's DOY — cached per-station in parquet.
        pct_of_normal = None
        try:
            pct_of_normal = snotel.snotel_pct_of_normal(triplet, swe_in)
            if pct_of_normal is not None:
                pct_values.append(pct_of_normal)
        except Exception as e:
            print(f"    ! {station['name']} normals skipped: {e}")

        snotel_summary.append({
            "name": station["name"],
            "elevation_ft": station["elevation_ft"],
            "swe_in": swe_in,
            "pct_of_normal": pct_of_normal,
            "snow_depth_in": elements.get("SNWD", {}).get("value"),
            "air_temp_f": elements.get("TOBS", {}).get("value"),
            "as_of": wteq.get("date") if wteq else None,
        })
    basin_avg_swe = round(sum(swe_values) / len(swe_values), 2) if swe_values else None
    basin_pct_of_normal = round(sum(pct_values) / len(pct_values), 1) if pct_values else None

    # 4. NWS — local weather forecast
    print("  → NWS point forecast")
    weather = nws.nws_forecast(GATEWAY["lat"], GATEWAY["lon"])
    nws.write_forecast_json(weather, GATEWAY["nwps_lid"])

    # Distill the current observed reading (prefer USGS IV; cross-check with NWPS observed)
    nwps_obs = nwps_info.get("status", {}).get("observed", {})
    flood_categories = nwps_info.get("flood", {}).get("categories", {})

    # Determine flood category for the current flow
    current_cfs = iv_data.get("discharge_cfs", {}).get("value")
    flood_category = "no_flooding"
    if current_cfs is not None:
        for cat in ("major", "moderate", "minor", "action"):
            threshold = flood_categories.get(cat, {}).get("flow")
            if threshold is not None and current_cfs >= threshold:
                flood_category = cat
                break

    snapshot = {
        "schema_version": 2,
        "generated_at": now,
        "gauge": {
            "usgs_id": GATEWAY["usgs_id"],
            "nwps_lid": GATEWAY["nwps_lid"],
            "name": GATEWAY["name"],
            "lat": GATEWAY["lat"],
            "lon": GATEWAY["lon"],
            "rfc": nwps_info.get("rfc", {}).get("abbreviation"),
            "wfo": nwps_info.get("wfo", {}).get("abbreviation"),
            "downstream_lid": nwps_info.get("downstreamLid") or None,
            "in_service": nwps_info.get("inService", {}).get("enabled"),
        },
        "current": {
            "discharge_cfs": iv_data.get("discharge_cfs", {}).get("value"),
            "discharge_cfs_observed_at": iv_data.get("discharge_cfs", {}).get("timestamp"),
            "gage_height_ft": iv_data.get("gage_height_ft", {}).get("value"),
            "water_temp_c": iv_data.get("water_temp_c", {}).get("value"),
            "water_temp_f": iv_data.get("water_temp_f", {}).get("value"),
            "flood_category": flood_category,
        },
        "thresholds": {
            "action_cfs": flood_categories.get("action", {}).get("flow"),
            "minor_cfs": flood_categories.get("minor", {}).get("flow"),
            "moderate_cfs": flood_categories.get("moderate", {}).get("flow"),
            "major_cfs": flood_categories.get("major", {}).get("flow"),
            "action_stage_ft": flood_categories.get("action", {}).get("stage"),
            "minor_stage_ft": flood_categories.get("minor", {}).get("stage"),
            "moderate_stage_ft": flood_categories.get("moderate", {}).get("stage"),
            "major_stage_ft": flood_categories.get("major", {}).get("stage"),
        },
        "forecast": {
            "active": nwps.is_forecast_active(nwps_fc),
            "issued_at": nwps_fc.get("issuedTime") if nwps.is_forecast_active(nwps_fc) else None,
            "primary_units": nwps_fc.get("primaryUnits") or None,
            "secondary_units": nwps_fc.get("secondaryUnits") or None,
            "points": nwps_fc.get("data", []),
            "reliability_note": nwps_info.get("forecastReliability"),
        },
        "snowpack": {
            "basin_avg_swe_in": basin_avg_swe,
            "basin_pct_of_normal": basin_pct_of_normal,
            "stations": snotel_summary,
        },
        "weather": {
            "wfo": weather["wfo"],
            "periods": weather["periods"][:8],  # ~4 days, day/night — what the UI shows above the fold
        },
        "historic_crests": nwps_info.get("flood", {}).get("crests", {}).get("historic", [])[:10],
    }

    return snapshot


def write_current_json(snapshot: dict) -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    path = DATA_ROOT / "current.json"
    path.write_text(json.dumps(snapshot, indent=2, default=str))
    return path


def main() -> None:
    snapshot = build_gateway_snapshot()
    path = write_current_json(snapshot)
    print()
    print(f"✓ Wrote {path.relative_to(DATA_ROOT.parent)}  ({path.stat().st_size:,} bytes)")
    print()
    print("--- Snapshot summary ---")
    cur = snapshot["current"]
    print(f"  Gauge: {snapshot['gauge']['name']}")
    print(f"  Flow:  {cur['discharge_cfs']} CFS  (gauge ht {cur['gage_height_ft']} ft)")
    if cur.get("water_temp_c") is not None:
        print(f"  Temp:  {cur['water_temp_c']} °C")
    print(f"  Flood category: {cur['flood_category']}")
    th = snapshot["thresholds"]
    print(f"  Thresholds (cfs): action={th['action_cfs']}  minor={th['minor_cfs']}  moderate={th['moderate_cfs']}  major={th['major_cfs']}")
    fc = snapshot["forecast"]
    print(f"  Forecast active: {fc['active']}  ({len(fc['points'])} points)")
    snow = snapshot["snowpack"]
    pct = snow.get("basin_pct_of_normal")
    pct_str = f"  [{pct}% of normal]" if pct is not None else ""
    print(f"  Basin avg SWE: {snow['basin_avg_swe_in']} in  ({len(snow['stations'])} stations){pct_str}")
    print(f"  Weather periods: {len(snapshot['weather']['periods'])}")
    print(f"  Historic crests embedded: {len(snapshot['historic_crests'])}")


if __name__ == "__main__":
    main()
