# Cloudflare setup for Snowline (owner only)

Snowline's tiles live in Cloudflare R2, not git. The map asks the edge worker
(`_worker.js`) for `/snow/api/tile/{date}/{file}.webp`, and the worker reads
R2 key `tiles/{date}/{file}.webp` from the bucket bound as `SNOWLINE_BUCKET`.

**Status on 2026-11-21:** this setup is done and working. Bucket
`snowline-tiles` is bound as `SNOWLINE_BUCKET`, CI writes to it with
`CF_API_TOKEN`, and `tools/release_check.py` gets the newest tiles from R2. The
bucket also holds `wind/` and the lidar terrain tiles. The steps below are kept
as a record of how it was set up and for rebuilding it. Contributors don't need
any of this.

Agents never do these steps and never handle the token.

## 1. Bucket

Dashboard → **R2** → if there is no bucket called `snowline-tiles`, **Create bucket** →
name `snowline-tiles`, location automatic.

## 2. Bind it to the Pages project

Dashboard → **Workers & Pages** → the `line` Pages project → **Settings** →
**Bindings** → **Add** → **R2 bucket** → Variable name `SNOWLINE_BUCKET`,
bucket `snowline-tiles`. Do it for **Production** (and Preview if you use it).
Then **Deployments** → latest → **Retry deployment** so the binding takes effect.

## 3. Roll the API token

The old `CF_API_TOKEN` has been in a local `.env` for months; replace it.

1. Dashboard → **My Profile** → **API Tokens** → **Create Token** → **Create Custom Token**.
2. Name `line-ci-r2`. Permissions: **Account → Workers R2 Storage → Edit**. Account resources: your account. No IP filter needed.
3. Copy the token once.
4. Delete (roll) the old token on the same page.
5. Put the new one in GitHub (it never touches a file):

   ```bash
   gh secret set CF_API_TOKEN --repo itogeo/line      # paste when prompted
   ```


## 4. Backfill the tiles you already have

From the repo root on your laptop:

```bash
export CF_ACCOUNT_ID=3b134bb7dc7ac46e5a2ffe71302f8d69
read -s CF_API_TOKEN && export CF_API_TOKEN          # paste, Enter (not echoed)
python snowline/pipeline/sync_r2.py --check           # lists what's missing
python snowline/pipeline/sync_r2.py                   # uploads it (~400 files incl. truecolor)
unset CF_API_TOKEN
```

Then upload the lidar terrain tiles (about 5,000 small files, once):

```bash
python snowline/pipeline/sync_r2.py --terrain --check
python snowline/pipeline/sync_r2.py --terrain
```

## 5. Check

```bash
curl -sI https://line.itogeospatial.com/snow/api/tile/2026-05-06/snow_r0c0.webp | grep -iE "^HTTP|x-tile-source"
```

Expect `HTTP/2 200` and `x-tile-source: r2`. For the terrain:
`curl -sI https://line.itogeospatial.com/snow/api/terrain/shade/13/1572/2920.webp`. If you see
`x-tile-source: no-r2-binding`, step 2 hasn't taken effect yet (redeploy).
`missing-in-r2` means step 4 didn't upload that file.

After this, the daily workflow finds new clear passes, the imagery workflow
processes them, uploads with `sync_r2.py`, and only then lists the date.

## Later (optional): public open-data bucket

To publish the snow masks from their own domain, give `snowline-tiles`
a public custom domain (R2 → bucket → Settings → Custom Domains, e.g.
`tiles.line.itogeospatial.com`). Nothing in the site depends on this.
