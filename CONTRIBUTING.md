# Contributing

Thanks for looking. Issues and pull requests are welcome: bug reports, a snow map that looks wrong somewhere you know well, new webcams, better methods.

Current state and open work: [snowline/PLAN.md](snowline/PLAN.md).

## Setup

Python 3.10+ and nothing else. CI runs 3.12.

```bash
git clone https://github.com/itogeo/line.git && cd line
python -m venv .venv && source .venv/bin/activate
pip install -r snowline/pipeline/requirements.txt
```

`rasterio` ships wheels with GDAL included for macOS, Linux and Windows, so no system GDAL is needed.

## Smoke tests

Every module has a `__main__` you can run on its own. These need network but no keys:

```bash
python -m lib.aoi                                        # prints the AOIs (offline)
python -m lib.s2index                                    # latest 12TVR scenes + monthly stats (~10-25 s)
python snowline/pipeline/build_sat_availability.py --days=30   # rewrites site/data/*.json; see below
python snowline/pipeline/fetch_bands.py --date=2026-10-03 --tiles=12TVR   # ~0.5 GB, ~1 min
python snowline/pipeline/process_tiles.py --date=2026-10-03
python snowline/pipeline/build_snotel_agreement.py --date=2026-10-03
```

These scripts write their real outputs into `snowline/site/` (that is the
pipeline). After experimenting, put the published files back with
`git checkout -- snowline/site` and delete new untracked files with
`git clean -n snowline/site` (check the list first) before you commit.

One tile is about 0.5 GB of band windows in `snowline/cache/`. A full date
(12 tiles) is several GB and needs about 4 GB of RAM. `update_date.sh`
deletes the cache when it finishes. If you call `fetch_bands.py` directly,
delete `snowline/cache/<date>` yourself. Use `--tiles` while developing.

## Preview the site

```bash
python tools/dev_server.py        # http://localhost:8787/snow/
```

This serves the pages and the tiles in `snowline/site/data_10m/` the way the Cloudflare worker does in production. Tiles are not in git, so a fresh clone shows the map with no snow layer until you run `fetch_bands.py` and `process_tiles.py` for a date. Wind, webcam proxies and feedback only work in production.

The pages carry a public Mapbox token. If the basemap does not load on `localhost`, the token is restricted to the live domain: put your own public token in its place while you work, and don't commit it.

## How changes reach the site

* **`main` is the live site.** Cloudflare Pages deploys `main` on every push, in a minute or two. There is no staging site.
* **Work on a branch and open a pull request** against `main`.
* **Bots commit to `main` several times a day.** The daily job commits `snowline/site/data/`. The imagery job commits `snowline/site/data_10m/dates.json`, `snowline/site/data_10m/*/snowline.json`, three files in `snowline/site/data/` and `snowline/site/stac/`. Branch from fresh `main`, rebase before you push, and never include those generated files in a pull request.
* **Tiles and wind are not deployed.** CI writes them straight to R2 and the worker reads them from there.
* **Check after a deploy:** `python tools/release_check.py` tests the live site (pages, newest map, tiles, data freshness). The daily job runs it too. `--base http://localhost:8787` points it at the local preview.
* **Don't run the imagery workflow with `force=true`** without asking. It reprocesses dates and overwrites their tiles in R2.
* The season is Oct 1 to May 31 (`lib/aoi.py`). Dates outside it are skipped by the pipeline.
* Without `CF_ACCOUNT_ID` and `CF_API_TOKEN` in your shell, `update_date.sh` skips the R2 upload and the map stays on your machine. That is the normal way to develop.

## Conventions

* **Python** for pipelines and tooling. The front end is plain HTML/JS with no build step. `_worker.js` is JS because Cloudflare needs it.
* New scripts go under `lib/` or `<product>/pipeline/` and get an `if __name__ == "__main__":` that runs a small, fast case.
* **Find scenes through `lib/s2index.py`**, not a STAC API, and read asset URLs from the index. Don't build them from templates.
* Anything shown on the site gets a visible source line that links to where it came from.
* Tiles (`*.webp`) go to R2, never into git.
* Never commit a `.env` or a token. CI reads secrets from GitHub Actions secrets.

## Repository secrets (maintainers)

| Secret | Used by |
|---|---|
| `CF_API_TOKEN` | R2 writes for tiles (`snowline-process-imagery.yml`) and wind (`snowline-wind.yml`), reading site feedback (`snowline-daily.yml`), and the RiverLine ingest |

The Cloudflare account id (`CF_ACCOUNT_ID`) is not secret. It is set in the
workflow files. Running `sync_r2.py` or `prune_r2.py` locally needs both
in your shell environment.

The Cloudflare setup is in [docs/cloudflare-setup.md](docs/cloudflare-setup.md).
