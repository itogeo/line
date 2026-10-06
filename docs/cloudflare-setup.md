# Cloudflare setup for Snowline (owner only)

Snowline's tiles live in Cloudflare R2, not git. The map asks the edge worker
(`_worker.js`) for `/snow/api/tile/{date}/{file}.webp`, and the worker reads
R2 key `tiles/{date}/{file}.webp` from the bucket bound as `SNOWLINE_BUCKET`.

**Status on 2026-10-05:** every tile request on the live site returns 404, so
the map shows no snow layer at all. The tiles exist only on Ian's laptop
(`snowline/site/data_10m/*/`, 26 dates, ~118 MB of snow tiles). Either the
binding is missing or the bucket is empty. The steps below fix both.

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

   Do the same on the new public repo once it exists.

## 4. Backfill the tiles you already have

From the repo root on your laptop:

```bash
export CF_ACCOUNT_ID=3b134bb7dc7ac46e5a2ffe71302f8d69
read -s CF_API_TOKEN && export CF_API_TOKEN          # paste, Enter (not echoed)
python snowline/pipeline/sync_r2.py --check           # lists what's missing
python snowline/pipeline/sync_r2.py                   # uploads it (~400 files incl. truecolor)
unset CF_API_TOKEN
```

## 5. Check

```bash
curl -sI https://line.itogeospatial.com/snow/api/tile/2026-05-06/snow_r0c0.webp | grep -iE "^HTTP|x-tile-source"
```

Expect `HTTP/2 200` and `x-tile-source: r2`. If you see
`x-tile-source: no-r2-binding`, step 2 hasn't taken effect yet (redeploy).
`missing-in-r2` means step 4 didn't upload that file.

After this, the daily workflow finds new clear passes, the imagery workflow
processes them, uploads with `sync_r2.py`, and only then lists the date.

## Later (optional): public open-data bucket

To publish the snow masks as open data (GUIDE.md 6.1), give `snowline-tiles`
a public custom domain (R2 → bucket → Settings → Custom Domains, e.g.
`tiles.line.itogeospatial.com`). Nothing in the site depends on this.
