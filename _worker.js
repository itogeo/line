// Map a site path onto the static asset that Cloudflare Pages serves with a
// 200. Pages uses "pretty" URLs: /x/index.html and /x/page.html answer with
// a 308 to /x/ and /x/page, which would leak /snowline/site/... into the
// address bar and break relative links. So ask for the pretty form directly.
function prettyAsset(base, effectivePath) {
  let p = effectivePath || '/';
  if (p.endsWith('/index.html')) p = p.slice(0, -'index.html'.length);
  else if (p.endsWith('.html')) p = p.slice(0, -'.html'.length);
  return base + p;
}

// "bytes=a-b" | "bytes=a-" | "bytes=-n" → an R2 range option, or null.
function parseRange(header) {
  const m = /^bytes=(\d*)-(\d*)$/.exec((header || '').trim());
  if (!m || (m[1] === '' && m[2] === '')) return null;
  if (m[1] === '') return { suffix: Number(m[2]) };
  const offset = Number(m[1]);
  return m[2] === '' ? { offset } : { offset, length: Number(m[2]) - offset + 1 };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname;
    const path = url.pathname;

    // ── REDIRECT OLD SUBDOMAINS ────────────────────────────────────────────────
    // Old: snow.line.*, snowline.*, river.line.*, riverline.*
    // New: line.itogeospatial.com/snow  and  line.itogeospatial.com/river
    if (!host.endsWith('.pages.dev') && host !== 'line.itogeospatial.com') {
      let newBase = null;
      if (host.includes('snow')) newBase = 'https://line.itogeospatial.com/snow';
      else if (host.includes('river')) newBase = 'https://line.itogeospatial.com/river';
      if (newBase) {
        const suffix = path === '/' ? '/' : path;
        return Response.redirect(newBase + suffix + url.search, 301);
      }
    }

    // ── DETERMINE SITE + EFFECTIVE PATH ───────────────────────────────────────
    // Path prefix wins; hostname fallback for .pages.dev testing
    let site = null;
    let effectivePath = path;

    // /snow and /river need their trailing slash, or the pages' relative
    // links (data/..., data_10m/...) resolve against the site root.
    if (path === '/snow' || path === '/river') {
      return Response.redirect(url.origin + path + '/' + url.search + url.hash, 301);
    }

    if (path === '/snow' || path.startsWith('/snow/')) {
      site = 'snow';
      effectivePath = path.slice('/snow'.length) || '/';
    } else if (path === '/river' || path.startsWith('/river/')) {
      site = 'river';
      effectivePath = path.slice('/river'.length) || '/';
    } else if (host.includes('snow')) {
      site = 'snow';
    } else if (host.includes('river')) {
      site = 'river';
    }

    // ── SHARED (all Line Network sites) ───────────────────────────────────────
    if (effectivePath.startsWith('/shared/')) {
      const sharedPath = '/_shared' + effectivePath.slice('/shared'.length);
      return env.ASSETS.fetch(new Request(new URL(sharedPath, url), request));
    }

    // ── SNOW ──────────────────────────────────────────────────────────────────

    if (site === 'snow') {
      // R2 tile serving — fall back to git-committed tiles if not in R2
      if (effectivePath.startsWith('/api/tile/')) {
        const tilePath = effectivePath.slice('/api/tile'.length);
        const key = 'tiles' + tilePath;
        if (env.SNOWLINE_BUCKET) {
          // GeoTIFFs are Cloud-Optimized: honour Range so GDAL/QGIS/rasterio
          // can read just the blocks they need straight from this URL.
          const isTif = key.endsWith('.tif');
          const range = isTif ? parseRange(request.headers.get('range')) : null;
          const obj = await env.SNOWLINE_BUCKET.get(key, range ? { range } : undefined);
          if (obj) {
            const headers = {
              'Content-Type': isTif ? 'image/tiff' : 'image/webp',
              'Cache-Control': 'public, max-age=86400',
              'Access-Control-Allow-Origin': '*',
              'Access-Control-Expose-Headers': 'Content-Range, Content-Length, Accept-Ranges',
              'X-Tile-Source': 'r2',
            };
            if (isTif) headers['Accept-Ranges'] = 'bytes';
            if (range && obj.size !== undefined) {
              const r = range;
              const start = 'suffix' in r ? obj.size - r.suffix : (r.offset || 0);
              const len = Math.min('suffix' in r ? r.suffix : (r.length ?? obj.size - start), obj.size - start);
              headers['Content-Range'] = `bytes ${start}-${start + len - 1}/${obj.size}`;
              return new Response(obj.body, { status: 206, headers });
            }
            return new Response(obj.body, { headers });
          }
        }
        // Not in R2 (or no R2 binding): try the static assets (local dev).
        // X-Tile-Source says which, so a blank map is quick to diagnose:
        //   curl -sI https://line.itogeospatial.com/snow/api/tile/<date>/snow_r0c0.webp
        const fb = await env.ASSETS.fetch(new Request(
          new URL('/snowline/site/data_10m' + tilePath, url),
          request,
        ));
        const h = new Headers(fb.headers);
        h.set('X-Tile-Source', fb.ok ? 'assets' : (env.SNOWLINE_BUCKET ? 'missing-in-r2' : 'no-r2-binding'));
        return new Response(fb.body, { status: fb.status, headers: h });
      }

      // Wind (fetch_wind.py, hourly): R2 key wind/{file}.json. Short cache,
      // the files are replaced every hour.
      if (effectivePath.startsWith('/api/wind/')) {
        const rel = effectivePath.slice('/api/'.length);            // wind/grid_48h.json
        if (!/^wind\/[a-z0-9_]+\.json$/.test(rel)) return new Response('bad wind path', { status: 400 });
        const obj = env.SNOWLINE_BUCKET ? await env.SNOWLINE_BUCKET.get(rel) : null;
        if (!obj) return new Response('not found', { status: 404, headers: { 'Access-Control-Allow-Origin': '*' } });
        return new Response(obj.body, { headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'public, max-age=600',
          'Access-Control-Allow-Origin': '*',
        } });
      }

      // Lidar terrain tiles: R2 key terrain/{layer}/{z}/{x}/{y}.webp, with the
      // static assets as a local-dev fallback. Outside the coverage a tile
      // simply doesn't exist; answer 204 so the map shows nothing there.
      if (effectivePath.startsWith('/api/terrain/')) {
        const rel = effectivePath.slice('/api/'.length);           // terrain/shade/z/x/y.webp
        if (!/^terrain\/[a-z]+\/\d+\/\d+\/\d+\.webp$/.test(rel)) return new Response('bad tile path', { status: 400 });
        const headers = {
          'Content-Type': 'image/webp',
          'Cache-Control': 'public, max-age=2592000',
          'Access-Control-Allow-Origin': '*',
        };
        if (env.SNOWLINE_BUCKET) {
          const obj = await env.SNOWLINE_BUCKET.get(rel);
          if (obj) return new Response(obj.body, { headers: { ...headers, 'X-Tile-Source': 'r2' } });
        }
        const fb = await env.ASSETS.fetch(new Request(new URL('/snowline/site/' + rel, url), request));
        if (fb.ok) return new Response(fb.body, { headers: { ...headers, 'X-Tile-Source': 'assets' } });
        return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'X-Tile-Source': 'none' } });
      }

      // Image proxy (webcams blocked by CORS)
      if (effectivePath === '/api/camproxy' && url.searchParams.get('url')) {
        const imgUrl = url.searchParams.get('url');
        const allowed = ['nps.gov', 'mdt.mt.gov', 'ipcamlive.com', 'mediaassets.kbzk.com'];
        const imgHost = new URL(imgUrl).hostname;
        if (!allowed.some(d => imgHost.endsWith(d))) {
          return new Response('Forbidden', { status: 403 });
        }
        try {
          const imgResp = await fetch(imgUrl, { headers: { 'User-Agent': 'snowline-webcam/1.0' } });
          const body = await imgResp.arrayBuffer();
          return new Response(body, {
            headers: {
              'Content-Type': imgResp.headers.get('Content-Type') || 'image/jpeg',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=120',
            },
          });
        } catch (e) {
          return new Response('Proxy error', { status: 502 });
        }
      }

      // FAA WeatherCams: newest image for one camera. The API needs a
      // weathercams.faa.gov Referer (browsers can't set it); the image host
      // doesn't, so redirect the <img> straight to the image.
      if (effectivePath === '/api/faacam' && /^\d+$/.test(url.searchParams.get('id') || '')) {
        try {
          const r = await fetch('https://weathercams.faa.gov/api/cameras/' + url.searchParams.get('id') + '/images/last/1', {
            headers: { 'Referer': 'https://weathercams.faa.gov/', 'User-Agent': 'Mozilla/5.0 (compatible; SnowlineCam/1.0)' },
          });
          if (!r.ok) return new Response('FAA API ' + r.status, { status: 502 });
          const img = (await r.json())?.payload?.[0]?.imageUri;
          if (!img || !img.startsWith('https://images.wcams-static.faa.gov/')) return new Response('No image', { status: 404 });
          return new Response(null, { status: 302, headers: { 'Location': img, 'Cache-Control': 'public, max-age=120' } });
        } catch (e) {
          return new Response('FAA error', { status: 502 });
        }
      }

      // SNOTEL API proxy (CORS)
      if (effectivePath === '/api/snotel' && url.searchParams.get('triplets')) {
        const triplets = url.searchParams.get('triplets');
        const begin = url.searchParams.get('begin') || '2025-10-01';
        const end = url.searchParams.get('end') || new Date().toISOString().slice(0, 10);
        const apiUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${triplets}&elements=SNWD,WTEQ&duration=DAILY&beginDate=${begin}&endDate=${end}`;
        try {
          const r = await fetch(apiUrl, { headers: { 'User-Agent': 'snowline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'SNOTEL API error' }), { status: 502 });
        }
      }

      // Feedback POST: saved to R2 first (feedback/{id}.json) so nothing is
      // lost, then filed as an issue in itogeo/line. If GitHub can't be
      // reached here (no GH_FEEDBACK_TOKEN, GitHub down), the nightly
      // snowline-daily run files it (snowline/pipeline/file_feedback.py).
      if (effectivePath === '/api/feedback' && request.method === 'POST') {
        const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
          status, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
        let text, date;
        try { ({ text, date } = await request.json()); } catch (e) { return json({ error: 'Bad request' }, 400); }
        if (!text || !String(text).trim()) return json({ error: 'Empty feedback' }, 400);
        text = String(text).slice(0, 5000);
        const at = new Date().toISOString();
        const id = at.replace(/[:.]/g, '-') + '-' + crypto.randomUUID().slice(0, 8) + '.json';
        const rec = { text, date: date || null, at };
        let saved = false, issue = null;
        if (env.SNOWLINE_BUCKET) {
          try {
            await env.SNOWLINE_BUCKET.put('feedback/' + id, JSON.stringify(rec), { httpMetadata: { contentType: 'application/json' } });
            saved = true;
          } catch (e) { /* try GitHub anyway */ }
        }
        if (env.GH_FEEDBACK_TOKEN) {
          try {
            const title = 'Feedback: ' + text.substring(0, 60) + (text.length > 60 ? '...' : '');
            const body = text + '\n\n---\n*Submitted from line.itogeospatial.com/snow*\n*Date viewed: ' + (date || 'unknown') + '*\n*' + at + '*';
            const gh = await fetch('https://api.github.com/repos/itogeo/line/issues', {
              method: 'POST',
              headers: { Authorization: 'Bearer ' + env.GH_FEEDBACK_TOKEN, 'Content-Type': 'application/json', 'User-Agent': 'snowline-feedback' },
              body: JSON.stringify({ title, body, labels: ['feedback', 'snowline'] }),
            });
            if (gh.ok) {
              issue = (await gh.json()).html_url;
              if (saved) await env.SNOWLINE_BUCKET.put('feedback/filed/' + id, JSON.stringify({ issue }));
            }
          } catch (e) { /* saved copy gets filed tonight */ }
        }
        if (saved || issue) return json({ ok: true, issue });
        return json({ error: 'Could not save feedback' }, 503);
      }

      // CORS preflight
      if (effectivePath.startsWith('/api/') && request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
          },
        });
      }

      // Static assets → rewrite to snowline/site/ prefix
      // Ask for the pretty URL so Pages answers 200 instead of a 308 to /snowline/site/...
      const snowPath = prettyAsset('/snowline/site', effectivePath);
      const asset = await env.ASSETS.fetch(new Request(new URL(snowPath, url), request));
      // Open data (scene tables, timelines, STAC catalog) is readable from
      // any origin, so STAC browsers and notebooks can load it directly.
      if (/^\/(data|data_10m|stac)\//.test(effectivePath)) {
        const h = new Headers(asset.headers);
        h.set('Access-Control-Allow-Origin', '*');
        return new Response(asset.body, { status: asset.status, headers: h });
      }
      return asset;
    }

    // ── RIVER ──────────────────────────────────────────────────────────────────

    if (site === 'river') {
      if (effectivePath === '/api/current') {
        const val = await env.RIVERLINE_KV.get('gateway:current');
        if (!val) return new Response('No data yet', { status: 503 });
        return new Response(val, {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-store',
          },
        });
      }

      if (effectivePath === '/api/chart') {
        const siteParam = url.searchParams.get('site') || '06043500';
        const [hist, bands] = await Promise.all([
          env.RIVERLINE_DB.prepare(
            'SELECT date, cfs FROM daily_flow WHERE site_id = ? ORDER BY date DESC LIMIT 90',
          ).bind(siteParam).all(),
          env.RIVERLINE_DB.prepare(
            'SELECT doy, p10, p25, p50, p75, p90 FROM doy_stats WHERE site_id = ? ORDER BY doy',
          ).bind(siteParam).all(),
        ]);
        return new Response(
          JSON.stringify({ site: siteParam, history: hist.results, bands: bands.results }),
          {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=300',
            },
          },
        );
      }

      // All active MT USGS gauges with WaterWatch percentile class → GeoJSON
      if (effectivePath === '/api/gauges/mt') {
        const usgsUrl = 'https://waterservices.usgs.gov/nwis/iv/?stateCd=mt&parameterCd=00060&format=json&siteStatus=active';
        const wwUrl = 'https://waterwatch.usgs.gov/webservices/realtime?region=mt&format=json';
        const [usgsResult, wwResult] = await Promise.allSettled([
          fetch(usgsUrl, { headers: { 'User-Agent': 'riverline/1.0' } }).then(r => r.json()),
          fetch(wwUrl, { headers: { 'User-Agent': 'riverline/1.0' } }).then(r => r.json()),
        ]);

        const series = usgsResult.status === 'fulfilled'
          ? (usgsResult.value?.value?.timeSeries || [])
          : [];

        // Build WaterWatch class lookup (cls 1=low … 5=high)
        const clsMap = {};
        if (wwResult.status === 'fulfilled') {
          const wwRaw = wwResult.value;
          const stations = Array.isArray(wwRaw)
            ? wwRaw
            : (wwRaw?.sites || wwRaw?.stations || []);
          for (const s of stations) {
            const sno = s.site_no || s.siteNo || s.siteNumber;
            const cls = parseInt(s.class || s.percentile_class || s.cls) || null;
            if (sno && cls) clsMap[sno] = cls;
          }
        }

        const features = [];
        for (const ts of series) {
          const loc = ts.sourceInfo?.geoLocation?.geogLocation;
          if (!loc) continue;
          const lng = parseFloat(loc.longitude);
          const lat = parseFloat(loc.latitude);
          if (!isFinite(lng) || !isFinite(lat)) continue;

          const id = ts.sourceInfo?.siteCode?.[0]?.value;
          if (!id) continue;
          const name = ts.sourceInfo?.siteName || id;
          const vals = ts.values?.[0]?.value || [];
          const lastVal = vals[vals.length - 1];
          const flow = lastVal ? parseFloat(lastVal.value) : null;
          const tsStr = lastVal?.dateTime || null;

          if (flow == null || !isFinite(flow) || flow < 0) continue;

          features.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lng, lat] },
            properties: { id, name, flow: Math.round(flow), ts: tsStr, cls: clsMap[id] || null },
          });
        }

        return new Response(
          JSON.stringify({ type: 'FeatureCollection', features }),
          {
            headers: {
              'Content-Type': 'application/geo+json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=900',
            },
          },
        );
      }

      // SNOTEL proxy — AWDB has no CORS headers; proxy single station's 30-day data
      if (effectivePath === '/api/snotel' && url.searchParams.get('triplet')) {
        const triplet = url.searchParams.get('triplet');
        const today = new Date().toISOString().slice(0, 10);
        const thirtyAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
        const apiUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${encodeURIComponent(triplet)}&elements=WTEQ,SNWD,TOBS&duration=DAILY&beginDate=${thirtyAgo}&endDate=${today}&periodRef=END`;
        try {
          const r = await fetch(apiUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'SNOTEL proxy error' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // NOAA NWPS stageflow proxy — NOAA has no CORS headers
      if (effectivePath.startsWith('/api/noaa/') && effectivePath.endsWith('/stageflow')) {
        const parts = effectivePath.split('/');
        const lid = parts[3];
        if (!/^[A-Z0-9]{3,10}$/i.test(lid)) {
          return new Response('Invalid lid', { status: 400 });
        }
        try {
          const noaaUrl = `https://api.water.noaa.gov/nwps/v1/gauges/${lid}/stageflow`;
          const r = await fetch(noaaUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=1800',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'NOAA API error' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // DNRC StAGE tsQuery proxy — async GP job pattern, returns 14/30-day discharge JSON
      if (effectivePath.startsWith('/api/dnrc/') && url.searchParams.has('days')) {
        const locationId = effectivePath.split('/')[3] || '';
        if (!/^[a-f0-9]{32}$/i.test(locationId)) {
          return new Response('Invalid locationId', { status: 400, headers: { 'Access-Control-Allow-Origin': '*' } });
        }
        const days = Math.min(365, Math.max(1, parseInt(url.searchParams.get('days')) || 14));
        const DNRC_MAP = 'https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WMB_StAGE/MapServer';
        const DNRC_GP  = 'https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WMB_StAGE_GPTools/GPServer/tsQuery';

        async function unzipFirstEntry(buf) {
          const v = new DataView(buf);
          if (v.getUint32(0, true) !== 0x04034b50) throw new Error('Not a ZIP');
          const method = v.getUint16(8, true);
          const fnLen  = v.getUint16(26, true);
          const exLen  = v.getUint16(28, true);
          const dataStart = 30 + fnLen + exLen;
          if (method === 0) {
            return new TextDecoder().decode(new Uint8Array(buf, dataStart));
          }
          if (method === 8) {
            const compSize = v.getUint32(18, true);
            const compressed = new Uint8Array(buf, dataStart, compSize);
            const ds = new DecompressionStream('deflate-raw');
            const writer = ds.writable.getWriter();
            writer.write(compressed);
            writer.close();
            const reader = ds.readable.getReader();
            const chunks = [];
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              if (value) chunks.push(value);
            }
            let total = 0; for (const c of chunks) total += c.length;
            const out = new Uint8Array(total); let pos = 0;
            for (const c of chunks) { out.set(c, pos); pos += c.length; }
            return new TextDecoder().decode(out);
          }
          throw new Error('Unsupported ZIP compression: ' + method);
        }

        try {
          // Step 1 — find real-time discharge SensorID
          const sensorQ = await fetch(
            `${DNRC_MAP}/3/query?where=${encodeURIComponent(`LocationID='${locationId}' AND Parameter='QR' AND ComputationPeriod<>'Daily'`)}&outFields=SensorID&f=json`,
            { headers: { 'User-Agent': 'riverline/1.0' } },
          );
          const sensorData = await sensorQ.json();
          let sensorId = sensorData?.features?.[0]?.attributes?.SensorID;
          if (!sensorId) {
            // Fallback to daily if no real-time
            const fallQ = await fetch(
              `${DNRC_MAP}/3/query?where=${encodeURIComponent(`LocationID='${locationId}' AND Parameter='QR'`)}&outFields=SensorID&f=json`,
              { headers: { 'User-Agent': 'riverline/1.0' } },
            );
            const fallData = await fallQ.json();
            sensorId = fallData?.features?.[0]?.attributes?.SensorID;
          }
          if (!sensorId) {
            return new Response(JSON.stringify({ error: 'No discharge sensor' }), {
              status: 404,
              headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            });
          }

          // Step 2 — submit tsQuery job (dates as Unix ms timestamps)
          const endMs   = Date.now();
          const startMs = endMs - days * 24 * 60 * 60 * 1000;
          const jobResp = await fetch(`${DNRC_GP}/submitJob`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'riverline/1.0' },
            body: `SensorID=${sensorId}&StartDate=${startMs}&EndDate=${endMs}&OutputType=csv&f=pjson`,
          });
          const jobData = await jobResp.json();
          const jobId   = jobData?.jobId;
          if (!jobId) throw new Error('No jobId');

          // Step 3 — poll until done (typically 2–4 s)
          let status = jobData?.jobStatus;
          for (let i = 0; i < 12 && status !== 'esriJobSucceeded' && status !== 'esriJobFailed'; i++) {
            await new Promise(r => setTimeout(r, 1500));
            const poll = await fetch(`${DNRC_GP}/jobs/${jobId}?f=pjson`, { headers: { 'User-Agent': 'riverline/1.0' } });
            status = (await poll.json())?.jobStatus;
          }
          if (status !== 'esriJobSucceeded') throw new Error('Job failed: ' + status);

          // Step 4 — get output file URL
          const outResp = await fetch(`${DNRC_GP}/jobs/${jobId}/results/OutputFile?f=pjson`, { headers: { 'User-Agent': 'riverline/1.0' } });
          const outData = await outResp.json();
          const fileUrl = outData?.value?.url;
          if (!fileUrl) throw new Error('No output URL');

          // Step 5 — fetch ZIP, unzip, parse CSV
          const zipResp = await fetch(fileUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const zipBuf  = await zipResp.arrayBuffer();
          const csv     = await unzipFirstEntry(zipBuf);

          const allLines = csv.trim().split('\n');
          const hdrs = allLines[0].split(',').map(h => h.trim().replace(/^"|"$/g, '').toLowerCase());
          const dtIdx  = Math.max(0, hdrs.findIndex(h => h.includes('date') || h.includes('time')));
          const valIdx = hdrs.findIndex(h => h.includes('value') || h === 'discharge' || h === 'cfs');
          const vi = valIdx >= 0 ? valIdx : 1;
          const rows = [];
          for (const line of allLines.slice(1)) {
            const parts = line.split(',');
            if (parts.length <= vi) continue;
            const dt  = parts[dtIdx].trim().replace(/^"|"$/g, '');
            const cfs = parseFloat(parts[vi].trim().replace(/^"|"$/g, ''));
            if (dt && !isNaN(cfs) && cfs >= 0 && cfs < 9000) rows.push({ dt, cfs });
          }

          return new Response(JSON.stringify({ rows }), {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=900',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'DNRC API error', detail: e.message }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // DNRC WRQS proxy — FeatureServer has no CORS headers
      if (effectivePath.startsWith('/api/wrqs')) {
        const layer = url.searchParams.get('layer') || '1';
        const xmin = url.searchParams.get('xmin');
        const ymin = url.searchParams.get('ymin');
        const xmax = url.searchParams.get('xmax');
        const ymax = url.searchParams.get('ymax');
        const where = url.searchParams.get('where') || '1=1';
        const geom = JSON.stringify({ xmin: parseFloat(xmin), ymin: parseFloat(ymin), xmax: parseFloat(xmax), ymax: parseFloat(ymax) });
        const fields = 'WR_NUMBER,SOURCE_NAME,PURPOSES,MAX_FLOW_CFS,PERIOD_OF_DIVERSIONS,OWNERS,ENF_PRTY_DT_CHAR,URL_ABSTRACT,MAX_ACRES';
        const featureUrl = `https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WRQS/FeatureServer/${layer}/query?geometry=${encodeURIComponent(geom)}&geometryType=esriGeometryEnvelope&spatialRel=esriSpatialRelIntersects&inSR=4326&where=${encodeURIComponent(where)}&outFields=${fields}&f=geojson&resultRecordCount=500`;
        try {
          const r = await fetch(featureUrl, { headers: { 'User-Agent': 'RiverLine/1.0 (Ito Geospatial)' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/geo+json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (_) {
          return new Response('{"type":"FeatureCollection","features":[]}', {
            status: 502,
            headers: { 'Content-Type': 'application/geo+json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // CORS preflight
      if (effectivePath.startsWith('/api/') && request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
          },
        });
      }

      // Static assets → rewrite to riverline/site/ prefix
      const riverPath = prettyAsset('/riverline/site', effectivePath);
      return env.ASSETS.fetch(new Request(new URL(riverPath, url), request));
    }

    // Default: redirect root to /snow; other unknown paths fall through to ASSETS
    if (path === '/') return Response.redirect(url.origin + '/snow', 302);
    return env.ASSETS.fetch(request);
  },
};
