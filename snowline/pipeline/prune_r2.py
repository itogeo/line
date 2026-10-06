#!/usr/bin/env python3
"""
Prune old tiles from the CF R2 bucket "snowline-tiles".

Keeps the most recent KEEP_SNOW dates of snow tiles and KEEP_TRUECOLOR dates
of truecolor tiles. Older objects are deleted from R2.

Also strips truecolor_file / truecolor_files from each date's snowline.json
for pruned truecolor dates (the frontend uses that field's absence to disable
the View Satellite Imagery button).

Requires env vars:
    CF_ACCOUNT_ID   — Cloudflare account ID
    CF_API_TOKEN    — Cloudflare API token with R2 object read + delete on snowline-tiles

Usage (called by process_imagery.yml after each pipeline run):
    python snowline/pipeline/prune_r2.py --keep-snow 30 --keep-truecolor 10
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


BUCKET = "snowline-tiles"
DATA_10M = Path(__file__).parent.parent / "site" / "data_10m"


def log(msg):
    print(f"[prune_r2] {msg}", flush=True)


def r2_request(method, path, account_id, token, body=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{BUCKET}/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if body:
        headers["Content-Type"] = "application/json"
    req = Request(url, method=method, headers=headers, data=body)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"R2 {method} {path}: HTTP {e.code} — {body}")


def list_r2_objects(account_id, token):
    """Return list of all object keys in the bucket via pagination."""
    keys = []
    cursor = None
    while True:
        path = "objects?limit=1000"
        if cursor:
            path += f"&cursor={cursor}"
        data = r2_request("GET", path, account_id, token)
        objects = data.get("result", {}).get("objects", [])
        keys.extend(o["key"] for o in objects)
        if not data.get("result", {}).get("truncated"):
            break
        cursor = data["result"].get("cursor")
    return keys


def delete_r2_object(key, account_id, token):
    r2_request("DELETE", f"objects/{key}", account_id, token)


def strip_truecolor_from_json(date_str):
    """Remove truecolor_file / truecolor_files from snowline.json for this date."""
    meta_path = DATA_10M / date_str / "snowline.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text())
        changed = False
        for collection_key in ("tiles", "chunks"):
            for item in meta.get(collection_key) or []:
                if item.pop("truecolor_file", None) is not None:
                    changed = True
                if item.pop("truecolor_files", None) is not None:
                    changed = True
        if changed:
            meta_path.write_text(json.dumps(meta))
            log(f"  {date_str}: stripped truecolor fields from snowline.json")
    except Exception as e:
        log(f"  WARN: failed to update {meta_path}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-snow", type=int, default=30,
                        help="Most-recent dates to keep snow tiles for (0 = keep all)")
    parser.add_argument("--keep-truecolor", type=int, default=10,
                        help="Number of most-recent dates to keep truecolor tiles for")
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not account_id or not token:
        log("ERROR: CF_ACCOUNT_ID and CF_API_TOKEN must be set")
        sys.exit(1)

    log("Listing R2 objects...")
    all_keys = list_r2_objects(account_id, token)
    log(f"Found {len(all_keys)} objects in R2")

    # Group keys by date and type (snow vs truecolor)
    # Key format: tiles/{date}/{filename}  e.g. tiles/2026-06-17/snow_r0c0.webp
    by_date = {}
    for key in all_keys:
        parts = key.split("/")
        if len(parts) < 3 or parts[0] != "tiles":
            continue
        date = parts[1]
        fname = parts[2]
        if date not in by_date:
            by_date[date] = {"snow": [], "truecolor": []}
        if fname.startswith("truecolor"):
            by_date[date]["truecolor"].append(key)
        else:
            by_date[date]["snow"].append(key)

    sorted_dates = sorted(by_date.keys(), reverse=True)
    log(f"Dates in R2: {len(sorted_dates)}")

    # Prune snow tiles beyond keep window
    # 0 = keep every snow tile (they are the open-data archive; ~5 MB/date)
    snow_prune_dates = sorted_dates[args.keep_snow:] if args.keep_snow > 0 else []
    deleted = 0
    for date in snow_prune_dates:
        keys = by_date[date]["snow"]
        if not keys:
            continue
        for key in keys:
            delete_r2_object(key, account_id, token)
            deleted += 1
        log(f"  {date}: deleted {len(keys)} snow tiles")

    # Prune truecolor tiles beyond keep window
    tc_prune_dates = sorted_dates[args.keep_truecolor:]
    for date in tc_prune_dates:
        keys = by_date[date]["truecolor"]
        if not keys:
            continue
        for key in keys:
            delete_r2_object(key, account_id, token)
            deleted += 1
        strip_truecolor_from_json(date)
        log(f"  {date}: deleted {len(keys)} truecolor tiles")

    if deleted == 0:
        log("Nothing to prune.")
    else:
        log(f"Done. Deleted {deleted} objects from R2.")


if __name__ == "__main__":
    main()
