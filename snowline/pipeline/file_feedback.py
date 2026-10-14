#!/usr/bin/env python3
"""
File site feedback as GitHub issues.

The site's Feedback box posts to the worker (_worker.js /api/feedback), which
saves each message to R2 as feedback/{id}.json and tries to open a GitHub issue
straight away. If it can't (no GH_FEEDBACK_TOKEN, GitHub down), this script,
run by snowline-daily, opens the issue with the workflow's own token. A
marker feedback/filed/{id}.json records each one filed, so none is filed twice
and the saved messages are never deleted.

Requires env vars:
    CF_ACCOUNT_ID, CF_API_TOKEN  — R2 read/write on snowline-tiles
    GITHUB_TOKEN                 — issues: write on itogeo/line
    GITHUB_REPOSITORY            — set by Actions (default itogeo/line)

Usage:
    python snowline/pipeline/file_feedback.py            # file anything unfiled
    python snowline/pipeline/file_feedback.py --dry-run  # list, file nothing
"""
import argparse
import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BUCKET = "snowline-tiles"


def log(msg):
    print(f"[file_feedback] {msg}", flush=True)


def r2(method, path, account, token, body=None, ctype=None, raw=False):
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/r2/buckets/{BUCKET}/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if ctype:
        headers["Content-Type"] = ctype
    with urlopen(Request(url, method=method, headers=headers, data=body)) as resp:
        data = resp.read()
    return data if raw else json.loads(data)


def list_keys(prefix, account, token):
    keys, cursor = [], None
    while True:
        path = f"objects?per_page=1000&prefix={quote(prefix)}" + (f"&cursor={cursor}" if cursor else "")
        d = r2("GET", path, account, token)
        res = d.get("result") or []
        keys += [o["key"] for o in (res if isinstance(res, list) else res.get("objects", []))]
        info = d.get("result_info") or {}
        cursor = info.get("cursor")
        if not cursor or not info.get("is_truncated", bool(cursor)):
            return keys


def open_issue(rec, repo, gh_token):
    text = rec.get("text", "").strip()
    title = "Feedback: " + text[:60] + ("..." if len(text) > 60 else "")
    body = (f"{text}\n\n---\n*Submitted from line.itogeospatial.com/snow*\n"
            f"*Date viewed: {rec.get('date') or 'unknown'}*\n*{rec.get('at', '')}*")
    req = Request(f"https://api.github.com/repos/{repo}/issues", method="POST",
                  data=json.dumps({"title": title, "body": body, "labels": ["feedback", "snowline"]}).encode(),
                  headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "User-Agent": "snowline-feedback"})
    with urlopen(req) as resp:
        return json.loads(resp.read())["html_url"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "itogeo/line")
    if not account or not token or (not gh_token and not args.dry_run):
        log("ERROR: CF_ACCOUNT_ID, CF_API_TOKEN and GITHUB_TOKEN must be set")
        return 1

    keys = list_keys("feedback/", account, token)
    filed = {k.rsplit("/", 1)[-1] for k in keys if k.startswith("feedback/filed/")}
    todo = [k for k in keys if k.count("/") == 1 and k.endswith(".json") and k.rsplit("/", 1)[-1] not in filed]
    log(f"{len(keys)} objects, {len(filed)} already filed, {len(todo)} to file")
    failed = 0
    for key in sorted(todo):
        rec = json.loads(r2("GET", f"objects/{quote(key)}", account, token, raw=True))
        if args.dry_run:
            log(f"  would file {key}: {rec.get('text', '')[:60]!r}")
            continue
        try:
            url = open_issue(rec, repo, gh_token)
        except HTTPError as e:
            log(f"  {key}: GitHub HTTP {e.code}")
            failed += 1
            continue
        marker = json.dumps({"issue": url}).encode()
        r2("PUT", f"objects/{quote('feedback/filed/' + key.rsplit('/', 1)[-1])}", account, token,
           body=marker, ctype="application/json")
        log(f"  {key} -> {url}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
