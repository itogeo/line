"""Push current snapshot to Cloudflare KV + D1.

Reads data/current.json (written by pipeline.py) and:
  1. PUTs the whole blob to KV key "gateway:current"
  2. INSERTs today's CFS for each gauge in current.gauges into D1 daily_flow

Required env vars (set in GitHub secrets or .env):
  CF_ACCOUNT_ID, CF_KV_NS_ID, CF_D1_DB_ID, CF_API_TOKEN

Run as a module:
  python -m src.ingest.push_cf
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
CF_BASE = "https://api.cloudflare.com/client/v4/accounts"


def _cf(method: str, url: str, token: str, body: str | bytes | None = None,
        content_type: str = "application/json") -> dict:
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        raise RuntimeError(f"CF API {method} {url} → HTTP {e.code}: {detail}") from None


def push_kv(account_id: str, ns_id: str, token: str, value: str) -> None:
    # Colon in key must be percent-encoded
    url = f"{CF_BASE}/{account_id}/storage/kv/namespaces/{ns_id}/values/gateway%3Acurrent"
    _cf("PUT", url, token, body=value, content_type="text/plain")
    print("  ✓ KV gateway:current updated")


def push_d1(account_id: str, db_id: str, token: str,
            site_id: str, date_str: str, cfs: float) -> None:
    url = f"{CF_BASE}/{account_id}/d1/database/{db_id}/query"
    body = json.dumps({
        "sql": "INSERT OR REPLACE INTO daily_flow (site_id, date, cfs) VALUES (?, ?, ?)",
        "params": [site_id, date_str, cfs],
    })
    result = _cf("POST", url, token, body=body)
    if not result.get("success"):
        raise RuntimeError(f"D1 query failed: {result.get('errors')}")
    print(f"  ✓ D1 daily_flow {site_id} {date_str} = {cfs} cfs")


def main() -> None:
    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    ns_id = os.environ.get("CF_KV_NS_ID", "")
    db_id = os.environ.get("CF_D1_DB_ID", "")
    token = os.environ.get("CF_API_TOKEN", "")

    missing = [k for k, v in {
        "CF_ACCOUNT_ID": account_id, "CF_KV_NS_ID": ns_id,
        "CF_D1_DB_ID": db_id, "CF_API_TOKEN": token,
    }.items() if not v]
    if missing:
        print(f"Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    current_text = (DATA / "current.json").read_text()
    current = json.loads(current_text)

    push_kv(account_id, ns_id, token, current_text)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Insert one row per gauge from the gauges strip
    gauges = current.get("gauges", [])
    if gauges:
        for gauge in gauges:
            cfs = gauge.get("discharge_cfs")
            site_id = gauge.get("site_id")
            if cfs is not None and site_id:
                push_d1(account_id, db_id, token, site_id, today, float(cfs))
    else:
        # Fallback: schema_version 2 — primary gauge only
        cfs = current.get("current", {}).get("discharge_cfs")
        if cfs is not None:
            push_d1(account_id, db_id, token, "06043500", today, float(cfs))
        else:
            print("  ! No discharge_cfs in current.json — skipping D1 write")


if __name__ == "__main__":
    main()
