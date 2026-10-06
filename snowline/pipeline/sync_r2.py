#!/usr/bin/env python3
"""
Upload processed Snowline tiles (WebP) to the Cloudflare R2 bucket the site
serves them from, skipping objects that are already there.

The map asks the edge worker for /api/tile/{date}/{file}.webp, and the
worker reads R2 key tiles/{date}/{file}.webp. Tiles are not kept in git, so
a date listed in dates.json without its tiles in R2 shows an empty map.
Run this once to backfill everything in site/data_10m/, and CI calls it
for each newly processed date.

Requires env vars (never commit them):
    CF_ACCOUNT_ID   Cloudflare account id
    CF_API_TOKEN    API token with "Workers R2 Storage: Edit" on the account

Usage:
    python pipeline/sync_r2.py --check            # what's missing? (lists only)
    python pipeline/sync_r2.py                    # upload every local date
    python pipeline/sync_r2.py --date=2026-10-03  # one date
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BUCKET = "snowline-tiles"
DATA_10M = Path(__file__).resolve().parent.parent / "site" / "data_10m"
API = "https://api.cloudflare.com/client/v4/accounts/{acct}/r2/buckets/{bucket}/objects"


def log(msg):
    print(f"[sync_r2] {msg}", flush=True)


def creds():
    acct, token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not acct or not token:
        log("CF_ACCOUNT_ID and CF_API_TOKEN must be set (see docs/cloudflare-setup.md).")
        sys.exit(2)
    return acct, token


def list_keys(acct, token, prefix="tiles/"):
    keys, cursor = set(), None
    while True:
        url = API.format(acct=acct, bucket=BUCKET) + f"?prefix={prefix}&per_page=1000"
        if cursor:
            url += f"&cursor={cursor}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(req, timeout=60) as r:
                data = json.load(r)
        except HTTPError as e:
            raise SystemExit(f"[sync_r2] list failed: HTTP {e.code} {e.read()[:300]!r}")
        res = data.get("result") or []
        objs = res if isinstance(res, list) else res.get("objects", [])
        keys.update(o["key"] for o in objs)
        info = data.get("result_info") or {}
        cursor = info.get("cursor")
        if not cursor or not info.get("is_truncated", bool(cursor)):
            break
    return keys


def put(acct, token, key, path):
    url = API.format(acct=acct, bucket=BUCKET) + "/" + key
    req = Request(url, method="PUT", data=path.read_bytes(), headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/webp",
    })
    with urlopen(req, timeout=120) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Only this date (YYYY-MM-DD)")
    ap.add_argument("--check", action="store_true", help="Report missing objects, upload nothing")
    args = ap.parse_args()
    acct, token = creds()

    dates = [args.date] if args.date else sorted(p.name for p in DATA_10M.iterdir() if p.is_dir())
    have = list_keys(acct, token)
    log(f"{len(have)} tile objects already in R2")
    missing = []
    for d in dates:
        for f in sorted((DATA_10M / d).glob("*.webp")):
            key = f"tiles/{d}/{f.name}"
            if key not in have:
                missing.append((key, f))
    log(f"{len(missing)} local tiles missing from R2")
    if args.check:
        for key, _ in missing[:50]:
            print("  " + key)
        return 0 if not missing else 1
    failed = 0
    for i, (key, f) in enumerate(missing, 1):
        try:
            put(acct, token, key, f)
            log(f"[{i}/{len(missing)}] {key} ({f.stat().st_size // 1024} KB)")
        except HTTPError as e:
            failed += 1
            log(f"[{i}/{len(missing)}] FAILED {key}: HTTP {e.code}")
    log(f"Done. {len(missing) - failed} uploaded, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
