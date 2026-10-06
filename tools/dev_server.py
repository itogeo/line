#!/usr/bin/env python3
"""
Local preview of the Line Network site, no Cloudflare account needed.

Mimics the routes in _worker.js that the static pages rely on:

    /snow/...                    -> snowline/site/...
    /snow/shared/...             -> _shared/...
    /snow/api/tile/{date}/{f}    -> snowline/site/data_10m/{date}/{f}  (R2 in production)
    /river/...                   -> riverline/site/...

Webcam proxies, feedback and the RiverLine APIs live only in the worker and
return 404 here.

Usage (from the repo root):
    python tools/dev_server.py            # http://localhost:8787/snow/
    python tools/dev_server.py --port 9000
"""

from __future__ import annotations

import argparse
import http.server
import mimetypes
import posixpath
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = [
    ("/snow/api/tile/", ROOT / "snowline/site/data_10m"),
    ("/snow/api/terrain/", ROOT / "snowline/site/terrain"),
    ("/snow/shared/", ROOT / "_shared"),
    ("/snow/", ROOT / "snowline/site"),
    ("/river/", ROOT / "riverline/site"),
]
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/javascript", ".js")


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Same as the worker: /snow and /river need their trailing slash or
        # the pages' relative links resolve against the site root.
        p = urllib.parse.urlsplit(self.path)
        if p.path in ("/", "/snow", "/river"):
            self.send_response(301)
            self.send_header("Location", ("/snow" if p.path == "/" else p.path) + "/" + (("?" + p.query) if p.query else ""))
            self.end_headers()
            return
        super().do_GET()

    def translate_path(self, path):
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        for prefix, base in ROUTES:
            if path.startswith(prefix):
                rel = posixpath.normpath(path[len(prefix):]).lstrip("/")
                if rel.startswith(".."):
                    return str(base / "__nope__")
                target = base / rel if rel not in ("", ".") else base
                if target.is_dir():
                    target = target / "index.html"
                elif not target.exists() and target.with_suffix(".html").exists():
                    target = target.with_suffix(".html")
                return str(target)
        return str(ROOT / "__nope__")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Snowline:  http://localhost:{args.port}/snow/")
    print(f"RiverLine: http://localhost:{args.port}/river/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
